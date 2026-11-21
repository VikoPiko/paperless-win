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
- [ ] The soak test passes 3 times in a row, with Windows Defender real-time protection **on**.
- [ ] Pre- and post-consume scripts work for `.ps1`, `.bat` and `.py`.
- [ ] A consume folder on an SMB share works in polling mode.

## Findings
_(fill in)_
