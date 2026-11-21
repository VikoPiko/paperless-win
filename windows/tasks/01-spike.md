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
- [ ] All of step 8 works, possibly with spike hacks. Every hack is listed in Findings.
- [ ] Findings answer each of these: Garnet OK? Granian multi-worker OK? Dependency changes needed? libmagic approach? Test-failure groups with counts?
- [ ] `bootstrap-dev.ps1` sets up a fresh machine non-interactively.
- [ ] `smoke.ps1` passes against the spike setup.
- [ ] `DECISIONS.md` is updated if any decision changed. Ask the user first if a decision has to flip.

## Findings
_(fill in — this section feeds every later phase)_
