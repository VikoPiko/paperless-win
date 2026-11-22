# P9 — Windows service

**Runs on:** Windows (admin). **Branch:** `winport/P09-service`

## Goal

paperless-win runs as a proper Windows service that starts at boot, stops cleanly, runs under a least-privilege account, and has sane file permissions.

## Design

- WinSW (pinned version, SHA256 recorded in `THIRD_PARTY.md`) is renamed to `paperless-win-service.exe`, with `windows/service/paperless-win-service.xml`:
  - `executable`: the venv's `paperless-ctl.exe`, `arguments`: `run`
  - `stopparentprocessfirst` / `stoptimeout` 30 s. Confirm the supervisor gets the signal and shuts children down (P6).
  - `onfailure` restart with delays; `startmode` Automatic (Delayed Start)
  - log mode: roll by size; logs dir under ProgramData
  - `env`: `PAPERLESS_CONFIGURATION_PATH=%ProgramData%\paperless-win\paperless.conf`
  - service account: **virtual account** `NT SERVICE\paperless-win`
- `paperless-ctl service install|uninstall|start|stop|status` wraps WinSW and sets ACLs:
  - `%ProgramData%\paperless-win\` and its subdirs: full control for `NT SERVICE\paperless-win`, `Administrators` and `SYSTEM`; nothing for `Users`, except the consume folder, which gets Modify for `Users` so people can drop files in.
  - `%ProgramFiles%\paperless-win\`: read and execute for the service account.
- Network consume folder or media on a NAS: a virtual account can't authenticate to SMB as a user. Document how to switch the service to a dedicated local or domain user (`paperless-ctl service set-account`), and validate that this works.
- Optional: a Windows Firewall rule for the web port, created only if the user opts in during install (LAN access).

## Steps

1. Write the XML template, the `service` subcommands and the ACL code (pywin32 or `icacls` subprocess; pick the simplest).
2. Integration test script `windows/scripts/test-service.ps1`, which must run as admin:
   install → start → `smoke.ps1` → restart the machine (manual step, documented) or restart the service → `smoke.ps1` → stop → check no processes are left → uninstall → check the service is gone and the data is kept.
3. Check that the event log or WinSW logs show useful errors when Garnet's port is taken, the config is invalid, or the DB is locked.

## Acceptance criteria

- [ ] `test-service.ps1` passes.
- [ ] The service survives a reboot (verified manually once, results in Findings).
- [ ] No files under ProgramData are writable by non-admin users except the consume folder.

## Findings

**Status: implemented and unit-tested; the three acceptance criteria are NOT yet verified, because they need an elevated prompt and this session is not elevated (`IsInRole(Administrator)` is False). Someone with admin rights must run `windows\scripts\test-service.ps1` and do the reboot check.**

What exists:

- `src/paperless_win/service.py` and `paperless-ctl service install|uninstall|start|stop|restart|status|set-account|acl|firewall|xml` (`windows/SERVICE.md` is the user-facing description). WinSW **2.12.0** (v2.13.0 calls itself experimental), SHA256 pinned in `bootstrap-dev.ps1` and `THIRD_PARTY.md`; the exe is not code-signed.
- The service XML runs `python -m paperless_win run`, stops with `stopexecutable` = `paperless-ctl stop --timeout 25` (the supervisor's own protocol, instead of relying on Ctrl+C reaching the process), `stoptimeout` 30 s, Automatic (delayed) start, restart after 10/30/60 s, WinSW logs rolled by size under `<logs>\service`, `PAPERLESS_CONFIGURATION_PATH`, virtual account `NT SERVICE\paperless-win`.
- ACLs through `icacls`, using SIDs (the virtual account's SID is computed from the name and was checked against `sc showsid` for two service names, so permissions can be set before the service exists): the data root loses inheritance and keeps SYSTEM, Administrators and the service account only; consume additionally gets Modify for Users; folders outside the root only get Modify for the service account; the app folder gets read and execute for the service account.
- `set-account` re-registers the service under a local or domain user (for NAS shares). The password sits in the XML only while WinSW registers (the file is restricted to SYSTEM and Administrators first), then is removed.
- Firewall rule for the web port on **private and domain** networks only, opt-in (`service firewall allow`, `service install --firewall`).
- Supervisor: a taken broker port is now reported in plain words even when another server answers PING; `paperless-ctl` reports an unreadable configuration as "the configuration is invalid: ..." with exit code 4.
- `windows/scripts/test-service.ps1` follows the task's steps 2 and 3 (install, smoke, process owner, permissions audit, restart, stop and "no process left", port taken, invalid configuration, uninstall and "data kept"). It uses its own data root (`PAPERLESS_WIN_DATA_ROOT`, new) and ports and refuses to touch an existing `paperless-win` service. **It has never been run.** It parses, and it exits with code 2 when not elevated. The database-locked case of step 3 is not automated.

What was verified here, without elevation:

- 31 unit tests (`tests/test_service.py`) for the XML, account parsing, the ACL plan, firewall commands and layout detection; the fork suite is 353 passed.
- WinSW itself: `paperless-win-service.exe status` accepts the generated XML (reports `NonExistent`).
- Not verified: install/start/stop through the Service Control Manager, the virtual account, ACL results on disk, the Event Log, `set-account`, the firewall rule, the reboot.

Things found on the way:

- WinSW v2 **self-elevates through UAC** for most commands, including `test` / `testwait` (console mode, which I tried in order to check the XML without admin). Each attempt left a `consent.exe` prompt on the secure desktop, which I cannot and will not approve; those prompts time out. Do not run WinSW commands from an unelevated script.
- A checkout under `C:\Users\<name>` cannot be run by the virtual account (profile folders deny it), and a `uv` venv points at a Python in the profile too. So the virtual account can only be tested properly from the self-contained layout the installer (P10) will create; `test-service.ps1 -Account auto` falls back to `system` for a profile checkout and says so.
- PowerShell 7 children are outside the supervisor's job object (found in P6); the process-tree walk added there also covers the service's stop path.
