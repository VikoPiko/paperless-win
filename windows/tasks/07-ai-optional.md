# P7 — Make local-AI dependencies optional

**Runs on:** any OS. **Branch:** `winport/P07-ai-optional`

## Goal

The base install does not include torch, sentence-transformers or llama-index-embeddings-huggingface. Everything except local HuggingFace embeddings works without them. Installing the `ai-local` extra brings them back.

## Context

- `pyproject.toml`: the `dependencies` list, `[tool.uv.sources] torch` (CPU index)
- `src/paperless_ai/embedding.py` (~L60–75): the HuggingFace import is already lazy
- `grep -rn "sentence_transformers\|torch\|HuggingFace" src --include=*.py`
- `PAPERLESS_AI_LLM_EMBEDDING_BACKEND` choices in settings

## Steps

1. Confirm nothing imports torch or sentence-transformers at module import time, including Django app loading, Celery task module imports and `manage.py check`. Test it: in a venv **without** those packages, run `manage.py check`, start a worker, consume a document, and use AI features with an OpenAI-compatible or Ollama backend (a mock server is fine).
2. In `pyproject.toml`, move `torch`, `sentence-transformers` and `llama-index-embeddings-huggingface` from `dependencies` to a new optional extra `ai-local`. Keep the torch CPU index source. Use **one contiguous marked hunk** and register it in PATCHES.md. Note: this also changes Linux installs of the fork. That's acceptable, but CI must install `--extra ai-local` on Linux so the upstream tests still run.
3. If the HuggingFace backend is configured but the extra isn't installed, show a clear error in settings validation or system checks _and_ in the UI status page: "Local embeddings require the AI add-on. Re-run the installer and select 'Local AI', or choose a remote embedding backend."
4. `uv lock` and check that the lock resolves for Windows with and without the extra.
5. Measure install size with and without the extra and put the numbers in Findings. The installer phase uses them.

## Acceptance criteria

- [ ] Base venv has no torch, and `smoke.ps1` passes.
- [ ] With the extra installed, the upstream AI tests pass (Linux CI).
- [ ] Clear error when the local backend is selected without the add-on.

## Findings

_(fill in)_
