# P1 — Windows feasibility spike

**Runs on:** Windows 10/11 x64 (required). **Branch:** `winport/P01-spike`

## Goal

Get one PDF through the full pipeline on native Windows (consume → OCR → thumbnail → index → search → visible in the UI), using manual commands and as few code changes as possible. Then write findings that confirm or change the decisions in `DECISIONS.md`.

This phase produces **knowledge, a dev bootstrap script and a smoke test**. Production code changes are limited to hacks clearly marked `# winport-spike:`. Revert those before merging, or turn them into issues for later phases.

## Context to read first

- `docker/rootfs/etc/s6-overlay/s6-rc.d/*/run` — what each service and init step does
- `docs/setup.md` → "Bare Metal Install"
- `src/paperless/settings/__init__.py` (Redis, Celery, paths)
- `windows/PLAN.md` → "Known code hotspots"

## Steps

1. **Write `windows/scripts/bootstrap-dev.ps1`.** It should be idempotent and install or locate:
   - uv, Python 3.13 (through uv), Git
   - Tesseract 5 (UB-Mannheim build), plus the `eng` and `deu` traineddata
   - Ghostscript 10.x (64-bit) and Poppler for Windows
   - pngquant, Garnet (latest release zip, unpacked to `.\.tools\garnet`), Node LTS and pnpm

   Prefer `winget` where a package exists. Otherwise download pinned versions with SHA256 checks into `.\.tools\`. Write `.\.tools\env.ps1`, which prepends all tool folders to `PATH` for the current shell.

2. **Install Python dependencies:** `uv sync --extra postgres --extra webserver`. Expect failures, and write each one down:
   - `psycopg[c]` + Linux-only wheel sources → try `psycopg[binary]` on Windows (environment marker).
   - `granian[uvloop]` → uvloop has no Windows build. Note whether the extra fails resolution or is skipped.
   - Check torch, tantivy, sqlite-vec, zxing-cpp, hiredis, pi-heif and python-magic (libmagic DLL!).

   Record the minimal `pyproject.toml` changes needed in Findings. Apply them here only as spike hacks.

3. **Build the frontend once:** `cd src-ui; pnpm install; pnpm run build --configuration production` (or the equivalent from `Dockerfile`). Check that the static files end up where Django expects them.
4. **Start Garnet:** `garnet-server --bind 127.0.0.1 --port 6379` (also try `--lua` if something needs Lua).
5. **Set the environment** (`.env` or `paperless.conf`): `PAPERLESS_DATA_DIR`, `PAPERLESS_MEDIA_ROOT` and `PAPERLESS_CONSUMPTION_DIR` under `.\.spike\`, `PAPERLESS_REDIS=redis://127.0.0.1:6379`, SQLite, `PAPERLESS_THUMBNAIL_FONT_NAME` pointing to a TTF on Windows.
6. **Run the init steps by hand:** `manage.py migrate`, `createsuperuser`, `document_index reindex`, and whatever else the s6 `init-*` scripts do.
7. **Start each service in its own terminal:**
   - `granian --interface asginl --ws --loop asyncio paperless.asgi:application` (also try `--workers 2`)
   - `celery --app paperless worker -P solo -n w1@%h --loglevel INFO --without-mingle --without-gossip`
   - `celery --app paperless beat`
   - `manage.py document_consumer`
8. **Exercise the system:** drop a scanned PDF, a PNG, a PDF with a barcode and a .txt file into the consume folder. Upload a PDF through the UI. Watch the live progress (websocket). Search for a word from the OCR text. Open the thumbnail. Run `manage.py document_exporter` and `document_sanity_checker`.
9. **Garnet compatibility:** confirm Celery task delivery and results, beat, channels pub/sub (live UI updates) and cachalot cache hits. Check the Garnet logs for unsupported commands.
10. **Run the backend tests once:** `cd src; uv run pytest -q -p no:randomly --maxfail=0 -n auto > ..\.spike\pytest-windows.txt`. Write a script `windows/scripts/summarize_failures.py` that groups failures by exception type and module. Commit the summary, not the raw log.
11. **Write `windows/scripts/smoke.ps1`.** It should:
    - assume the services are running and `PAPERLESS_URL`, `PAPERLESS_USER` and `PAPERLESS_PASS` are set,
    - upload `windows/fixtures/smoke.pdf` (a small, generated, non-private scanned PDF with a known word) through the REST API,
    - poll the task until it succeeds or a 5-minute timeout passes,
    - then assert: the document exists, its content contains the known word, the thumbnail returns 200, and search finds it.

