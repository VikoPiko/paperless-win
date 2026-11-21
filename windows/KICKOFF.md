# How to drive this with Claude Code

## One-time setup (you)

1. On GitHub, fork `paperless-ngx/paperless-ngx` and rename the fork to `paperless-win`.
2. On your **Windows** machine, install Git for Windows, PowerShell 7 and Claude Code. Then:
   ```powershell
   git clone https://github.com/<you>/paperless-win.git
   cd paperless-win
   git remote add upstream https://github.com/paperless-ngx/paperless-ngx.git
   ```
3. Copy `CLAUDE.md` and the `windows/` folder from this plan into the repo root.
4. Start `claude` in the repo root.

## Prompt per phase

Paste this, changing only the task file name:

> Read CLAUDE.md and windows/PLAN.md, then do windows/tasks/00-fork-setup.md.
> Work on the branch the task names. Tick the checklist items as you complete them,
> fill in the Findings section, update the status in PLAN.md, and register any
> upstream edits in PATCHES.md. Stop and ask me before changing any decision in
> DECISIONS.md. At the end, list the commands you ran and their results.

Suggested order: 00 → 01 → (review P1 findings together before continuing) → 02 → 03 → 04 → 05 → 06 → 07 → 09 → 10 → 11 → 12 → 08.

## Tips

- Use plan mode (Shift+Tab) for P1, P3 and P6. These are the phases where the design is most likely to need adjusting once Claude Code has read the code.
- Start a fresh session per phase. CLAUDE.md, PLAN.md and the Findings sections carry the context between sessions.
- After P1, re-read its Findings yourself. If Garnet or Granian didn't work, the decisions change, and every later task should be adjusted before you continue.
- Upstream releases: when the weekly watcher opens a "Sync upstream" issue, prompt:
  > Read CLAUDE.md and do windows/UPSTREAM-SYNC.md for upstream tag vX.Y.Z.
