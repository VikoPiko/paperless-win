"""Django system checks for things only a Windows install can get wrong.

Registered when the ``paperless_win`` app is imported (see ``apps.py``). Every check
returns an empty list on Linux, so Docker installs see no change.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Tags
from django.core.checks import Warning as CheckWarning
from django.core.checks import register

from paperless_win import platform


@register(Tags.compatibility)
def unpaper_check(app_configs: Any, **kwargs: Any) -> list[CheckWarning]:
    """``PAPERLESS_OCR_CLEAN=clean`` needs unpaper, which Windows does not ship (D10).

    Without this check every consume would fail with OCRmyPDF's
    ``MissingDependencyError: Could not find program 'unpaper'``, which is correct but
    only visible once a document has already failed.
    """
    if not platform.IS_WINDOWS:
        return []
    if getattr(settings, "OCR_CLEAN", "none") not in {"clean", "clean-final"}:
        return []
    if platform.find_binary("unpaper") is not None:
        return []
    return [
        CheckWarning(
            f"PAPERLESS_OCR_CLEAN={settings.OCR_CLEAN} needs unpaper, which was not found.",
            hint=(
                "unpaper is not bundled with paperless-win. Set PAPERLESS_OCR_CLEAN=none, "
                "or install an unpaper binary and point PAPERLESS_BIN_UNPAPER at it. "
                "Until then every document will fail to consume."
            ),
            id="paperless_win.W001",
        ),
    ]


@register(Tags.compatibility)
def libmagic_check(app_configs: Any, **kwargs: Any) -> list[CheckWarning]:
    """python-magic must find the libmagic DLL (D8), or no file can be identified."""
    if not platform.IS_WINDOWS:
        return []
    try:
        import magic

        magic.from_buffer(b"%PDF-1.7", mime=True)
    except Exception as exc:
        return [
            CheckWarning(
                f"libmagic is not usable ({type(exc).__name__}: {exc}).",
                hint=(
                    "Put libmagic-1.dll and magic.mgc in a folder under PAPERLESS_BIN_DIR "
                    "(the installer does this). Without it no document can be consumed."
                ),
                id="paperless_win.W002",
            ),
        ]
    return []
