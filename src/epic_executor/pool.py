"""Agent pool for concurrent task execution."""

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Awaitable

from .parser import TaskDefinition
from .scheduler import ExecutionPlan, get_ready_tasks


@dataclass
class TaskResult:
    """Result of a task execution."""

    task_num: int
    success: bool
    impl_output: str = ""
    verify_output: str = ""
    files_modified: list[str] = field(default_factory=list)


@dataclass
class PoolStatus:
    """Status of the execution pool."""

    completed: set[int] = field(default_factory=set)
    failed: set[int] = field(default_factory=set)
    in_progress: set[int] = field(default_factory=set)
    results: dict[int, TaskResult] = field(default_factory=dict)


async def run_pool(
    tasks: list[TaskDefinition],
    plan: ExecutionPlan,
    project_root: str,
    impl_fn: Callable[[TaskDefinition, str], Awaitable[dict]],
    verify_fn: Callable[[TaskDefinition, str, dict], Awaitable[dict]],
    max_concurrent: int = 4,
    on_task_complete: Callable[[TaskResult], Awaitable[None]] | None = None,
) -> PoolStatus:
    """Run tasks with dependency-aware parallelism.

    Args:
        tasks: List of task definitions
        plan: Execution plan with dependencies
        project_root: Root directory for implementation
        impl_fn: Implementation function
        verify_fn: Verification function
        max_concurrent: Maximum parallel tasks
        on_task_complete: Optional callback for task completion
    """
    status = PoolStatus()
    task_map = {t.number: t for t in tasks}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def execute_task(task_num: int) -> TaskResult:
        async with semaphore:
            task = task_map[task_num]

            # Run implementation
            impl_result = await impl_fn(task, project_root)

            # Run verification
            verify_result = await verify_fn(task, project_root, impl_result)

            success = impl_result.get("success", False) and verify_result.get(
                "passed", False
            )

            return TaskResult(
                task_num=task_num,
                success=success,
                impl_output=impl_result.get("output", ""),
                verify_output=verify_result.get("test_output", ""),
                files_modified=impl_result.get("files_modified", []),
            )

    pending_tasks: set[asyncio.Task] = set()
    task_to_num: dict[asyncio.Task, int] = {}

    while len(status.completed) + len(status.failed) < len(tasks):
        # Find tasks ready to run
        ready = get_ready_tasks(plan, status.completed, status.in_progress)

        # Start new tasks up to limit
        for task_num in ready:
            if task_num not in status.in_progress and len(pending_tasks) < max_concurrent:
                status.in_progress.add(task_num)
                async_task = asyncio.create_task(execute_task(task_num))
                pending_tasks.add(async_task)
                task_to_num[async_task] = task_num

        if not pending_tasks:
            # No tasks running and none ready - might be stuck
            if ready:
                continue
            break

        # Wait for at least one task to complete
        done, pending_tasks = await asyncio.wait(
            pending_tasks, return_when=asyncio.FIRST_COMPLETED
        )

        for completed_task in done:
            task_num = task_to_num.pop(completed_task)
            status.in_progress.discard(task_num)

            try:
                result = completed_task.result()
                status.results[task_num] = result

                if result.success:
                    status.completed.add(task_num)
                else:
                    status.failed.add(task_num)

                if on_task_complete:
                    await on_task_complete(result)

            except Exception as e:
                result = TaskResult(
                    task_num=task_num,
                    success=False,
                    impl_output=f"Task failed with exception: {e}",
                )
                status.results[task_num] = result
                status.failed.add(task_num)

                if on_task_complete:
                    await on_task_complete(result)

    return status
