"""Minimal Django app so the fork can ship data migrations and signal hooks.

It has no models and is a no-op on Linux. It is listed in ``INSTALLED_APPS`` by a
one-line hook in ``paperless/settings/__init__.py``.
"""

from django.apps import AppConfig


class PaperlessWinConfig(AppConfig):
    name = "paperless_win"
    label = "paperless_win"
    verbose_name = "paperless-win"

    def ready(self) -> None:
        from paperless_win import checks  # noqa: F401  (registers the system checks)
