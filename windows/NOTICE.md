# Notice: paperless-win is a modified version of paperless-ngx

**paperless-win** is an unofficial port of [paperless-ngx](https://github.com/paperless-ngx/paperless-ngx)
to native Windows. It is **not** made, endorsed or supported by the paperless-ngx project or its
contributors. Do not report problems with paperless-win to them: use the issues of this repository,
[VikoPiko/paperless-win](https://github.com/VikoPiko/paperless-win/issues).

## Licence

paperless-ngx is free software under the **GNU General Public License, version 3**. paperless-win is a
modified version of it and is distributed under the same licence: see `LICENSE` (the unchanged upstream
file; the installer shows it, and installs it as `LICENSE.txt`). The upstream copyright notices in the
source files are kept.

The installer also contains programs from other projects under their own licences (among them Ghostscript
under the AGPL and Tesseract under the Apache licence). Each one is listed with its licence and the
address of its source code in `windows/THIRD_PARTY.md` (installed as `THIRD_PARTY.md`); the licence texts are
in the `licenses` folder of the installation, and the installer's licence page lists every component.

## What was changed

- **Base:** paperless-ngx **v3.5.1** (upstream commit `35b043919`, 17 November 2026). The modifications
  start on 21 November 2026. The upstream release tag is the base of every release of this fork; a
  version is named `X.Y.Z-win.N` after the upstream version it is built on.
- **New code, in places upstream does not use:** the Python package `src/paperless_win/` (Windows helpers,
  the supervisor that replaces the container's process manager, the `paperless-ctl` command, the Windows
  service integration, the installer's configuration step) and the folder `windows/` (plan, build scripts,
  installer, tests, documentation).
- **Small edits to upstream files:** every one is marked `winport:` in the source and listed with its reason
  in `windows/PATCHES.md`. In short: paths stored in the database are always written with `/`; Windows
  file-handling differences (renaming, locking, long paths); finding the bundled programs (Tesseract,
  Ghostscript, Poppler, libmagic and so on); running `qpdf` and reading PDF page sizes in-process, because
  the command-line tools are not bundled; the Celery worker recycling and task time-limit handling; an
  optional "local AI" extra; and a few build and CI files.
- **Not changed:** the web interface, the REST API, the data model (one added migration for the path
  separator) and the feature set, except for what is listed under "accepted trade-offs" in
  `windows/PLAN.md` (for example, no `unpaper` and no Gotenberg).

The exact difference to upstream is always available with `git diff v3.5.1..` in the source repository.

## How it was made

The modifications were written by Claude Code (Anthropic's AI coding assistant) working under the direction
of the repository owner, who set the goals and rules (`CLAUDE.md`, `windows/PLAN.md`). The code is tested
(see `windows/SKIPPED_TESTS.md` for what is not) but has not had an independent security audit. As with all
GPL software, there is no warranty: keep backups.
