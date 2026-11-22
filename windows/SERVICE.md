# Running paperless-win as a Windows service

paperless-win runs as **one** Windows service, `paperless-win`. [WinSW](https://github.com/winsw/winsw)
(a small MIT-licensed wrapper, renamed `paperless-win-service.exe`) registers `paperless-ctl run` with
the Service Control Manager. The supervisor behind it starts Garnet, the web server, the scheduler,
the consumer and the workers, and restarts them when they crash (see `windows/tasks/06-runtime-supervisor.md`).

All service commands need an **elevated** (administrator) prompt.

```powershell
paperless-ctl init                              # once: folders, database, indexes
paperless-ctl service install --start           # register and start (account: NT SERVICE\paperless-win)
paperless-ctl service status
paperless-ctl service stop | start | restart
paperless-ctl service uninstall                 # removes the service only; data, logs and config stay
```

In a source checkout, use `python -m paperless_win ...` instead of `paperless-ctl ...`.

## What `install` sets up

- **Start at boot**, automatic (delayed), so the network and disks are up first.
- **Restart on failure** after 10 s, 30 s, then 60 s (the supervisor exits non-zero when a part is in a
  crash loop); the failure count resets after an hour without failures.
- **Stop** runs `paperless-ctl stop`: web, scheduler and consumer are stopped first, workers get up to
  10 s to finish their current task, Garnet goes last. WinSW kills whatever is left after 30 s. A task
  that was cut short is marked as failed in the web UI at the next start.
- **Logs**: WinSW's own logs in `<logs>\service\` (rolled by size, 8 files), the supervisor and every
  child in `<logs>\` (`supervisor.log`, `web.log`, `worker1.log`, ...). WinSW also reports service events to the
  Windows Event Log (Application); not yet verified on this fork (needs an elevated run).
- **Configuration**: `%ProgramData%\paperless-win\paperless.conf` (override with `PAPERLESS_CONFIGURATION_PATH`).

## Who the service runs as

| Account                              | When                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------ |
| `NT SERVICE\paperless-win` (default) | Local folders only. No password, no rights beyond what we grant.         |
| a local or domain user               | The consume folder or media folder is on a NAS / network share.          |
| `LocalSystem` (`--account system`)   | Not recommended; used by the test script for checkouts below `C:\Users`. |

A virtual account has no network identity, so it cannot sign in to an SMB share. To use a share:

```powershell
paperless-ctl service set-account CORP\svc-paperless     # asks for the password
paperless-ctl service set-account .\paperless            # a local user
```

The account needs "Log on as a service" (granted automatically) and read/write on the share. Polling
for new files is switched on automatically for network paths (P5). The password is
held in the WinSW XML (readable by Administrators and SYSTEM only) just while registering, then removed;
afterwards Windows keeps it in the service configuration. Set the `PAPERLESS_WIN_SERVICE_PASSWORD`
environment variable to avoid the prompt in scripts.

## Folder permissions

`install` (and `paperless-ctl service acl`) apply these with `icacls`:

| Folder                                                  | Who                                                                                        |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `%ProgramData%\paperless-win\` and everything below     | Full control: SYSTEM, Administrators, the service account. **Nobody else, not even read.** |
| the consume folder inside it                            | additionally **Modify for Users**, so everyone can drop files in                           |
| data/media/consume folders elsewhere (NAS, other drive) | only **Modify for the service account** is added; the existing permissions stay            |
| `%ProgramFiles%\paperless-win\`                         | read and execute for the service account                                                   |

`paperless.conf` holds the secret key and database password, which is why Users get no access to the data root.

## Firewall

The web interface listens on `PAPERLESS_BIND_ADDR`:`PAPERLESS_PORT`. To reach it from other machines:

```powershell
paperless-ctl service firewall allow            # TCP port of the web UI, private and domain networks only
paperless-ctl service firewall remove
```

`service install --firewall` does the same during installation. The rule is never created on public networks.

## When it does not start

`paperless-ctl check` prints a readable report. Typical messages in `<logs>\service\*.err.log` and `supervisor.log`:

- `garnet exited ... is another server already using that port?` : something else listens on the Redis
  port. Stop it, change `PAPERLESS_REDIS`, or set `PAPERLESS_WIN_BROKER=external` to use that server.
- `error: the configuration is invalid: ...` : a value in `paperless.conf` could not be read (a number
  that is not a number, a folder that cannot be created...).
- `... crashed 5 times within 180 s; giving up` : a child is in a crash loop; its own log
  (`web.log`, `worker1.log`...) says why. The service then restarts after the delays above.

## Testing

`windows\scripts\test-service.ps1` (elevated) installs the service against a throw-away data root, runs
the smoke test, checks the permissions, restarts, stops, provokes the failure messages above and
uninstalls. It never touches an existing `paperless-win` service. After it passes, reboot once and check
that the service came up by itself: `Get-Service paperless-win`, then `paperless-ctl status`.
