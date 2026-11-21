# Decisions (ADR log)

Short entries. Newest at the bottom. Format: context → decision → consequences.

## D1 — Fork model: track upstream release tags
- **Context:** Want upstream features/security fixes; fork should be a Windows layer, not a rewrite.
- **Decision:** `main` = upstream release tag + winport layer. Merge each upstream release tag via `sync/vX.Y.Z` branch. Don't track `dev`.
- **Consequences:** Thin-diff discipline (`CLAUDE.md` rules 2–3, `PATCHES.md`). Some upstream refactors will force rework of hooks.

## D2 — Redis: bundle Garnet
- **Context:** Celery broker, Channels layer and Django cache all use Redis. Valkey/Redis have no maintained native Windows builds.
- **Decision:** Ship Microsoft Garnet, bound to 127.0.0.1, started by our supervisor. No Redis-free mode in v1.
- **Consequences:** Must verify compatibility (P1). Extra ~100 MB process. Users never see it.

## D3 — AI: optional add-on
- **Context:** torch + sentence-transformers ≈ 2 GB; only needed for *local* embeddings. Remote backends (OpenAI-compatible, Ollama) are light.
- **Decision:** Move local-embedding deps to an `ai-local` extra; installer offers it as an optional component (download on demand).
- **Consequences:** One `pyproject.toml` hunk to maintain; settings validation must explain how to enable local embeddings.

## D4 — Name: paperless-win
- **Decision:** Repo/product name `paperless-win`. Clearly marked unofficial; issues go to the fork, never upstream.

## D5 — Workers: Celery solo pool, N processes
- **Context:** Celery doesn't officially support Windows; prefork/billiard unreliable. OCRmyPDF is not meant to be called concurrently from threads in one process.
- **Decision:** N `celery worker -P solo` processes (unique `-n`), supervised; recycle after K tasks; watchdog enforces time limits by killing the process tree.

## D6 — Service wrapper: WinSW
- **Decision:** WinSW (MIT, single exe + XML) wraps `paperless-ctl run`. No pywin32 service code.
- **Consequences:** Supervisor must handle Ctrl-Break/stop signal from WinSW and shut down children cleanly.
