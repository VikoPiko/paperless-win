# P8 — Office documents without Gotenberg

**Runs on:** Windows. **Branch:** `winport/P08-office`  **Priority:** after v0.1.0 is acceptable.

## Goal
Office and email-to-PDF conversion works on Windows without containers, using user-installed LibreOffice and an optional Tika server.

## Context
- `src/paperless/parsers/tika.py`: Tika for text and metadata, Gotenberg `libre_office.to_pdf()` for the archive PDF
- `src/paperless/parsers/mail.py`: Gotenberg for HTML/EML → PDF
- the parser registry (`src/paperless/parsers/registry.py`)

## Design
- **Text and metadata:** Tika server is a Java jar that runs fine on Windows. `paperless-ctl` can supervise it as an optional child if `PAPERLESS_WIN_TIKA_JAR` and a Java runtime are configured. Otherwise the user points `PAPERLESS_TIKA_ENDPOINT` at their own Tika.
- **PDF conversion:** add a Windows-only converter in `paperless_win/office.py` that runs `soffice --headless --convert-to pdf --outdir <tmp> <file>`. It uses a per-call `-env:UserInstallation=file:///<tmp-profile>` to avoid profile locks, runs one conversion at a time (a lock), has a timeout, and kills the process tree on hang.
- **HTML/EML → PDF:** try LibreOffice (`--convert-to pdf` on .html). If the quality is poor, consider an optional headless Chromium/Edge print-to-PDF (`msedge --headless --print-to-pdf`). Edge is on every Windows 10/11 machine, which makes it attractive. Spike both and pick one.
- **Hook:** when `PAPERLESS_WIN_OFFICE_CONVERTER=local` (the default on Windows when Gotenberg isn't configured), the parsers call our converter instead of the Gotenberg client. Ideally that's one marked hook per call site.

## Acceptance criteria
- [ ] DOCX, XLSX, PPTX, ODT and EML (HTML body) files consume into searchable documents with an archive PDF.
- [ ] 20 conversions running at once through the workers cause no hangs or profile-lock errors.
- [ ] If LibreOffice is missing, the error message tells the user exactly what to install.

## Findings
_(fill in)_
