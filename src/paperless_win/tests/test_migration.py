from __future__ import annotations

import uuid
from importlib import import_module

import pytest
from django.apps import apps as django_apps

from documents.models import Document
from paperless_win import platform

pytestmark = pytest.mark.django_db


def make(filename: str | None, archive: str | None = None) -> Document:
    doc = Document.objects.create(
        title="t",
        mime_type="application/pdf",
        checksum=uuid.uuid4().hex,
    )
    Document.objects.filter(pk=doc.pk).update(
        filename=filename,
        archive_filename=archive,
    )
    return doc


def run() -> None:
    migration = import_module("paperless_win.migrations.0001_posix_stored_paths")
    migration.to_posix(django_apps, None)


def stored(doc: Document) -> tuple[str | None, str | None]:
    row = Document.objects.filter(pk=doc.pk).values_list("filename", "archive_filename")
    return row[0]


def test_rewrites_backslashes_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    doc = make("2024\\ACME\\Invoice.pdf", "2024\\ACME\\Invoice.pdf")
    run()
    assert stored(doc) == ("2024/ACME/Invoice.pdf", "2024/ACME/Invoice.pdf")


def test_is_idempotent_and_leaves_clean_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    clean = make("a/b.pdf", None)
    mixed = make("a\\b/c.pdf", "x\\y.pdf")
    run()
    run()
    assert stored(clean) == ("a/b.pdf", None)
    assert stored(mixed) == ("a/b/c.pdf", "x/y.pdf")


def test_is_a_noop_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "IS_WINDOWS", False)
    doc = make("odd\\name.pdf", None)
    run()
    assert stored(doc) == ("odd\\name.pdf", None)
