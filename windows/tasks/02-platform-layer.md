# P2 — Platform layer

**Runs on:** Windows (tests must also pass on Linux). **Branch:** `winport/P02-platform-layer`

## Goal
A single fork-owned module, `paperless_win.platform`, answers every "where is X on this OS" question, and upstream code is hooked into it with tiny edits.

## Context
- P1 Findings
- `src/paperless/settings/__init__.py`: config search loop (~L33), `GNUPG_HOME` (~L1000), `THUMBNAIL_FONT_NAME` (~L1043), data and media dir defaults
- `src/paperless/checks.py` → `binaries_check`, Tesseract language check
- every `subprocess.run([...])` / `run_subprocess([...])` that calls a binary by bare name (`grep -rn "run_subprocess\|subprocess\." src --include=*.py`)

## Design
`src/paperless_win/platform.py`:
```python
IS_WINDOWS: bool
def app_dir() -> Path            # install dir (frozen layout) or repo root (dev)
def program_data_dir() -> Path   # %ProgramData%\paperless-win on Windows; None-equivalent on Linux
def config_search_paths() -> list[Path]
def default_tmp_dir() -> Path    # tempfile.gettempdir()
def default_font() -> Path       # bundled LiberationSerif-Regular.ttf on Windows
def find_binary(name: str) -> str | None
```
`find_binary` resolves in this order: `PAPERLESS_BIN_<NAME>` env override, then `PAPERLESS_BIN_DIR`, then `app_dir()/bin/**`, then `PATH`. It maps Windows names (`gs` → `gswin64c.exe` / `gswin64.exe`, adds `.exe`). On Linux it behaves exactly like `shutil.which`.

Also make sure `PATH` contains the bundled `bin` dirs at process start, so OCRmyPDF, pdf2image and others find Tesseract and Ghostscript without changes. Do this in one place, a `paperless_win.bootstrap.apply()` called once.

## Steps
1. Implement `platform.py` and `bootstrap.py`, with unit tests in `src/paperless_win/tests/`. Monkeypatch `sys.platform` and env vars so the tests also run on Linux.
2. **Hook 1, settings:** at the very top of `paperless/settings/__init__.py`, add `from paperless_win.bootstrap import apply as _winport_apply; _winport_apply()`. Make the config search loop use `config_search_paths()` when on Windows. Use `default_tmp_dir()` and `default_font()` for the GNUPG and thumbnail-font defaults on Windows only. Keep each hunk minimal and marked.
3. **Hook 2, binary calls:** wherever upstream runs `"pdftoppm"`, `"pdfinfo"`, `"gs"`, `"tesseract"` or `"qpdf"` by bare name, wrap the name in `find_binary(...)`. Some of these calls disappear in P4; still make them correct now.
4. **Hook 3, checks:** `binaries_check` and the Tesseract language check use `find_binary`.
5. Bundle `windows/assets/fonts/LiberationSerif-Regular.ttf` (SIL OFL, add it to `THIRD_PARTY.md`).
6. Register each upstream edit in `PATCHES.md`.

## Acceptance criteria
- [ ] With **no** tool folders on `PATH` but `PAPERLESS_BIN_DIR` set, `manage.py check` shows no binary warnings and `smoke.ps1` passes.
- [ ] Linux test suite unchanged (green).
- [ ] `check_patches.py` passes. Upstream files touched ≤ 5.

## Findings
_(fill in)_
