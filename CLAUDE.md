# CLAUDE.md — paperless-win

This repository is **paperless-win**, an _unofficial_ Windows port of
[paperless-ngx](https://github.com/paperless-ngx/paperless-ngx). It is a fork that
tracks upstream releases and adds a thin Windows layer so the app runs natively on
Windows 10/11 (no Docker, no WSL), installed via a normal installer and running as a
Windows service.

Read this file first, then `windows/PLAN.md`, then the task file you were asked to do
(`windows/tasks/NN-*.md`).

## Golden rules

1. **Never contact upstream.** Do not open PRs, issues, discussions or comments on
   `paperless-ngx/paperless-ngx` or any `paperless-ngx` org repo. Upstream does not
   support Windows and does not accept AI-generated PRs (see their `AGENTS.md`).
   PRs are only ever opened against this fork (`origin`), and only when the user asks.
2. **Keep the upstream diff thin.** We merge every upstream release. Every line we
   change in an upstream-owned file is a future merge conflict. Prefer, in order:
   1. new code in fork-owned locations (see "Where code goes"),
   2. a one-line hook in an upstream file that calls into fork-owned code,
   3. a small, local edit to upstream code — only when 1 and 2 are impossible.
3. **Mark and register every upstream edit.** Each changed hunk in an upstream file
   gets a `# winport: <short reason> (Pnn)` comment (or `// winport:` in TS), and the
   file + reason is added to `windows/PATCHES.md` in the same commit.
   `uv run python windows/scripts/check_patches.py` must pass.
4. **Linux must keep working.** Upstream's Linux test suite and Docker image must
   still build and pass. Windows behaviour goes behind `sys.platform == "win32"`
   (via `paperless_win.platform`), never by changing Linux defaults — unless the
   change is a pure bug fix that is correct on both (e.g. storing POSIX paths).
5. **Don't weaken tests.** Fix tests that assume POSIX when cheap. Otherwise skip on
   Windows with `@pytest.mark.skipif(sys.platform == "win32", reason="winport: ...")`
   and list it in `windows/SKIPPED_TESTS.md` with a reason and a follow-up note.
6. **Do not edit upstream's `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`** (merge
   noise). Where they conflict with this file for work _inside this fork_, this file
   wins; their rules about upstream contributions remain fully in force.
7. **Verify before claiming.** When handing back, list the commands you actually ran
   and their results. If you could not run something (e.g. you're not on Windows),
   say so plainly.

## Where code goes

| Location                          | Owner    | What lives there                                                                                                          |
| --------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------- |
| `src/paperless_win/`              | fork     | All Windows-specific Python: platform helpers, binary lookup, supervisor, service glue, Celery hooks, `paperless-ctl` CLI |
| `windows/`                        | fork     | Plan, task files, patch inventory, packaging (installer, build scripts), smoke tests, WinSW config, third-party manifest  |
| `.github/workflows/winport-*.yml` | fork     | Windows CI and release workflows                                                                                          |
| everything else                   | upstream | Touch only per rule 2/3                                                                                                   |

`paperless_win` must import cleanly on Linux too (it's just unused there), so tests can
run everywhere.

## Fixed decisions (see `windows/DECISIONS.md` for rationale)

- **Fork model:** track upstream _release tags_ (not `dev`). Sync procedure in
  `windows/UPSTREAM-SYNC.md`.
- **Redis:** ship Microsoft **Garnet** (Redis-compatible, native Windows) and run it as
  a child of our supervisor on `127.0.0.1`. No Redis-free mode for now.
- **AI features:** remote LLM/embedding backends (OpenAI-compatible, Ollama) work in
  the base install. Local embeddings (torch, sentence-transformers,
  llama-index-embeddings-huggingface) are an **optional add-on** extra (`ai-local`).
- **Database:** SQLite by default. PostgreSQL/MariaDB supported if the user points at
  an existing server; we don't bundle a DB server.
- **Task workers:** Celery `--pool=solo`, N separate worker processes managed by our
  supervisor (no prefork on Windows).
- **Web server:** Granian with `--loop asyncio` (uvloop doesn't exist on Windows).
  Fallback: uvicorn, only if P0 shows Granian is unfit.
- **Service:** one Windows service (WinSW wrapper) runs `paperless-ctl run`, which
  supervises Garnet, web, scheduler, consumer and workers.
- **Python:** 3.13 (pinned for the Windows build; check wheels before bumping).
- **Name / branding:** "paperless-win". The README and installer state clearly that it
  is unofficial and not affiliated with paperless-ngx. In-app title is set via
  upstream's existing `PAPERLESS_APP_TITLE` setting, not by editing the Angular code.
- **License:** GPL-3.0, same as upstream. Keep upstream notices. Every bundled
  third-party binary is listed in `windows/THIRD_PARTY.md` with its license and source.

## Environment

- Most tasks **must run on a Windows 10/11 x64 machine** (Claude Code on Windows with
  Git for Windows). Task files say when Linux is fine.
- Shell: PowerShell 7 (`pwsh`) for scripts in `windows/scripts/`. Don't write `.sh`
  for Windows tooling.
- Python env: `uv`. Backend tests: `cd src; uv run pytest <path>`.
  Windows smoke test: `pwsh windows/scripts/smoke.ps1`.
- Dev tools on Windows (installed by `windows/scripts/bootstrap-dev.ps1`): uv,
  Tesseract, Ghostscript, Poppler, pngquant, Garnet, Node + pnpm (frontend builds).
- Paths in code: use `pathlib`. Paths **stored in the DB or in export manifests are
  always POSIX** (`/`). Convert at the disk boundary.

## Working style

- One task file = one branch `winport/Pnn-short-name` = one focused PR to `origin`.
- Start each task by reading its "Context" files. Update the task's checklist and
  `windows/PLAN.md` status table as you go.
- Record any new decision or deviation in `windows/DECISIONS.md` (short ADR entry).
- If a task's assumption turns out wrong (e.g. Garnet lacks a command Celery needs),
  stop, write the finding into the task file under "Findings", and ask the user
  before switching approach.
- Commit messages: `winport(Pnn): <what>`.
