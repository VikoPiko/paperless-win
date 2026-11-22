# Tests skipped on Windows

The list itself is **`windows/skipped_tests.toml`**, applied by the pytest plugin
`src/paperless_win/pytest_plugin.py` on Windows only (`windows/scripts/run-tests.ps1` turns it on).
Linux runs never see it, and no upstream test file is edited, which keeps merges clean.

Policy (CLAUDE.md rule 5): fix a test if the fix is cheap and local; otherwise add it to the
TOML with a `reason` and a `follow_up`. Entries are node IDs, or a prefix at a `::` / `[` boundary
(module, class, function, all parametrisations). Budget: about 2% of the suite.

Current state (upstream v3.5.1): **34 entries** (a class-level entry counts once).

| Entries | Why                                                                                                                                            | Follow-up                                                          |
| ------: | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
|       1 | gpg is not on PATH on Windows (Git ships an msys gpg; Gpg4win is the native option). Mail GPG decryption is optional                           | P4/P12: decide how to provide gpg                                  |
|       8 | relies on POSIX chmod/permission semantics, which NTFS ACLs do not mirror                                                                      | none planned; OS semantics                                         |
|      13 | compares str(Path) with a POSIX string; production code stores POSIX paths since P3 (the test, not the code, is wrong on Windows)              | cheap upstreamable test fix (use as_posix); not submitted upstream |
|       3 | pre/post-consume scripts are executed directly; the test writes a POSIX shell script                                                           | P5 (script dispatch)                                               |
|       4 | sample files are checked out with CRLF line endings (git autocrlf); expected text has LF                                                       | P11: check out with core.autocrlf=false on the Windows runner      |
|       1 | by design on Windows: overlong names are shortened to fit MAX_PATH (paperless_win.paths) instead of falling back to the ID name                | none; behaviour differs by design (P3)                             |
|       1 | simulates a missing pdfinfo executable; on Windows the page size is read with pikepdf (paperless_win.pdf), so there is no pdfinfo call to fail | none; behaviour differs by design (P4)                             |
|       3 | unexplained Windows-only difference (SVG validation message, date/timezone edge, SQLite WAL file locking); not yet investigated                | triage after P4                                                    |

Entries marked P5/P11/P12 are expected to shrink as those phases land. Re-check this file at every
upstream sync: a test that starts passing on Windows should be removed from the TOML.
