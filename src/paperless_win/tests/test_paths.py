from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath

import pytest

from paperless_win import paths
from paperless_win import platform

RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10))}
RESERVED |= {f"LPT{i}" for i in range(1, 10)}
ILLEGAL = set('<>:"\\|?*') | {chr(c) for c in range(32)}


def is_legal_ntfs_component(name: str) -> bool:
    """Independent re-statement of the NTFS rules, used to check our output."""
    if not name or name != name.rstrip(". ") or set(name) & ILLEGAL:
        return False
    return name.split(".", maxsplit=1)[0].upper() not in RESERVED


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    monkeypatch.delenv("PAPERLESS_WIN_MAX_PATH", raising=False)


@pytest.fixture
def linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", False)


class TestToAndFromDb:
    def test_to_db_is_posix_for_pure_paths(self) -> None:
        assert paths.to_db(PurePosixPath("2024/ACME/Invoice.pdf")) == (
            "2024/ACME/Invoice.pdf"
        )

    def test_to_db_accepts_both_separators_on_windows(self, windows: None) -> None:
        assert paths.to_db("2024\\ACME\\Invoice.pdf") == "2024/ACME/Invoice.pdf"
        assert paths.to_db("2024/ACME/Invoice.pdf") == "2024/ACME/Invoice.pdf"

    def test_to_db_keeps_backslash_on_linux(self, linux: None) -> None:
        # a backslash is an ordinary character in a Linux file name
        assert paths.to_db("a\\b.pdf") == "a\\b.pdf"

    @pytest.mark.parametrize("absolute", ["/etc/passwd", "C:/Users/x.pdf", "C:\\x.pdf"])
    def test_to_db_rejects_absolute_paths(self, windows: None, absolute: str) -> None:
        with pytest.raises(ValueError, match="relative"):
            paths.to_db(absolute)

    def test_from_db_tolerates_backslashes_on_windows(self, windows: None) -> None:
        assert paths.from_db("a\\b\\c.pdf").parts[-3:] == ("a", "b", "c.pdf")
        assert paths.from_db("a/b/c.pdf").parts[-3:] == ("a", "b", "c.pdf")

    def test_from_db_leaves_linux_rows_alone(self, linux: None) -> None:
        assert paths.from_db("a\\b.pdf") == Path("a\\b.pdf")


class TestSanitizeComponent:
    @pytest.mark.parametrize(
        "name",
        [
            "CON",
            "con",
            "aux.",
            "AUX.txt",
            "NUL",
            "COM1",
            "lpt9",
            "foo  ",
            "foo.",
            "a:b*c?",
            '"q"',
            "a<b>c|d",
            "tab\there",
            "...",
        ],
    )
    def test_windows_output_is_always_legal(self, windows: None, name: str) -> None:
        assert is_legal_ntfs_component(paths.sanitize_component(name)), name

    def test_ordinary_names_are_untouched(self, windows: None) -> None:
        for name in ("Invoice", "ACME Corp", "Müller", "2024-01-05", "a.b.c", "日本語"):
            assert paths.sanitize_component(name) == name

    def test_dot_components_are_left_for_the_safety_check(self, windows: None) -> None:
        assert paths.sanitize_component("..") == ".."

    def test_empty_result_becomes_underscore(self, windows: None) -> None:
        assert paths.sanitize_component("???") == "___"
        assert paths.sanitize_component(" ") != ""

    def test_linux_is_identity(self, linux: None) -> None:
        for name in ("CON", "aux.", "a:b*c?", "foo  "):
            assert paths.sanitize_component(name) == name


class TestSanitizeRelativePath:
    def test_every_component_is_sanitised(self, windows: None) -> None:
        result = paths.sanitize_relative_path("2024/CON/foo  /a:b*c?")
        assert all(is_legal_ntfs_component(p) for p in result.split("/"))
        assert result.startswith("2024/")

    def test_separators_stay_slashes(self, windows: None) -> None:
        assert "\\" not in paths.sanitize_relative_path("a/b/c")

    def test_linux_identity(self, linux: None) -> None:
        assert paths.sanitize_relative_path("a/CON/b") == "a/CON/b"


