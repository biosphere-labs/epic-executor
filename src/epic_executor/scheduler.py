"""Dependency graph and execution scheduling."""

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .parser import TaskDefinition


@dataclass
class ExecutionPlan:
    """Execution plan with parallel levels."""

    levels: list[list[int]]  # Tasks grouped by level (parallel within level)
    task_order: list[int]  # Flat topological order
    dependency_map: dict[int, list[int]]  # task_num -> [dependency_nums]


def build_dependency_graph(tasks: list["TaskDefinition"]) -> dict[int, list[int]]:
    """Build adjacency list: task_num -> [tasks that depend on it]."""
    graph = defaultdict(list)
    for task in tasks:
        for dep_num in task.dependencies:
            graph[dep_num].append(task.number)
    return dict(graph)


def build_in_degree(
    tasks: list["TaskDefinition"],
    pre_completed: set[int] | None = None,
) -> dict[int, int]:
    """Count incoming edges for each task.

    Args:
        tasks: List of tasks to schedule
        pre_completed: Set of task numbers already completed (dependencies satisfied)
    """
    pre_completed = pre_completed or set()
    in_degree = {}
    for task in tasks:
        # Only count dependencies that aren't already completed
        unsatisfied_deps = [d for d in task.dependencies if d not in pre_completed]
        in_degree[task.number] = len(unsatisfied_deps)
    return in_degree


def create_execution_plan(
    tasks: list["TaskDefinition"],
    pre_completed: set[int] | None = None,
) -> ExecutionPlan:
    """Create parallel execution plan using Kahn's algorithm.

    Args:
        tasks: List of tasks to schedule
        pre_completed: Set of task numbers already completed (for resume)
    """
    if not tasks:
        return ExecutionPlan(levels=[], task_order=[], dependency_map={})

    pre_completed = pre_completed or set()
    task_map = {t.number: t for t in tasks}
    graph = build_dependency_graph(tasks)
    in_degree = build_in_degree(tasks, pre_completed)

    # Find tasks with no dependencies (level 0)
    queue = deque([num for num, deg in in_degree.items() if deg == 0])

    levels = []
    task_order = []
    dependency_map = {t.number: list(t.dependencies) for t in tasks}

    while queue:
        current_level = list(queue)
        levels.append(current_level)
        task_order.extend(current_level)

        next_queue = deque()
        for task_num in current_level:
            for dependent in graph.get(task_num, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_queue.append(dependent)

        queue = next_queue

    if len(task_order) != len(tasks):
        missing = set(t.number for t in tasks) - set(task_order)
        raise ValueError(f"Circular dependency detected involving tasks: {missing}")

    return ExecutionPlan(
        levels=levels,
        task_order=task_order,
        dependency_map=dependency_map,
    )


def get_ready_tasks(
    plan: ExecutionPlan,
    completed: set[int],
    in_progress: set[int],
) -> list[int]:
    """Get tasks ready to execute (dependencies met, not started)."""
    ready = []
    for task_num in plan.task_order:
        if task_num in completed or task_num in in_progress:
            continue
        deps = plan.dependency_map.get(task_num, [])
        if all(dep in completed for dep in deps):
            ready.append(task_num)
    return ready
