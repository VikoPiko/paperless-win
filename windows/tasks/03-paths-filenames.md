# P3 — Path storage and Windows-safe filenames

**Runs on:** Linux is fine for most of this; final verification on Windows. **Branch:** `winport/P03-paths`

## Goal

Paths stored in the DB and in export manifests are always POSIX (`a/b/c.pdf`) on every OS. Generated storage paths are legal on NTFS. Existing Windows databases with backslashes get repaired.

## Context

- `src/documents/signals/handlers.py` (~L490–560): `instance.filename = str(new_filename)` — produces `\` on Windows.
- `src/documents/consumer.py` (~L700–745), `src/documents/tasks.py` (~L430): where `filename` and `archive_filename` get set.
- `src/documents/file_handling.py`: `generate_unique_filename`, `generate_filename`, `format_filename` (`.strip(os.sep)`), `delete_empty_directories`, the `is_relative_to` safety checks.
- `src/documents/templating/filepath.py` (~L51): `.strip(os.sep)` on `/`-joined templates. This is a real bug on Windows.
- `src/documents/models.py` (~L520–590): `source_path`, `archive_path`, `get_public_filename` (`pathvalidate.sanitize_filename`).
- `src/documents/management/commands/document_exporter.py` / `document_importer.py`: manifest paths.
- `FilePathField` on `archive_filename`.

## Steps

1. Write failing tests first. Simulate Windows path semantics with `PureWindowsPath`-based helpers where possible, so the tests run on Linux:
   - a template `{{ created_year }}/{{ correspondent }}/{{ title }}` stores `2024/ACME/Invoice.pdf`, never with `\`;
   - leading and trailing `/` are stripped on both OSes;
   - a correspondent named `CON`, `aux.`, `foo  ` or `a:b*c?` produces a legal NTFS path for **every** component;
   - total path length beyond 260 characters is handled (truncate the title and keep the extension, or use a `\\?\` long path; pick one and document it);
   - `A.pdf` vs `a.pdf` is a collision on Windows (case-insensitive uniqueness check).
2. Add `paperless_win.paths`:
   - `to_db(path: Path | str) -> str` (as_posix, relative)
   - `from_db(s: str) -> Path`
   - `sanitize_component(s) -> str`, using `pathvalidate` with `platform="windows"` on Windows and the current behaviour on Linux
   - `fits_max_path(root, rel) -> bool`
3. Hook these into upstream with small marked edits:
   - use `"/"` instead of `os.sep` in the two `.strip(os.sep)` calls. This is a pure fix that's correct on both OSes. Note it as upstreamable, but **do not submit** it (CLAUDE.md rule 1).
   - wherever `filename` or `archive_filename` is assigned, store `to_db(...)`.
   - sanitize each component in `generate_filename` on Windows.
4. Exporter and importer: write POSIX paths in the manifest and accept both `/` and `\` when importing, so a Linux export imports on Windows and the other way round.
5. Add a data migration in a fork-owned Django app. If needed, add a minimal `paperless_win` AppConfig to `INSTALLED_APPS` on all OSes; it's a no-op on Linux. The migration rewrites `\` to `/` in `filename`, `archive_filename` and any other stored relative paths. It's idempotent and a no-op when nothing matches.
6. Run the full test modules for file handling, consumer, exporter and importer on Linux, then on Windows.

## Acceptance criteria

- [ ] The new tests pass on both OSes. Existing upstream file-handling tests still pass on Linux.
- [ ] Round trip: export on Windows, import on Linux (or under the Linux CI job with a Windows-produced fixture), and the reverse.
- [ ] `smoke.ps1` passes, with a storage path template configured that uses nested folders.

## Findings

_(fill in)_
