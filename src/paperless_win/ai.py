"""The local-AI add-on is optional: say so clearly when it is missing.

Local embeddings (the ``huggingface`` embedding backend) need torch, sentence-transformers
and llama-index-embeddings-huggingface, which live in the ``ai-local`` extra. A base install
has none of them. Everything else (OpenAI-compatible or Ollama backends, classification,
search) works without.
"""

from __future__ import annotations

import importlib.util

REQUIRED_MODULES = (
    "torch",
    "sentence_transformers",
    "llama_index.embeddings.huggingface",
)

MESSAGE = (
    "Local embeddings (the 'huggingface' embedding backend) require the AI add-on, which is "
    "not installed. Re-run the installer and select 'Local AI' (or install the 'ai-local' "
    "extra), or choose a remote embedding backend (openai-like or ollama)."
)


class LocalAiNotInstalledError(ImportError):
    """The huggingface embedding backend was selected but the ai-local extra is missing."""


def _present(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # parent package missing
        return False


def missing_modules() -> list[str]:
    return [m for m in REQUIRED_MODULES if not _present(m)]


def local_embeddings_available() -> bool:
    return not missing_modules()


def require_local_embeddings() -> None:
    """Raise ``LocalAiNotInstalledError`` (with the user-facing text) if the add-on is absent."""
    if not local_embeddings_available():
        raise LocalAiNotInstalledError(MESSAGE)
