"""The version comparison of windows/scripts/upstream_watch.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3] / "windows" / "scripts" / "upstream_watch.py"
)

LISTING = (
    "aaa\trefs/tags/v3.5.1\n"
    "bbb\trefs/tags/v3.10.0\n"
    "ccc\trefs/tags/v3.9.9\n"
    "ddd\trefs/tags/v3.11.0-beta.1\n"
    "eee\trefs/tags/not-a-version\n"
)


def load():
    spec = importlib.util.spec_from_file_location("upstream_watch", SCRIPT)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="needs a full checkout")


def test_newest_compares_numbers_not_text_and_ignores_prereleases() -> None:
    watch = load()
    assert watch.newest(watch.tag_names(LISTING)) == (3, 10, 0)
    assert watch.fmt((3, 10, 0)) == "v3.10.0"


def test_nothing_found() -> None:
    watch = load()
    assert watch.newest(watch.tag_names("aaa\trefs/tags/v3.11.0-rc.1\n")) is None
    assert watch.newest([]) is None


def test_the_fork_version_is_read_from_version_py() -> None:
    watch = load()
    version = watch.fork_version(SCRIPT.parents[2] / "src" / "paperless" / "version.py")
    assert len(version) == 3
    assert all(isinstance(n, int) for n in version)
