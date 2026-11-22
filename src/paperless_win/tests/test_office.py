"""Office documents and e-mail without Gotenberg (P8): the converter, its HTTP side and the stack wiring."""

from __future__ import annotations

import io
import json
import sys
import threading
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

import pikepdf
import pytest

from paperless_win import office
from paperless_win import stack


def make_pdf(pages: int = 1) -> bytes:
    pdf = pikepdf.Pdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(200, 200))
    buffer = io.BytesIO()
    pdf.save(buffer)
    return buffer.getvalue()


class FakeTools:
    """Stands in for soffice and the browser: records the command line, writes the output file."""

    def __init__(self, *, code: int = 0, write: bool = True, text: str = "") -> None:
        self.calls: list[list[str]] = []
        self.code = code
        self.write = write
        self.text = text

    def __call__(self, argv: list[str], timeout: float) -> tuple[int, str]:
        self.calls.append(argv)
        if self.write:
            if "--convert-to" in argv:
                outdir = Path(argv[argv.index("--outdir") + 1])
                (outdir / "document.pdf").write_bytes(make_pdf())
            else:
                target = next(a for a in argv if a.startswith("--print-to-pdf="))
                Path(target.split("=", 1)[1]).write_bytes(make_pdf())
        return self.code, self.text


def config(tmp_path: Path, **overrides) -> office.OfficeConfig:
    values = {
        "soffice": Path("C:/LibreOffice/program/soffice.exe"),
        "browser": Path("C:/Edge/msedge.exe"),
        "work_dir": tmp_path / "office",
        "concurrency": 1,
        "timeout": 30.0,
        "port": 0,
    }
    values.update(overrides)
    return office.OfficeConfig(**values)


# -- finding the programs ----------------------------------------------------------------------
def test_configured_paths_are_used_only_if_the_file_exists(tmp_path: Path) -> None:
    soffice = tmp_path / "soffice.exe"
    soffice.write_text("x")
    assert office.find_soffice({"PAPERLESS_WIN_SOFFICE": str(soffice)}) == soffice
    assert (
        office.find_soffice({"PAPERLESS_WIN_SOFFICE": str(tmp_path / "nope.exe")})
        is None
    )
    browser = tmp_path / "msedge.exe"
    browser.write_text("x")
    assert office.find_browser({"PAPERLESS_WIN_BROWSER": str(browser)}) == browser
    assert (
        office.find_browser({"PAPERLESS_WIN_BROWSER": str(tmp_path / "x.exe")}) is None
    )


def test_the_program_files_folder_is_found_even_when_the_shell_hides_x86(
    tmp_path: Path,
) -> None:
    edge = (
        tmp_path
        / "Program Files (x86)"
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe"
    )
    edge.parent.mkdir(parents=True)
    edge.write_text("x")
    # no ProgramFiles(x86) variable at all, only the system drive
    assert office.find_browser({"SystemDrive": str(tmp_path)}) == edge


def test_java_comes_from_the_setting_then_java_home(tmp_path: Path) -> None:
    java = tmp_path / "jdk" / "bin" / "java.exe"
    java.parent.mkdir(parents=True)
    java.write_text("x")
    assert office.find_java({"JAVA_HOME": str(tmp_path / "jdk")}) == java
    assert office.find_java({"PAPERLESS_WIN_JAVA": str(java)}) == java
    assert office.find_java({"PAPERLESS_WIN_JAVA": str(tmp_path / "no.exe")}) is None


def test_the_tika_jar_is_found_by_setting_or_in_the_tool_folders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jar = tmp_path / "tools" / "tika" / "tika-server-standard-3.3.3.jar"
    jar.parent.mkdir(parents=True)
    jar.write_text("x")
    assert office.find_tika_jar({"PAPERLESS_WIN_TIKA_JAR": str(jar)}) == jar
    monkeypatch.setattr(office.platform, "tool_roots", lambda: [tmp_path / "tools"])
    assert office.find_tika_jar({}) == jar
    monkeypatch.setattr(office.platform, "tool_roots", lambda: [tmp_path / "empty"])
    assert office.find_tika_jar({}) is None


# -- LibreOffice -------------------------------------------------------------------------------
def test_pdfa_needs_the_export_filter_of_the_document_type() -> None:
    assert office.pdf_export_filter(".docx", None) == "pdf"
    assert office.pdf_export_filter(".docx", "unknown") == "pdf"
    writer = office.pdf_export_filter(".DOCX", "PDF/A-2b")
    assert writer.startswith("pdf:writer_pdf_Export:")
    assert json.loads(writer.split(":", 2)[2]) == {
        "SelectPdfVersion": {"type": "long", "value": "2"},
    }
    assert office.pdf_export_filter(".xlsx", "PDF/A-3b").startswith(
        "pdf:calc_pdf_Export:",
    )
    assert office.pdf_export_filter(".pptx", "PDF/A-1b").startswith(
        "pdf:impress_pdf_Export:",
    )


