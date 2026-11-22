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
   - pages: licence (GPL-3 + unofficial disclaimer) → install dir → data dir (default `%ProgramData%\paperless-win`) → consume folder → admin username and password → OCR languages (checkboxes; eng is always installed; other languages are downloaded or bundled) → components: _Core_ (required), _Local AI add-on_ (downloads the wheelhouse and needs network), _Firewall rule for LAN access_.
   - install: copy files → `uv venv --python app\python\python.exe app\venv` → `uv pip install --offline --find-links app\wheelhouse\base -r requirements.txt` → write `paperless.conf` (generate a random `PAPERLESS_SECRET_KEY`, set paths, Redis URL for Garnet, admin creds via env just for init) → `paperless-ctl init` → `paperless-ctl service install` → start → open the browser at `http://localhost:8000`.
   - **upgrade:** stop the service → replace app files (keep `paperless.conf` and data) → reinstall the venv → `paperless-ctl init` (migrations) → start. Take a pre-upgrade backup of the SQLite DB file (`data\db.sqlite3.bak-<ver>`).
   - **uninstall:** stop and remove the service and app files. Ask whether to keep the data (default: keep).
4. Code signing: not in v0.1.0. Document the SmartScreen warning in the README. Leave a hook for signing later.

## Acceptance criteria

- [ ] Clean Windows 11 VM (no Python, no tools): installer → browser opens → login works → `smoke.ps1` passes. _Not done: needs a VM and an administrator; silent non-admin install + smoke passed on the development machine (see Findings)._
- [x] Upgrade from the previous build keeps the documents and settings, and migrations run (tested with the same version over itself; migrations run in `init`, a newer schema was not available to test).
- [x] Uninstall with "keep data", then reinstall: the existing library is picked up.
- [x] The base installer size is recorded in Findings (314 MB).
- [x] The build is reproducible: two builds of the same commit produce identical `app\` contents (ignore timestamps, compare the hash list).

## Findings

### What was built

`windows/build/` (`manifest.json` = the single list of pinned inputs, `build.ps1`, `make-third-party.py`, `split_requirements.py`, `build-constraints.txt`), `windows/installer/paperless-win.iss`, `src/paperless_win/setup_conf.py` and the `paperless-ctl setup` / `init --admin-user --admin-password-file` commands the installer calls. All install logic is in Python (tested on Linux too); the Inno script only collects answers and runs `paperless-ctl`. `bootstrap-dev.ps1` reads the same manifest and installs Inno Setup to `.tools\innosetup` (no admin needed).

### Measured (Windows 11, no administrator rights, `/CURRENTUSER /NOSERVICE`)

| What                                                     | Result                                                                                                                                                               |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Installer size, `lzma2/max` (default)                    | **314 MB** (target < 500 MB; the same file offers eng+deu+fra+spa+ita+nld)                                                                                           |
| Installer size, `-FastCompression` (what the tests used) | 444 MB                                                                                                                                                               |
| Staged `app\`                                            | 11 667 files, 1 037 MB                                                                                                                                               |
| Fresh silent install                                     | 303 s (of which `paperless-ctl init` 233 s: migrations, index, static files, bytecode)                                                                               |
| Upgrade over the same version                            | 108 s; `paperless.conf` byte-identical, documents kept, `db.sqlite3.bak-<old version>` written, OCR languages kept                                                   |
| Uninstall (keep data), then reinstall                    | uninstall 12 s, app folder gone, data and `paperless.conf` kept; reinstall 113 s picks up the library ("a user admin already exists", conf and secret key unchanged) |
| `smoke.ps1` against the installed app                    | passes after the first install and after the reinstall (consume, OCR text, thumbnail, download, search)                                                              |
| Reproducible build                                       | two builds of the same commit: `app\` hash lists identical (0 differing lines)                                                                                       |

### Bugs the install tests found (all fixed)

- `uv pip install --require-hashes` failed because the list for the locally built wheels has no hashes: the install list is now exported with `--no-hashes` (every download is still hash-checked while the wheelhouse is built; the ai-local list keeps its hashes).
- A failing set-up step ended in Inno's runtime-error dialog and **hung a silent install forever**: now the message goes to the install log (a box only when not silent) and the installer exits with code 1.
- A first install that failed half-way left registry values that made the retry look like an upgrade (no admin account, default port): the installer now writes `Complete=1` at the very end and only treats an install with that flag as an upgrade.
- An upgrade deleted the OCR languages the user had chosen (they live under `bin\`): they are set aside in `{tmp}` and put back.
- The pre-upgrade database backup looked in `<data>\data\db.sqlite3` instead of `<data>\db.sqlite3`, so no backup was made.
- An empty consume-folder field was rejected by the folder page (silent install aborted); an empty value now means `<data>\consume`.

### Deviations from the task text

- The wheelhouse is made with `pip wheel` instead of `uv pip download`: `langdetect` only has a source distribution, so it is built into a wheel with pinned `setuptools`/`wheel` and `SOURCE_DATE_EPOCH` (identical from build to build).
- The `mariadb` extra is **not** in the installer: `mysqlclient` has no Windows wheel. PostgreSQL works. Users of MariaDB/MySQL would need a build toolchain (document in P12).
- Tesseract languages deu/fra/spa/ita/nld are bundled in the installer (small) and copied according to the checkboxes, so no download is needed. The uv and the Python are bundled too, so the base install needs no network.
- The Local AI add-on is installed from PyPI/the PyTorch CPU index at install time (about 600 MB) when its task is ticked, not shipped as a separate wheelhouse download.
- `windows/THIRD_PARTY.md` has generated tables between `BEGIN/END` markers; `make-third-party.py --check` (and a unit test) fail when they are out of date.

### Not verified (cannot be done here)

- A clean Windows 11 VM: all runs were on this development machine, which has Python, Tesseract etc. installed (`find_binary` resolved tesseract, gs and pngquant to the bundled `appin` copies, but `pdftoppm` to a Poppler from the WinGet folder on this machine's `PATH`: `PATH` is searched before `appin`, so a user-installed tool wins; a clean VM is needed to prove the bundled set is complete).
- Installing the Windows service from the installer (administrator rights and UAC needed): the code path (`service install --force --start`, firewall rule) is the P9 code, tested only up to the XML/ACL/command rendering. Needs an elevated run of `windows\scripts\test-service.ps1` and one installer run as administrator.
- The final page's "Open paperless-win in the browser" box (skipped in silent mode) and the wizard pages themselves (all runs were silent).
- Silent install with `/ADMINUSER` and `/ADMINPASSWORD` puts the password on the command line, as any silent installer parameter does; use the wizard when that matters.
- `smoke.ps1 -StartStack -Python <other env>` still sets `PYTHONPATH` to the repo's `src`, so it tests the repo code with that environment: the installed app was started with its own `paperless-ctl.cmd run` and smoke-tested without `-StartStack`.

### Out of scope / follow-ups

- Code signing (SmartScreen will warn: README in P12; `SIGN_COMMAND` hook exists in `build.ps1`).
- P11 builds the release in CI with the same `build.ps1`.
