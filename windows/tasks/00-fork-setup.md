# P0 — Fork setup and scaffolding

**Runs on:** any OS. **Branch:** `winport/P00-fork-setup`

## Goal

The fork exists with the right remotes and branch model. The winport scaffolding (folders, docs, patch checker, empty Python package, Windows CI skeleton) is committed, and upstream automation that makes no sense in a fork is switched off.

## Prerequisites (user does these, Claude Code verifies)

- [x] User forked `paperless-ngx/paperless-ngx` to `<user>/paperless-win` on GitHub (fork, then rename). _(verified: `git ls-remote origin` reaches `VikoPiko/paperless-win`, HEAD = `dev` @ `4973be8`)_
- [x] Local clone, with `origin` = fork and `upstream` = paperless-ngx. _(`origin` was set; `upstream` added by Claude with push URL set to `DISABLED`)_

## Steps

1. Verify the remotes (`git remote -v`). Add `upstream` if it's missing. `git fetch upstream --tags`.
2. Create `main` from the latest upstream **release tag** (currently `v3.5.1`, or newer if one exists), not from `dev`. Make `main` the default branch on the fork (tell the user if this needs the GitHub UI).
3. Add the plan files to the repo: `CLAUDE.md`, `windows/PLAN.md`, `windows/DECISIONS.md`, `windows/PATCHES.md`, `windows/SKIPPED_TESTS.md`, `windows/UPSTREAM-SYNC.md`, `windows/tasks/*`.
4. Create the `src/paperless_win/` package with `__init__.py` (holds `__version__ = "<upstream>-win.0"`) and an empty `platform.py`. It is not a Django app yet, just an importable package. Make sure pytest and ruff pick it up the same way as the sibling packages under `src/`.
5. Write `windows/scripts/check_patches.py`, which:
   - finds every file outside `src/paperless_win/`, `windows/`, `CLAUDE.md` and `.github/workflows/winport-*` that contains `winport:`,
   - compares that set with the table in `windows/PATCHES.md`,
   - exits non-zero on a mismatch and prints both differences.
6. Disable upstream workflows that publish or spam: Docker image publishing, crowdin/translation sync, issue and PR bots, cleanup-tags, project-actions, repo-maintenance. Disable them through the GitHub UI or `gh workflow disable`. Do **not** delete the workflow files, since deleting them causes merge conflicts. List what you disabled in `DECISIONS.md` (D7).
7. Add `.github/workflows/winport-ci.yml` (skeleton) that:
   - runs `check_patches.py` on ubuntu,
   - on `windows-latest`: checks out, installs uv, runs `uv sync`, and runs `python -c "import paperless_win"`. Full tests come in P11.
8. Replace the top of `README.md` with a short block:

   > **paperless-win** is an unofficial Windows port of paperless-ngx. Not affiliated with or supported by the paperless-ngx project. Report issues here, not upstream.

   Keep the rest of the upstream README below it. Register the README edit in `PATCHES.md`, because it is an upstream file.

## Acceptance criteria

- [x] `git log --oneline -1 main~N` shows the upstream tag as the base. _(local `main` = `v3.5.1` = `35b043919 Bump version to 3.5.1`; not yet pushed)_
- [x] `python windows/scripts/check_patches.py` passes (README row present). _(Plain `python`: `uv run` cannot sync on Windows yet, see Findings.)_
- [x] The `winport-ci` workflow passes on the fork. _(Both jobs green on `winport/P00-fork-setup`: Patch inventory, Windows import smoke printing `3.5.1-win.0`.)_
- [x] No upstream workflow will push images or open issues or PRs. _(Nine workflows disabled; see Findings. D7 still to be written, pending the user's OK.)_

## Out of scope

Any functional change to paperless.

## Findings

**Done locally (branch `winport/P00-fork-setup`, based on local `main` = `v3.5.1`):**

- Steps 1-5, 7 and 8 are complete: `upstream` remote and tags, plan files copied in, `src/paperless_win/` package, `check_patches.py`, `winport-ci.yml` skeleton, README notice.
- `PATCHES.md` has two rows: `README.md` (notice) and `pyproject.toml` (adds `src/paperless_win/tests` to pytest `testpaths`, so the fork's tests are collected like the sibling packages). Ruff already picks up `src/` via `tool.ruff.src`.

**Done on GitHub (via `gh`, logged in as the fork owner):**

- `main` (= `v3.5.1`) pushed; default branch switched from `dev` to `main` (by the user, via `gh repo edit`).
- The fork's workflows only registered after the user clicked "enable" on the Actions tab (until then `gh api .../actions/workflows` returned 0). The user set the Actions policy to "local only" while the upstream workflows were disabled, then back to "all".
- Disabled with `gh workflow disable`: `ci-docker`, `ci-release`, `issue-bot`, `pr-bot`, `project-actions`, `translate-strings`. Already `disabled_fork` (GitHub refuses to disable them again): `cleanup-tags`, `crowdin`, `repo-maintenance`, plus `codeql-analysis`.
- Still active: `ci-backend`, `ci-frontend`, `ci-lint`, `ci-static-analysis`. `ci-docs` was disabled at the user's request (it would try to deploy to Pages).
- The token needed the `workflow` scope (`gh auth refresh -h github.com -s workflow`) to push `winport-ci.yml`.

**D7** (list of disabled workflows) written to `DECISIONS.md` with the user's OK.

**Surprises:**

1. **`uv sync` cannot work on Windows yet.** `[tool.uv] environments` in `pyproject.toml` lists only linux x86_64/aarch64 and macOS arm64, so `uv sync --dry-run` fails with "The current Python platform is not compatible with the lockfile's supported environments". Fixing it means editing `pyproject.toml` and re-locking, which belongs to P1/P2 (see the `pyproject.toml` hotspot in `PLAN.md`) and is a functional change, which is out of scope here. Deviation from step 7: the Windows CI job installs uv but skips `uv sync` and runs `uv run --no-project ... import paperless_win` with `PYTHONPATH=src`, with a TODO in the workflow. `uv run python windows/scripts/check_patches.py` has the same problem on Windows, so use plain `python`.
2. **Repo location:** the clone is nested at `Desktop/paperless-win/paperless-win/`. The outer folder still holds the original copies of `CLAUDE.md` and `windows/`. These are copies, not moves; the committed ones are inside the clone. Delete the outer duplicates, or move the clone up a level.
3. `pyproject.toml` `requires-python` is `>=3.11` and CI upstream uses 3.12/3.14; CLAUDE.md pins 3.13 for the Windows build, so the new workflow uses 3.13.

**Verified:** `check_patches.py` passes, and fails (exit 1, both diffs printed) with an unregistered marker or a stale row. `ruff check` / `ruff format --check` are clean on the new files. The new test passes with a standalone pytest (the repo's own pytest config cannot be used on Windows yet, for the reason in Surprise 1).
