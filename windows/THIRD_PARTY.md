# Third-party components

paperless-win is GPL-3.0, like upstream paperless-ngx. This file lists every third-party
binary or asset the fork bundles or downloads, with its license and source. Python
dependencies are listed by `pyproject.toml` / `uv.lock` and are not repeated here.

> Licenses below are the ones we believe apply as of the pinned versions. P12 must
> re-verify each entry against the shipped files and add copies of the license texts to
> the installer before the first release.

## Bundled in the installer (planned) and used by the dev bootstrap

| Component                                | Version                                  | License          | Source                                                                         | Notes                                                                                                                                               |
| ---------------------------------------- | ---------------------------------------- | ---------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tesseract OCR                            | 5.4.0.20240606 (UB-Mannheim build)       | Apache-2.0       | https://github.com/UB-Mannheim/tesseract                                       | `eng`, `deu` traineddata; more languages selectable                                                                                                 |
| tessdata_fast `deu.traineddata`          | main @ fetch time, SHA256 pinned         | Apache-2.0       | https://github.com/tesseract-ocr/tessdata_fast                                 |                                                                                                                                                     |
| Ghostscript                              | 10.08.0                                  | AGPL-3.0         | https://github.com/ArtifexSoftware/ghostpdl-downloads                          | Source offer must accompany the installer                                                                                                           |
| Poppler (Windows build)                  | 26.09.0-0                                | GPL-2.0-or-later | https://github.com/oschwartz10612/poppler-windows                              |                                                                                                                                                     |
| pngquant                                 | 2.17.0                                   | GPL-3.0-or-later | https://pngquant.org/                                                          | Download URL is unversioned; the bootstrap pins the SHA256                                                                                          |
| Microsoft Garnet                         | 2.2.13                                   | MIT              | https://github.com/microsoft/garnet                                            | Redis-compatible server (D2)                                                                                                                        |
| libmagic (`libmagic-1.dll`, `magic.mgc`) | from `python-magic-bin` 0.4.14 win_amd64 | BSD-2-Clause     | https://github.com/ahupp/python-magic (wheel), https://www.darwinsys.com/file/ | Only the DLL and database are used (D8); 2018-era build                                                                                             |
| Liberation Serif                         | 2.1.5                                    | SIL OFL 1.1      | https://github.com/liberationfonts/liberation-fonts                            | `windows/assets/fonts/LiberationSerif-Regular.ttf`, license in `windows/assets/fonts/LICENSE-Liberation-OFL.txt`; thumbnail font for text documents |

## Development only (never shipped)

| Component | Version | License                                 | Source                       | Notes                                                             |
| --------- | ------- | --------------------------------------- | ---------------------------- | ----------------------------------------------------------------- |
| 7-Zip     | 26.06   | LGPL-2.1-or-later (+ unRAR restriction) | https://github.com/ip7z/7zip | Unpacks the Tesseract/Ghostscript installers without admin rights |
| Node.js   | 24.22.3 | MIT                                     | https://nodejs.org/          | Builds the Angular frontend                                       |
| pnpm      | 11.15.1 | MIT                                     | https://pnpm.io/             |                                                                   |

Planned, not yet bundled: WinSW (MIT, P9), Inno Setup (dev only, P10).

## Not bundled (user-installed, optional)

| Component                   | License          | Used for                                         | Notes                                                                                                                                   |
| --------------------------- | ---------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| Gpg4win / GnuPG for Windows | GPL-3.0-or-later | Decrypting GPG-encrypted mail (`paperless_mail`) | Found in its default install folders by `paperless_win.platform.gpg_dirs()`. Git for Windows' msys `gpg` is ignored on purpose.         |
| unpaper                     | GPL-2.0-or-later | `PAPERLESS_OCR_CLEAN=clean`                      | No maintained Windows build; the setting defaults to `none` (D10). A user-supplied binary can be selected with `PAPERLESS_BIN_UNPAPER`. |

## Dropped by P4

`qpdf` and `pdfinfo` are **not needed** on Windows: `paperless_win.pdf` does the same work with pikepdf (`qpdf --replace-input` repairs, page size). `pdftoppm` and `pdftotext` (Poppler) are still used and ship in the Poppler package. `pdfinfo.exe` is part of that same package, so the upstream binary check, which still looks for it, cannot trigger in a normal install.
