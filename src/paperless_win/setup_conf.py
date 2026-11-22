"""Write ``paperless.conf`` for a new installation (``paperless-ctl setup``).

Called by the installer, so the logic lives here (testable, no Pascal string handling). Rules:

* The file is created once. On an upgrade it is left alone, so the secret key and every setting
  the user changed survive; ``--force`` rewrites it but keeps the existing secret key.
* The admin password is never written to it: ``paperless-ctl init --admin-password-file`` passes
  it to the one process that creates the account.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

SECRET_RE = re.compile(r"^PAPERLESS_SECRET_KEY=(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class ConfValues:
    data_dir: Path
    consume_dir: Path | None = None
    media_dir: Path | None = None
    ocr_languages: str = "eng"
    port: int = 8000
    bind: str = "127.0.0.1"
    redis_port: int = 6379
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def consume(self) -> Path:
        return self.consume_dir or self.data_dir / "consume"

    @property
    def media(self) -> Path:
        return self.media_dir or self.data_dir / "media"


def new_secret_key() -> str:
    return secrets.token_urlsafe(50)


def existing_secret_key(conf: Path) -> str | None:
    try:
        match = SECRET_RE.search(conf.read_text(encoding="utf-8"))
    except OSError:
        return None
    return match.group(1).strip() if match else None


def render_conf(values: ConfValues, secret_key: str) -> str:
    lines = [
        "# paperless-win configuration, written by `paperless-ctl setup`.",
        "# Edit freely and restart the service. Every setting is documented in the paperless-ngx",
        "# configuration docs (https://docs.paperless-ngx.com/configuration/).",
        f"PAPERLESS_DATA_DIR={values.data_dir}",
        f"PAPERLESS_MEDIA_ROOT={values.media}",
        f"PAPERLESS_CONSUMPTION_DIR={values.consume}",
        f"PAPERLESS_SCRATCH_DIR={values.data_dir / 'scratch'}",
        f"PAPERLESS_STATICDIR={values.data_dir / 'static'}",
        f"PAPERLESS_LOGGING_DIR={values.data_dir / 'logs'}",
        f"PAPERLESS_REDIS=redis://127.0.0.1:{values.redis_port}",
        f"PAPERLESS_SECRET_KEY={secret_key}",
        f"PAPERLESS_OCR_LANGUAGE={values.ocr_languages}",
        f"PAPERLESS_PORT={values.port}",
        f"PAPERLESS_BIND_ADDR={values.bind}",
        "PAPERLESS_APP_TITLE=paperless-win",  # the title in the browser; upstream setting, no UI change
    ]
    lines.extend(f"{key}={value}" for key, value in sorted(values.extra.items()))
    return "\n".join(lines) + "\n"


def write_conf(conf: Path, values: ConfValues, *, force: bool = False) -> str:
    """Create ``conf``. Returns ``"created"``, ``"kept"`` (already there) or ``"rewritten"``."""
    existed = conf.exists()
    if existed and not force:
        return "kept"
    secret = existing_secret_key(conf) if existed else None
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(render_conf(values, secret or new_secret_key()), encoding="utf-8")
    return "rewritten" if existed else "created"


def read_admin_password(path: Path) -> str:
    """Read the password from a file written by the installer, then delete the file."""
    text = path.read_text(encoding="utf-8-sig")
    try:
        path.unlink()
    except OSError:
        pass
    return text.rstrip("\r\n")
