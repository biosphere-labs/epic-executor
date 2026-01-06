"""Status tracking for epic execution - enables resume capability."""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


STATUS_FILENAME = "execution-status.json"


@dataclass
class TaskStatus:
    """Status of a single task."""

    task_number: int
    status: str  # "pending", "in_progress", "completed", "failed"
    started_at: str | None = None
    completed_at: str | None = None
    commit_hash: str | None = None
    files_modified: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ExecutionStatus:
    """Overall execution status for an epic."""

    epic_name: str
    branch_name: str
    worktree_path: str
    started_at: str
    tasks: dict[int, TaskStatus] = field(default_factory=dict)
    last_updated: str = ""

    def save(self, epic_path: Path) -> Path:
        """Save status to the epic folder."""
        status_file = epic_path / STATUS_FILENAME
        self.last_updated = datetime.now().isoformat()

        # Convert to dict for JSON serialization
        data = {
            "epic_name": self.epic_name,
            "branch_name": self.branch_name,
            "worktree_path": self.worktree_path,
            "started_at": self.started_at,
            "last_updated": self.last_updated,
            "tasks": {str(k): asdict(v) for k, v in self.tasks.items()},
        }

        status_file.write_text(json.dumps(data, indent=2))
        return status_file

    @classmethod
    def load(cls, epic_path: Path) -> "ExecutionStatus | None":
        """Load status from epic folder if it exists."""
        status_file = epic_path / STATUS_FILENAME
        if not status_file.exists():
            return None

        try:
            data = json.loads(status_file.read_text())
            status = cls(
                epic_name=data["epic_name"],
                branch_name=data["branch_name"],
                worktree_path=data["worktree_path"],
                started_at=data["started_at"],
                last_updated=data.get("last_updated", ""),
            )

            for task_num_str, task_data in data.get("tasks", {}).items():
                task_num = int(task_num_str)
                status.tasks[task_num] = TaskStatus(**task_data)

            return status
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def get_completed_tasks(self) -> set[int]:
        """Get set of completed task numbers."""
        return {
            num for num, task in self.tasks.items()
            if task.status == "completed"
        }

    def get_failed_tasks(self) -> set[int]:
        """Get set of failed task numbers."""
        return {
            num for num, task in self.tasks.items()
            if task.status == "failed"
        }

    def mark_started(self, task_num: int) -> None:
        """Mark a task as started."""
        if task_num not in self.tasks:
            self.tasks[task_num] = TaskStatus(task_number=task_num, status="pending")

        self.tasks[task_num].status = "in_progress"
        self.tasks[task_num].started_at = datetime.now().isoformat()

    def mark_completed(
        self,
        task_num: int,
        files_modified: list[str] | None = None,
        commit_hash: str | None = None,
    ) -> None:
        """Mark a task as completed."""
        if task_num not in self.tasks:
            self.tasks[task_num] = TaskStatus(task_number=task_num, status="pending")

        self.tasks[task_num].status = "completed"
        self.tasks[task_num].completed_at = datetime.now().isoformat()
        if files_modified:
            self.tasks[task_num].files_modified = files_modified
        if commit_hash:
            self.tasks[task_num].commit_hash = commit_hash

    def mark_failed(self, task_num: int, error: str | None = None) -> None:
        """Mark a task as failed."""
        if task_num not in self.tasks:
            self.tasks[task_num] = TaskStatus(task_number=task_num, status="pending")

        self.tasks[task_num].status = "failed"
        self.tasks[task_num].completed_at = datetime.now().isoformat()
        self.tasks[task_num].error = error


def load_or_create_status(
    epic_path: Path,
    epic_name: str,
    branch_name: str,
    worktree_path: str,
) -> ExecutionStatus:
    """Load existing status or create new one."""
    existing = ExecutionStatus.load(epic_path)
    if existing:
        # Update worktree path in case it changed
        existing.worktree_path = worktree_path
        return existing

    return ExecutionStatus(
        epic_name=epic_name,
        branch_name=branch_name,
        worktree_path=worktree_path,
        started_at=datetime.now().isoformat(),
    )
