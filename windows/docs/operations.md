# Running paperless-win

## paperless-ctl

`paperless-ctl.cmd` is in the program folder (`C:\Program Files\paperless-win`). Add that folder to your
`PATH`, or run it with the full path. Run commands as an administrator when they touch the service.

| Command                                                                     | What it does                                                                                                                                                                                                                                                     |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `paperless-ctl status`                                                      | The state of every process (broker, web, scheduler, consumer, workers): pid, uptime, restarts, last exit.                                                                                                                                                        |
| `paperless-ctl check`                                                       | Checks the helper programs, the broker, the folders, the OCR languages and Django's own checks. Run it first when something is wrong.                                                                                                                            |
| `paperless-ctl run`                                                         | Starts everything and supervises it, in the foreground (what the service does). Stop it with `Ctrl+C`. Not needed when the service is installed.                                                                                                                 |
| `paperless-ctl stop [--timeout N] [--force]`                                | Asks a running supervisor to shut down and waits; `--force` kills it if it does not stop in time.                                                                                                                                                                |
| `paperless-ctl init`                                                        | Creates the folders, migrates the database, builds the search index. The installer runs it; you only need it after changing the database.                                                                                                                        |
| `paperless-ctl manage <command>`                                            | Runs paperless-ngx's `manage.py` with the right environment: `createsuperuser`, `document_exporter`, `document_importer`, `document_index`, `document_thumbnails` and the rest of [the administration commands](https://docs.paperless-ngx.com/administration/). |
| `paperless-ctl service install\|uninstall\|start\|stop\|restart\|status`    | Controls the Windows service (administrator).                                                                                                                                                                                                                    |
| `paperless-ctl service set-account`, `acl`, `firewall allow\|remove`, `xml` | Service account, folder permissions, firewall rule, the WinSW configuration. See [configuration](configuration.md) and [SERVICE.md](../SERVICE.md).                                                                                                              |

Exit codes: 0 fine, 1 something failed, 4 the configuration is invalid.

You can also start and stop the service from `services.msc` or with `Start-Service paperless-win` /
`Stop-Service paperless-win`. Stopping takes a few seconds: the web server and the consumer are stopped first, a worker that is
processing a document gets `PAPERLESS_WIN_STOP_TIMEOUT` seconds (default 10) to finish, and then the rest
is stopped. A document that is cut off at that point is marked as failed when paperless-win starts again;
a file from the consume folder normally stays there and is imported again (we have not tested a forced cut-off).

## Logs

Everything is in `<data folder>\logs` (default `C:\ProgramData\paperless-win\logs`):

| File                                                                             | Content                                                                                                                                                                       |
| -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `paperless.log`                                                                  | The application log (what the web interface's "Logs" page shows).                                                                                                             |
| `supervisor.log`                                                                 | Starts, stops, restarts and crashes of every process, and the output of all of them in one place.                                                                             |
| `web.log`, `consumer.log`, `beat.log`, `worker1.log`, `garnet.log`, `celery.log` | One file per process.                                                                                                                                                         |
| `service\*.log`                                                                  | The Windows service wrapper: `*.wrapper.log` (start and stop), `*.err.log` / `*.out.log` (what the program printed before it had its own log), `stop.log` (the stop command). |
| `install.log`                                                                    | What the installer ran, with the output.                                                                                                                                      |

Files are rotated by size. When something does not start, read `service\paperless-win-service.err.log`
first: configuration errors are reported there in plain words.

## Backup

Two kinds of backup, and you want both.

**1. The documents, as an export** (readable without paperless-win, restorable into any version):

```
mkdir D:\backup\paperless-export
paperless-ctl manage document_exporter D:\backup\paperless-export
```

The target folder must exist. The exporter writes your original and archive files, the thumbnails and a
`manifest.json` with every tag, correspondent, user and setting. Run it again into the same folder to
update it (add `-d` to delete what is no longer in paperless).

**2. The settings and the secret key:** copy `C:\ProgramData\paperless-win\paperless.conf` (the secret key
signs your login sessions).

A plain copy of the data folder also works if paperless-win is stopped while you copy (`paperless-ctl
service stop`): the database, `media`, and the `index` folder (the index can be rebuilt, so it may be left
out). Copying while it runs is not safe for the SQLite database. A PostgreSQL database needs its own
backup (`pg_dump`).

## Restore

On a new installation (any computer):

1. Install paperless-win (see [install](install.md)); you may reuse the old `PAPERLESS_SECRET_KEY` line in
   the new `paperless.conf` if you want existing login sessions and stored credentials to stay valid.
2. Copy the export folder to the computer, then:

   ```
   paperless-ctl service stop
   paperless-ctl manage document_importer D:\backup\paperless-export
   paperless-ctl service start
   ```

   The importer is meant for a new installation without documents. It copies the files into the media
   folder, fills the database and rebuilds the search index. It warns "Found existing user(s)" because the
   installer created an administrator: **the accounts from the export replace it**, so sign in with the user
   name and password of the old installation afterwards. We tried exactly this (export from one
   installation, import into a second, new one): the document came across with its content, checksum and
   archive file.

## Moving from Docker (or Linux) to paperless-win

Both versions use the same export format, so the way over is an export and an import:

1. On the old installation, run the exporter as described in the
   [paperless-ngx documentation](https://docs.paperless-ngx.com/administration/#exporter) (with Docker:
   `docker compose exec webserver document_exporter ../export`), and copy the export folder to the
   Windows computer.
2. Install paperless-win and import the folder as above.
3. Check the settings that use paths or programs: `PAPERLESS_OCR_LANGUAGE` (the languages must be
   installed, see [configuration](configuration.md)), `PAPERLESS_FILENAME_FORMAT` (characters Windows does
   not allow in file names are replaced; names that become too long are shortened), mail rules, and the
   consume folder.

We have tested Windows to Windows. An export made on Linux has not been imported here; the importer
accepts both `/` and `\` in the manifest, and the automated tests cover that, but a real Docker export was
not tried. Keep the old installation until you have checked the result.

## Upgrading

Run the new installer over the old one (see [install](install.md#upgrading)). paperless-win follows the
paperless-ngx release numbers: version `3.5.1-win.2` is paperless-ngx 3.5.1 with the second set of changes
for Windows. A new paperless-ngx release arrives as a new version here some time after upstream's release.

## What to do when the computer restarts

Nothing: the service starts with Windows (a minute or so after boot, it uses delayed start). Check with
`paperless-ctl service status` or `paperless-ctl status`.
