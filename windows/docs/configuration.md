# Configuring paperless-win

## paperless.conf

All settings are the normal [paperless-ngx settings](https://docs.paperless-ngx.com/configuration/): one
`NAME=value` per line, comments start with `#`. They live in

```
C:\ProgramData\paperless-win\paperless.conf
```

(created by the installer; a `paperless.conf` in the program folder is read as a fallback). Only
administrators can change or read the file: it contains the secret key. **Restart the service after a
change** (`paperless-ctl service restart`, or restart `paperless-win` in `services.msc`).

The installer writes these lines; change them freely:

```
PAPERLESS_DATA_DIR=D:\paperless
PAPERLESS_MEDIA_ROOT=D:\paperless\media
PAPERLESS_CONSUMPTION_DIR=D:\paperless\consume
PAPERLESS_SCRATCH_DIR=D:\paperless\scratch
PAPERLESS_STATICDIR=D:\paperless\static
PAPERLESS_LOGGING_DIR=D:\paperless\logs
PAPERLESS_REDIS=redis://127.0.0.1:6379
PAPERLESS_SECRET_KEY=<generated: keep it secret, and keep it when you move to another computer>
PAPERLESS_OCR_LANGUAGE=eng+deu
PAPERLESS_PORT=8000
PAPERLESS_BIND_ADDR=127.0.0.1
PAPERLESS_APP_TITLE=paperless-win
```

Paths can be written with backslashes or forward slashes. `PAPERLESS_BIND_ADDR=0.0.0.0` makes paperless-win
answer on the network (see the firewall rule below); `PAPERLESS_APP_TITLE` is the title shown in the
browser.

**The database** is SQLite (`<data folder>\db.sqlite3`) unless you point paperless-win at an existing
PostgreSQL server with the usual `PAPERLESS_DBHOST`, `PAPERLESS_DBNAME`, `PAPERLESS_DBUSER` and
`PAPERLESS_DBPASS` settings. MariaDB/MySQL is not included in this build.

## Settings that only exist on Windows

| Setting                        | Default          | What it does                                                                                                                            |
| ------------------------------ | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `PAPERLESS_BIN_DIR`            | none             | An extra folder searched (first) for the helper programs, below which each program may sit in its own folder.                           |
| `PAPERLESS_BIN_<NAME>`         | none             | The exact file to use for one program, for example `PAPERLESS_BIN_GARNETSERVER`, `PAPERLESS_BIN_UNPAPER`. It wins over everything else. |
| `PAPERLESS_WIN_BROKER`         | (bundled Garnet) | `external`: do not start the bundled broker, use the server at `PAPERLESS_REDIS`. Not tested by us.                                     |
| `PAPERLESS_WIN_RECYCLE_AFTER`  | `1`              | A worker exits and is restarted after this many tasks. This keeps memory flat; raise it only if you process many tiny documents.        |
| `PAPERLESS_WIN_WATCHDOG_GRACE` | `30`             | Seconds a task may run past `PAPERLESS_WORKER_TIMEOUT` (default 1800 s) before the supervisor kills it and marks it failed.             |
| `PAPERLESS_WIN_STOP_TIMEOUT`   | `10`             | Seconds each process gets to stop before it is killed when paperless-win shuts down.                                                    |
| `PAPERLESS_WIN_MAX_PATH`       | `259`            | Longest file path paperless-win creates. Raise it only if Windows long paths are enabled.                                               |

The workers and the web port are the usual `PAPERLESS_TASK_WORKERS` (default 1) and `PAPERLESS_PORT`.

## Helper programs

The installer carries Tesseract (OCR), Ghostscript, Poppler, pngquant and libmagic, and paperless-win finds
them itself. Programs found on the system `PATH` are used **before** the bundled ones, so a Tesseract you
installed yourself wins. Two programs are not included:

- **unpaper** (the `PAPERLESS_OCR_CLEAN` options): unavailable unless you supply the file with
  `PAPERLESS_BIN_UNPAPER`.
- **jbig2enc**: not bundled; PDFs come out slightly larger.

### More OCR languages

English plus the languages you ticked are installed (German, French, Spanish, Italian, Dutch can be added
by running the installer again). For any other language download its `.traineddata` file from the
[tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) project and use a copy of the tessdata
folder that survives upgrades:

1. Copy the folder `C:\Program Files\paperless-win\bin\tesseract\tessdata` to, say, `C:\ProgramData\tessdata`.
2. Put the new `.traineddata` file into it.
3. Add these lines to `paperless.conf` and restart the service:

   ```
   TESSDATA_PREFIX=C:\ProgramData\tessdata
   PAPERLESS_OCR_LANGUAGE=eng+pol
   ```

`paperless-ctl check` tells you whether the languages are found. (Files put directly into the program
folder's `tessdata` are removed by an upgrade, except for the five languages the installer offers.)

## Folders on a network share (NAS)

- **Consume folder on a share.** Windows does not report changes on SMB shares reliably, so paperless-win
  polls such a folder every 10 seconds on its own (override with `PAPERLESS_CONSUMER_POLLING_INTERVAL`). A
  mapped drive letter works only for the user who mapped it, so use the UNC form
  (`\\nas\scans`) in `paperless.conf`.
- **The service account.** By default the service runs as the virtual account `NT SERVICE\paperless-win`,
  which has no password and no rights on the network, so it cannot open a share. For a share, run the
  service as a real user who can open it:

  ```
  paperless-ctl service set-account DOMAIN\user
  ```

  It asks for the password (or reads `PAPERLESS_WIN_SERVICE_PASSWORD` from the environment). The password
  is kept by Windows, not in `paperless.conf`. `paperless-ctl service set-account virtual` goes back.

- Keep the database, the search index and the broker on a local disk: SQLite on a network share is not
  reliable.

## The Windows service

- Name `paperless-win`; starts automatically with Windows (delayed start); restarts itself after a crash
  after 10, 30 and then 60 seconds.
- Runs as `NT SERVICE\paperless-win` (see above). The data folder is writable only by SYSTEM,
  Administrators and that account; the consume folder is also writable by ordinary users so that anyone
  can drop scans there.
- Its own log, and the log of the program that starts it, are in `<data folder>\logs\service`.
- `paperless-ctl service firewall allow` opens the web port for private and domain networks;
  `paperless-ctl service firewall remove` closes it again. Details are in [SERVICE.md](../SERVICE.md).
