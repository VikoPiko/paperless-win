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

_(fill in)_
