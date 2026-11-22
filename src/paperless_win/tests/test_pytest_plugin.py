from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from paperless_win import pytest_plugin as plugin

if TYPE_CHECKING:
    from pathlib import Path


def test_matches_exact_prefix_and_params() -> None:
    patterns = ["src/a/test_x.py::TestA::test_one", "src/b/test_y.py"]
    assert plugin.matches("src/a/test_x.py::TestA::test_one", patterns)
    assert plugin.matches("src/a/test_x.py::TestA::test_one[param]", patterns)
    assert plugin.matches("src\\b\\test_y.py::TestB::test_two", patterns)
    assert not plugin.matches("src/a/test_x.py::TestA::test_one_more", patterns)
    assert not plugin.matches("src/a/test_x.py::TestA::test_two", patterns)
    assert not plugin.matches("src/b/test_yy.py::TestB::test_two", patterns)


def test_entries_require_reason_and_follow_up(tmp_path: Path) -> None:
    bad = tmp_path / "skips.toml"
    bad.write_text('[[skip]]\ntests = ["x"]\nreason = "r"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="follow_up"):
        plugin.load_entries(bad)


def test_missing_file_means_no_skips(tmp_path: Path) -> None:
    assert plugin.load_entries(tmp_path / "nope.toml") == []


def test_checked_in_list_is_valid() -> None:
    assert isinstance(plugin.load_entries(), list)
