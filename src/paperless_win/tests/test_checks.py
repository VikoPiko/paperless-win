from __future__ import annotations

import pytest
from django.core.checks.registry import registry

from paperless_win import checks
from paperless_win import platform


def test_checks_are_silent_on_linux(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", False)
    settings.OCR_CLEAN = "clean"
    assert checks.unpaper_check(None) == []
    assert checks.libmagic_check(None) == []


def test_unpaper_warning_when_clean_requested_without_binary(
    monkeypatch: pytest.MonkeyPatch,
    settings,
) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    monkeypatch.setattr(platform, "find_binary", lambda name: None)
    settings.OCR_CLEAN = "clean"
    messages = checks.unpaper_check(None)
    assert [m.id for m in messages] == ["paperless_win.W001"]
    assert "PAPERLESS_OCR_CLEAN=none" in messages[0].hint


@pytest.mark.parametrize(
    ("clean", "have_binary"),
    [("none", False), ("clean", True), ("clean-final", True)],
)
def test_no_unpaper_warning_when_not_needed(
    monkeypatch: pytest.MonkeyPatch,
    settings,
    clean: str,
    *,
    have_binary: bool,
) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    monkeypatch.setattr(
        platform,
        "find_binary",
        lambda name: "unpaper.exe" if have_binary else None,
    )
    settings.OCR_CLEAN = clean
    assert checks.unpaper_check(None) == []


def test_libmagic_warning_when_magic_is_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    import magic

    monkeypatch.setattr(platform, "IS_WINDOWS", True)

    def boom(*args, **kwargs):
        raise OSError("no dll")

    monkeypatch.setattr(magic, "from_buffer", boom)
    assert [m.id for m in checks.libmagic_check(None)] == ["paperless_win.W002"]


def test_checks_are_registered_with_django() -> None:
    assert checks.unpaper_check in registry.registered_checks
    assert checks.libmagic_check in registry.registered_checks