class TestMaxPath:
    ROOT = Path("C:/ProgramData/paperless-win/media/documents/originals")

    def test_short_paths_pass_through(self, windows: None) -> None:
        assert paths.shorten_to_fit(self.ROOT, "2024/ACME/Invoice") == (
            "2024/ACME/Invoice"
        )

    def test_long_title_is_truncated_and_fits(self, windows: None) -> None:
        rel = "2024/ACME/" + "x" * 400
        result = paths.shorten_to_fit(self.ROOT, rel)
        assert result is not None
        assert result.startswith("2024/ACME/x")
        assert paths.fits_max_path(self.ROOT, result, reserve=paths.DEFAULT_RESERVE)
        assert len(str(self.ROOT / result)) + 4 <= paths.max_path()  # ".pdf" fits too

    def test_directories_are_never_touched(self, windows: None) -> None:
        result = paths.shorten_to_fit(self.ROOT, "a" * 20 + "/" + "b" * 400)
        assert result is not None
        assert result.startswith("a" * 20 + "/")

    def test_returns_none_when_nothing_fits(self, windows: None) -> None:
        assert paths.shorten_to_fit(self.ROOT, ("d" * 100 + "/") * 3 + "file") is None

    def test_limit_is_configurable(
        self,
        windows: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rel = "a/" + "x" * 400
        monkeypatch.setenv("PAPERLESS_WIN_MAX_PATH", "32000")
        assert paths.shorten_to_fit(self.ROOT, rel) == rel

    def test_trailing_dot_after_truncation_is_removed(self, windows: None) -> None:
        rel = "d/" + "x" * 150 + "." + "y" * 400
        result = paths.shorten_to_fit(self.ROOT, rel)
        assert result is not None
        assert is_legal_ntfs_component(result.rpartition("/")[2])


class TestFinalize:
    def test_linux_returns_input_even_when_long(self, linux: None) -> None:
        rel = "CON/" + "x" * 1000
        assert paths.finalize_relative_path(rel, Path("/root")) == rel

    def test_windows_sanitises_then_shortens(self, windows: None) -> None:
        root = Path("C:/m/documents/originals")
        result = paths.finalize_relative_path("CON/" + "x" * 1000, root)
        assert result is not None
        first, _, rest = result.partition("/")
        assert is_legal_ntfs_component(first)
        assert paths.fits_max_path(root, result, reserve=paths.DEFAULT_RESERVE)
        assert rest.startswith("x")


class TestManifestRecords:
    def test_backslashes_become_slashes_on_windows(self, windows: None) -> None:
        record = {
            "model": "documents.document",
            "__exported_file_name__": "2024\\ACME\\a.pdf",
            "__exported_thumbnail_name__": "t\\a.webp",
            "__exported_archive_name__": None,
            "fields": {
                "filename": "2024\\ACME\\a.pdf",
                "archive_filename": "x/y.pdf",
                "title": "a\\b",
            },
        }
        result = paths.normalize_manifest_record(record)
        assert result["__exported_file_name__"] == "2024/ACME/a.pdf"
        assert result["__exported_thumbnail_name__"] == "t/a.webp"
        assert result["__exported_archive_name__"] is None
        assert result["fields"]["filename"] == "2024/ACME/a.pdf"
        assert result["fields"]["archive_filename"] == "x/y.pdf"
        assert result["fields"]["title"] == "a\\b"  # only path fields are touched

    def test_linux_records_are_untouched(self, linux: None) -> None:
        record = {
            "__exported_file_name__": "odd\\name.pdf",
            "fields": {"filename": "odd\\name.pdf"},
        }
        assert paths.normalize_manifest_record(record) == {
            "__exported_file_name__": "odd\\name.pdf",
            "fields": {"filename": "odd\\name.pdf"},
        }

    def test_records_without_paths_pass_through(self, windows: None) -> None:
        assert paths.normalize_manifest_record(
            {"model": "documents.tag", "fields": {}},
        ) == {
            "model": "documents.tag",
            "fields": {},
        }