def test_a_conversion_runs_soffice_on_a_kept_profile(tmp_path: Path) -> None:
    tools = FakeTools()
    converter = office.Converter(config(tmp_path), tools)
    pdf = converter.libreoffice_to_pdf("Report.DOCX", b"data", "PDF/A-2b")
    assert pikepdf.Pdf.open(io.BytesIO(pdf)).pages
    argv = tools.calls[0]
    assert "--headless" in argv
    assert "--nolockcheck" in argv
    profile = next(a for a in argv if a.startswith("-env:UserInstallation="))
    assert profile.endswith(
        "/profiles/0",
    )  # kept between calls: a new profile costs about 20 s
    assert argv[argv.index("--convert-to") + 1].startswith("pdf:writer_pdf_Export:")
    converter.libreoffice_to_pdf("another.docx", b"data")
    assert (
        next(a for a in tools.calls[1] if a.startswith("-env:UserInstallation="))
        == profile
    )
    assert not list((tmp_path / "office" / "scratch").iterdir())  # no leftovers


def test_missing_libreoffice_says_what_to_install(tmp_path: Path) -> None:
    converter = office.Converter(config(tmp_path, soffice=None), FakeTools())
    with pytest.raises(office.OfficeError) as error:
        converter.libreoffice_to_pdf("a.docx", b"x")
    assert error.value.status == 503
    assert "LibreOffice was not found" in str(error.value)
    assert "libreoffice.org/download" in str(error.value)
    assert "PAPERLESS_WIN_SOFFICE" in str(error.value)


def test_a_file_without_extension_is_refused(tmp_path: Path) -> None:
    with pytest.raises(office.OfficeError, match="no extension") as error:
        office.Converter(config(tmp_path), FakeTools()).libreoffice_to_pdf(
            "noext",
            b"x",
        )
    assert error.value.status == 400


def test_a_failed_conversion_throws_the_profile_away(tmp_path: Path) -> None:
    converter = office.Converter(
        config(tmp_path),
        FakeTools(code=-1, write=False, text="did not finish within 30 s"),
    )
    profile = tmp_path / "office" / "profiles" / "0"
    profile.mkdir(parents=True)
    (profile / "lock").write_text("stale")
    with pytest.raises(
        office.OfficeError,
        match=r"could not convert 'a\.docx': did not finish",
    ) as error:
        converter.libreoffice_to_pdf("a.docx", b"x")
    assert error.value.status == 500
    assert (
        not profile.exists()
    )  # a hung LibreOffice may leave it locked: the next call starts clean
    # and the slot is free again
    assert converter.slots.qsize() == 1


def test_each_allowed_conversion_has_its_own_profile(tmp_path: Path) -> None:
    converter = office.Converter(config(tmp_path, concurrency=2), FakeTools())
    assert sorted(converter.slots.queue) == [0, 1]


# -- the browser -------------------------------------------------------------------------------
def test_html_is_printed_with_the_paper_size_and_margins_of_the_request(
    tmp_path: Path,
) -> None:
    printed: list[str] = []

    def tools(argv: list[str], timeout: float) -> tuple[int, str]:
        index = Path(
            next(a for a in argv if a.endswith("index.html")).removeprefix("file:///"),
        )
        printed.append(index.read_text(encoding="utf-8") if index.exists() else "")
        target = next(a for a in argv if a.startswith("--print-to-pdf="))
        Path(target.split("=", 1)[1]).write_bytes(make_pdf())
        return 0, ""

    converter = office.Converter(config(tmp_path), tools)
    fields = {
        "paperWidth": "8.27in",
        "paperHeight": "11.7in",
        "marginTop": "0.1in",
        "marginRight": "0.1in",
        "marginBottom": "0.1in",
        "marginLeft": "0.1in",
    }
    converter.html_to_pdf(
        {
            "index.html": b"<html><head></head><body>hi</body></html>",
            "logo.png": b"png",
        },
        fields,
    )
    assert (
        "@page { size: 8.27in 11.7in; margin: 0.1in 0.1in 0.1in 0.1in; }" in printed[0]
    )
    assert "<body>hi</body>" in printed[0]


