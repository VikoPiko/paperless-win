# Installing paperless-win

paperless-win is an **unofficial** port of paperless-ngx to Windows. It is not affiliated with the
paperless-ngx project; problems go to the [issues of this repository](https://github.com/VikoPiko/paperless-win/issues).
Once it is running, the web interface is the one of paperless-ngx: its
[documentation](https://docs.paperless-ngx.com) explains how to use it.

## What you need

- Windows 10 or 11, 64 bit (x64). Nothing else has to be installed: Python, the OCR engine and the other
  tools are inside the installer.
- About 2.1 GB of disk space right after the installation (1.6 GB program folder, which keeps the bundled
  packages so that a repair needs no download, and 0.5 GB for the new data folder), plus room for your
  documents (paperless keeps the original and an archive copy of every document, a thumbnail and the
  search index).
- Memory: with one worker, count on about 1.5 GB in total while a document is being OCR'd. Measured in our
  tests: an OCR worker peaked at 580 MB and goes back to 130 MB between documents (it is restarted after
  every document); the web server uses about 210 MB, the consumer and the scheduler 130 MB each, the
  broker 270 MB and the supervisor 60 MB. More workers (`PAPERLESS_TASK_WORKERS`) need more memory.
- Administrator rights are needed to install the Windows service (it starts with the computer). Without
  them the installer can still install for your user; you then start paperless-win yourself (see below).

## Install in five steps

1. Download `paperless-win-setup-<version>.exe` from the
   [releases](https://github.com/VikoPiko/paperless-win/releases) page, and the `SHA256SUMS` file next to it.
   Compare the checksum: `Get-FileHash .\paperless-win-setup-<version>.exe -Algorithm SHA256`.
2. Run it. The installer is **not code-signed**, so Windows SmartScreen shows "Windows protected your
   PC": choose **More info**, then **Run anyway**.
3. Choose the **data folder** (default `C:\ProgramData\paperless-win`: the database, your documents, the
   search index and the logs; pick a drive with enough room) and the **consume folder** (files you put
   there are imported automatically).
4. Enter a **user name and password** for the first administrator account, and the **web port**
   (default 8000). Tick the **OCR languages** you need (English is always installed).
5. Finish. When the installer is done (a few minutes: it sets up the database and the search index), open
   <http://localhost:8000/> and sign in. The Start menu has "paperless-win" (opens the page) and a link to
   the consume folder.

Optional tasks on the components page:

- **Let other computers on the network open paperless-win** opens the web port in Windows Firewall for
  _private and domain_ networks only, and makes the web server listen on all addresses. Without it,
  paperless-win only answers on this computer. There is no HTTPS: for access from outside your own network
  put a reverse proxy in front of it.
- **Local AI add-on** installs the packages for embeddings that run on this computer (PyTorch and
  friends, about 600 MB, needs internet access during setup). It is not needed for AI features that use
  an online or separate service (OpenAI-compatible servers, Ollama): those work in the base install.
  To add it later, run the installer again and tick the task.

## Where things are

| What                         | Where                                                              |
| ---------------------------- | ------------------------------------------------------------------ |
| Program                      | `C:\Program Files\paperless-win` (or the folder you chose)         |
| Configuration                | `C:\ProgramData\paperless-win\paperless.conf`                      |
| Data, documents, index, logs | the data folder you chose (default `C:\ProgramData\paperless-win`) |
| Logs                         | `<data folder>\logs` (see [operations](operations.md))             |
| Service                      | `paperless-win` in the Services app (`services.msc`)               |

## Without administrator rights

Run the installer with `/CURRENTUSER /NOSERVICE`. There is then no Windows service: start paperless-win from a command prompt with

```
"<program folder>\paperless-ctl.cmd" run
```

and stop it with `Ctrl+C` (or `paperless-ctl stop` from another window).

## Unattended install

All the usual [Inno Setup switches](https://jrsoftware.org/ishelp/index.php?topic=setupcmdline) work, plus
these:

| Parameter                             | Meaning                                                                                                                                                    |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/VERYSILENT /SUPPRESSMSGBOXES`       | no windows, no questions (a failing step is written to the install log; the exit code is 1)                                                                |
| `/DIR=C:\Apps\paperless-win`          | program folder                                                                                                                                             |
| `/DATADIR=D:\paperless`               | data folder                                                                                                                                                |
| `/CONSUMEDIR=D:\inbox`                | consume folder (default `<data folder>\consume`)                                                                                                           |
| `/ADMINUSER=admin /ADMINPASSWORD=...` | first administrator (at least 8 characters; the password is on the command line, so it is visible to other users of the computer while the installer runs) |
| `/PORT=8000`                          | web port                                                                                                                                                   |
| `/LANGS=deu,fra`                      | extra OCR languages: `deu`, `fra`, `spa`, `ita`, `nld`                                                                                                     |
| `/TASKS="firewall,ailocal"`           | the optional tasks above                                                                                                                                   |
| `/NOSERVICE`                          | do not register the Windows service                                                                                                                        |
| `/CURRENTUSER` or `/ALLUSERS`         | install for the current user (no administrator needed) or for everyone                                                                                     |
| `/LOG=C:\setup.log`                   | Inno Setup's own log                                                                                                                                       |

Example:

```
.\paperless-win-setup-3.5.1-win.1.exe /VERYSILENT /SUPPRESSMSGBOXES /DATADIR=D:\paperless `
    /ADMINUSER=admin /ADMINPASSWORD=change-me-now /LANGS=deu /TASKS=firewall
```

What the installer did, step by step, is written to `<data folder>\logs\install.log`.

## Upgrading

Run the new installer over the old one. It keeps `paperless.conf`, your data folder, the account, the port
and the OCR languages (it does not ask again), makes a copy of the SQLite database next to the original
(`db.sqlite3.bak-<old version>`), replaces the program files, runs the database migrations and starts the
service again. The copy is not deleted: remove it once you are happy. A PostgreSQL database is not backed
up by the installer: do that yourself first.

If an upgrade fails half-way, install the previous version again; if the database was changed by the
failed migration, restore the `.bak` copy (stop the service first, then copy it over `db.sqlite3`).

## Uninstalling

"Apps" in Windows Settings, or `unins000.exe` in the program folder. The service is removed. The installer
asks whether to **keep your documents, database and settings** (the default is to keep them): a later
installation picks up the same library when you choose the same data folder. `unins000.exe /VERYSILENT`
keeps the data; add `/DELETEDATA` to delete it as well.
