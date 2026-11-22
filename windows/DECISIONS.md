# Decisions (ADR log)

Short entries. Newest at the bottom. Format: context → decision → consequences.

## D1 — Fork model: track upstream release tags

- **Context:** Want upstream features/security fixes; fork should be a Windows layer, not a rewrite.
- **Decision:** `main` = upstream release tag + winport layer. Merge each upstream release tag via `sync/vX.Y.Z` branch. Don't track `dev`.
- **Consequences:** Thin-diff discipline (`CLAUDE.md` rules 2–3, `PATCHES.md`). Some upstream refactors will force rework of hooks.

## D2 — Redis: bundle Garnet

- **Context:** Celery broker, Channels layer and Django cache all use Redis. Valkey/Redis have no maintained native Windows builds.
- **Decision:** Ship Microsoft Garnet, bound to 127.0.0.1, started by our supervisor. No Redis-free mode in v1.
- **Consequences:** Must verify compatibility (P1). Extra ~100 MB process. Users never see it.

## D3 — AI: optional add-on

- **Context:** torch + sentence-transformers ≈ 2 GB; only needed for _local_ embeddings. Remote backends (OpenAI-compatible, Ollama) are light.
- **Decision:** Move local-embedding deps to an `ai-local` extra; installer offers it as an optional component (download on demand).
- **Consequences:** One `pyproject.toml` hunk to maintain; settings validation must explain how to enable local embeddings.

## D4 — Name: paperless-win

- **Decision:** Repo/product name `paperless-win`. Clearly marked unofficial; issues go to the fork, never upstream.

## D5 — Workers: Celery solo pool, N processes

- **Context:** Celery doesn't officially support Windows; prefork/billiard unreliable. OCRmyPDF is not meant to be called concurrently from threads in one process.
- **Decision:** N `celery worker -P solo` processes (unique `-n`), supervised; recycle after K tasks; watchdog enforces time limits by killing the process tree.

## D6 — Service wrapper: WinSW

- **Decision:** WinSW (MIT, single exe + XML) wraps `paperless-ctl run`. No pywin32 service code.
- **Consequences:** Supervisor must handle Ctrl-Break/stop signal from WinSW and shut down children cleanly.

## D7 — Disable upstream automation that publishes or spams

- **Context:** The fork inherits upstream workflows that publish Docker images, sync translations, run issue/PR bots or deploy upstream's docs site. None make sense for this fork, and some would act on the wrong repo.
- **Decision:** Disable them with `gh workflow disable` (GitHub does not let a fork's owner edit this from the repo, and deleting the files would cause merge conflicts on every upstream sync). The workflow files stay untouched. Disabled manually: `ci-docker`, `ci-release`, `ci-docs`, `issue-bot`, `pr-bot`, `project-actions`, `translate-strings`. Already `disabled_fork` by GitHub (cannot run on forks): `cleanup-tags`, `crowdin`, `repo-maintenance`, `codeql-analysis`. Kept active: `ci-backend`, `ci-frontend`, `ci-lint`, `ci-static-analysis` (upstream's Linux test and lint suites, which support the "Linux must keep working" rule).
- **Consequences:** After each upstream sync, check that new upstream workflows are not active (`gh workflow list --all`). The disabled state lives in GitHub settings, not in git. `ci-docs` can be re-enabled in P12 if we publish docs.

## D8 — libmagic on Windows

- **Context:** `python-magic` needs libmagic. `python-magic-bin`'s bundled `magic.py` is old and crashes on `pathlib.Path` (`ctypes.ArgumentError` in `ConsumableDocument`), which breaks every consume.
- **Decision:** Keep `python-magic` (0.4.27). Ship only `libmagic-1.dll` + `magic.mgc` (from the `python-magic-bin` 0.4.14 win_amd64 wheel) in a folder on `PATH`, with `MAGIC` pointing at `magic.mgc`. Never install `python-magic-bin` itself.
- **Consequences:** The bundled libmagic is from 2018, so newer formats may be misdetected; look for a newer DLL build in P4. `bootstrap-dev.ps1` does this for dev, the installer must do it for users.

## D9 — Web tier is a single Granian worker on Windows

