# Licence texts of the bundled programs

The build copies this folder into the application (`licenses\` in the installation folder). One file per
component of `windows/build/manifest.json`; the texts are verbatim from the component's own package or from
its repository at the pinned version:

| File                              | Component                                                        | Taken from                                                                     |
| --------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `Tesseract.txt`                   | Tesseract OCR and the `tessdata_fast` language data (Apache-2.0) | `doc\LICENSE` of the pinned Tesseract package                                  |
| `Ghostscript.txt`                 | Ghostscript (AGPL-3.0)                                           | `doc\COPYING` of the pinned Ghostscript package                                |
| `Garnet.txt`                      | Microsoft Garnet (MIT)                                           | `LICENSE` at tag `v2.2.13` of github.com/microsoft/garnet                      |
| `WinSW.txt`                       | WinSW (MIT)                                                      | `LICENSE.txt` at tag `v2.12.0` of github.com/winsw/winsw                       |
| `Uv-MIT.txt`, `Uv-Apache-2.0.txt` | uv (MIT or Apache-2.0, at your option)                           | `LICENSE-MIT` and `LICENSE-APACHE` at tag `0.11.10` of github.com/astral-sh/uv |
| `LibMagic.txt`                    | libmagic (BSD-2-Clause style)                                    | `COPYING` at tag `FILE5_48` of github.com/file/file                            |
| `Pcre2.txt`                       | PCRE2 (BSD-3-Clause with the PCRE2 exception)                    | `LICENCE.md` at tag `pcre2-10.47` of github.com/PCRE2Project/pcre2             |

CPython (`python\LICENSE.txt`), Poppler (`bin\poppler\share\poppler\COPYING*`), pngquant
(`bin\pngquant\pngquant\COPYRIGHT`) and Liberation Serif (`assets\fonts\LICENSE-Liberation-OFL.txt`)
already carry their texts in their own folders. `windows/THIRD_PARTY.md` lists everything with its source.
When a component is added or updated in the manifest, add or replace its text here (a unit test fails
otherwise).
