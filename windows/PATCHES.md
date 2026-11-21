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
| `src/paperless/settings/__init__.py` | P2 | Import `paperless_win` hooks; add Windows `paperless.conf` locations to the config search; call `bootstrap.apply()` after the conf is read (PATH, libmagic, Windows defaults) | No (fork-specific) |
| `src/paperless/checks.py` | P2 | `binaries_check` uses `find_binary` (`gs` is `gswin64c` on Windows; identical to `shutil.which` on Linux) | Yes, harmless on Linux |
