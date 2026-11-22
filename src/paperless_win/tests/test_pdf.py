from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

import pikepdf
import pytest

from paperless_win import pdf
from paperless_win import platform

if TYPE_CHECKING:
    from pathlib import Path


def make_pdf(
    path: Path,
    *,
    media=(0, 0, 595, 842),
    crop=None,
    rotate=None,
    inherit: bool = False,
) -> Path:
    """One-page PDF with the given boxes. ``inherit`` puts them on /Pages, not the page."""
    doc = pikepdf.new()
    doc.add_blank_page(page_size=(595, 842))
    page = doc.pages[0].obj
    holder = page.Parent if inherit else page
    if inherit:
        del page["/MediaBox"]
    holder["/MediaBox"] = list(media)
    if crop is not None:
        holder["/CropBox"] = list(crop)
    if rotate is not None:
        holder["/Rotate"] = rotate
    doc.save(path)
    return path


# (id, kwargs, expected (width, height) after rotation, per pdfinfo/pdftoppm -cropbox)
CASES = [
    ("a4", {}, (595, 842)),
    ("letter", {"media": (0, 0, 612, 792)}, (612, 792)),
    ("rot90", {"rotate": 90}, (842, 595)),
    ("rot270", {"rotate": 270}, (842, 595)),
    ("rot180", {"rotate": 180}, (595, 842)),
    ("rot_negative", {"rotate": -90}, (842, 595)),
    ("cropbox", {"crop": (10, 20, 310, 420)}, (300, 400)),
    ("cropbox_rotated", {"crop": (0, 0, 200, 400), "rotate": 90}, (400, 200)),
    ("cropbox_clipped", {"crop": (-50, -50, 700, 900)}, (595, 842)),
    ("odd_size", {"media": (0, 0, 100.5, 200.25)}, (100.5, 200.25)),
    ("offset_origin", {"media": (100, 200, 400, 700)}, (300, 500)),
    ("swapped_corners", {"media": (595, 842, 0, 0)}, (595, 842)),
    (
        "inherited",
        {"inherit": True, "media": (0, 0, 300, 400), "rotate": 90},
        (400, 300),
    ),
    ("large", {"media": (0, 0, 5000, 7000)}, (5000, 7000)),
]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_first_page_size_matches_expectation(
    tmp_path: Path,
    kwargs: dict,
    expected: tuple[float, float],
) -> None:
    size = pdf.first_page_size_points(make_pdf(tmp_path / "t.pdf", **kwargs))
    assert size == pytest.approx(expected)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_first_page_size_matches_real_pdfinfo(
    tmp_path: Path,
    kwargs: dict,
    expected: tuple[float, float],
) -> None:
    """Compare with Poppler's pdfinfo itself (skipped where Poppler is not installed)."""
    pdfinfo = platform.find_binary("pdfinfo")
    if pdfinfo is None:
        pytest.skip("pdfinfo not available")
    path = make_pdf(tmp_path / "t.pdf", **kwargs)
    out = subprocess.run(
        [pdfinfo, "-f", "1", "-l", "1", str(path)],
        capture_output=True,
        text=True,
        check=True,
        env={"LC_ALL": "C", "PATH": ""},
    ).stdout
    match = re.search(
        r"^Page\s+1 size:\s+([\d.eE+-]+) x ([\d.eE+-]+) pts",
        out,
        re.MULTILINE,
    )
    assert match is not None, out
    width, height = float(match.group(1)), float(match.group(2))
    rot = re.search(r"^Page\s+1 rot:\s+(\d+)", out, re.MULTILINE)
    if rot and int(rot.group(1)) in (90, 270):
        width, height = height, width
    assert pdf.first_page_size_points(path) == pytest.approx((width, height), abs=0.01)


def test_unreadable_or_pageless_files_give_none(tmp_path: Path) -> None:
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf")
    assert pdf.first_page_size_points(junk) is None
    assert pdf.first_page_size_points(tmp_path / "missing.pdf") is None
    empty = tmp_path / "empty.pdf"
    pikepdf.new().save(empty)
    assert pdf.first_page_size_points(empty) is None


