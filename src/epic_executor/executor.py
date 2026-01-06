"""Main epic executor - orchestrates the full pipeline."""

import asyncio
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.table import Table

from .parser import parse_epic_folder, TaskDefinition
from .scheduler import create_execution_plan, ExecutionPlan
from .planner import (
    generate_plan,
    render_plan_markdown,
    save_plan,
    parse_epic_info,
    has_existing_dependency_graph,
    find_dependency_graph_section,
    ExecutionPlanDetail,
)
from .pool import run_pool, PoolStatus, TaskResult
from .impl_agent import run_implementation
from .verify_agent import run_verification
from .worktree import create_worktree, copy_dependencies, get_repo_root, WorktreeInfo

console = Console()

# Files that may contain existing execution plans
EXISTING_PLAN_FILES = [
    "execution-status.md",
    "parallel-analysis.md",
    "execution-plan.md",
    "plan.md",
]


def find_existing_plan(epic_path: Path) -> Path | None:
    """Check if an existing execution plan file exists."""
    for filename in EXISTING_PLAN_FILES:
        plan_file = epic_path / filename
        if plan_file.exists():
            return plan_file
    return None


def check_epic_dependency_graph(epic_path: Path) -> tuple[bool, str | None]:
    """Check if epic.md has a dependency graph section.

    Returns (has_graph, graph_content).
    """
    content = find_dependency_graph_section(epic_path)
    return (content is not None, content)


def parse_existing_plan_info(plan_file: Path) -> dict:
    """Parse basic info from an existing plan file."""
    content = plan_file.read_text()
    info = {
        "file": plan_file,
        "has_dependency_graph": "Dependency Graph" in content or "dependency graph" in content.lower(),
        "has_worktree_info": "worktree:" in content.lower(),
    }
    return info


async def execute_epic(
    epic_folder: str,
    project_root: str,
    max_concurrent: int = 4,
    on_progress: Callable[[str], None] | None = None,
) -> PoolStatus:
    """Execute all tasks in an epic folder."""

    def log(msg: str):
        if on_progress:
            on_progress(msg)
        console.print(msg)

    log(f"[bold]Parsing epic folder:[/bold] {epic_folder}")
    tasks = parse_epic_folder(epic_folder)
    log(f"Found {len(tasks)} tasks")

    if not tasks:
        log("[red]No tasks found![/red]")
        return PoolStatus()

    log("Building dependency graph and execution plan...")
    plan = create_execution_plan(tasks)
    log(f"Execution levels: {plan.levels}")

    async def progress_callback(result: TaskResult):
        status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
        log(f"Task {result.task_num:03d} {status}")

    log(f"[bold]Starting execution with {max_concurrent} concurrent agents...[/bold]")
    status = await run_pool(
        tasks=tasks,
        plan=plan,
        project_root=project_root,
        impl_fn=run_implementation,
        verify_fn=run_verification,
        max_concurrent=max_concurrent,
        on_task_complete=progress_callback,
    )

    log("")
    log("[bold]Execution complete:[/bold]")
    log(f"  Completed: {len(status.completed)}/{len(tasks)}")
    log(f"  Failed: {len(status.failed)}")

    return status


def display_plan(plan: ExecutionPlanDetail) -> None:
    """Display the execution plan in a nice format."""
    console.print()
    console.print(f"[bold blue]Epic:[/bold blue] {plan.epic.name}")
    console.print(f"[bold]Branch:[/bold] {plan.epic.branch_name}")
    console.print(f"[bold]Tasks:[/bold] {len(plan.tasks)}")
    console.print(f"[bold]Parallel levels:[/bold] {len(plan.schedule.levels)}")
    console.print()

    task_map = {t.task_number: t for t in plan.tasks}

    for level_idx, level in enumerate(plan.schedule.levels):
        table = Table(title=f"Level {level_idx} (parallel)")
        table.add_column("Task", style="cyan")
        table.add_column("Name")
        table.add_column("Dependencies")
        table.add_column("Files")

        for task_num in level:
            task = task_map[task_num]
            deps = ", ".join(str(d) for d in task.dependencies) or "None"
            files = len(task.files_to_create) + len(task.files_to_modify)
            file_str = f"{files} files" if files else "-"
            table.add_row(f"{task_num:03d}", task.name, deps, file_str)

        console.print(table)
        console.print()

    if plan.conflicts:
        console.print("[yellow]⚠ File conflicts detected:[/yellow]")
        for t1, t2, f in plan.conflicts[:5]:
            console.print(f"  Task {t1:03d} and {t2:03d} both touch: {f}")
        if len(plan.conflicts) > 5:
            console.print(f"  ... and {len(plan.conflicts) - 5} more")
        console.print()


async def plan_epic(epic_folder: str, output_dir: Path) -> ExecutionPlanDetail:
    """Generate and save an execution plan for an epic."""
    epic_path = Path(epic_folder)

    # Check for existing plan
    existing = find_existing_plan(epic_path)
    if existing:
        info = parse_existing_plan_info(existing)
        console.print(f"[green]Found existing plan:[/green] {existing.name}")
        if info["has_dependency_graph"]:
            console.print("  ✓ Contains dependency graph")
        if info["has_worktree_info"]:
            console.print("  ✓ Contains worktree info")
        console.print()

    # Generate plan
    plan = generate_plan(epic_folder)

    # Display it
    display_plan(plan)

    # Save it
    plan_path = save_plan(plan, output_dir)
    console.print(f"[green]Plan saved to:[/green] {plan_path}")

    return plan


async def setup_worktree(
    epic_folder: str,
    worktree_base: Path,
) -> WorktreeInfo:
    """Set up a git worktree for the epic."""
    epic_path = Path(epic_folder)
    epic_info = parse_epic_info(epic_path)

    console.print(f"[bold]Creating worktree for:[/bold] {epic_info.name}")
    console.print(f"[bold]Branch:[/bold] {epic_info.branch_name}")

    worktree = create_worktree(epic_path, epic_info.branch_name, worktree_base)

    if worktree.is_new:
        console.print(f"[green]Created new worktree:[/green] {worktree.path}")
    else:
        console.print(f"[yellow]Using existing worktree:[/yellow] {worktree.path}")

    console.print(f"[bold]Commit:[/bold] {worktree.commit}")

    # Copy dependencies from main repo to worktree
    repo_root = get_repo_root(epic_path)
    if repo_root is None:
        for parent in epic_path.parents:
            repo_root = get_repo_root(parent)
            if repo_root:
                break

    if repo_root and worktree.path != repo_root:
        copied = copy_dependencies(repo_root, worktree.path)
        if copied:
            console.print("[bold]Copied dependencies:[/bold]")
            for dep in copied:
                console.print(f"  - {dep}")
            worktree.copied_deps = copied

    return worktree
