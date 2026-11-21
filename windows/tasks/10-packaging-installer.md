# P10 — Reproducible build and installer

**Runs on:** Windows (CI: `windows-latest`). **Branch:** `winport/P10-installer`

## Goal
`pwsh windows/build/build.ps1` produces `dist/paperless-win-setup-<ver>.exe` from a clean checkout. The build is reproducible, uses pinned and checksummed inputs, and needs no network at install time for the base install.

## Build pipeline (`windows/build/`)
1. `manifest.json` lists every third-party input with version, URL, SHA256 and licence: python-build-standalone (CPython 3.13 x64), Tesseract and traineddata, Ghostscript, Poppler, pngquant, libmagic DLL + `magic.mgc`, Garnet, WinSW, the Liberation font, and the optional Java/Tika entries (not bundled). `THIRD_PARTY.md` is **generated** from this file.
2. `build.ps1` steps:
   - download the inputs to a cache and verify SHA256;
   - build the frontend: `pnpm install --frozen-lockfile`, then the production build;
   - `uv export --frozen --no-dev --extra webserver --extra postgres --extra mariadb` → requirements, then `uv pip download`/`wheel` into `wheelhouse/base/`;
   - do the same for `--extra ai-local` → `wheelhouse/ai-local/` (shipped as a separate download, not inside the base installer);
   - lay out the staging dir:
     ```
     app\python\        (standalone CPython)
     app\src\           (src\ incl. built static)
     app\bin\<tool>\    (tesseract, gs, poppler, pngquant, magic, garnet)
     app\service\       (winsw exe + xml)
     app\wheelhouse\base\
     app\uv.exe
     ```
   - compile the Inno Setup script `windows/installer/paperless-win.iss`.
3. **Installer behaviour (Inno Setup):**
   - pages: licence (GPL-3 + unofficial disclaimer) → install dir → data dir (default `%ProgramData%\paperless-win`) → consume folder → admin username and password → OCR languages (checkboxes; eng is always installed; other languages are downloaded or bundled) → components: *Core* (required), *Local AI add-on* (downloads the wheelhouse and needs network), *Firewall rule for LAN access*.
   - install: copy files → `uv venv --python app\python\python.exe app\venv` → `uv pip install --offline --find-links app\wheelhouse\base -r requirements.txt` → write `paperless.conf` (generate a random `PAPERLESS_SECRET_KEY`, set paths, Redis URL for Garnet, admin creds via env just for init) → `paperless-ctl init` → `paperless-ctl service install` → start → open the browser at `http://localhost:8000`.
   - **upgrade:** stop the service → replace app files (keep `paperless.conf` and data) → reinstall the venv → `paperless-ctl init` (migrations) → start. Take a pre-upgrade backup of the SQLite DB file (`data\db.sqlite3.bak-<ver>`).
   - **uninstall:** stop and remove the service and app files. Ask whether to keep the data (default: keep).
4. Code signing: not in v0.1.0. Document the SmartScreen warning in the README. Leave a hook for signing later.

## Acceptance criteria
- [ ] Clean Windows 11 VM (no Python, no tools): installer → browser opens → login works → `smoke.ps1` passes.
- [ ] Upgrade from the previous build keeps the documents and settings, and migrations run.
- [ ] Uninstall with "keep data", then reinstall: the existing library is picked up.
- [ ] The base installer size is recorded in Findings (target < 500 MB with eng+deu).
- [ ] The build is reproducible: two builds of the same commit produce identical `app\` contents (ignore timestamps, compare the hash list).

## Findings
_(fill in)_
