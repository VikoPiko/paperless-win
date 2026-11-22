# Third-party components

paperless-win is GPL-3.0, like upstream paperless-ngx. This file lists every third-party
binary or asset the fork bundles or downloads, with its license and source. Python
dependencies are listed by `pyproject.toml` / `uv.lock` and are not repeated here.

> Licenses below are the ones we believe apply as of the pinned versions. P12 must
> re-verify each entry against the shipped files and add copies of the license texts to
> the installer before the first release.

## Bundled in the installer and used by the dev bootstrap

This table is generated from `windows/build/manifest.json` by `python windows/build/make-third-party.py`; do not edit it by hand.

<!-- prettier-ignore-start -->
<!-- BEGIN BUNDLED -->
| Component | Version | License | Source | Notes |
| --- | --- | --- | --- | --- |
| CPython (python-build-standalone, stripped) | 3.13.18 (release 20261110) | PSF-2.0 | https://github.com/astral-sh/python-build-standalone | The interpreter of the installed app; the venv is created from it at install time. SHA256 matches the release's SHA256SUMS. SHA256 `2e0fed09d48989f64c9305da9ff2d37a41c0d13ab2aa6283405b2b620dfbf805`. |
| Tesseract OCR | 5.4.0.20240606 (UB-Mannheim build) | Apache-2.0 | https://github.com/UB-Mannheim/tesseract | Unpacked with 7-Zip (the installer asks for admin rights); `eng` and `osd` traineddata from it, more languages selectable SHA256 `c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9`. |
| tessdata_fast `deu.traineddata` | main @ fetch time, SHA256 pinned | Apache-2.0 | https://github.com/tesseract-ocr/tessdata_fast | SHA256 `19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d`. |
| Ghostscript | 10.08.0 | AGPL-3.0 | https://github.com/ArtifexSoftware/ghostpdl-downloads | Source offer must accompany the installer SHA256 `52a91b8bf09298788d7a57b9206127026c23eacd75405f0a131e26dc381dce50`. |
| Poppler (Windows build) | 26.09.0-0 | GPL-2.0-or-later | https://github.com/oschwartz10612/poppler-windows | SHA256 `7a6f256a0ddf7536182246a5733331bf4677cbcc34f4663774947ad34556c8d0`. |
| pngquant | 2.17.0 | GPL-3.0-or-later | https://pngquant.org/ | pngquant.org serves an unversioned URL; if the hash stops matching, review and re-pin SHA256 `bd0257aeeccfe446a4cd764927e26f8af6051796f28abed104307284107b120d`. |
| Microsoft Garnet | 2.2.13 | MIT | https://github.com/microsoft/garnet | Redis-compatible broker (D2) SHA256 `cc8212d7c7a671c490e5c87967fc43025a22215922bdbdad5eccff00915c7b82`. |
| libmagic (`libmagic-1.dll`, `magic.mgc`) | 5.48 (conda-forge build `hf886114_2`) | BSD-2-Clause | https://github.com/file/file, https://anaconda.org/conda-forge/libmagic | Replaced the 2018 `python-magic-bin` DLL (D13) SHA256 `ae2d4f4cb525a0d3dd1111b8442d7ed3c1500d2901467522601ee8eaf175e0ee`. |
| PCRE2 (`pcre2-8.dll`, `pcre2-posix.dll`) | 10.47 (conda-forge build `h8466c1e_1`) | BSD-3-Clause (with PCRE2 exemption) | https://github.com/PCRE2Project/pcre2, https://anaconda.org/conda-forge/pcre2 | Required by libmagic SHA256 `d8e9ea26b52a09d880d1e5371830c8dd5b4c099a6db64dbdf8236440744b7499`. |
| WinSW (`paperless-win-service.exe`) | 2.12.0 | MIT | https://github.com/winsw/winsw | Service wrapper (D6). Not code-signed. v2.13.0 is described as experimental by its authors SHA256 `05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da`. |
| uv | 0.11.10 | MIT OR Apache-2.0 | https://github.com/astral-sh/uv | Creates the venv and installs the bundled wheels at install time (no network); installs the Local AI add-on. SHA256 matches the release's published checksum SHA256 `7a0c424c7bc55a74751f13592235953ebbe182fa00355f7ae3fb7ab734a51638`. |
| tessdata_fast `fra.traineddata` (French) | main @ fetch time, SHA256 pinned | Apache-2.0 | https://github.com/tesseract-ocr/tessdata_fast | Copied by the installer only if the language is selected SHA256 `ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca`. |
| tessdata_fast `spa.traineddata` (Spanish) | main @ fetch time, SHA256 pinned | Apache-2.0 | https://github.com/tesseract-ocr/tessdata_fast | Copied by the installer only if the language is selected SHA256 `6f2e04d02774a18f01bed44b1111f2cd7f3ba7ac9dc4373cd3f898a40ea6b464`. |
| tessdata_fast `ita.traineddata` (Italian) | main @ fetch time, SHA256 pinned | Apache-2.0 | https://github.com/tesseract-ocr/tessdata_fast | Copied by the installer only if the language is selected SHA256 `b8f89e1e785118dac4d51ae042c029a64edb5c3ee42ef73027a6d412748d8827`. |
| tessdata_fast `nld.traineddata` (Dutch) | main @ fetch time, SHA256 pinned | Apache-2.0 | https://github.com/tesseract-ocr/tessdata_fast | Copied by the installer only if the language is selected SHA256 `ced0e5e046a84c908a6aa7accbef9a232c4a5d9a8276691b81c6ee64d02963f6`. |
| Liberation Serif | 2.1.5 | SIL OFL 1.1 | https://github.com/liberationfonts/liberation-fonts | Lives in the repository: `windows/assets/fonts/LiberationSerif-Regular.ttf`, license in `windows/assets/fonts/LICENSE-Liberation-OFL.txt`; thumbnail font for text documents |
<!-- END BUNDLED -->
<!-- prettier-ignore-end -->