def test_page_css_accepts_units_and_ignores_rubbish() -> None:
    assert office.page_css({}) == ""
    assert (
        office.page_css({"paperWidth": "210mm", "paperHeight": "297mm"})
        == "@page { size: 210mm 297mm; }"
    )
    assert (
        office.page_css({"paperWidth": "8.5", "paperHeight": "11"})
        == "@page { size: 8.5in 11in; }"
    )
    assert office.page_css({"paperWidth": "red", "paperHeight": "11in"}) == ""
    assert office.inject_css("<p>no head</p>", "@page { }").startswith("<style>")


def test_html_without_a_browser_says_what_to_install(tmp_path: Path) -> None:
    with pytest.raises(office.OfficeError, match="Microsoft Edge") as error:
        office.Converter(config(tmp_path, browser=None), FakeTools()).html_to_pdf(
            {"index.html": b"x"},
            {},
        )
    assert error.value.status == 503


def test_html_needs_an_index_file(tmp_path: Path) -> None:
    with pytest.raises(office.OfficeError, match=r"no index\.html"):
        office.Converter(config(tmp_path), FakeTools()).html_to_pdf(
            {"other.html": b"x"},
            {},
        )


# -- merging -------------------------------------------------------------------------------------
def test_parts_are_merged_in_the_order_of_their_names() -> None:
    merged = office.merge_pdfs(
        [("00002_b.pdf", make_pdf(3)), ("00001_a.pdf", make_pdf(1))],
    )
    assert len(pikepdf.Pdf.open(io.BytesIO(merged)).pages) == 4
    with pytest.raises(office.OfficeError, match="not a readable PDF"):
        office.merge_pdfs([("00001_a.pdf", b"not a pdf")])


# -- running programs ----------------------------------------------------------------------------
def test_a_hanging_program_is_killed_after_the_timeout() -> None:
    code, text = office.run_tool(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        1,
    )
    assert code == -1
    assert "did not finish within 1 s" in text


def test_a_program_that_finishes_returns_its_output() -> None:
    code, text = office.run_tool([sys.executable, "-c", "print('hello')"], 30)
    assert (code, text.strip()) == (0, "hello")


# -- the HTTP side -------------------------------------------------------------------------------
def multipart(
    files: dict[str, bytes],
    fields: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in (fields or {}).items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    for name, data in files.items():
        body += (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + data
            + b"\r\n"
        )
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


@pytest.fixture
def server(tmp_path: Path):
    converter = office.Converter(config(tmp_path), FakeTools())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), office.make_handler(converter))
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield converter, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def post(
    base: str,
    path: str,
    files: dict[str, bytes],
    fields: dict[str, str] | None = None,
):
    body, content_type = multipart(files, fields)
    request = urllib.request.Request(
        base + path,
        data=body,
        headers={"Content-Type": content_type},
    )
    return urllib.request.urlopen(request, timeout=30)


def test_form_files_and_fields_are_parsed() -> None:
    body, content_type = multipart({"a.docx": b"\x00\x01"}, {"pdfa": "PDF/A-2b"})
    form = office.parse_multipart(content_type, body)
    assert form.files == {"a.docx": b"\x00\x01"}
    assert form.fields == {"pdfa": "PDF/A-2b"}


def test_the_service_answers_the_three_routes(server) -> None:
    _converter, base = server
    with urllib.request.urlopen(base + "/health", timeout=10) as health:
        state = json.loads(health.read())
    assert state == {"status": "up", "libreoffice": True, "browser": True}
    with post(
        base,
        "/forms/libreoffice/convert",
        {"a.docx": b"data"},
        {"pdfa": "PDF/A-2b"},
    ) as reply:
        assert reply.headers["Content-Type"] == "application/pdf"
        assert reply.read().startswith(b"%PDF")
    with post(
        base,
        "/forms/chromium/convert/html",
        {"index.html": b"<html></html>"},
    ) as reply:
        assert reply.read().startswith(b"%PDF")
    with post(
        base,
        "/forms/pdfengines/merge",
        {"00001_a.pdf": make_pdf(), "00002_b.pdf": make_pdf()},
    ) as reply:
        assert len(pikepdf.Pdf.open(io.BytesIO(reply.read())).pages) == 2


def test_errors_come_back_as_text_with_the_right_status(server) -> None:
    converter, base = server
    with pytest.raises(urllib.error.HTTPError) as unknown:
        post(base, "/forms/nothing", {"a": b"x"})
    assert unknown.value.code == 404
    converter.config.soffice = None
    with pytest.raises(urllib.error.HTTPError) as missing:
        post(base, "/forms/libreoffice/convert", {"a.docx": b"x"})
    assert missing.value.code == 503
    assert "LibreOffice was not found" in missing.value.read().decode()


