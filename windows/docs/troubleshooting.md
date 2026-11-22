# Troubleshooting

Start with two commands, as administrator:

```
paperless-ctl check
paperless-ctl status
```

`check` reports missing programs, an unreachable broker, folders that cannot be written, OCR languages that
are not installed and invalid settings, each with a sentence on what to do. The logs are described in
[operations](operations.md#logs).

## The installer

**"Windows protected your PC" (SmartScreen).** The installer is not code-signed yet, which is what
SmartScreen reacts to. Choose **More info**, then **Run anyway**, after comparing the file's checksum with
`SHA256SUMS` from the release page. Some antivirus programs also warn about unsigned installers; the
checksum is how you know it is the file that was published.

**The installer finished but the web page does not open.** Open `<data folder>\logs\install.log`: the last
lines say what failed (and, if the service did not start, its state and its logs). Typical causes are a
port that is already used (below) and a data folder the service account cannot write (below).

**An installation that stops with "could not be set up".** The same log has the output of the step that
failed. A silent installation exits with code 1 and writes the same message to the log instead of opening
a window.

## Starting and stopping

**"Port 8000 is already in use" / the web page shows another program.** Another program listens on the port
(very often another paperless, or a development server). Choose a free port with `PAPERLESS_PORT` in
`paperless.conf` and restart the service. Find out who uses a port with
`Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess` and `Get-Process -Id <that id>`.

**"garnet exited ... is another server already using that port?"** The bundled broker listens on
`127.0.0.1:6379`. If you run Redis or another Garnet there, either stop it, change the port in
`PAPERLESS_REDIS`, or set `PAPERLESS_WIN_BROKER=external` to use that server (not tested by us).

**The service starts and stops again at once.** Read `<data folder>\logs\service\paperless-win-service.err.log`.
"the configuration is invalid: ..." names the setting. `PermissionError` means the service account cannot
read the program folder or write the data folder: run `paperless-ctl service acl` (administrator) to apply
the permissions again.

**It does not stop.** `paperless-ctl stop --force` ends everything it started. The Services app shows
"Stopping" for a few seconds at most; if it stays, the logs in `service\stop.log` say why.

## Documents

**A scan I dropped into the consume folder is not imported.** The consumer waits until the scanner or copy
program has finished writing the file (it checks that it can open the file exclusively), so a file that is
still being copied is not touched. Give it a few seconds; look at `consumer.log`. Temporary Office files
(`~$...`), `.tmp` and `.part` files are ignored on purpose. For a folder on a network share see
[configuration](configuration.md#folders-on-a-network-share-nas).

**"The selected ocr language xyz is not installed".** The language is in `PAPERLESS_OCR_LANGUAGE` but its
`.traineddata` file is missing: see "More OCR languages" in [configuration](configuration.md).

**A document failed ("Error occurred while consuming document").** The failed task and its message are on
the _Tasks_ page of the web interface, and in `paperless.log`. If the message mentions a file that is
"being used by another process", an antivirus scanner or a backup program was holding the file: exclude the
scratch folder (`<data folder>\scratch`) from real-time scanning, or retry.

**Very long file names.** Windows limits a path to 259 characters unless long paths are enabled. paperless-win
shortens the file name when the path would exceed it (never below 8 characters), and fixes what Windows does
not allow in a name: illegal characters, reserved names such as `CON` or `NUL`, trailing dots and spaces.
Only the names on disk change. If long paths are enabled on your computer, raise `PAPERLESS_WIN_MAX_PATH`.

**Slow OCR.** OCR of a page takes seconds; a scan with many pages takes minutes. One worker processes one
document at a time: raise `PAPERLESS_TASK_WORKERS` if you have memory and cores to spare (each worker can
use about 600 MB while it works). Real-time antivirus scanning of the scratch folder slows it down (we did
not measure by how much).

## Optional features

**Office documents (Word, Excel...).** Not available out of the box: they need LibreOffice and Apache Tika
(Java), which are not bundled and which this release does not set up yet.

**Local AI.** If `PAPERLESS_AI_ENABLED=true` with the local embedding backend and you did not install the
add-on, `paperless-ctl check` says so (`paperless_win.E001`). Run the installer again and tick the "Local
AI add-on" task, or use an online/separate embedding service instead.

**Email (mail rules).** Work as in paperless-ngx; the computer needs outgoing access to your mail server.

## Antivirus and Windows Defender

Real-time scanning inspects every file the OCR pipeline creates and can slow processing. Excluding the data
folder's `scratch` folder is the safest place to start. If a security program blocks the service from
starting (look in the Windows Event Viewer, "System" log, source "Service Control Manager"), allow
`C:\Program Files\paperless-win\venv\Scripts\python.exe` and `...\bin\garnet\...\GarnetServer.exe`.

## Reporting a problem

Open an issue at [github.com/VikoPiko/paperless-win/issues](https://github.com/VikoPiko/paperless-win/issues),
**not** with paperless-ngx: they do not support Windows and cannot help. Include the paperless-win version
(`VERSION` in the program folder), the output of `paperless-ctl check`, and the relevant lines of the logs.
Remove anything private from them first (document titles, user names, the secret key).