def test_degenerate_box_gives_none(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "t.pdf", media=(0, 0, 0, 0))
    assert pdf.first_page_size_points(path) is None


def test_page_size_hook_declines_on_linux(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", False)
    assert pdf.page_size_hook(make_pdf(tmp_path / "t.pdf")) is NotImplemented


def test_page_size_hook_answers_on_windows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    assert pdf.page_size_hook(make_pdf(tmp_path / "t.pdf")) == pytest.approx((595, 842))


class TestRepair:
    def test_normal_pdf_stays_readable(self, tmp_path: Path) -> None:
        path = make_pdf(tmp_path / "t.pdf")
        pdf.repair_in_place(path)
        with pikepdf.open(path) as doc:
            assert len(doc.pages) == 1

    def test_damaged_pdf_is_repaired(self, tmp_path: Path) -> None:
        """Cut off the xref table and trailer: pdftoppm cannot read this, qpdf can."""
        path = make_pdf(tmp_path / "t.pdf")
        data = path.read_bytes()
        path.write_bytes(data[: data.rindex(b"xref")])
        pdf.repair_in_place(path)
        with pikepdf.open(path) as doc:
            assert len(doc.pages) == 1

    def test_unrecoverable_file_raises_called_process_error(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "junk.pdf"
        path.write_bytes(b"this is not a pdf at all")
        with pytest.raises(subprocess.CalledProcessError):
            pdf.repair_in_place(path)

    def test_encrypted_pdf_with_empty_user_password(self, tmp_path: Path) -> None:
        path = tmp_path / "enc.pdf"
        doc = pikepdf.new()
        doc.add_blank_page()
        doc.save(path, encryption=pikepdf.Encryption(owner="owner", user=""))
        pdf.repair_in_place(path)
        with pikepdf.open(path) as repaired:
            assert len(repaired.pages) == 1

    def test_password_protected_pdf_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "locked.pdf"
        doc = pikepdf.new()
        doc.add_blank_page()
        doc.save(path, encryption=pikepdf.Encryption(owner="o", user="secret"))
        with pytest.raises(subprocess.CalledProcessError):
            pdf.repair_in_place(path)


class TestShim:
    def test_declines_on_linux(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", False)
        args = ["qpdf", "--replace-input", str(make_pdf(tmp_path / "t.pdf"))]
        assert pdf.shim_subprocess(args) is None

    def test_handles_replace_input_on_windows(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", True)
        target = make_pdf(tmp_path / "t.pdf")
        result = pdf.shim_subprocess(
            ["qpdf", "--warning-exit-0", "--replace-input", target],
        )
        assert result is not None
        assert result.returncode == 0

    @pytest.mark.parametrize(
        "args",
        [
            ["pdftoppm", "-png", "a.pdf", "out"],
            [
                "qpdf",
                "--decrypt",
                "--replace-input",
                "a.pdf",
            ],  # options we do not emulate
            ["qpdf", "in.pdf", "out.pdf"],
            ["qpdf"],
            [],
        ],
    )
    def test_declines_everything_else(
        self,
        monkeypatch: pytest.MonkeyPatch,
        args: list,
    ) -> None:
        monkeypatch.setattr(platform, "IS_WINDOWS", True)
        assert pdf.shim_subprocess(args) is None

    def test_run_subprocess_uses_the_shim(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The real hook point: no qpdf executable is started."""
        from documents.utils import run_subprocess

        monkeypatch.setattr(platform, "IS_WINDOWS", True)
        monkeypatch.setenv("PATH", "")
        path = make_pdf(tmp_path / "t.pdf")
        data = path.read_bytes()
        path.write_bytes(data[: data.rindex(b"xref")])
        run_subprocess(["qpdf", "--replace-input", path])
        with pikepdf.open(path) as doc:
            assert len(doc.pages) == 1
