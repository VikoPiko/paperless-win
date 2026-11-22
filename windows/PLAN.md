# paperless-win — Port plan

Unofficial native-Windows port of paperless-ngx. Base: upstream **v3.5.1**
(`dev` @ `4973be8`, 2026-11-19). Target: Windows 10 22H2+ / Windows 11, x64.

## Goal

A Windows user downloads `paperless-win-setup-x.y.z.exe`, clicks through, and gets:

- a Windows service ("paperless-win") that starts at boot,
- the web UI on `http://localhost:8000`,
- a consume folder they can drop scans into,
- OCR, thumbnails, full-text search, mail fetching, workflows — feature parity with
  the Linux build except the documented trade-offs below,
- an upgrade path that installs the next version over the top and migrates data.

Docker (incl. Docker Desktop on Windows) remains possible via upstream images; this
fork doesn't touch that path.

## Accepted trade-offs

| Area                    | Trade-off                                                                                               |
| ----------------------- | ------------------------------------------------------------------------------------------------------- |
| `unpaper` cleaning      | Unavailable on Windows unless the user supplies a binary; `OCR_CLEAN` options show as unavailable.      |
| `jbig2enc`              | Not bundled; OCRmyPDF falls back to other optimizers (slightly larger PDFs).                            |
| Office docs             | No Gotenberg. Tika (Java jar) + **local LibreOffice** conversion, optional, both user-installed.        |
| Task time limit         | Enforced by our supervisor watchdog (kill process tree), not by Celery.                                 |
| Redis                   | Garnet bundled; we don't support an external Redis on Windows in v1 (it would work, but it's untested). |
| Local AI embeddings     | Optional add-on, large download.                                                                        |
| Network consume folders | Polling mode recommended/defaulted for UNC paths.                                                       |
| Multi-node / scaling    | Single machine only.                                                                                    |

## Architecture (Windows)

```
Windows Service "paperless-win"  (WinSW → paperless-ctl run)
└─ paperless_win.supervisor
   ├─ garnet-server.exe          127.0.0.1:6379 (private)
   ├─ granian (asyncio loop)     web + websockets, :8000
   ├─ celery beat                scheduler
   ├─ manage.py document_consumer  (watchfiles; polling for UNC)
   ├─ celery worker -P solo  ×N  (each: own hostname, heartbeat file, recycled)
   └─ watchdog                   time limits → kill process tree (Job Objects/psutil)

%ProgramFiles%\paperless-win\   app: python, venv, src, static, bin\ (tesseract, gs, poppler, pngquant, garnet, winsw)
%ProgramData%\paperless-win\    paperless.conf, data\, media\, consume\, logs\
```

## Phases

Each phase is a task file in `windows/tasks/` written for Claude Code. Do them in order;
P7/P8 can run in parallel with P5/P6 once P4 is done.

| #   | Task file                   | Outcome                                                                | Needs Windows? | Status                                                  |
| --- | --------------------------- | ---------------------------------------------------------------------- | -------------- | ------------------------------------------------------- |
| P0  | `00-fork-setup.md`          | Fork, remotes, fork docs, patch-checker, Windows CI skeleton           | No             | ☑ done (PR open)                                        |
| P1  | `01-spike.md`               | Manual Windows run end-to-end; findings decide go/no-go details        | **Yes**        | ◐ done, Findings awaiting review                        |
| P2  | `02-platform-layer.md`      | `paperless_win.platform`: binary lookup, default paths, config search  | Yes            | ☑ done, CI green                                        |
| P3  | `03-paths-filenames.md`     | POSIX-stored paths, Windows-safe filenames, data migration             | Partly         | ☑ done, CI green                                        |
| P4  | `04-external-tools.md`      | pikepdf instead of qpdf/pdfinfo CLIs, poppler/libmagic wiring          | Yes            | ☑ done, CI green                                        |
| P5  | `05-consumer-robustness.md` | File-lock retries, stable-file detection, script dispatch, UNC polling | Yes            | ☑ done, CI green                                        |
| P6  | `06-runtime-supervisor.md`  | `paperless-ctl` (init/run/check), supervisor, solo workers, watchdog   | Yes            | ☑ done (soak passed)                                    |
| P7  | `07-ai-optional.md`         | `ai-local` extra; base works without torch                             | No             | ☑ done, CI green                                        |
| P8  | `08-office-docs.md`         | Local LibreOffice converter as Gotenberg alternative                   | Yes            | ☐                                                       |
| P9  | `09-windows-service.md`     | WinSW service, accounts, ACLs, logs                                    | Yes            | ◐ CI-verified, reboot check pending                     |
| P10 | `10-packaging-installer.md` | Reproducible build script + Inno Setup installer + upgrade             | Yes            | ◐ CI install test passes, clean-VM pending              |
| P11 | `11-ci-release.md`          | Windows test job, smoke job, release workflow                          | No (CI)        | ◐ CI + dry run done, release untested                   |
| P12 | `12-docs-branding.md`       | README, user docs, disclaimers, THIRD_PARTY                            | No             | ◐ docs and licences done, fresh-VM test needs the owner |
| —   | `../UPSTREAM-SYNC.md`       | Repeatable procedure for each upstream release                         | Partly         | ongoing                                                 |