def test_gotenberg_client_errors_show_what_the_service_said(server) -> None:
    """paperless reports ``Error while converting document to PDF: <the client's error>``."""
    gotenberg_client = pytest.importorskip("gotenberg_client")
    office.install_error_details()
    converter, base = server
    converter.config.soffice = None
    sample = Path(__file__).parent / "office-sample.docx"
    sample.write_bytes(b"not really a document")
    try:
        with (
            gotenberg_client.GotenbergClient(host=base, timeout=30) as client,
            client.libre_office.to_pdf() as route,
        ):
            route.convert(sample)
            with pytest.raises(Exception, match="LibreOffice was not found") as error:
                route.run()
    finally:
        sample.unlink(missing_ok=True)
    assert "503" in str(error.value)
    assert "PAPERLESS_WIN_SOFFICE" in str(error.value)


# -- the stack: what is started and where paperless is pointed -----------------------------------
class Settings:
    TIKA_ENABLED = True
    LOGGING_DIR = "logs"
    TASK_WORKERS = 1
    CELERY_TASK_TIME_LIMIT = 1800


def office_config(
    tmp_path: Path,
    environ: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> stack.StackConfig:
    java = tmp_path / "java.exe"
    jar = tmp_path / "tika-server-standard-3.3.3.jar"
    java.write_text("x")
    jar.write_text("x")
    monkeypatch.setattr(office, "find_java", lambda _e=None: java)
    monkeypatch.setattr(office, "find_tika_jar", lambda _e=None: jar)
    return stack.StackConfig.from_settings(Settings(), environ)


def test_nothing_extra_starts_unless_tika_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Off(Settings):
        TIKA_ENABLED = False

    cfg = stack.StackConfig.from_settings(Off(), {})
    assert not cfg.office
    assert not cfg.tika
    assert [s.name for s in stack.build_specs(cfg, {})].count("office") == 0


def test_tika_enabled_starts_tika_and_the_office_service_and_points_paperless_at_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = office_config(tmp_path, {}, monkeypatch)
    specs = {s.name: s for s in stack.build_specs(cfg, {})}
    assert "tika" in specs
    assert "office" in specs
    assert specs["tika"].argv[1:3] == ["-jar", cfg.tika_jar]
    assert "9998" in specs["tika"].argv
    assert specs["office"].argv[-2:] == ["-m", "paperless_win.office"]
    # workers need them to the end: they stop with the broker, after the workers
    assert specs["office"].stop_phase == stack.PHASE_BROKER
    env = stack.child_environment(cfg)
    assert env["PAPERLESS_TIKA_ENDPOINT"] == "http://127.0.0.1:9998"
    assert env["PAPERLESS_TIKA_GOTENBERG_ENDPOINT"] == "http://127.0.0.1:3000"
    order = [s.name for s in stack.build_specs(cfg, {})]
    assert order.index("office") < order.index(
        "web",
    )  # ready before anything can ask for a conversion


def test_servers_the_user_named_are_left_alone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environ = {
        "PAPERLESS_TIKA_ENDPOINT": "http://tika.local:9998",
        "PAPERLESS_TIKA_GOTENBERG_ENDPOINT": "http://gotenberg.local:3000",
    }
    cfg = office_config(tmp_path, environ, monkeypatch)
    assert not cfg.office
    assert not cfg.tika
    assert stack.office_warnings(cfg, environ) == []
    env = stack.child_environment(cfg)
    assert (
        env.get("PAPERLESS_TIKA_ENDPOINT") != "http://127.0.0.1:9998"
    )  # not overwritten by us


def test_the_external_converter_setting_turns_our_service_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = office_config(
        tmp_path,
        {"PAPERLESS_WIN_OFFICE_CONVERTER": "external"},
        monkeypatch,
    )
    assert not cfg.office
    assert cfg.tika


def test_a_missing_part_is_explained_with_what_to_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(office, "find_java", lambda _e=None: None)
    monkeypatch.setattr(office, "find_tika_jar", lambda _e=None: None)
    monkeypatch.setattr(office, "find_soffice", lambda _e=None: None)
    monkeypatch.setattr(office, "find_browser", lambda _e=None: None)
    cfg = stack.StackConfig.from_settings(Settings(), {})
    text = "\n".join(stack.office_warnings(cfg, {}))
    assert "LibreOffice was not found" in text
    assert "no web browser" in text
    assert "no Java runtime" in text
    assert "tika-server-standard" in text
