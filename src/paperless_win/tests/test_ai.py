"""The ai-local extra is optional: clear errors without it, nothing imports it eagerly."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperless_win import ai
from paperless_win import checks

SRC = Path(__file__).resolve().parents[2]


def pretend_missing(monkeypatch: pytest.MonkeyPatch, *missing: str) -> None:
    monkeypatch.setattr(ai, "_present", lambda module: module not in missing)


def test_available_when_every_module_is_importable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pretend_missing(monkeypatch)
    assert ai.local_embeddings_available()
    assert ai.missing_modules() == []
    ai.require_local_embeddings()  # does not raise


def test_missing_modules_are_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    pretend_missing(monkeypatch, "torch", "sentence_transformers")
    assert ai.missing_modules() == ["torch", "sentence_transformers"]
    assert not ai.local_embeddings_available()


def test_require_raises_the_user_facing_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pretend_missing(monkeypatch, "torch")
    with pytest.raises(ai.LocalAiNotInstalledError) as excinfo:
        ai.require_local_embeddings()
    text = str(excinfo.value)
    assert "AI add-on" in text
    assert "Local AI" in text
    assert "remote embedding backend" in text
    assert isinstance(excinfo.value, ImportError)


def test_a_missing_parent_package_counts_as_missing() -> None:
    assert not ai._present("definitely_not_installed.sub.module")


def settings_for(*, enabled: bool, backend: str | None) -> SimpleNamespace:
    return SimpleNamespace(AI_ENABLED=enabled, LLM_EMBEDDING_BACKEND=backend)


def test_check_reports_an_error_for_huggingface_without_the_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pretend_missing(monkeypatch, "torch")
    monkeypatch.setattr(
        checks,
        "settings",
        settings_for(enabled=True, backend="huggingface"),
    )
    (error,) = checks.local_ai_check(None)
    assert error.id == "paperless_win.E001"
    assert "torch" in error.hint
    assert "Local AI" in error.msg


@pytest.mark.parametrize(
    ("enabled", "backend"),
    [(False, "huggingface"), (True, "ollama"), (True, "openai-like"), (True, None)],
)
def test_check_is_quiet_when_local_embeddings_are_not_wanted(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool,
    backend: str | None,
) -> None:
    pretend_missing(monkeypatch, "torch", "sentence_transformers")
    monkeypatch.setattr(
        checks,
        "settings",
        settings_for(enabled=enabled, backend=backend),
    )
    assert checks.local_ai_check(None) == []


def test_check_is_quiet_when_the_extra_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pretend_missing(monkeypatch)
    monkeypatch.setattr(
        checks,
        "settings",
        settings_for(enabled=True, backend="huggingface"),
    )
    assert checks.local_ai_check(None) == []


def test_embedding_model_for_huggingface_fails_clearly_without_the_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paperless.models import LLMEmbeddingBackend
    from paperless_ai import embedding

    pretend_missing(monkeypatch, "llama_index.embeddings.huggingface")
    config = SimpleNamespace(llm_embedding_backend=LLMEmbeddingBackend.HUGGINGFACE)
    with pytest.raises(ai.LocalAiNotInstalledError, match="AI add-on"):
        embedding.get_embedding_model(config)  # type: ignore[arg-type]


def test_nothing_imports_torch_while_the_app_loads() -> None:
    """Django setup, the task modules and the AI modules must not pull in torch.

    Run in a fresh interpreter: with the extra installed this still proves the imports are
    lazy, and in a base venv it proves they do not need the packages at all.
    """
    code = textwrap.dedent(
        """
        import os, sys
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "paperless.settings")
        os.environ.setdefault("PAPERLESS_SECRET_KEY", "test")
        import django
        django.setup()
        import documents.tasks, paperless.celery
        import paperless_ai.embedding, paperless_ai.indexing, paperless_ai.client
        bad = [m for m in ("torch", "sentence_transformers", "transformers") if m in sys.modules]
        print("LOADED:" + ",".join(bad))
        """,
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=SRC,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "LOADED:" in result.stdout
    assert result.stdout.strip().splitlines()[-1] == "LOADED:"
