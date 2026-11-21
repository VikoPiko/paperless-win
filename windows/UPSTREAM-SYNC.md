# Upstream sync procedure (task for Claude Code)

Run when upstream publishes a new release tag `vX.Y.Z`. Can be done on Linux for the
merge; Windows needed for the final smoke test.

## Steps

1. `git fetch upstream --tags`
2. Read upstream's changelog for the release (`docs/changelog.md` in the tag). Note any
   change touching: settings, Celery config, `docker/rootfs` init/service scripts,
   consumer, file handling, parsers, dependencies. Write a short summary into the PR
   description.
3. `git switch -c sync/vX.Y.Z main` then `git merge vX.Y.Z`.
4. Resolve conflicts. Rules:
   - In upstream files, take upstream's version, then re-apply our `winport:` hunks
     listed in `windows/PATCHES.md`.
   - If upstream changed `docker/rootfs/etc/s6-overlay/s6-rc.d/*` (new init step or
     service), mirror it in `paperless_win/ctl.py` / `supervisor.py`.
   - If upstream added a binary dependency (Dockerfile `RUNTIME_PACKAGES`), add it to
     `paperless_win.platform` lookup, `bootstrap-dev.ps1`, the build manifest and
     `THIRD_PARTY.md` — or document it as unavailable.
   - If upstream changed `pyproject.toml` deps, re-run `uv lock` and check Windows
     wheels exist (`uv pip compile --python-platform windows ...`).
5. `uv run python windows/scripts/check_patches.py`
6. Linux: `cd src && uv run pytest -x -q -n auto`
7. Windows: full test run + `pwsh windows/scripts/smoke.ps1`
8. Bump fork version `X.Y.Z-win.N` (N resets to 1 on each upstream bump).
9. Open PR `sync/vX.Y.Z → main` **on origin only**. Never on upstream.