## Development only (never shipped)

<!-- prettier-ignore-start -->
<!-- BEGIN DEV -->
| Component | Version | License | Source | Notes |
| --- | --- | --- | --- | --- |
| 7-Zip | 26.06 | LGPL-2.1-or-later (+ unRAR restriction) | https://github.com/ip7z/7zip | Unpacks the Tesseract/Ghostscript installers and the conda packages without admin rights. The MSI is only unpacked (msiexec /a), never installed SHA256 `6dc822569e777d9a3ecd5ffcbc22b55600af87e6c5d9810a64e8566cf5a4af9f`. |
| Node.js | 24.22.3 | MIT | https://nodejs.org/ | Builds the Angular frontend (Angular 21 needs Node >= 22.22.3 or >= 24.15; upstream's Dockerfile builds with Node 24) SHA256 `e612af99f626ab415ea225af6bce5c971feb448cb5cae250bb1c3fa50c5f7d9f`. |
| Inno Setup | 6.7.4 | Inno Setup License (free, redistribution of the compiler is restricted) | https://jrsoftware.org/isinfo.php | Compiles the installer; installed for the current user only (no admin). The installer it produces needs no Inno Setup on the target machine SHA256 `a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c`. |
| pnpm | 11.15.1 | MIT | https://pnpm.io/ | Installed through Node's package tooling; the frontend lockfile pins the packages it installs |
<!-- END DEV -->
<!-- prettier-ignore-end -->

## Not bundled (user-installed, optional)

| Component                   | License          | Used for                                         | Notes                                                                                                                                   |
| --------------------------- | ---------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| Gpg4win / GnuPG for Windows | GPL-3.0-or-later | Decrypting GPG-encrypted mail (`paperless_mail`) | Found in its default install folders by `paperless_win.platform.gpg_dirs()`. Git for Windows' msys `gpg` is ignored on purpose.         |
| unpaper                     | GPL-2.0-or-later | `PAPERLESS_OCR_CLEAN=clean`                      | No maintained Windows build; the setting defaults to `none` (D10). A user-supplied binary can be selected with `PAPERLESS_BIN_UNPAPER`. |

## Dropped by P4

`qpdf` and `pdfinfo` are **not needed** on Windows: `paperless_win.pdf` does the same work with pikepdf (`qpdf --replace-input` repairs, page size). `pdftoppm` and `pdftotext` (Poppler) are still used and ship in the Poppler package. `pdfinfo.exe` is part of that same package, so the upstream binary check, which still looks for it, cannot trigger in a normal install.

The libmagic and PCRE2 DLLs need the Microsoft Visual C++ 14 runtime (`VCRUNTIME140.dll`). Python 3.13 ships it next to `python.exe`; the installer (P10) must provide it for any other process that loads these DLLs.
