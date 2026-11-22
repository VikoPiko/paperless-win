<!-- winport: unofficial-port notice (P00), install and docs section (P12) -->

> **paperless-win** is an unofficial Windows port of paperless-ngx. Not affiliated with or supported by the paperless-ngx project. Report issues here, not upstream.

# paperless-win

paperless-win runs [paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) **natively on Windows 10 and 11**: no Docker, no WSL, no virtual machine. You download an installer, answer four questions, and get the paperless-ngx web interface at `http://localhost:8000`, a folder you can drop scans into, and a Windows service that starts with the computer. It is the same application as upstream (same web interface, same API, same documents), built from the upstream release tag with a thin Windows layer; what changed is listed in [`windows/PATCHES.md`](windows/PATCHES.md) and [`windows/NOTICE.md`](windows/NOTICE.md).

**It is not made, endorsed or supported by the paperless-ngx project.** Do not report problems with it to them: use the [issues of this repository](https://github.com/VikoPiko/paperless-win/issues).

## Install

1. Download `paperless-win-setup-<version>.exe` (and `SHA256SUMS`) from the [releases](https://github.com/VikoPiko/paperless-win/releases) page. The installer is not code-signed yet: SmartScreen will say "Windows protected your PC", so compare the checksum, then choose **More info**, **Run anyway**.
2. Run it as an administrator (it installs a Windows service).
3. Pick the data folder and the consume folder, create the first administrator account, choose the web port and the OCR languages.
4. Wait a few minutes while it sets up the database and the search index.
5. Open `http://localhost:8000` and sign in.

Needs Windows 10/11 (64 bit), about 2 GB of disk space and 1.5 GB of memory while OCR runs. Nothing else has to be installed; the installer works without internet access. More in [`windows/docs/install.md`](windows/docs/install.md) (including unattended installation).

## Documentation

- [Installing](windows/docs/install.md), [configuring](windows/docs/configuration.md), [running, backing up, upgrading and moving from Docker](windows/docs/operations.md), [troubleshooting](windows/docs/troubleshooting.md), [the Windows service](windows/SERVICE.md)
- Using paperless-ngx itself (tags, correspondents, workflows, mail rules, the API...): the [upstream documentation](https://docs.paperless-ngx.com) applies unchanged.
- For contributors: [`windows/PLAN.md`](windows/PLAN.md), [`windows/UPSTREAM-SYNC.md`](windows/UPSTREAM-SYNC.md), [`windows/THIRD_PARTY.md`](windows/THIRD_PARTY.md).

## What is different from the Linux version

| Area                    | In paperless-win                                                                                                                                                                                    |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Installation, processes | An installer and one Windows service; the container's process manager is replaced by a supervisor (`paperless-ctl`).                                                                                |
| Broker                  | Microsoft Garnet (Redis-compatible), bundled and started by the service. An external Redis is not supported yet.                                                                                    |
| Database                | SQLite by default; PostgreSQL if you provide a server. MariaDB/MySQL is not included.                                                                                                               |
| Task workers            | Several single-task worker processes (Windows has no prefork); a worker is restarted after every document, and a task past its time limit is killed by the supervisor.                              |
| `unpaper`, `jbig2enc`   | Not included (cleaning options and the smallest PDFs are unavailable unless you supply the programs).                                                                                               |
| Office documents        | Word, Excel, PowerPoint, OpenDocument and e-mail work through LibreOffice, Java and a Tika server that you install yourself (optional, not bundled); our own small service stands in for Gotenberg. |
| Local AI embeddings     | Optional add-on (large download). Online and separate AI services work in the base install.                                                                                                         |
| Network consume folders | Polled every 10 s; the service must run as a user that can open the share.                                                                                                                          |
| Scale                   | One computer.                                                                                                                                                                                       |

## How this port was made

paperless-win is a **derivative work**: the application is [paperless-ngx](https://github.com/paperless-ngx/paperless-ngx), written by the paperless-ngx contributors (building on [Paperless-ng](https://github.com/jonaswinkler/paperless-ng) and the original [Paperless](https://github.com/the-paperless-project/paperless)). All credit for the application belongs to them. This fork adds only what is needed to run it on Windows, and it is rebuilt on every upstream release.

- **Base:** upstream release **v3.5.1** (the modifications start on 21 November 2026). A version is named `X.Y.Z-win.N` after the upstream version it is built on.
- **Method:** the port was planned and written in phases (feasibility spike, platform layer, file paths, external tools, consumer, supervisor, Windows service, installer, CI and release, documentation; see [`windows/PLAN.md`](windows/PLAN.md)) by **[Claude Code](https://claude.com/claude-code)**, Anthropic's AI coding assistant, working under the direction of the repository owner ([VikoPiko](https://github.com/VikoPiko)), who set the goals and the rules in [`CLAUDE.md`](CLAUDE.md). Treat it like any young software written largely by an AI: it has been tested (the upstream test suite runs on Windows with the skips listed in [`windows/SKIPPED_TESTS.md`](windows/SKIPPED_TESTS.md); install, upgrade and service tests run in CI), but it has not had an independent security audit and has not been tried on a clean machine by a second person. **Keep backups of your documents and of the data folder.**
- **A thin layer on top of upstream:** new code lives in [`src/paperless_win/`](src/paperless_win/) (supervisor, service integration, `paperless-ctl`) and [`windows/`](windows/) (installer, build scripts, tests, documentation). The few edits inside upstream files are each marked `winport:` in the source and listed with their reason in [`windows/PATCHES.md`](windows/PATCHES.md); the full difference is `git diff v3.5.1..`. See [`windows/NOTICE.md`](windows/NOTICE.md).
- **Following upstream:** a weekly workflow reads only the public list of upstream release tags (anonymously) and opens an issue in _this_ repository when a new one appears. Nothing is ever sent to the upstream project; see [`windows/UPSTREAM-SYNC.md`](windows/UPSTREAM-SYNC.md).

If something works in paperless-ngx but not here, it is probably a problem of this port: report it in the [issues of this repository](https://github.com/VikoPiko/paperless-win/issues), and never to the paperless-ngx project.

## Legal

- **Licence.** paperless-ngx is free software under the **GNU General Public License v3.0**. paperless-win is a modified version of it and is distributed under the same licence, with the upstream copyright notices kept: see [`LICENSE`](LICENSE). You may use, study, change and redistribute it under those terms.
- **No warranty.** As the GPL says, the software is provided "as is", without warranty of any kind. The authors are not liable for loss of data or any other damage.
- **Bundled programs.** The installer contains programs from other projects under their own licences, among them Ghostscript (AGPL-3.0), Tesseract (Apache-2.0), Poppler (GPL), Microsoft Garnet (MIT) and Python. Each one is listed with its licence, version and the address of its source code in [`windows/THIRD_PARTY.md`](windows/THIRD_PARTY.md); the licence texts are in [`windows/licenses/`](windows/licenses/) and in the installation, and the installer's licence page lists every component. The source code of all of them is available from the addresses given there.
- **Names.** "paperless-ngx" and its logo belong to the paperless-ngx project; they are used here only to say what this software is based on. This project is not affiliated with, sponsored or endorsed by that project, and is named "paperless-win" to avoid any suggestion that it is. Windows, Microsoft Edge, Word, Excel and PowerPoint are trademarks of Microsoft; LibreOffice is a trademark of The Document Foundation; Claude is a trademark of Anthropic. They are named only to describe what works with this software.
- **Your data.** Documents stay on your computer. The software connects to other services only if you configure it to (for example an online AI service, or e-mail accounts for mail rules). The installer is not code-signed yet, and the web interface is plain HTTP: keep it on your own computer or network, or put a reverse proxy in front of it.
- **Security issues** in this port: please use the [issues](https://github.com/VikoPiko/paperless-win/issues) of this repository. Security issues in paperless-ngx itself follow upstream's own policy.

<!-- /winport -->

[![ci](https://github.com/paperless-ngx/paperless-ngx/workflows/ci/badge.svg)](https://github.com/paperless-ngx/paperless-ngx/actions)
[![Crowdin](https://badges.crowdin.net/paperless-ngx/localized.svg)](https://crowdin.com/project/paperless-ngx)
[![Documentation Status](https://img.shields.io/github/deployments/paperless-ngx/paperless-ngx/github-pages?label=docs)](https://docs.paperless-ngx.com)
[![codecov](https://codecov.io/gh/paperless-ngx/paperless-ngx/branch/main/graph/badge.svg?token=VK6OUPJ3TY)](https://codecov.io/gh/paperless-ngx/paperless-ngx)
[![Chat on Matrix](https://matrix.to/img/matrix-badge.svg)](https://matrix.to/#/%23paperlessngx%3Amatrix.org)
[![demo](https://cronitor.io/badges/ve7ItY/production/W5E_B9jkelG9ZbDiNHUPQEVH3MY.svg)](https://demo.paperless-ngx.com)

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/assets/logo_full_white.png" width="50%">
    <source media="(prefers-color-scheme: light)" srcset="https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/assets/logo_full_black.png" width="50%">
    <img src="https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/assets/logo_full_black.png" width="50%">
  </picture>
</p>

<!-- omit in toc -->

# Paperless-ngx

Paperless-ngx is a document management system that transforms your physical documents into a searchable online archive so you can keep, well, _less paper_.

Paperless-ngx is the official successor to the original [Paperless](https://github.com/the-paperless-project/paperless) & [Paperless-ng](https://github.com/jonaswinkler/paperless-ng) projects and is designed to distribute the responsibility of advancing and supporting the project among a team of people. [Consider joining us!](#community-support)

Thanks to the generous folks at [Fyra Stack](https://fyrastack.com), a demo is available at [demo.paperless-ngx.com](https://demo.paperless-ngx.com) using login `demo` / `demo`. _Note: demo content is reset frequently and confidential information should not be uploaded._

- [Features](#features)
- [Getting started](#getting-started)
- [Contributing](#contributing)
  - [Community Support](#community-support)
  - [Translation](#translation)
  - [Feature Requests](#feature-requests)
  - [Bugs](#bugs)
- [Related Projects](#related-projects)
- [Important Note](#important-note)

<p align="right">Demo hosting provided by:<br/>
  <a href="https://fyrastack.com">
    <img src="docs/assets/sponsors/fyra-stack.svg" alt="" width="28px" align="absmiddle"> Fyra Stack
  </a>
</p>

# Features

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/assets/screenshots/documents-smallcards-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/assets/screenshots/documents-smallcards.png">
  <img src="https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/assets/screenshots/documents-smallcards.png">
</picture>

A full list of [features](https://docs.paperless-ngx.com/#features) and [screenshots](https://docs.paperless-ngx.com/#screenshots) are available in the [documentation](https://docs.paperless-ngx.com/).

# Getting started

The easiest way to deploy paperless is `docker compose`. The files in the [`/docker/compose` directory](https://github.com/paperless-ngx/paperless-ngx/tree/main/docker/compose) are configured to pull the image from the GitHub container registry.

If you'd like to jump right in, you can configure a `docker compose` environment with our install script:

```bash
bash -c "$(curl -L https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/install-paperless-ngx.sh)"
```

More details and step-by-step guides for alternative installation methods can be found in [the documentation](https://docs.paperless-ngx.com/setup/#installation).

Migrating from Paperless-ng is easy, just drop in the new docker image! See the [documentation on migrating](https://docs.paperless-ngx.com/setup/#migrating-to-paperless-ngx) for more details.

<!-- omit in toc -->

### Documentation

The documentation for Paperless-ngx is available at [https://docs.paperless-ngx.com](https://docs.paperless-ngx.com/).

# Contributing

If you feel like contributing to the project, please do! Bug fixes, enhancements, visual fixes etc. are always welcome. If you want to implement something big: Please start a discussion about that! The [documentation](https://docs.paperless-ngx.com/development/) has some basic information on how to get started.

## Community Support

People interested in continuing the work on paperless-ngx are encouraged to reach out here on github and in the [Matrix Room](https://matrix.to/#/#paperless:matrix.org). If you would like to contribute to the project on an ongoing basis there are multiple [teams](https://github.com/orgs/paperless-ngx/people) (frontend, ci/cd, etc) that could use your help so please reach out!

## Translation

Paperless-ngx is available in many languages that are coordinated on Crowdin. If you want to help out by translating paperless-ngx into your language, please head over to https://crowdin.com/project/paperless-ngx, and thank you! More details can be found in [CONTRIBUTING.md](https://github.com/paperless-ngx/paperless-ngx/blob/main/CONTRIBUTING.md#translating-paperless-ngx).

## Feature Requests

Feature requests can be submitted via [GitHub Discussions](https://github.com/paperless-ngx/paperless-ngx/discussions/categories/feature-requests), you can search for existing ideas, add your own and vote for the ones you care about.

## Bugs

For bugs please [open an issue](https://github.com/paperless-ngx/paperless-ngx/issues) or [start a discussion](https://github.com/paperless-ngx/paperless-ngx/discussions) if you have questions.

# Related Projects

Please see [the wiki](https://github.com/paperless-ngx/paperless-ngx/wiki/Related-Projects) for a user-maintained list of related projects and software that is compatible with Paperless-ngx.

# Important Note

> Document scanners are typically used to scan sensitive documents like your social insurance number, tax records, invoices, etc. **Paperless-ngx should never be run on an untrusted host** because information is stored in clear text without encryption. No guarantees are made regarding security (but we do try!) and you use the app at your own risk.
> **The safest way to run Paperless-ngx is on a local server in your own home with backups in place**.
