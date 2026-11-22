r"""Rewrite backslashes to ``/`` in stored relative paths (Windows databases only).

Paths in the database are always POSIX (see ``paperless_win.paths``). Installs that ran
before that rule may hold ``2024\ACME\Invoice.pdf``. Idempotent, and a no-op when nothing
matches. On Linux a backslash is a legal file name character, so nothing is touched.
"""

from django.db import migrations
from django.db.models import F
from django.db.models import Value
from django.db.models.functions import Replace

from paperless_win import platform

FIELDS = ("filename", "archive_filename")


def to_posix(apps, schema_editor) -> None:
    if not platform.IS_WINDOWS:
        return
    document = apps.get_model("documents", "Document")
    manager = document._default_manager
    for field in FIELDS:
        manager.filter(**{f"{field}__contains": "\\"}).update(
            **{field: Replace(F(field), Value("\\"), Value("/"))},
        )


class Migration(migrations.Migration):
    dependencies = [("documents", "0030_note_format")]

    operations = [migrations.RunPython(to_posix, migrations.RunPython.noop)]
