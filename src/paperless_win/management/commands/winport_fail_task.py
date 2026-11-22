"""Mark a task as failed in the database. Run by the supervisor after it killed a stuck worker.

A killed worker never gets to report failure itself, so without this the task would show as
"started" in the web UI forever.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from documents.models import PaperlessTask


class Command(BaseCommand):
    help = "Mark a task as failed because its worker was stopped by the supervisor"

    def add_arguments(self, parser) -> None:
        parser.add_argument("task_id")
        parser.add_argument(
            "--reason",
            default="The task was stopped by the supervisor.",
        )

    def handle(self, *args, **options) -> None:
        task_id, reason = options["task_id"], options["reason"]
        task = PaperlessTask.objects.filter(task_id=task_id).first()
        if task is None:
            self.stdout.write(f"No task {task_id}; nothing to do")
            return
        if task.status in PaperlessTask.COMPLETE_STATUSES:
            self.stdout.write(f"Task {task_id} already finished ({task.status})")
            return
        now = timezone.now()
        task.status = PaperlessTask.Status.FAILURE
        task.date_done = now
        task.result_data = {
            "error_type": "SupervisorStopped",
            "error_message": reason,
        }
        fields = ["status", "date_done", "result_data"]
        if task.date_started:
            task.duration_seconds = (now - task.date_started).total_seconds()
            fields.append("duration_seconds")
        task.save(update_fields=fields)
        self.stdout.write(f"Task {task_id} marked as failed")