## Acceptance criteria

- [x] All of step 8 works, possibly with spike hacks. Every hack is listed in Findings. _(Caveat: upload was via the REST API, which is what the UI calls; I did not click through the UI in a browser. The Angular shell and its assets are served (200).)_
- [x] Findings answer each of these: Garnet OK? Granian multi-worker OK? Dependency changes needed? libmagic approach? Test-failure groups with counts?
- [x] `bootstrap-dev.ps1` sets up a fresh machine non-interactively. _(Tested: `.tools` rebuilt from scratch in 55 s with no prompts, exit 0, re-run is a 2 s no-op. uv, git and winget Node are not required to be absent: uv and git are installed via winget if missing, which I could not test on a machine without them.)_
- [x] `smoke.ps1` passes against the spike setup. _(Also verified it fails, exit 1, for a word that is not in the document.)_
- [x] No decision has to flip, so `DECISIONS.md` is untouched. Proposed new entries are listed below and wait for the user's OK.

## Findings

**Spike run on:** Windows 11 Pro 10.0.26200, upstream v3.5.1, Python 3.13.13, Garnet 2.2.13, Tesseract 5.4.0, Ghostscript 10.08.0, Poppler 26.09, pngquant 2.17, Node 24.22.3 / pnpm 11.15.1. Nothing was installed system-wide: everything but uv/git is unpacked into `.tools/` (gitignored).

## Answers to the acceptance questions

| Question                       | Answer                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Garnet OK?**                 | **Yes.** Celery task delivery and results (`celery-task-meta-*` keys), beat (scheduled `mail_fetch` ran and succeeded), channels pub/sub (a live websocket received `STARTED → WORKING 20/70/90/95 → SUCCESS` for an upload) and django-cachalot (2nd identical query = 0 DB queries, `pngx_cachalot_*` keys) all work. **Lua is disabled by default** (`EVAL`/`SCRIPT LOAD` return "Lua scripting support disabled") and nothing needed it. **Streams (`XADD`) are unsupported**, which Celery's Redis transport does not use. `INFO commandstats` is off unless `--commandstats-monitor` is set. Garnet's log showed no unsupported-command errors. No reason to leave D2. |
| **Granian multi-worker OK?**   | **No.** `GRANIAN_WORKERS=2` logs "Due to a bug in Windows unblocking socket implementation granian can't support multiple workers on this platform. Number of workers will now fallback to 1." One worker with `--loop asyncio` works fine (12/12 requests 200, websocket OK, smoke test passes). The decision stands (Granian + asyncio), but the web tier is **single-worker**; the plan's "Granian multi-worker" wish is dropped. Uvicorn stays as fallback only.                                                                                                                                                                                                         |
| **Dependency changes needed?** | See "pyproject changes" below: add Windows to `[tool.uv] environments`, switch the Postgres extra to `psycopg[binary]` on Windows. `granian[uvloop]` needs no change (uvloop is skipped by its own marker).                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **libmagic approach?**         | Keep `python-magic` 0.4.27 and supply only `libmagic-1.dll` + `magic.mgc` (taken from the `python-magic-bin` 0.4.14 win_amd64 wheel) in a folder on `PATH`, with `MAGIC` pointing at `magic.mgc`. **Do not install `python-magic-bin`**: its bundled `magic.py` is old and crashes on `pathlib.Path` (`ctypes.ArgumentError ... 'WindowsPath' ... c_char_p`) in `ConsumableDocument`. The bundled libmagic is from 2018, so newer formats may be misdetected; a newer build is a P4 follow-up. `bootstrap-dev.ps1` does this.                                                                                                                                                |
| **Test failure groups**        | See table below: **3,979 of 4,187 pass**; 195 fail/error, in about 9 root causes. Full grouping in `windows/spike/pytest-windows-summary.md`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |

