"""Office documents and e-mail without Gotenberg (P8).

paperless-ngx turns Office files and e-mails into PDF by calling a Gotenberg server over HTTP (through
``gotenberg_client``). There is no Gotenberg for Windows, so this module is a small server that speaks the
three Gotenberg routes paperless uses and does the work with programs the user has installed:

* ``POST /forms/libreoffice/convert``   LibreOffice (``soffice --convert-to pdf``)
* ``POST /forms/chromium/convert/html`` Microsoft Edge or Chrome (``--print-to-pdf``)
* ``POST /forms/pdfengines/merge``      pikepdf

The supervisor starts it (``python -m paperless_win.office``) when Tika is enabled and no other Gotenberg
endpoint is configured, and points ``PAPERLESS_TIKA_GOTENBERG_ENDPOINT`` at it. No upstream file changes.

Design notes (measured with LibreOffice 26.8): a conversion with a new LibreOffice profile takes about
23 s, with a profile that has been used before about 4.6 s, so profiles are kept and handed out one at a
time (``PAPERLESS_WIN_OFFICE_CONCURRENCY`` of them, default 1: LibreOffice does not like two instances on
one profile). A conversion that hangs is killed with its whole process tree, and its profile is thrown away.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

from paperless_win import jobs
from paperless_win import platform

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger("paperless.winport.office")

DEFAULT_PORT = 3000  # the port of Gotenberg, which is what paperless defaults to
DEFAULT_TIMEOUT = 300.0
INSTALL_HINT = (
    "Install LibreOffice (https://www.libreoffice.org/download/, the 64-bit Windows installer) "
    "or set PAPERLESS_WIN_SOFFICE to the full path of its soffice.exe, then try again."
)
BROWSER_HINT = (
    "Install Microsoft Edge (it is part of Windows 10 and 11) or Google Chrome, or set "
    "PAPERLESS_WIN_BROWSER to the full path of msedge.exe or chrome.exe."
)

# the LibreOffice filter that makes PDF/A depends on the kind of document
WRITER = {
    ".doc",
    ".docx",
    ".odt",
    ".rtf",
    ".txt",
    ".html",
    ".htm",
    ".xml",
    ".wpd",
    ".sxw",
    ".dot",
    ".dotx",
}
CALC = {".xls", ".xlsx", ".ods", ".csv", ".sxc", ".xlt", ".xltx"}
IMPRESS = {".ppt", ".pptx", ".odp", ".sxi", ".pps", ".ppsx", ".pot", ".potx"}
DRAW = {".odg", ".vsd", ".vsdx", ".sxd"}
PDF_VERSION = {"PDF/A-1b": 1, "PDF/A-2b": 2, "PDF/A-3b": 3}


class OfficeError(Exception):
    """A request that cannot be served; ``status`` is the HTTP status and ``str()`` is shown to the user."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _first_existing(candidates: list[Path]) -> Path | None:
    return next((c for c in candidates if c.is_file()), None)


def _program_roots(environ: Mapping[str, str]) -> list[str]:
    """Program Files folders. Some shells hide ``ProgramFiles(x86)`` (its name has brackets): fall back."""
    drive = environ.get("SystemDrive") or "C:"
    roots = [
        environ.get("ProgramFiles") or f"{drive}/Program Files",
        environ.get("ProgramFiles(x86)") or f"{drive}/Program Files (x86)",
        environ.get("ProgramW6432"),
    ]
    return [r for r in dict.fromkeys(roots) if r]


def find_soffice(environ: Mapping[str, str] | None = None) -> Path | None:
    """``PAPERLESS_WIN_SOFFICE``, then the folders of a normal LibreOffice installation, then the bundled tools."""
    environ = os.environ if environ is None else environ
    configured = environ.get("PAPERLESS_WIN_SOFFICE")
    if configured:
        return Path(configured) if Path(configured).is_file() else None
    candidates = [
        Path(r) / "LibreOffice" / "program" / "soffice.exe"
        for r in _program_roots(environ)
    ]
    found = _first_existing(candidates)
    if found:
        return found
    which = platform.find_binary("soffice")
    return Path(which) if which else None


