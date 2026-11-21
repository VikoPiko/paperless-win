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
- [ ] Someone unfamiliar with the project can follow `install.md` on a fresh VM without asking questions. Ask the user to do this test.
- [ ] Every bundled third-party component appears in `THIRD_PARTY.md` with its licence.