## Spike hacks (none committed)

Saved as `windows/spike/pyproject-spike.patch` (and `uv.lock`, regenerable). Marked `winport-spike:`; the working tree is reverted at the end of this task.

1. `pyproject.toml`: add `sys_platform == 'win32' and platform_machine == 'AMD64' and platform_python_implementation == 'CPython'` to `[tool.uv] environments`; then `uv lock` adds only `pywin32` and `psycopg-binary` and `uv sync --extra webserver --extra postgres` succeeds (100 s, includes CPU torch 2.14).
2. `pyproject.toml`: postgres extra: `psycopg[c,pool]` and `psycopg-c` get `; sys_platform != 'win32'`, plus `psycopg[binary,pool]==3.3.4; sys_platform == 'win32'`. Without it `uv sync --extra postgres` fails building `psycopg-c` (`pg_config` not found).
3. Environment only: `PAPERLESS_OCR_CLEAN=none` (no unpaper), `PAPERLESS_THUMBNAIL_FONT_NAME=C:\Windows\Fonts\arial.ttf`, `PAPERLESS_SCRATCH_DIR` under `.spike`, `PAPERLESS_CONSUMER_ENABLE_BARCODES=true`, folders created by hand (see below), libmagic as above. **No Python source was changed.**
   Side note: `uv lock` with our uv 0.11.10 rewrote the lock header `revision = 5` to `3`. Upstream's lock was written by a newer uv; pin the same uv version in P2/P11 to avoid lock churn.

## What worked (step 8)

- `consume`: scanned-style PDF (OCR'd, text found), PNG (OCR'd), `.txt`, and a barcode (`PATCHT`) PDF that split into 2 documents. Barcode detection works through `pdf2image` (Poppler on `PATH`) and `zxing-cpp`.
- REST upload, task polling, thumbnail (200), original download, Tantivy full-text search, live websocket progress.
- `document_exporter` (11/11 docs), `document_sanity_checker` ("No issues detected"), `manage.py check`.
- Frontend build: Node 24 needed (Angular 21 refuses Node 22.18; needs ≥ 22.22.3 or ≥ 24.15). `ng build --configuration production` takes 47 s and writes to `src/documents/static/frontend/` (gitignored, which is where Django expects it). `collectstatic` was also run (7,437 files into `PAPERLESS_STATICDIR`).

## Real runtime bugs found on Windows (not just tests)

1. **`/api/status/` returns HTTP 500**: `os.statvfs` does not exist (24 tests too). The UI's System Status page would break. Needs a `shutil.disk_usage` path. (P2/P3)
2. **`document_exporter` fails on the second run into the same folder**: `os.rename(manifest.json.tmp, manifest.json)` raises `FileExistsError: [WinError 183]`. Needs `os.replace`. Same pattern in the classifier (`test_classifier`). Correct on both OSes, so it is a pure fix. (P3)
3. **System check warns "Paperless can't find gs"**: the Windows binary is `gswin64c`. OCRmyPDF itself found it, so consumption works. (P2)
4. **`document_index reindex` crashes if `DATA_DIR/index` is missing** (the Docker `init-folders` step creates `index`, `media/documents/originals`, `.../thumbnails`, `export`, scratch). `paperless-ctl init` must create them. (P6)
5. **`unpaper` is missing**, and the default `OCR_CLEAN=clean` makes **every** consume fail with `MissingDependencyError: Could not find program 'unpaper'`. Already an accepted trade-off, but the Windows default must be `none` (or the setting must degrade), otherwise a fresh install cannot consume anything. (P2)
6. **Stored paths use backslashes** with filename templates (30 tests, e.g. `'none\\none.pdf' != 'none/none.pdf'`). Not exercised live (no `FILENAME_FORMAT` was set). (P3)

