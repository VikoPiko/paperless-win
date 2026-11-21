# P11 — CI and releases

**Runs on:** GitHub Actions. **Branch:** `winport/P11-ci`

## Goal

Every PR to the fork is tested on Linux (proving the fork didn't break upstream behaviour) and on Windows (proving the port works). Tags produce an installer release.

## Workflows (all fork-owned, `winport-*.yml`)

1. `winport-ci.yml` (PRs and pushes to `main`):
   - `patches`: `check_patches.py`
   - `linux-tests`: same command as upstream's backend CI, with `--extra ai-local`
   - `windows-tests`: `windows-latest`. Install the tools with `bootstrap-dev.ps1` (cache `.tools`), start Garnet, run `uv run pytest -n auto`. Upload the failure summary. Fail if a test fails that isn't listed in `SKIPPED_TESTS.md`.
   - `windows-smoke`: `paperless-ctl init && paperless-ctl run` (background) → `smoke.ps1`
   - `frontend`: upstream's frontend test command (unchanged, Linux)
2. `winport-release.yml` (tag `v*-win.*`):
   - `build.ps1` → installer + AI add-on wheelhouse zip + `SHA256SUMS`
   - install-test job: a fresh runner silently installs the artifact (`/VERYSILENT` with params) → `smoke.ps1`
   - GitHub Release with notes: the upstream version it's based on, fork changes, known limitations, the SmartScreen note
3. `winport-upstream-watch.yml` (weekly cron): checks for a new upstream release tag and opens an **issue on the fork** titled "Sync upstream vX.Y.Z" that links `UPSTREAM-SYNC.md`. It never touches upstream.

## Acceptance criteria

- [ ] A PR that breaks a Windows-only path fails CI; a PR that breaks Linux fails CI.
- [ ] Tagging `v3.5.1-win.1` produces a release whose installer passes the install-test job.

## Findings

_(fill in)_
