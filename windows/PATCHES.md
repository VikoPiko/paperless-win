# Upstream patch inventory

Every upstream-owned file this fork modifies. Each hunk in the file carries a
`winport:` marker comment. `windows/scripts/check_patches.py` fails CI if a file with
markers is missing here, or a listed file has no markers.

Keep this list short. Before adding a row, ask: can this be a hook into
`src/paperless_win/` instead?

| File | Phase | Why | Upstreamable on its own merits? |
|---|---|---|---|
| `README.md` | P0 | Unofficial-port notice at the top | No (fork-specific) |
| `pyproject.toml` | P0 | Add `src/paperless_win/tests` to pytest `testpaths` | No (fork-specific) |
| `.gitignore` | P1 | Ignore `.tools/` (bootstrap downloads) and `.spike/` (spike data) | No (fork-specific) |
