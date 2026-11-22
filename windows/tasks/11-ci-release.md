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

- [x] A PR that breaks a Windows-only path fails CI; a PR that breaks Linux fails CI. (Shown by what the jobs caught while this branch was built: the Windows service job failed three times on real bugs, and the Python 3.14 backend job failed on a `%` in an argparse help text that passed on 3.13 locally.)
- [ ] Tagging `v3.5.1-win.1` produces a release whose installer passes the install-test job. _The build and the install-test job pass from the branch `winport/release-test`; the last job, which publishes the GitHub release, only runs for a tag and has **not been run**: publishing a release on the fork is an outward-facing step that needs the owner's go-ahead._

## Findings

### What exists

- `winport-ci.yml`: `check-patches` (also `make-third-party.py --check`), `windows-tests` (bootstrap, `uv sync --frozen --extra webserver --extra postgres --extra ai-local`, `run-tests.ps1` with the skip list, JUnit artifact, failure summary), `windows-smoke` (a base install without the AI extra: `paperless-ctl init`, then `smoke.ps1 -StartStack`, stack logs on failure) and `windows-service` (`test-service.ps1` as administrator, with logs and process list on failure).
- Linux backend tests (with `--extra ai-local`, from P7), frontend tests, lint and static analysis are **upstream's own workflows** (`ci-*.yml`), which run unchanged on the fork; `winport-ci.yml` does not duplicate them.
- `winport-release.yml`: tag `v*-win.*` (or a push to the branch `winport/release-test`, which uses version `0.0.0-ci` and never publishes) builds the installer plus the Local AI wheels, writes `SHA256SUMS`, then **installs it silently on a fresh runner as administrator** (with the service), checks the checksums and that the service runs, runs `smoke.ps1` against it, uninstalls and checks the data is kept; only then (tag only) `gh release create` on this repository with notes from `windows/release-notes.md` (upstream version, SmartScreen note, known limitations).
- `winport-upstream-watch.yml` + `windows/scripts/upstream_watch.py` (unit-tested): weekly, reads the **tag names** of the public upstream repository (`git ls-remote --tags`, anonymous, nothing is written there), compares the newest stable `vX.Y.Z` with `src/paperless/version.py` and opens an issue "Sync upstream vX.Y.Z" **on this fork** (once per release). Reading upstream's tag list is what the task asks for; it is the only contact with the upstream repository.

### Measured (GitHub-hosted `windows-latest`, Windows Server 2025)

| What                            | Result                                                                                  |
| ------------------------------- | --------------------------------------------------------------------------------------- |
| Windows tests                   | 4426 passed, 97 skipped (same as locally), 7.3 min; smoke 2.6 min; service test 4.4 min |
| Release build (with warm cache) | 6 min; the install-test job 10 min                                                      |
| Service test                    | passes end to end; stop takes 5.8 s                                                     |

### What the first CI runs found (all fixed)

- The Windows smoke job needs a `PAPERLESS_SECRET_KEY` (upstream refuses the default); the workflow sets a throw-away one.
- **P9 service bugs** (WinSW 2.12 has no `restartwait`; WinSW appends the service's arguments to the stop command so the service could never be stopped; a permission-audit false positive): see the P9 findings.
- **P10 installer bug**: the service account could not read the installed venv: see the P10 findings.
- Python 3.14 (the backend job's version): argparse rejects `%ProgramData%` in a help text; a new unit test renders the help of every command.

### Not done / follow-ups

- Publishing a release (see the acceptance criterion): when the owner agrees, tag `v3.5.1-win.1` on `main` after the P-branches are merged.
- The windows jobs are not yet marked as required checks (branch protection is a GitHub setting).
- The Linux jobs run unchanged from upstream; a deliberately broken Linux change was not tried.
- If `windows-tests` becomes flaky under load (two upstream tests did locally once, "Access is denied" in a tantivy index commit, see the P6 findings) rerun first, then look.
