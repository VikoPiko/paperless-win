# P12 — Docs, branding, licences

**Runs on:** any OS. **Branch:** `winport/P12-docs`

## Goal

A Windows user can install, use, back up, upgrade and troubleshoot paperless-win without reading Linux docs. The project is clearly unofficial and licence-compliant.

## Deliverables

1. `README.md` top section (expanded from P0) covering:
   - what this is, the unofficial disclaimer, and where to report issues (this fork, never upstream);
   - download and install in 5 steps, with system requirements;
   - feature differences from upstream (the trade-off table from PLAN.md);
   - a link to the upstream docs for general usage (the UI and features are the same).
2. `windows/docs/` (Markdown):
   - `install.md`: installer options, unattended install parameters
   - `configuration.md`: `paperless.conf` location, Windows-specific settings (`PAPERLESS_BIN_DIR`, `PAPERLESS_WIN_*`), the service account, network shares
   - `operations.md`: `paperless-ctl` reference, logs location, backup and restore (`document_exporter` to a folder plus the ProgramData backup), upgrades, moving from Docker to paperless-win (export → import)
   - `troubleshooting.md`: SmartScreen, Defender exclusions, port conflicts, file-lock errors, OCR language packs, LibreOffice/Tika setup
3. Branding:
   - set `PAPERLESS_APP_TITLE=paperless-win` in the generated default config (uses the upstream setting, no UI code changes);
   - give the installer, service display name and Start-menu entries the name "paperless-win" and their own icon. Do not use the paperless-ngx logo as the product logo; a simple original icon is fine.
4. Licences:
   - `LICENSE` stays GPL-3.0 (upstream file, untouched);
   - `windows/NOTICE.md`: states this is a modified version of paperless-ngx, lists the modifications at a high level (point to `PATCHES.md` + `src/paperless_win/`), and gives the date of the fork base (GPL-3 §5a);
   - `THIRD_PARTY.md` (generated in P10) includes licence texts or links for every bundled binary, and the installer shows it;
   - add a source offer or link in the installer's "About" (GPL/AGPL components).

## Acceptance criteria

- [ ] Someone unfamiliar with the project can follow `install.md` on a fresh VM without asking questions. **Needs the user (or a volunteer): not done.** The steps in it were checked against the real installer, but only by the author of the docs.
- [x] Every bundled third-party component appears in `THIRD_PARTY.md` with its licence (the table is generated from the build manifest, and a unit test fails if a bundled component has no licence text in `windows/licenses/`).

## Findings

### What was done

- `README.md` (inside the existing `winport` block, registered in `PATCHES.md`): what this is, the unofficial disclaimer and where to report issues (this fork), the five install steps with requirements, links to the docs, and the table of differences from the Linux version.
- `windows/docs/`: `install.md` (wizard, unattended parameters, upgrade, uninstall), `configuration.md` (`paperless.conf`, the Windows-only settings, helper programs, extra OCR languages, network shares and the service account), `operations.md` (`paperless-ctl` reference, logs, backup, restore, moving from Docker), `troubleshooting.md`. They are installed with the program, in its `docs` folder.
- Branding: `PAPERLESS_APP_TITLE=paperless-win` is written into the generated `paperless.conf` (upstream setting, no UI change; unit-tested); the installer, uninstaller and Start-menu entry use an original icon (`windows/installer/paperless-win.ico`, drawn by `make_icon.py`; it is not the paperless-ngx logo); the service is named `paperless-win`.
- Licences: `windows/NOTICE.md` (modified version of paperless-ngx, base v3.5.1 of 17 Nov 2026, modifications since 21 Nov 2026, pointer to `PATCHES.md`); `windows/licenses/` holds the licence texts that the components do not ship themselves, and the build installs them in the `licenses` folder; the installer's licence page now lists every bundled component with its licence and source, plus a statement where the source code of paperless-win and of each bundled program can be had (for Ghostscript, AGPL, the exact release); `THIRD_PARTY.md` has a verification note.

### Verified while writing (so the docs do not guess)

- Export and import between two installations on this machine: `document_exporter` into an existing folder, then `document_importer` into a second, new installation: the document came across with content, checksum and archive file. The importer needs the target folder to exist, and **the accounts from the export replace the administrator the installer created** (tried: the new administrator was gone afterwards).
- `TESSDATA_PREFIX=<folder>` in `paperless.conf` makes `paperless-ctl check` find a language that is not in the program folder. That survives upgrades; files put into the program folder's own `tessdata` do not (except the five languages the installer offers).
- Measured: installed program 1.57 GB, a new data folder 0.5 GB; memory per process from the P6 soak.
- The full local build still works with the new files (docs, licences, icon, licence page); the CI install test is run on the P12 branch (see P11).

### Not verified / for the owner

- **The fresh-VM acceptance test above.**
- Moving from a real Docker installation: only Windows to Windows was tried. The importer accepts both `/` and `\` in a manifest and the unit tests cover it.
- Not tried: the offline Local AI add-on (`paperless-win-ai-local-<version>.zip`) is built by the release workflow, but its use is not documented because the procedure was not tested; the firewall option; the wizard pages (every run was silent); the "Defender" advice (written as advice, not measured).
- **The source-offer wording on the installer's licence page is mine and should be read by the owner.** It points to the GitHub repository for paperless-win and to each component's release for the rest, and promises nothing beyond that (no "three years" written offer). If the project wants a formal offer, that text is in `windows/build/build.ps1`.
- Poppler: the Windows package ships only the licences of its data files; that the programs are GPL-2.0-or-later is the Poppler project's statement (noted in `THIRD_PARTY.md`).
- The licence texts in `windows/licenses/` were fetched from the projects' own repositories at the pinned tags (or copied from the shipped packages); they were read, not compared with notices inside the binaries.
