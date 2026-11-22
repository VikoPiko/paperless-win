**paperless-win @TAG@** is an unofficial port of [paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) @UPSTREAM@ to native Windows (no Docker, no WSL). It is not affiliated with or endorsed by the paperless-ngx project, and problems with it must not be reported there: use the issues of this repository.

## Download

- `paperless-win-setup-@TAG_FILE@.exe`: the installer (Windows 10/11, 64 bit). It runs without network access; the optional Local AI add-on is the only part that downloads anything.
- `paperless-win-ai-local-@TAG_FILE@.zip`: the wheels of the optional Local AI add-on (local embeddings with PyTorch), for machines without internet access.
- `SHA256SUMS`: checksums of the files above. `app-hashes-@TAG_FILE@.txt`: the hash of every file in the installed application folder (two builds of the same commit give the same list).

## Installing

Run the installer, choose the data folder, the consume folder, an administrator account and the OCR languages. As an administrator it also installs the Windows service `paperless-win` (starts with the computer); without administrator rights it installs for your user and you start it with `paperless-ctl run`.

**The installer is not code-signed.** Windows SmartScreen will show "Windows protected your PC": choose "More info", then "Run anyway", after comparing the checksum with `SHA256SUMS`.

## What this release contains

- paperless-ngx @UPSTREAM@ with the changes listed in `windows/PATCHES.md` of the source tree (kept as small as possible).
- Bundled and licensed as listed in `windows/THIRD_PARTY.md`: CPython, Tesseract (with the OCR languages), Ghostscript (AGPL), Poppler, pngquant, Microsoft Garnet (Redis-compatible broker), libmagic, WinSW and the Liberation font.
- SQLite by default; PostgreSQL works against a server you provide. MariaDB/MySQL is not included (no Windows wheel for `mysqlclient`).

## Known limitations

- Windows 10 and 11 on x64 only.
- Office documents (Word, Excel, ...) need LibreOffice and Tika/Gotenberg, which are not bundled yet.
- No HTTPS in the box: put a reverse proxy in front of it, or keep it on your own network.
- Not code-signed (see above).
- Not every upstream test runs on Windows: the skipped ones are listed with their reasons in `windows/SKIPPED_TESTS.md`.