def find_browser(environ: Mapping[str, str] | None = None) -> Path | None:
    """``PAPERLESS_WIN_BROWSER``, then Edge (always there on Windows 10/11), then Chrome."""
    environ = os.environ if environ is None else environ
    configured = environ.get("PAPERLESS_WIN_BROWSER")
    if configured:
        return Path(configured) if Path(configured).is_file() else None
    roots = _program_roots(environ)
    local = environ.get("LOCALAPPDATA")
    candidates = [
        Path(r) / "Microsoft" / "Edge" / "Application" / "msedge.exe" for r in roots
    ]
    candidates += [
        Path(r) / "Google" / "Chrome" / "Application" / "chrome.exe"
        for r in [*roots, local]
        if r
    ]
    return _first_existing(candidates)


JAVA_HINT = (
    "Install a Java runtime (for example Eclipse Temurin, https://adoptium.net/) or set "
    "PAPERLESS_WIN_JAVA to the full path of java.exe."
)
TIKA_HINT = (
    "Download tika-server-standard-<version>.jar from https://tika.apache.org/download.html and set "
    "PAPERLESS_WIN_TIKA_JAR to its full path, or run your own Tika server and set PAPERLESS_TIKA_ENDPOINT."
)


def find_java(environ: Mapping[str, str] | None = None) -> Path | None:
    """``PAPERLESS_WIN_JAVA``, ``JAVA_HOME``, then ``java.exe`` on the ``PATH``."""
    environ = os.environ if environ is None else environ
    configured = environ.get("PAPERLESS_WIN_JAVA")
    if configured:
        return Path(configured) if Path(configured).is_file() else None
    home = environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / "java.exe").is_file():
        return Path(home) / "bin" / "java.exe"
    which = shutil.which("java")
    return Path(which) if which else None


def find_tika_jar(environ: Mapping[str, str] | None = None) -> Path | None:
    """``PAPERLESS_WIN_TIKA_JAR``, else a ``tika-server-standard-*.jar`` in the tools folders."""
    environ = os.environ if environ is None else environ
    configured = environ.get("PAPERLESS_WIN_TIKA_JAR")
    if configured:
        return Path(configured) if Path(configured).is_file() else None
    for root in platform.tool_roots():
        for jar in sorted(root.glob("**/tika-server-standard-*.jar"), reverse=True):
            return jar
    return None


def file_uri(path: Path) -> str:
    """``file:///C:/dir/file`` for a path (LibreOffice wants this form for its profile)."""
    return Path(path).resolve().as_uri()


def pdf_export_filter(extension: str, pdfa: str | None) -> str:
    """The value of ``--convert-to``: plain ``pdf``, or the export filter with a PDF/A version."""
    version = PDF_VERSION.get(pdfa or "")
    if version is None:
        return "pdf"
    extension = extension.lower()
    if extension in CALC:
        name = "calc_pdf_Export"
    elif extension in IMPRESS:
        name = "impress_pdf_Export"
    elif extension in DRAW:
        name = "draw_pdf_Export"
    else:
        name = "writer_pdf_Export"
    options = {"SelectPdfVersion": {"type": "long", "value": str(version)}}
    return f"pdf:{name}:{json.dumps(options, separators=(',', ':'))}"


LENGTH = re.compile(r"^\d+(\.\d+)?(in|mm|cm|pt|px|pc)?$")


