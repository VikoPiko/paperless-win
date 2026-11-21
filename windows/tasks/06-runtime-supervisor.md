# P6 — `paperless-ctl` and the process supervisor

**Runs on:** Windows. **Branch:** `winport/P06-supervisor`

## Goal
One command, `paperless-ctl run`, starts and supervises the whole stack on Windows. This replaces s6-overlay. `paperless-ctl init` does what the s6 `init-*` scripts do.

## Context
- `docker/rootfs/etc/s6-overlay/s6-rc.d/` — every `init-*` and `svc-*` `run` script. This is the spec to copy.
- `docker/management_script.sh`, `docker/install_management_commands.sh`
- Celery settings in `paperless/settings/__init__.py` (~L700–750)
- P1 Findings (Granian/Garnet behaviour)

## Design
`src/paperless_win/ctl.py` is exposed as a console script `paperless-ctl`. Add it through a **fork-owned** entry point if you can (a small `windows/pyproject-winport.toml` or a `[project.scripts]` hunk registered in PATCHES.md).

Subcommands:
- `init`: create the dirs; run `migrate`; create the superuser from `PAPERLESS_ADMIN_USER`/`_PASSWORD` if set; set up or migrate the search index; migrate the LLM index; check Tesseract languages; run `collectstatic` if needed; compile bytecode. Every step is idempotent, and the order matches the s6 `dependencies.d`.
- `run`: start the supervisor in the foreground. Stop on Ctrl-C, Ctrl-Break, or the stop request from WinSW.
- `check`: `manage.py check` plus binary and Garnet reachability and dir permissions. Prints a readable report.
- `manage ...`: passes through to `manage.py` with the right env loaded (the Windows equivalent of upstream's management script wrappers).
- `status`: shows which child processes are up, their PIDs, uptime and restart counts (read from a state file).

`src/paperless_win/supervisor.py`:
- Children: garnet → (wait for PING) → web (granian, `--loop asyncio`) → beat → consumer → workers ×`PAPERLESS_TASK_WORKERS`.
- Each worker runs `celery -A paperless worker -P solo -n w{i}@%h --without-mingle --without-gossip`.
- **Recycling:** a fork-owned Celery signal module, loaded through a hook, counts finished tasks. After `PAPERLESS_WIN_RECYCLE_AFTER` tasks (default 1, matching upstream's `MAX_TASKS_PER_CHILD=1`), it asks the worker to shut down gracefully. The supervisor then starts a new one. Measure the startup cost; if it's too slow, raise the default and document the memory trade-off.
- **Watchdog:** each worker writes `{task_id, started_at}` to `logs/run/w{i}.json` on `task_prerun` and clears it on `task_postrun`. If a task runs longer than `CELERY_TASK_TIME_LIMIT`, the supervisor kills the worker's **whole process tree** (tesseract, gs children) using a Windows Job Object or `psutil`, marks the task failed (through the result backend or by letting Celery's redelivery or ack handling deal with it; decide and document), and restarts the worker.
- Restart policy: exponential backoff per child, and give up after K crashes in M minutes with a clear log message.
- Start every child inside a Job Object with `KILL_ON_JOB_CLOSE`, so that if the supervisor dies, nothing is left orphaned.
- Logs: each child's stdout and stderr go to rotating files in `%ProgramData%\paperless-win\logs\` (concurrent-log-handler is already a dependency), plus a combined `supervisor.log`.
- Flower (optional): starts if `PAPERLESS_ENABLE_FLOWER` is set, like s6 does.

## Steps
1. Implement `ctl.py` and `supervisor.py`, with unit tests for the restart policy, recycling and watchdog logic. Use fake child processes so the tests run on Linux too.
2. Add the Celery hook (one marked line in `paperless/celery.py`, or wherever the Celery app is defined) that imports `paperless_win.celery_signals` on Windows.
3. Windows integration tests:
   - kill a worker in Task Manager: it's restarted within 5 s;
   - a task that sleeps longer than the time limit (test-only task, enabled via env): its tree is killed, the worker comes back, and the task shows as failed in the UI;
   - Ctrl-C: every child exits within 15 s and no orphan processes remain (check with `Get-Process`).
4. Make `smoke.ps1` able to start the stack itself (`paperless-ctl run` in the background), wait for `/api/` to respond, run the checks, then stop the stack.

## Acceptance criteria
- [ ] `paperless-ctl init && paperless-ctl run` on a clean data dir leads to a passing `smoke.ps1`.
- [ ] Every integration test in step 3 passes.
- [ ] A 4-hour soak (consume script in a loop, 2 workers) shows no memory growth trend in any long-lived process and no stuck tasks.

## Findings
_(fill in)_
