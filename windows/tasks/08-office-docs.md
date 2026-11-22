# P8 — Office documents without Gotenberg

**Runs on:** Windows. **Branch:** `winport/P08-office` **Priority:** after v0.1.0 is acceptable.

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

- [x] DOCX, XLSX, PPTX, ODT and EML (HTML body) files consume into searchable documents with an archive PDF.
- [x] 20 conversions running at once through the workers cause no hangs or profile-lock errors.
- [x] If LibreOffice is missing, the error message tells the user exactly what to install.

## Findings

**Status: done and verified on a real stack on this machine; the CI job `windows-office` runs the same script on a GitHub runner.**

### Design (deviates from the task text: proposed, needs the owner's OK to be recorded in `DECISIONS.md`)

The task asked for hooks at each Gotenberg call site and a new `paperless_win/office.py` converter. Instead, `src/paperless_win/office.py` is a small **Gotenberg-compatible HTTP service**: it answers the three routes paperless uses (`/forms/libreoffice/convert`, `/forms/chromium/convert/html`, `/forms/pdfengines/merge`, plus `/health`) and the supervisor starts it as a child when Tika is enabled, pointing `PAPERLESS_TIKA_GOTENBERG_ENDPOINT` at it. Reasons: **zero upstream files changed** (no new hunks in `PATCHES.md`; both the Tika parser and the mail parser, and any future caller of `gotenberg_client`, work unchanged), and conversions are queued in one place, which is where a "one at a time" lock has to live anyway (the workers are separate processes). Proposed `DECISIONS.md` entry (not written, as the rules ask): _D14, Office documents: a Gotenberg-compatible local service backed by user-installed LibreOffice and Edge/Chrome, instead of call-site hooks; Tika and Java are user-supplied too._

- LibreOffice converts Office files; `pdf` for plain output and the `*_pdf_Export` filter with `SelectPdfVersion` when PDF/A is asked for (the filter depends on writer, calc, impress or draw).
- Microsoft Edge (always present on Windows 10/11), else Chrome, prints the HTML of an e-mail: `--headless=new --print-to-pdf`, with the paper size and margins paperless sends turned into an `@page` rule (A4 came out as 8.26 x 11.69 in). Spiked LibreOffice for HTML: not needed, Edge's result was good.
- Merge of the two e-mail PDFs: pikepdf, in the order of the numbered file names.
- Tika: the supervisor runs `java -jar tika-server-standard-<v>.jar` (found by `PAPERLESS_WIN_TIKA_JAR` or in the tool folders) on 127.0.0.1:9998 when `PAPERLESS_TIKA_ENABLED=true` and no endpoint is configured; ready in about 2 s here.
- Neither LibreOffice, Java nor Tika are bundled (user-installed; `THIRD_PARTY.md` lists them as optional with pinned test downloads).

### Measured (LibreOffice 26.8.3 unpacked without admin rights, Tika 3.3.3, Java 25, Edge)

| What                                                             | Result                                                                                                                                                                                                                             |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LibreOffice with a **new profile**                               | 23 s per conversion: far too slow per call                                                                                                                                                                                         |
| LibreOffice with a **kept profile**                              | 4.6-5.2 s. The service keeps one profile per allowed concurrent conversion (default 1), hands them out one at a time, and throws a profile away when a conversion fails or hangs                                                   |
| Edge print of an HTML e-mail                                     | 1-2 s                                                                                                                                                                                                                              |
| The five fixtures through paperless (consume folder)             | all five became documents with an archive PDF and the known word in the text, in 32 s                                                                                                                                              |
| 20 conversions requested at the same moment (direct, 20 threads) | 20 of 20 OK in 99 s (they queue), no `soffice` process left                                                                                                                                                                        |
| 20 DOCX uploaded at the same moment through the API              | 20 of 20 became documents in 113 s, no failed task, no leftover process                                                                                                                                                            |
| LibreOffice missing                                              | the failed document says "Error while converting document to PDF: HTTP 503: LibreOffice was not found. Install LibreOffice (https://www.libreoffice.org/download/, the 64-bit Windows installer) or set PAPERLESS_WIN_SOFFICE ..." |

### Findings on the way

- `gotenberg_client`'s `HttpStatusError` has **no message**, so paperless would show "Error while converting document to PDF: " and nothing else. `office.install_error_details()` (called from the existing `bootstrap.apply()` hook) makes it include the HTTP status and the server's reply. It patches `__str__` of a third-party class, guarded for a missing or changed library; a unit test uses the real client against the service.
- The client sends lengths with units (`8.27in`), not numbers: found by logging the requests of the real client.
- Python-magic crashed my first manual test (no `bootstrap.apply()`); not a product bug, but it cost a 5-minute timeout: every standalone script that touches the parsers must call `bootstrap.apply()` first.
- Git Bash hides `ProgramFiles(x86)` (the brackets): program folders have a fallback now.
- **Seen once, not P8:** of 20 files copied into the consume folder at the same moment, the watcher missed the event of one and the 5-minute rescan imported it ("Rescan found untracked file"), so it took 5 minutes. P5's area; a shorter rescan interval on Windows may be worth a look.

### Not verified / follow-ups

- Whether LibreOffice and Edge start when the service runs as `NT SERVICE\paperless-win` (session 0, no profile): not tested. The CI job runs as a normal runner user.
- PDF/A: the export filter is requested and the PDFs carry PDF/A markers, but conformance was not validated (no veraPDF); the PDF of an e-mail's HTML part is a plain PDF, not PDF/A.
- Chrome instead of Edge, a Windows without Edge, other Java versions, `.doc`/`.rtf` beyond the sample `.doc`, very large files, and an Office file with macros or a password were not tried.
- `paperless-ctl check` and the supervisor log say what is missing; the installer does not offer to install any of it.
- A CI job `windows-office` runs `windows/scripts/office-integration.ps1` (downloads the 376 MB LibreOffice MSI and the 74 MB Tika jar through `bootstrap-dev.ps1 -WithOffice`).
