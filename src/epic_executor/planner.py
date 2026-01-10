"""Plan generation for epic execution."""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from .parser import TaskDefinition, parse_epic_folder
from .scheduler import create_execution_plan, ExecutionPlan


@dataclass
class EpicInfo:
    """Information about an epic."""

    name: str
    description: str
    branch_name: str
    source_path: Path
    worktree_path: str | None = None  # Pre-configured worktree from epic.md


@dataclass
class FileAssignment:
    """Tracks which task owns which file."""

    file_path: str
    task_number: int
    action: str  # "create" or "modify"


@dataclass
class ExecutionPlanDetail:
    """Detailed execution plan with file assignments."""

    epic: EpicInfo
    tasks: list[TaskDefinition]
    schedule: ExecutionPlan
    file_assignments: dict[str, FileAssignment]
    conflicts: list[tuple[int, int, str]]
    sequenced_tasks: list[tuple[int, int]]


def parse_epic_info(epic_path: Path) -> EpicInfo:
    """Parse epic.md to extract epic name, description, and worktree path."""
    epic_file = epic_path / "epic.md"

    if not epic_file.exists():
        folder_name = epic_path.name
        return EpicInfo(
            name=folder_name.replace("-", " ").title(),
            description="",
            branch_name=f"feature/{folder_name}",
            source_path=epic_path,
        )

    content = epic_file.read_text()

    name = ""
    description = ""
    worktree_path = None

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            name = frontmatter.get("name", "")
            description = frontmatter.get("description", "")
            worktree_path = frontmatter.get("worktree") or frontmatter.get("worktree_path")

    if not name:
        heading_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if heading_match:
            name = heading_match.group(1).strip()

    if not name:
        name = epic_path.name.replace("-", " ").title()

    branch_name = "feature/" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    # Also check execution-status.json for existing worktree path
    if not worktree_path:
        status_file = epic_path / "execution-status.json"
        if status_file.exists():
            import json
            try:
                status = json.loads(status_file.read_text())
                worktree_path = status.get("worktree_path")
            except (json.JSONDecodeError, KeyError):
                pass

    return EpicInfo(
        name=name,
        description=description,
        branch_name=branch_name,
        source_path=epic_path,
        worktree_path=worktree_path,
    )


def find_dependency_graph_section(epic_path: Path) -> str | None:
    """Check if epic.md has a Dependency Graph section.

    Returns the section content if found, None otherwise.
    """
    epic_file = epic_path / "epic.md"
    if not epic_file.exists():
        return None

    content = epic_file.read_text()

    # Look for "Dependency Graph" or "Parallel Execution" section
    # Supports both ## headings and **bold:** format
    patterns = [
        # Markdown headings
        r"^##\s+Dependency\s+Graph\s*:?\s*\n(.*?)(?=^##\s|\Z)",
        r"^##\s+Parallel\s+Execution\s*:?\s*\n(.*?)(?=^##\s|\Z)",
        r"^##\s+Execution\s+Order\s*:?\s*\n(.*?)(?=^##\s|\Z)",
        # Bold text format: **Dependency Graph:**
        r"\*\*Dependency\s+Graph:?\*\*:?\s*\n(.*?)(?=\n\*\*[A-Z]|\n##\s|\Z)",
        r"\*\*Parallel\s+Execution:?\*\*:?\s*\n(.*?)(?=\n\*\*[A-Z]|\n##\s|\Z)",
        r"\*\*Execution\s+Order:?\*\*:?\s*\n(.*?)(?=\n\*\*[A-Z]|\n##\s|\Z)",
    ]

    for pattern in patterns:
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


def has_existing_dependency_graph(epic_path: Path) -> bool:
    """Check if the epic has an existing dependency graph defined."""
    return find_dependency_graph_section(epic_path) is not None


def detect_file_conflicts(
    tasks: list[TaskDefinition],
) -> tuple[dict[str, list[int]], list[tuple[int, int, str]]]:
    """Detect which tasks touch the same files."""
    file_to_tasks: dict[str, list[int]] = defaultdict(list)

    for task in tasks:
        for f in task.files_to_create:
            file_to_tasks[f].append(task.task_number)
        for f in task.files_to_modify:
            file_to_tasks[f].append(task.task_number)

    conflicts = []
    for file_path, task_nums in file_to_tasks.items():
        if len(task_nums) > 1:
            for i, t1 in enumerate(task_nums):
                for t2 in task_nums[i + 1 :]:
                    conflicts.append((t1, t2, file_path))

    return dict(file_to_tasks), conflicts