def page_css(fields: Mapping[str, str]) -> str:
    """An ``@page`` rule from the paper size and margins paperless sends ("8.27in", "0.1in"), so the browser honours them."""

    def length(name: str) -> str | None:
        value = (fields.get(name) or "").strip()
        if not LENGTH.match(value):
            return None
        return (
            value if value[-1].isalpha() else f"{value}in"
        )  # Gotenberg's default unit is the inch

    parts = []
    width, height = length("paperWidth"), length("paperHeight")
    if width and height:
        parts.append(f"size: {width} {height};")
    margins = [length(f"margin{side}") for side in ("Top", "Right", "Bottom", "Left")]
    if all(margins):
        parts.append("margin: " + " ".join(margins) + ";")
    return "@page { " + " ".join(parts) + " }" if parts else ""


def inject_css(html: str, css: str) -> str:
    if not css:
        return html
    style = f"<style>{css}</style>"
    match = re.search(r"</head\s*>", html, re.IGNORECASE)
    if match:
        return html[: match.start()] + style + html[match.start() :]
    return style + html


def merge_pdfs(parts: list[tuple[str, bytes]]) -> bytes:
    """Concatenate PDFs in the order of their names (Gotenberg's rule; paperless numbers them)."""
    import pikepdf

    out = pikepdf.Pdf.new()
    try:
        for _name, data in sorted(parts, key=lambda p: p[0]):
            try:
                with pikepdf.Pdf.open(io.BytesIO(data)) as source:
                    out.pages.extend(source.pages)
            except pikepdf.PdfError as error:
                msg = f"a part to merge is not a readable PDF: {error}"
                raise OfficeError(400, msg) from error
        buffer = io.BytesIO()
        out.save(buffer)
        return buffer.getvalue()
    finally:
        out.close()


