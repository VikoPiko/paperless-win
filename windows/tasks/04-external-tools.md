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

- [ ] A Windows install no longer needs `qpdf.exe` or `pdfinfo.exe`. `pdftoppm.exe` is still needed.
- [ ] Mime detection test passes on Windows.
- [ ] OCR, thumbnail and barcode-split tests in the upstream suite pass on Windows, or are listed in `SKIPPED_TESTS.md` with a reason.
- [ ] `smoke.ps1` passes, with a barcode-separator PDF added to the smoke fixtures.

## Findings

_(fill in)_
