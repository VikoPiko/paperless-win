# P4 — External tools: fewer binaries, correct wiring

**Runs on:** Windows. **Branch:** `winport/P04-external-tools`

## Goal

Cut the number of CLI tools we have to bundle, and make the remaining ones work reliably on Windows.

## Context

- `src/documents/consumer.py` (~L438): `qpdf --replace-input ...` (find out exactly what it does: decrypt? linearize? repair?)
- `src/paperless/parsers/utils.py` (~L305): `pdfinfo` to get the page size
- `src/documents/parsers.py` (~L96): `pdftoppm` to make thumbnails
- `src/documents/barcodes.py` (~L541): `pdf2image.convert_from_path`
- `python-magic` usage (`grep -rn "magic\." src --include=*.py`)
- P1 Findings on libmagic

## Steps

1. **qpdf CLI → pikepdf.** pikepdf is already a dependency through OCRmyPDF. Put an equivalent function in `paperless_win/pdf.py`. Call it from the consumer **only on Windows** (keep the upstream behaviour on Linux to keep the diff small). Test it with encrypted, damaged and normal PDFs. Remove `qpdf` from the required binaries on Windows.
2. **pdfinfo → pikepdf** for the page size, again only on Windows: read the CropBox of page 1, falling back to the MediaBox, and match pdfinfo's rotation handling. Compare the output with pdfinfo on about 10 sample PDFs, including rotated and odd-sized pages.
3. **pdftoppm / pdf2image:** keep Poppler, which is the most faithful renderer. Pass `poppler_path=find_binary_dir("pdftoppm")` to pdf2image on Windows. Make sure the subprocess calls work when paths contain spaces and non-ASCII characters.
4. **libmagic:** implement the approach chosen in P1. The preferred approach is to bundle `libmagic-1.dll` + `magic.mgc` in `bin\`, with `MAGIC` env set by `bootstrap.apply()`, and check that `python-magic` loads it. Add a test that detects the mime type of PDF, PNG, TIFF, JPEG, HEIC, EML, TXT, DOCX.
5. **OCRmyPDF:** confirm it finds Tesseract, Ghostscript and pngquant through `PATH` set by `bootstrap.apply()`. Run OCR with `PAPERLESS_OCR_MODE` set to skip, redo and force. Confirm that `unpaper`-dependent options fail gracefully with a clear message when unpaper is missing, rather than crashing the task. If they crash, add a Windows-only settings or config validation.
6. **GnuPG** (mail decryption): find the Gpg4win `gpg.exe` through `find_binary`, so `python-gnupg` works. The test can be skipped if gpg isn't installed.
7. Write `windows/THIRD_PARTY.md` entries for each binary that will be bundled: name, version, licence, source URL and SHA256.

## Acceptance criteria

- [x] A Windows install no longer needs `qpdf.exe` or `pdfinfo.exe`. `pdftoppm.exe` is still needed. _(Verified: the smoke test and the suite pass with no `qpdf` anywhere; `pdfinfo` is only used by the new test that compares against it. The upstream binary check still *looks* for `pdfinfo`, which ships inside the Poppler package anyway.)_
- [x] Mime detection test passes on Windows. _(`test_mime.py`: 11 types x 3 directory names (ASCII, accented + spaces, Japanese) against the real DLL, 46 tests with the unit tests.)_
- [x] OCR, thumbnail and barcode-split tests in the upstream suite pass on Windows, or are listed in `SKIPPED_TESTS.md` with a reason. _(Full suite: 4,246 passed, 98 skipped, 0 failed. Every skip is in the list or upstream's own.)_
- [x] `smoke.ps1` passes, with a barcode-separator PDF added to the smoke fixtures. _(`smoke.ps1 -Barcode` against a live stack: the 3-page `windows/fixtures/barcode.pdf` splits into exactly 2 documents.)_

## Findings

**Implemented (all fork-owned except 2 tiny hooks):**

- `paperless_win.pdf`: `repair_in_place` (pikepdf, same qpdf library as the CLI), `shim_subprocess` (recognises `qpdf --replace-input [--warning-exit-0]` and runs it in-process), `first_page_size_points` and `page_size_hook` (pikepdf replacement for `pdfinfo`).
- `paperless_win.magic_compat`: Unicode-safe, more accurate `magic.from_file`, installed by `bootstrap.apply()`.
- `paperless_win.checks`: Django checks `paperless_win.W001` (unpaper missing while `OCR_CLEAN=clean`) and `W002` (libmagic unusable). Windows only, silent on Linux.
- `platform.gpg_dirs()`: Gpg4win's default folders are appended to `PATH` when present.
- `smoke.ps1 -Barcode` and `windows/fixtures/barcode.pdf`.
- 101 more tests in `src/paperless_win/tests/` (pdf 45, mime 46, checks 7, gpg 3).

**Upstream edits (2 files):** `documents/utils.py` (`run_subprocess` asks the shim first) and `paperless/parsers/utils.py` (`get_pdf_first_page_size_points` asks `page_size_hook` first). I did **not** change `consumer.py` / `parsers.py` as the task text suggested: upstream's tests mock `documents.consumer.run_subprocess` and assert the `qpdf` command, so replacing those call sites would have broken Linux tests. Hooking the one central function keeps every call site and test intact, and covers both qpdf call sites at once. Poppler's `pdftoppm` needed no change: it is found through `PATH` (set by `bootstrap.apply()`), including folders with spaces and non-ASCII names (covered by the mime test directories and the live barcode run).

**Findings (some are real bugs the plan did not predict):**

1. **libmagic cannot open non-ASCII paths on Windows** (`cannot open ... (No such file or directory)`). Upstream calls `magic.from_file` on the working copy, which keeps the original file name, so any document called `Müller Rechnung.pdf`, and any user whose profile path contains an accent, would fail to consume. Fixed in `magic_compat` without touching upstream.
2. **The bundled libmagic (2018) does not know HEIC/HEIF/AVIF** (reports `application/octet-stream`, so iPhone photos would not consume) **nor DOCX/XLSX/PPTX**. `magic_compat` corrects both from the file's `ftyp` box and zip entries. **Follow-up (P10):** replace the 2018 DLL with a current libmagic build (candidates: vcpkg or conda-forge `libmagic`) and then this refinement becomes a safety net. D8 should note this when the installer is built.
3. `pikepdf.PasswordError` is **not** a `PdfError`: a password-protected PDF would have escaped the repair and page-size helpers. Caught explicitly (test added).
4. **Live comparison with real `pdfinfo`**: 14 generated PDFs (A4, Letter, rotations 90/180/270/-90, CropBox smaller and larger than the MediaBox, inherited boxes and rotation, offset origin, swapped corners, odd 100.5 x 200.25 and 5000 x 7000 sizes) all match to 0.01 pt. UserUnit is not handled (neither is it checked by upstream's regex).
5. Repair behaviour vs `qpdf --replace-input`: a PDF with its xref table and trailer cut off is repaired and readable; a file that is not a PDF raises `CalledProcessError` (callers already catch it); an encrypted PDF with an empty user password is rewritten and stays readable; a password-protected one raises. I could not compare against the real qpdf CLI (not installed here), only against pikepdf's embedded library.
6. **Two upstream tests un-skipped** (qpdf thumbnail fallback and pdftoppm fallback), and one new skip was added by design (`test_pdfinfo_not_installed_returns_none` simulates a missing `pdfinfo`, which Windows no longer calls).
7. **OCR modes** (this version names them `auto`, `redo`, `force`, `off`; there is no `skip`): `auto`, `redo` and `force` all consume `smoke.pdf` and find the known word; `off` skips OCR as expected. Switched live through `/api/config/`.
8. **unpaper**: with `OCR_CLEAN=clean` and no unpaper, a consume fails _gracefully_: the task shows `MissingDependencyError: Could not find program 'unpaper' on the PATH` and nothing crashes; the new `W001` check now says so at startup with the fix. Clearing the setting restores normal operation.
9. **GnuPG:** `gpg` is looked up through the default Gpg4win folders only. Git for Windows ships `usr\bin\gpg.exe` (msys), which I deliberately ignore because it cannot use a Windows `GNUPGHOME`. I could not test with a real Gpg4win (not installed), so the 50 mail-GPG tests stay in the skip list; the lookup is unit-tested with fake folders.

**Windows suite after P4:** 4,246 passed, 98 skipped, 0 failed, of 4,344 cases (P3: 4,143 / 99). `check_patches.py` OK (17 files).

**Process note:** a background "wait for the test run" shell loop waited for an `exit` line the run never wrote, so it looked like the tests were stuck for about 80 minutes while they had finished in 4.5 minutes. Use the test run's own completion notification, not an `until grep` loop.