def run_tool(argv: list[str], timeout: float) -> tuple[int, str]:
    """Run a program in its own job; on timeout kill it and everything it started. ``(code, output)``."""
    process, job = jobs.launch(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        jobs.kill_tree(job, process.pid)
        process.communicate()
        return -1, f"did not finish within {timeout:.0f} s"
    finally:
        job.close()
    return process.returncode, output or ""


@dataclass
class OfficeConfig:
    soffice: Path | None
    browser: Path | None
    work_dir: Path  # profiles and scratch files
    concurrency: int = 1
    timeout: float = DEFAULT_TIMEOUT
    port: int = DEFAULT_PORT

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> OfficeConfig:
        environ = os.environ if environ is None else environ
        work = environ.get("PAPERLESS_WIN_OFFICE_DIR")
        if not work:
            data = environ.get("PAPERLESS_DATA_DIR")
            work = (
                str(Path(data) / "office")
                if data
                else str(Path(tempfile.gettempdir()) / "paperless-win-office")
            )
        return cls(
            soffice=find_soffice(environ),
            browser=find_browser(environ),
            work_dir=Path(work),
            concurrency=max(
                int(environ.get("PAPERLESS_WIN_OFFICE_CONCURRENCY") or 1),
                1,
            ),
            timeout=float(
                environ.get("PAPERLESS_WIN_OFFICE_TIMEOUT") or DEFAULT_TIMEOUT,
            ),
            port=int(environ.get("PAPERLESS_WIN_OFFICE_PORT") or DEFAULT_PORT),
        )


class Converter:
    """The conversions. One LibreOffice profile per allowed concurrent conversion, reused between calls."""

    def __init__(self, config: OfficeConfig, runner=run_tool) -> None:
        self.config = config
        self.run = runner
        self.slots: queue.Queue[int] = queue.Queue()
        for slot in range(config.concurrency):
            self.slots.put(slot)

    # -- LibreOffice -------------------------------------------------------------------------
    def libreoffice_to_pdf(
        self,
        name: str,
        data: bytes,
        pdfa: str | None = None,
    ) -> bytes:
        soffice = self.config.soffice
        if soffice is None:
            raise OfficeError(503, f"LibreOffice was not found. {INSTALL_HINT}")
        suffix = Path(name).suffix
        if not suffix:
            raise OfficeError(
                400,
                f"the file name '{name}' has no extension, so LibreOffice cannot tell its type",
            )
        slot = self.slots.get()
        try:
            return self._libreoffice(soffice, slot, Path(name).name, suffix, data, pdfa)
        finally:
            self.slots.put(slot)

    def _libreoffice(
        self,
        soffice: Path,
        slot: int,
        name: str,
        suffix: str,
        data: bytes,
        pdfa: str | None,
    ) -> bytes:
        profile = self.config.work_dir / "profiles" / str(slot)
        job_dir = Path(tempfile.mkdtemp(prefix="convert-", dir=self._scratch()))
        try:
            source = job_dir / f"document{suffix.lower()}"
            source.write_bytes(data)
            argv = [
                str(soffice),
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--nodefault",
                "--nologo",
                "--nofirststartwizard",
                f"-env:UserInstallation={file_uri(profile)}",
                "--convert-to",
                pdf_export_filter(suffix, pdfa),
                "--outdir",
                str(job_dir),
                str(source),
            ]
            started = time.monotonic()
            code, output = self.run(argv, self.config.timeout)
            result = job_dir / "document.pdf"
            if code != 0 or not result.is_file():
                # a hung or crashed LibreOffice can leave its profile locked or half written: start over
                shutil.rmtree(profile, ignore_errors=True)
                detail = (
                    output.strip().splitlines()[-1]
                    if output.strip()
                    else f"exit code {code}"
                )
                msg = f"LibreOffice could not convert '{name}': {detail}"
                raise OfficeError(500, msg)
            logger.info(
                "converted %s with LibreOffice in %.1f s",
                name,
                time.monotonic() - started,
            )
            return result.read_bytes()
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    # -- Edge / Chrome -----------------------------------------------------------------------
    def html_to_pdf(self, files: dict[str, bytes], fields: Mapping[str, str]) -> bytes:
        browser = self.config.browser
        if browser is None:
            raise OfficeError(
                503,
                f"No web browser was found to print the e-mail. {BROWSER_HINT}",
            )
        if "index.html" not in files:
            raise OfficeError(400, "the request has no index.html")
        job_dir = Path(tempfile.mkdtemp(prefix="html-", dir=self._scratch()))
        try:
            for name, payload in files.items():
                (job_dir / Path(name).name).write_bytes(payload)
            index = job_dir / "index.html"
            html = index.read_bytes().decode("utf-8", errors="replace")
            index.write_text(inject_css(html, page_css(fields)), encoding="utf-8")
            out = job_dir / "out.pdf"
            argv = [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--allow-file-access-from-files",
                "--no-pdf-header-footer",
                f"--user-data-dir={job_dir / 'browser-profile'}",
                f"--print-to-pdf={out}",
                file_uri(index),
            ]
            started = time.monotonic()
            code, output = self.run(argv, min(self.config.timeout, 120.0))
            if not out.is_file() or out.stat().st_size == 0:
                detail = (
                    output.strip().splitlines()[-1]
                    if output.strip()
                    else f"exit code {code}"
                )
                raise OfficeError(
                    500,
                    f"the browser could not print the page: {detail}",
                )
            logger.info(
                "printed HTML with %s in %.1f s",
                browser.name,
                time.monotonic() - started,
            )
            return out.read_bytes()
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    def _scratch(self) -> Path:
        scratch = self.config.work_dir / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        return scratch

    def warm_up(self) -> None:
        """Make the LibreOffice profiles now (the first start of a profile takes 20 s)."""
        soffice = self.config.soffice
        if soffice is None:
            return
        for _ in range(self.config.concurrency):
            try:
                self.libreoffice_to_pdf("warm-up.txt", b"warm-up")
            except OfficeError as error:
                logger.warning("warm-up conversion failed: %s", error)
                return


# -- the HTTP side ---------------------------------------------------------------------------
@dataclass
class Form:
    files: dict[str, bytes]
    fields: dict[str, str]


def parse_multipart(content_type: str, body: bytes) -> Form:
    message = BytesParser(policy=policy.HTTP).parsebytes(
        b"Content-Type: "
        + content_type.encode("latin-1")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + body,
    )
    form = Form({}, {})
    if not message.is_multipart():
        return form
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            form.files[filename] = payload
        elif name:
            form.fields[str(name)] = payload.decode("utf-8", errors="replace")
    return form


def handle_post(converter: Converter, path: str, form: Form) -> bytes:
    """The PDF for a Gotenberg-style request."""
    logger.debug("%s: files %s, fields %s", path, list(form.files), form.fields)
    if path == "/forms/libreoffice/convert":
        if not form.files:
            raise OfficeError(400, "the request has no file")
        name, data = next(iter(form.files.items()))
        return converter.libreoffice_to_pdf(name, data, form.fields.get("pdfa"))
    if path == "/forms/chromium/convert/html":
        return converter.html_to_pdf(form.files, form.fields)
    if path == "/forms/pdfengines/merge":
        if not form.files:
            raise OfficeError(400, "the request has no file to merge")
        return merge_pdfs(list(form.files.items()))
    raise OfficeError(404, f"paperless-win's office service does not implement {path}")


def make_handler(converter: Converter) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            logger.debug(format, *args)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path.split("?")[0] in {"/health", "/"}:
                state = {
                    "status": "up",
                    "libreoffice": bool(converter.config.soffice),
                    "browser": bool(converter.config.browser),
                }
                self._send(200, json.dumps(state).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                form = parse_multipart(self.headers.get("Content-Type", ""), body)
                pdf = handle_post(converter, self.path.split("?")[0], form)
            except OfficeError as error:
                logger.error("%s: %s", self.path, error)
                self._send(
                    error.status,
                    str(error).encode("utf-8"),
                    "text/plain; charset=utf-8",
                )
            except Exception as error:
                logger.exception("%s failed", self.path)
                self._send(
                    500,
                    f"unexpected error: {error}".encode(),
                    "text/plain; charset=utf-8",
                )
            else:
                self._send(200, pdf, "application/pdf")

    return Handler


def serve(config: OfficeConfig, host: str = "127.0.0.1") -> None:
    config.work_dir.mkdir(parents=True, exist_ok=True)
    converter = Converter(config)
    if config.soffice is None:
        logger.error(
            "LibreOffice was not found: Office documents cannot be converted. %s",
            INSTALL_HINT,
        )
    if config.browser is None:
        logger.error(
            "No browser was found: e-mail HTML cannot be printed. %s",
            BROWSER_HINT,
        )
    server = ThreadingHTTPServer((host, config.port), make_handler(converter))
    server.daemon_threads = True
    threading.Thread(target=converter.warm_up, daemon=True).start()
    logger.info(
        "office service on http://%s:%s (LibreOffice: %s, browser: %s)",
        host,
        config.port,
        config.soffice,
        config.browser,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


# -- error text for gotenberg_client ----------------------------------------------------------
def install_error_details() -> None:
    """Make gotenberg_client's HTTP errors say what the server answered.

    Its ``HttpStatusError`` has no message, so paperless reports "Error while converting document to
    PDF: " and nothing else. With this the text of the reply (for example "LibreOffice was not found.
    Install ...") ends up in the task's error message. Harmless when the library is absent or changes.
    """
    try:
        from gotenberg_client import _errors
    except ImportError:
        return
    cls = getattr(_errors, "HttpStatusError", None)
    if cls is None or getattr(cls, "_winport_detail", False):
        return

    def __str__(self) -> str:
        response = getattr(self, "response", None)
        if response is None:
            return "HTTP error"
        text = ""
        with contextlib.suppress(Exception):
            text = (
                (response.content or b"")
                .decode("utf-8", errors="replace")
                .strip()[:1000]
            )
        status = getattr(response, "status_code", "")
        return f"HTTP {status}: {text}" if text else f"HTTP {status}"

    cls.__str__ = __str__
    cls._winport_detail = True


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [office] %(message)s")
    serve(OfficeConfig.from_environment())
    return 0


if __name__ == "__main__":
    sys.exit(main())
