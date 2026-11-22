# P5 — Consume pipeline robustness on Windows

**Runs on:** Windows. **Branch:** `winport/P05-consumer`

## Goal

Dropping files into the consume folder works reliably on Windows, despite file locking, scanners that write slowly, antivirus scans and network shares.

## Context

- `src/documents/management/commands/document_consumer.py` (watchfiles, stability tracker, rescan, polling)
- `src/documents/consumer.py` (pre/post-consume scripts ~L299–400, file moves)
- `src/documents/utils.py` (`copy_file_with_basic_stats`, `run_subprocess`)
- `src/documents/file_handling.py` (moves and renames of originals and archives)
- `src/paperless_ai/vector_store.py` (`os.replace` swap), `src/paperless_ai/indexing.py` (filelock)

## Steps

1. **Retry helper** `paperless_win.fs.retry_io(fn, *, attempts, backoff)`: retries on `PermissionError` and the Windows sharing-violation winerrors 32 and 33, with exponential backoff (default about 5 s total). Use it around every move, rename, replace or unlink of document files, through small marked hooks or by wrapping the upstream helper functions in one place if they're centralised. Write tests that hold a file open from another process and release it after 1 s.
2. **Stable-file detection:** confirm the consumer's stability tracker waits until size and mtime stop changing **and** the file can be opened exclusively, which matters on Windows. Add the exclusive-open probe on Windows only.
3. **Network consume folders:** if `CONSUMPTION_DIR` is a UNC path or a mapped network drive, use polling by default (`CONSUMER_POLLING_INTERVAL` > 0, for example 10 s) and log why. Put this in `paperless_win.platform` as `is_network_path()`.
4. **Pre/post-consume scripts:** on Windows, choose how to run the script from its extension:
   - `.ps1` → `pwsh -NoProfile -ExecutionPolicy Bypass -File`, falling back to `powershell.exe` if pwsh isn't installed
   - `.bat` / `.cmd` → `cmd /c`
   - `.py` → `sys.executable`
   - `.exe` → run directly
   - anything else → a clear error

   Pass the same environment variables upstream passes. Add `windows/examples/post-consume.ps1` as a Windows version of `scripts/post-consumption-example.sh`.

5. **Ignore patterns:** add Windows junk to the default ignores on Windows only: `Thumbs.db`, `desktop.ini`, `~$*` (Office lock files), `*.tmp`, `*.part`, `*.crdownload`.
6. **Vector store / index swaps:** check the `os.replace`-based swap in `paperless_ai/vector_store.py` and the tantivy index directory on Windows while readers have the file open. Use `retry_io` if needed.
7. Long soak test `windows/scripts/soak-consume.ps1`: copy 200 mixed files into the consume folder in bursts, including slow writes that copy in chunks with delays. Assert that all 200 get consumed, there are no duplicates, and the consume folder ends up empty.

## Acceptance criteria

- [x] The soak test passes 3 times in a row, with Windows Defender real-time protection **on**.
- [x] Pre- and post-consume scripts work for `.ps1`, `.bat` and `.py`.
- [x] A consume folder on an SMB share works in polling mode.

## Findings

**Result: all three acceptance criteria met (2026-11-22).**

- **Soak, Defender real-time ON** (it is enabled on this machine; exclusions are not readable without admin, so none were assumed): 3 consecutive runs of 200 mixed files (50 PDF, 50 PNG, 100 TXT; 12 written slowly under an exclusive lock, 8 chunks 250 ms apart; bursts of 20) into a local consume folder with 1 web + 2 solo workers + consumer. Run times 26.2 / 21.1 / 21.0 min. Each run: 200/200 files became exactly one document, 0 duplicates, text files byte-identical in content, consume folder empty, 0 failed tasks. About 11% of image files did not reproduce the random token through OCR; that is OCR accuracy on random strings, not a consume failure (token is only hard-checked for TXT).
- **SMB:** consume folder `\\localhost\C$\...\consume-smb` (loopback admin share). The consumer logged `Watching ... using polling (interval: 10.0s)` without any setting: `bootstrap` detects UNC and mapped-drive paths with `fs.is_network_path` and defaults `PAPERLESS_CONSUMER_POLLING_INTERVAL=10` (explicit values win). 40-file soak (6 slow writers) over the share: 40/40 consumed, no duplicates, folder empty. Not tested: a real remote SMB server and a mapped drive letter (detection is unit-tested with `GetDriveTypeW` mocked).
- **Retry helper** `paperless_win.fs.retry_io` (PermissionError, winerror 32/33, 6 attempts, 0.16 s doubling, about 5 s). Hooked into: `copy_file_with_basic_stats`, the original/working-copy `unlink`s in `consumer.py`, the two `shutil.move`s in `signals/handlers.py`, and the vector-store swap in `paperless_ai/vector_store.py`. Tested with a second process holding the file and releasing it after about 1 s. During the soaks no `WinError`/`PermissionError` reached the logs.
- **Stable-file detection:** upstream's tracker already waits for size/mtime to stop changing; on Windows `TrackedFile.is_unchanged` additionally requires `fs.file_is_released` (CreateFileW with share-none; only winerror 32/33 count as "still locked"). `tests/test_tracker_probe.py` covers it; the slow exclusive-lock writers in the soak never produced a half-written document.
- **Scripts:** `scripts.script_arguments` dispatches by extension on Windows (`.ps1` pwsh -> WindowsPowerShell -> `powershell`, `.bat/.cmd` via `cmd /c`, `.py` via `sys.executable`, `.exe` direct, otherwise a clear error). Hooked once in `documents.utils.run_subprocess`, so pre- and post-consume both use it. Verified for real (not only mocked) for `.ps1`, `.bat` and `.py`; examples in `windows/examples/post-consume.{ps1,cmd,py}`. Three upstream tests that run `.sh` scripts stay skipped (listed in `SKIPPED_TESTS.md`).
- **Ignore patterns:** upstream already ignores `Thumbs.db` and `desktop.ini`; Windows adds `~$*`, `*.tmp`, `*.part`, `*.crdownload` through `bootstrap._merge_ignore_patterns` (Windows only, no upstream edit).
- **Index:** the Whoosh/tantivy index and filelock paths were exercised by every consume and delete in the soaks (about 1,800 documents indexed/removed) with no lock errors, so no hook was added there.
- **Not changed:** in the full suite two timing-sensitive tests in `test_management_consumer` can fail when the machine is under load; they pass in isolation.
