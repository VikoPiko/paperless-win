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

- [x] Base venv has no torch, and `smoke.ps1` passes.
- [x] With the extra installed, the upstream AI tests pass (Linux CI).
- [x] Clear error when the local backend is selected without the add-on.

## Findings

**Result: all three acceptance criteria met (2026-11-22); Linux CI result is recorded in the PLAN row.**

- **Nothing imports torch eagerly.** The only non-test reference to the HuggingFace stack is the lazy import inside `paperless_ai/embedding.py` (`HUGGINGFACE` branch). `paperless_win/tests/test_ai.py::test_nothing_imports_torch_while_the_app_loads` proves it in a fresh interpreter (Django setup, `documents.tasks`, `paperless.celery`, `paperless_ai.*` leave `torch`, `sentence_transformers`, `transformers` out of `sys.modules`). `LLM_EMBEDDING_BACKEND` has no default, so a base install only meets the HuggingFace path if someone selects it.
- **Base venv verified for real.** `uv sync --frozen --no-dev --extra webserver` into `.venv-base` (no torch, no sentence-transformers, no llama-index-embeddings-huggingface; `find_spec` confirms). In it: `manage.py check` clean; the whole stack under `paperless-ctl run` (`smoke.ps1 -StartStack -Python .venv-base\Scripts\python.exe`) passes; with `PAPERLESS_AI_ENABLED=true` and the `openai-like` backend pointed at a mock embedding server, consuming a document sent exactly one `/v1/embeddings` request and nothing failed. No real LLM chat backend was tried (upstream's tests mock those).
- **Clear error, three places.** (1) `manage.py check` / `paperless-ctl init`: `paperless_win.E001` when `PAPERLESS_AI_ENABLED` and `PAPERLESS_AI_LLM_EMBEDDING_BACKEND=huggingface` but a package is missing, with the list of missing packages as hint. Only the environment is looked at, so a backend picked in the web UI is not caught here. (2) At use: `get_embedding_model` calls `paperless_win.ai.require_local_embeddings()` first and raises `LocalAiNotInstalledError` ("Local embeddings ... require the AI add-on ... Re-run the installer and select 'Local AI' ... or choose a remote embedding backend"). (3) The status page already shows the last failed LLM index task's `error_message`, which is that text; no Angular change was needed. Checked in the base venv: `check` fails with E001 for huggingface and passes for `ollama`; `get_embedding_model` raises the message. Not checked: the status page in a browser with the failing task.
- **Lock.** D11 was still only a spike patch, so this phase carries it: Windows x64 added to `[tool.uv] environments`, `psycopg[binary]` on `win32`. `uv lock` (uv 0.11.10, same lock revision 5) resolves 274 packages in a few seconds with no network trouble; `uv.lock` changes by about 900 lines (the Windows environment adds markers to most packages, torch moves under the extra). `uv lock --check` passes. `uv sync --frozen` works for Windows with and without `--extra ai-local`.
- **Install size (unpacked venv, no `.pyc`):** base **503 MB** (largest: scipy 85, babel 29, scikit-learn 26, llama_index 22, django 22), with `ai-local` **1,053 MB**; the add-on is **about 550 MB** (torch 450, transformers 44, sympy 25, ...). The old all-in `.venv` of this repo is 1,312 MB with the dev tools. The installer (P10) should compress these; scipy is in the base because scikit-learn needs it.
- **Linux.** The two `uv sync` calls in `ci-backend.yml` get `--extra ai-local`; Docker (`uv export --all-extras`) and the release workflow already include every extra, so the image is unchanged. Anyone running `uv sync` on the fork without the extra no longer gets local embeddings.
- **Not changed:** `docs/` (the AI add-on needs a user-facing note in P12) and the installer's "Local AI" option (P10).