- **Context:** Granian refuses multiple workers on Windows ("bug in Windows unblocking socket implementation") and falls back to 1. One worker with `--loop asyncio` handled HTTP and websockets fine in P1.
- **Decision:** Keep Granian + asyncio with one worker; `PAPERLESS_WEBSERVER_WORKERS` is effectively ignored on Windows. Uvicorn remains a fallback only if a real problem appears.
- **Consequences:** No horizontal scaling of the web process; Celery workers still scale (D5).

## D10 — OCR cleaning off by default on Windows

- **Context:** `unpaper` is unavailable on Windows (accepted trade-off in `PLAN.md`), and the upstream default `OCR_CLEAN=clean` makes every consume fail with `MissingDependencyError`.
- **Decision:** On Windows the default for `PAPERLESS_OCR_CLEAN` becomes `none` (via `paperless_win.platform`, not by changing Linux defaults). Users who supply an `unpaper` binary can opt back in.
- **Consequences:** The `unpaper`-dependent tests (about 40) run with `OCR_CLEAN=none` or are skipped on Windows (P2).

## D11 — Windows in the uv lock and psycopg binary wheel

- **Context:** `[tool.uv] environments` lists only Linux/macOS, so `uv sync` fails on Windows; `psycopg[c]` has no Windows wheel and fails building from source.
- **Decision:** Add a Windows x64 CPython environment to `environments`, and in the `postgres` extra use `psycopg[binary,pool]` on `sys_platform == 'win32'` (keep `psycopg[c]`/`psycopg-c` elsewhere). Re-lock with the same uv version as upstream to limit lock churn. Spike patch: `windows/spike/pyproject-spike.patch`.
- **Consequences:** One small `pyproject.toml` hunk plus a larger `uv.lock` diff to carry in every upstream sync (P2/P4; register both in `PATCHES.md`).

## D12 — Thin hooks at central points; Windows test skips live in a fork-owned list

- **Context:** Several Windows differences (qpdf/pdfinfo CLIs, upstream tests that assume POSIX) could be handled by editing many upstream call sites and test files, each a future merge conflict, and upstream's own tests mock specific call sites (`documents.consumer.run_subprocess`).
- **Decision:** (1) Prefer hooking the single central function: `documents.utils.run_subprocess` asks `paperless_win.pdf.shim_subprocess` first (`qpdf --replace-input` runs in-process through pikepdf on Windows); `get_pdf_first_page_size_points` asks `page_size_hook`; the importer's `iter_manifest_records` normalises manifest paths. Call sites and Linux tests stay untouched. (2) Tests that cannot pass on Windows are skipped by a pytest plugin from `windows/skipped_tests.toml` (Windows only, every entry needs a reason and a follow-up), not by editing upstream test files. This is how CLAUDE.md rule 5 is implemented here.
- **Consequences:** Budget about 2% of the suite in the skip list; review it at every upstream sync. `windows/scripts/run-tests.ps1` enables the plugin; the Windows CI job (P11) must set `PYTEST_ADDOPTS=-p paperless_win.pytest_plugin` and `PYTHONPATH=src`.

## D13 — libmagic 5.48 from conda-forge, replacing the 2018 python-magic-bin DLL (amends D8)

- **Context:** D8 shipped the DLL from `python-magic-bin` 0.4.14 (2018). It reports HEIC/HEIF/AVIF (iPhone photos) and Office Open XML files as `application/octet-stream`, so those would not be consumed.
- **Decision:** Ship libmagic 5.48 (`libmagic-5.48-hf886114_2.conda`) plus PCRE2 10.47 (`pcre2-10.47-h8466c1e_1.conda`) from conda-forge, both BSD-licensed, SHA256-pinned in `bootstrap-dev.ps1`: `libmagic-1.dll`, `magic.mgc`, `pcre2-posix.dll`, `pcre2-8.dll` in one folder on `PATH`, `MAGIC` set by `bootstrap.apply()` (unchanged from D8). Still use `python-magic`, never `python-magic-bin`. 5.48 recognises HEIC and DOCX natively; the Python sniffing in `paperless_win.magic_compat` stays as a safety net.
- **Consequences:** The DLLs need the VC++ 14 runtime (P10 must provide it). 5.48 still cannot open non-ASCII paths (ANSI file API), so `magic_compat` keeps the Unicode-safe `from_file` wrapper. Upgrading libmagic later means re-pinning two files.