**Definition of done for v0.1.0 (first public release):** P0–P6, P9–P12 complete;
`smoke.ps1` passes on a clean Windows 11 VM from the installer; Linux CI green;
`SKIPPED_TESTS.md` reviewed.

## Known code hotspots (found while planning, upstream v3.5.1)

- `src/paperless/settings/__init__.py` — config search paths (`/etc/...`), `GNUPG_HOME`
  falls back to `/tmp`, `THUMBNAIL_FONT_NAME` → `/usr/share/fonts/...`, Celery
  settings (`MAX_TASKS_PER_CHILD=1`, `TASK_TIME_LIMIT`), Redis URLs.
- `src/paperless/settings/custom.py` — `parse_redis_url` (unix sockets irrelevant on Windows).
- `src/paperless/checks.py` — `binaries_check` uses `shutil.which("gs")`; Windows name is `gswin64c`.
- `src/documents/parsers.py`, `src/paperless/parsers/utils.py` — `pdftoppm`, `pdfinfo` subprocesses.
- `src/documents/barcodes.py` — `pdf2image.convert_from_path` (needs `poppler_path`).
- `src/documents/consumer.py` — pre/post-consume scripts executed directly; `qpdf --replace-input`.
- `src/documents/signals/handlers.py:~530` — `instance.filename = str(new_filename)` → backslashes on Windows.
- `src/documents/templating/filepath.py:~51`, `src/documents/file_handling.py:~138` — `.strip(os.sep)` on `/`-based templates.
- `src/documents/models.py:~573` — `pathvalidate.sanitize_filename` covers final component only.
- `src/documents/management/commands/document_consumer.py` — watchfiles; polling interval setting.
- `src/paperless_ai/embedding.py` — HuggingFace import already lazy (good for P7).
- `pyproject.toml` — `psycopg[c]` + Linux-only custom wheels; `granian[uvloop]`; torch index.
- `docker/rootfs/etc/s6-overlay/s6-rc.d/*` — reference for what `paperless-ctl init/run` must replicate.

## Risk register

| Risk                                                                   | Likelihood     | Mitigation                                                                                                                        |
| ---------------------------------------------------------------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Garnet lacks a Redis feature used by kombu / channels_redis / cachalot | Medium         | P1 verifies explicitly; enable Garnet Lua if needed; fallback: Memurai (check redistribution licence) or a DB-backed broker later |
| Celery instability on Windows                                          | Medium         | Solo pool, process-per-worker, recycling, watchdog; soak test in P6                                                               |
| File locking (`PermissionError`) during consume/move                   | High           | Retry/backoff helper; stable-file check; Defender exclusion guidance                                                              |
| Granian Windows quirks (workers, signals)                              | Low-Med        | P1 check; uvicorn fallback                                                                                                        |
| Upstream churn causing merge pain                                      | High (ongoing) | Thin-diff rules, `PATCHES.md`, tag-based sync, CI on both OSes                                                                    |
| Bundled-binary licences (Ghostscript AGPL, Poppler GPL)                | Low            | GPL-3 project; ship licences + source links in `THIRD_PARTY.md`                                                                   |
| Installer size                                                         | Medium         | AI add-on optional; Tesseract languages selectable                                                                                |