def assign_files_to_tasks(
    tasks: list[TaskDefinition],
    schedule: ExecutionPlan,
) -> tuple[dict[str, FileAssignment], list[tuple[int, int]]]:
    """Assign files to tasks, sequencing conflicting tasks."""
    assignments: dict[str, FileAssignment] = {}
    sequenced: list[tuple[int, int]] = []
    task_map = {t.task_number: t for t in tasks}

    for task_num in schedule.task_order:
        task = task_map[task_num]

        for f in task.files_to_create:
            if f in assignments:
                owner = assignments[f].task_number
                sequenced.append((owner, task_num))
            else:
                assignments[f] = FileAssignment(f, task_num, "create")

        for f in task.files_to_modify:
            if f in assignments:
                owner = assignments[f].task_number
                sequenced.append((owner, task_num))
            else:
                assignments[f] = FileAssignment(f, task_num, "modify")

    return assignments, sequenced


def generate_plan(epic_path: str) -> ExecutionPlanDetail:
    """Generate a detailed execution plan for an epic."""
    path = Path(epic_path)

    epic = parse_epic_info(path)
    tasks = parse_epic_folder(epic_path)
    schedule = create_execution_plan(tasks)
    _, conflicts = detect_file_conflicts(tasks)
    assignments, sequenced = assign_files_to_tasks(tasks, schedule)

    return ExecutionPlanDetail(
        epic=epic,
        tasks=tasks,
        schedule=schedule,
        file_assignments=assignments,
        conflicts=conflicts,
        sequenced_tasks=sequenced,
    )


def render_plan_markdown(plan: ExecutionPlanDetail) -> str:
    """Render the execution plan as markdown."""
    lines = []

    lines.append(f"# Execution Plan: {plan.epic.name}")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Epic source:** `{plan.epic.source_path}`")
    lines.append(f"**Branch:** `{plan.epic.branch_name}`")
    lines.append(f"**Total tasks:** {len(plan.tasks)}")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Parallel levels:** {len(plan.schedule.levels)}")
    lines.append(f"- **File conflicts detected:** {len(plan.conflicts)}")
    lines.append(f"- **Sequenced task pairs:** {len(plan.sequenced_tasks)}")
    lines.append("")

    lines.append("## Execution Schedule")
    lines.append("")

    task_map = {t.task_number: t for t in plan.tasks}

    for level_idx, level in enumerate(plan.schedule.levels):
        lines.append(f"### Level {level_idx} (parallel)")
        lines.append("")
        lines.append("| Task | Name | Dependencies | Files |")
        lines.append("|------|------|--------------|-------|")

        for task_num in level:
            task = task_map[task_num]
            deps = ", ".join(str(d) for d in task.dependencies) or "None"
            files = task.files_to_create + task.files_to_modify
            file_count = f"{len(files)} files" if files else "None specified"
            lines.append(f"| {task_num:03d} | {task.name} | {deps} | {file_count} |")

        lines.append("")

    lines.append("## Task Details")
    lines.append("")

    for task in plan.tasks:
        lines.append(f"### Task {task.task_number:03d}: {task.name}")
        lines.append("")

        if task.dependencies:
            lines.append(
                f"**Dependencies:** {', '.join(f'{d:03d}' for d in task.dependencies)}"
            )
        else:
            lines.append("**Dependencies:** None")
        lines.append("")

        if task.files_to_create:
            lines.append("**Files to create:**")
            for f in task.files_to_create:
                lines.append(f"- `{f}`")
            lines.append("")

        if task.files_to_modify:
            lines.append("**Files to modify:**")
            for f in task.files_to_modify:
                lines.append(f"- `{f}`")
            lines.append("")

        if task.acceptance_criteria:
            lines.append("**Acceptance criteria:**")
            for ac in task.acceptance_criteria:
                lines.append(f"- [ ] {ac}")
            lines.append("")

        lines.append("---")
        lines.append("")

    if plan.conflicts:
        lines.append("## File Conflicts")
        lines.append("")
        lines.append(
            "The following tasks touch the same files and will be sequenced:"
        )
        lines.append("")
        lines.append("| File | Tasks |")
        lines.append("|------|-------|")

        file_conflicts: dict[str, list[int]] = defaultdict(list)
        for t1, t2, f in plan.conflicts:
            if t1 not in file_conflicts[f]:
                file_conflicts[f].append(t1)
            if t2 not in file_conflicts[f]:
                file_conflicts[f].append(t2)

        for f, tasks in sorted(file_conflicts.items()):
            task_str = ", ".join(f"{t:03d}" for t in sorted(tasks))
            lines.append(f"| `{f}` | {task_str} |")

        lines.append("")

    return "\n".join(lines)


def save_plan(plan: ExecutionPlanDetail, output_dir: Path) -> Path:
    """Save the plan to a markdown file."""
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r"[^a-z0-9]+", "-", plan.epic.name.lower()).strip("-")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{safe_name}-{timestamp}.md"

    plan_path = output_dir / filename
    plan_path.write_text(render_plan_markdown(plan))

    return plan_path
