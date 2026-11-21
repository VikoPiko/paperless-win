"""Storage-path behaviour end to end (Django models, filename templates, rename signal)."""

from __future__ import annotations

import json
import sys
import uuid
from typing import TYPE_CHECKING

import pytest
from django.core.management import call_command

from documents.file_handling import generate_filename
from documents.file_handling import generate_unique_filename
from documents.models import Correspondent
from documents.models import Document
from paperless_win import platform
from paperless_win.tests.test_paths import is_legal_ntfs_component

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

TEMPLATE = "{{ created_year }}/{{ correspondent }}/{{ title }}"


@pytest.fixture
def originals(settings: SettingsWrapper, tmp_path: Path) -> Path:
    settings.ORIGINALS_DIR = tmp_path / "documents" / "originals"
    settings.ARCHIVE_DIR = tmp_path / "documents" / "archive"
    settings.ORIGINALS_DIR.mkdir(parents=True)
    settings.ARCHIVE_DIR.mkdir(parents=True)
    settings.FILENAME_FORMAT = TEMPLATE
    return settings.ORIGINALS_DIR


def make_doc(title: str = "Invoice", correspondent: str | None = "ACME") -> Document:
    corr = Correspondent.objects.create(name=correspondent) if correspondent else None
    return Document.objects.create(
        title=title,
        mime_type="application/pdf",
        checksum=uuid.uuid4().hex,
        correspondent=corr,
    )


def test_nested_template_is_posix(originals: Path) -> None:
    doc = make_doc()
    year = doc.created.year
    assert generate_filename(doc).as_posix() == f"{year}/ACME/Invoice.pdf"


@pytest.mark.parametrize("fmt", ["/" + TEMPLATE, TEMPLATE + "/", "/" + TEMPLATE + "/"])
def test_leading_and_trailing_slashes_are_stripped(
    originals: Path,
    settings,
    fmt: str,
) -> None:
    settings.FILENAME_FORMAT = fmt
    doc = make_doc()
    assert generate_filename(doc).as_posix() == f"{doc.created.year}/ACME/Invoice.pdf"


def test_remove_none_placeholders_strip_slashes(originals: Path, settings) -> None:
    settings.FILENAME_FORMAT_REMOVE_NONE = True
    doc = make_doc(correspondent=None)
    assert generate_filename(doc).as_posix() == f"{doc.created.year}/Invoice.pdf"


@pytest.mark.parametrize(
    "name",
    ["CON", "aux.", "foo  ", "a:b*c?", "NUL", "com1", "x|y"],
)
def test_every_component_is_legal_on_ntfs(
    originals: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    doc = make_doc(title=name, correspondent=name)
    parts = generate_filename(doc).as_posix().split("/")
    assert len(parts) == 3
    assert all(is_legal_ntfs_component(p) for p in parts), parts


def test_overlong_title_fits_max_path_and_keeps_extension(
    originals: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    doc = make_doc(title="T" * 600)
    result = generate_unique_filename(doc)
    assert result.suffix == ".pdf"
    assert len(str(originals / result)) <= 259


def test_unfittable_template_falls_back_to_id_naming(
    originals: Path,
    settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    monkeypatch.setenv("PAPERLESS_WIN_MAX_PATH", str(len(str(originals)) + 10))
    doc = make_doc()
    assert generate_filename(doc).as_posix() == f"{doc.pk:07}.pdf"


def test_database_stores_posix_after_rename(originals: Path) -> None:
    """The rename signal must persist 'a/b/c.pdf', never 'a\\b\\c.pdf' (P1 finding)."""
    doc = make_doc()
    (originals / "scratch").mkdir()
    # The original lives at the ID-based name until the first save with a template
    Document.objects.filter(pk=doc.pk).update(filename=f"{doc.pk:07}.pdf")
    (originals / f"{doc.pk:07}.pdf").write_bytes(b"%PDF-1.4")
    doc.refresh_from_db()
    doc.save()
    stored = Document.objects.get(pk=doc.pk).filename
    assert stored == f"{doc.created.year}/ACME/Invoice.pdf"
    assert "\\" not in stored
    assert (originals / stored).is_file()


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="needs a case-insensitive filesystem",
)
def test_case_only_difference_is_a_collision_on_windows(
    originals: Path,
    settings,
) -> None:
    settings.FILENAME_FORMAT = "{{ title }}"
    first = make_doc(title="Report", correspondent=None)
    (originals / generate_filename(first)).write_bytes(b"%PDF")
    second = make_doc(title="report", correspondent=None)
    assert generate_unique_filename(second).name == "report_01.pdf"


def test_export_manifest_contains_only_posix_paths(
    originals: Path,
    settings: SettingsWrapper,
    tmp_path: Path,
) -> None:
    """A manifest written on Windows must import on Linux (and the reverse): no '\\'."""
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    settings.THUMBNAIL_DIR.mkdir()
    doc = make_doc()
    Document.objects.filter(pk=doc.pk).update(filename=f"{doc.pk:07}.pdf")
    (originals / f"{doc.pk:07}.pdf").write_bytes(b"%PDF-1.4")
    doc.refresh_from_db()
    doc.save()  # moves the file into the nested template location
    doc.refresh_from_db()
    doc.thumbnail_path.write_bytes(b"webp")

    target = tmp_path / "export"
    target.mkdir()
    call_command(
        "document_exporter",
        str(target),
        "--no-progress-bar",
        skip_checks=True,
    )

    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    record = next(r for r in manifest if r["model"] == "documents.document")
    exported = (
        record["fields"]["filename"],
        record["__exported_file_name__"],
        record["__exported_thumbnail_name__"],
    )
    assert exported[0] == f"{doc.created.year}/ACME/Invoice.pdf"
    assert not any("\\" in value for value in exported), exported
    assert (target / record["__exported_file_name__"]).is_file()
