"""Worker-side half of the supervisor: recycling, graceful stop and the watchdog record.

Imported from ``paperless/celery.py`` (one marked line). It only does anything inside a
worker that the supervisor started (it sets ``PAPERLESS_WIN_WORKER_INDEX``), so web, beat,
the consumer and every Linux deployment are unaffected.

Why this exists: Celery's ``solo`` pool (the only pool that works on Windows) ignores
``worker_max_tasks_per_child`` and ``task_time_limit``.

* **Recycling.** After ``PAPERLESS_WIN_RECYCLE_AFTER`` finished tasks (default 1, matching
  the Docker image's ``MAX_TASKS_PER_CHILD=1``) the worker shuts down after the current
  message and the supervisor starts a fresh one. This hands memory back to the OS, which
  OCR-heavy tasks need.
* **Graceful stop.** The supervisor asks a worker to leave by creating ``w<i>.stop``; the
  worker finishes its task first.
* **Watchdog record.** ``w<i>.json`` says which task runs since when, so the supervisor
  can kill a worker whose task ran past the time limit.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger("paperless.winport.worker")

ENV_RUN_DIR = "PAPERLESS_WIN_RUN_DIR"
ENV_INDEX = "PAPERLESS_WIN_WORKER_INDEX"
ENV_RECYCLE = "PAPERLESS_WIN_RECYCLE_AFTER"
POLL_SECONDS = 0.5


class TaskTracker:
    """Writes the watchdog record and counts tasks. No Celery import: easy to test."""

    def __init__(
        self,
        run_dir: Path,
        index: int,
        recycle_after: int = 1,
        wall=time.time,
    ) -> None:
        self.record = run_dir / f"w{index}.json"
        self.stop_file = run_dir / f"w{index}.stop"
        self.recycle_after = recycle_after
        self.finished = 0
        self._wall = wall

    def started(self, task_id: str | None, task_name: str = "") -> None:
        data = {
            "task_id": task_id,
            "task_name": task_name,
            "pid": os.getpid(),
            "started_at": self._wall(),
        }
        tmp = self.record.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self.record)
        except OSError:
            logger.warning(
                "Could not write %s; the watchdog is blind for this task",
                self.record,
            )

    def finished_task(self) -> bool:
        """Clear the record. True if the worker has now done its share and should be recycled."""
        with contextlib.suppress(OSError):
            self.record.unlink(missing_ok=True)
        self.finished += 1
        return 0 < self.recycle_after <= self.finished

    def stop_requested(self) -> bool:
        return self.stop_file.exists()


def request_worker_stop() -> None:
    """Warm shutdown: Celery's main loop stops after the message it is working on."""
    from celery.worker import state

    state.should_stop = 0


def install() -> TaskTracker | None:
    run_dir, index = os.environ.get(ENV_RUN_DIR), os.environ.get(ENV_INDEX)
    if not run_dir or not index or not index.isdigit():
        return None
    from celery import signals

    try:
        recycle = int(os.environ.get(ENV_RECYCLE) or 1)
    except ValueError:
        recycle = 1
    tracker = TaskTracker(Path(run_dir), int(index), recycle)

    def on_prerun(sender=None, task_id=None, task=None, **kwargs) -> None:
        tracker.started(task_id, getattr(task or sender, "name", ""))

    def on_postrun(**kwargs) -> None:
        if tracker.finished_task():
            logger.info(
                "Worker w%s finished %s task(s); recycling",
                index,
                tracker.finished,
            )
            request_worker_stop()

    def watch_for_stop_file() -> None:
        while True:
            if tracker.stop_requested():
                request_worker_stop()
                return
            time.sleep(POLL_SECONDS)

    def on_ready(**kwargs) -> None:
        threading.Thread(
            target=watch_for_stop_file,
            name="winport-stop",
            daemon=True,
        ).start()

    signals.task_prerun.connect(on_prerun, weak=False)
    signals.task_postrun.connect(on_postrun, weak=False)
    signals.worker_ready.connect(on_ready, weak=False)
    return tracker


TRACKER = install()