## Test failures (3,979 pass / 195 fail or error of 4,187)

| Count | Cause                                                                                                                                                                                                                                                                            | Phase                                                     |
| ----: | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
|    50 | `gpg` not on PATH: `paperless_mail` preprocessor tests error in setup (`Unable to run gpg`). Mail GPG decryption is optional                                                                                                                                                     | skip + note, or ship/locate gpg (P4)                      |
|    40 | `unpaper` missing (tesseract parser 33, barcodes 7): tests assume default `OCR_CLEAN`                                                                                                                                                                                            | set `OCR_CLEAN=none` in the Windows test env or skip (P2) |
|    30 | POSIX-vs-backslash paths (`file_handling`, `filepath_nfc`, `api_objects`, `consumer`, `importer`, `task_signals`)                                                                                                                                                                | P3                                                        |
|    24 | `os.statvfs` (`test_api_status`)                                                                                                                                                                                                                                                 | P3                                                        |
|    13 | `WinError 32`: temp files left open (`bulk_download` 8, `share_link_bundles` 3, `vector_store` 1, `permission_filtering` 1)                                                                                                                                                      | test hygiene, cheap (P3/P4)                               |
|     8 | `FileExistsError` on rename (exporter, classifier)                                                                                                                                                                                                                               | P3                                                        |
|     3 | `gs` check (`test_checks`)                                                                                                                                                                                                                                                       | P2                                                        |
|     3 | CRLF in expected text (text/mail parser tests)                                                                                                                                                                                                                                   | P3                                                        |
|    24 | Other: POSIX permission semantics (`unreadable`, `no_access`, `permission_error`, `missing_permissions` ~8), `%y` needs year ≥ 1900 on Windows, `/usr/share/fonts` thumbnail font (2), SVG-logo/date/archiver oddities, `workflows` "Refusing to write file outside of root" (3) | triage per phase                                          |

Run: `cd src; python -m pytest -q -p no:randomly -n auto` from a clean environment, 300 s. Use `windows/scripts/summarize_failures.py <junit.xml>` to regroup.

## Files added

`windows/scripts/bootstrap-dev.ps1`, `smoke.ps1`, `make_fixtures.py`, `summarize_failures.py`; `windows/fixtures/smoke.pdf`; `windows/spike/pyproject-spike.patch`, `windows/spike/pytest-windows-summary.md`; `.gitignore` gets `.tools/` and `.spike/` (registered in `PATCHES.md`).
Notes on running: processes started with `Start-Process` and piped to `Out-Null` make the calling shell hang until they exit; redirect their output to files instead (what `.spike/start.ps1` does). Running services lock files in `.tools\`, so stop them before re-running the bootstrap.

## Gotchas for later phases

- NSIS installers for Tesseract and Ghostscript ask for elevation; we do not run them. The bootstrap unpacks their payload with 7-Zip (itself unpacked from the MSI via `msiexec /a`), so it needs no admin rights. The real installer (P10) can bundle the unpacked trees.
- `.tools\garnet\net10.0\GarnetServer.exe` (not `garnet-server`).
- Celery `-P solo` worker, beat and `document_consumer` showed no crashes during the spike (every restart was mine); a real soak test is still P6's job. The consumer uses native FS events by default; polling and UNC were not tried (P5).
- `/api/status/` would also report redis/celery state; not checked because of bug 1.

## Proposed DECISIONS.md entries (not written, need the user's OK)

- **D8 — libmagic:** `python-magic` + `libmagic-1.dll`/`magic.mgc` from the `python-magic-bin` wheel on `PATH`/`MAGIC`; never install `python-magic-bin` itself.
- **D9 — Single web worker:** Granian on Windows is limited to 1 worker; keep Granian + asyncio.
- **D10 — OCR default:** Windows default `OCR_CLEAN=none` because unpaper is unavailable.
- **D11 — Windows lock/environments:** add Windows to uv `environments` (one hunk in `pyproject.toml`, to be done in P2/P4) and `psycopg[binary]` on Windows.
