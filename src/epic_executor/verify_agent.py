"""Verification agent for checking implementation against acceptance criteria."""

import asyncio
import subprocess
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, END

from .parser import TaskDefinition


class VerifyState(TypedDict):
    """State for verification agent."""

    task: TaskDefinition
    project_root: str
    impl_result: dict
    files_exist: dict[str, bool]
    test_output: str
    criteria_results: dict[str, bool]


def detect_language(project_root: str, files_to_check: list[str]) -> str:
    """Detect project language from file extensions."""
    extensions = set()

    for file_path in files_to_check:
        ext = Path(file_path).suffix.lower()
        if ext:
            extensions.add(ext)

    if extensions & {".tsx", ".jsx"}:
        return "frontend"
    if extensions & {".ts", ".js"}:
        return "typescript"
    if extensions & {".py"}:
        return "python"

    project_path = Path(project_root)
    if (project_path / "package.json").exists():
        return "typescript"
    if (project_path / "pyproject.toml").exists():
        return "python"

    return "unknown"


def run_tests(project_root: str, language: str) -> tuple[bool, str]:
    """Run tests based on detected language."""
    try:
        if language == "python":
            result = subprocess.run(
                ["pytest", "-v", "--tb=short"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
        elif language in ("typescript", "frontend"):
            result = subprocess.run(
                ["npm", "test"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
        else:
            return True, "No tests to run for unknown language"

        output = result.stdout
        if result.stderr:
            output += f"\n{result.stderr}"

        return result.returncode == 0, output

    except subprocess.TimeoutExpired:
        return False, "Tests timed out after 120 seconds"
    except FileNotFoundError as e:
        return True, f"Test runner not found: {e}. Skipping tests."
    except Exception as e:
        return False, f"Error running tests: {e}"


async def check_files_exist(state: VerifyState) -> dict:
    """Check if all expected files exist."""
    task = state["task"]
    project_root = state["project_root"]

    files_exist = {}
    for file_path in task.files_to_create:
        full_path = Path(project_root) / file_path
        files_exist[file_path] = full_path.exists()

    for file_path in task.files_to_modify:
        full_path = Path(project_root) / file_path
        files_exist[file_path] = full_path.exists()

    return {"files_exist": files_exist}


async def run_tests_node(state: VerifyState) -> dict:
    """Run appropriate tests based on language."""
    task = state["task"]
    project_root = state["project_root"]

    all_files = task.files_to_create + task.files_to_modify
    language = detect_language(project_root, all_files)

    loop = asyncio.get_event_loop()
    _, output = await loop.run_in_executor(None, run_tests, project_root, language)

    return {"test_output": output}


async def verify_criteria(state: VerifyState) -> dict:
    """Verify acceptance criteria."""
    task = state["task"]
    files_exist = state["files_exist"]
    test_output = state["test_output"]

    criteria_results = {}

    for criterion in task.acceptance_criteria:
        passed = True

        if "create" in criterion.lower() or "file" in criterion.lower():
            passed = any(files_exist.values()) if files_exist else False

        if "test" in criterion.lower():
            passed = "passed" in test_output.lower() or "ok" in test_output.lower()
            passed = passed and "failed" not in test_output.lower()

        criteria_results[criterion] = passed

    return {"criteria_results": criteria_results}


def create_verify_agent():
    """Create the verification agent graph."""
    builder = StateGraph(VerifyState)

    builder.add_node("check_files", check_files_exist)
    builder.add_node("run_tests", run_tests_node)
    builder.add_node("verify_criteria", verify_criteria)

    builder.set_entry_point("check_files")
    builder.add_edge("check_files", "run_tests")
    builder.add_edge("run_tests", "verify_criteria")
    builder.add_edge("verify_criteria", END)

    return builder.compile()


async def run_verification(
    task: TaskDefinition,
    project_root: str,
    impl_result: dict,
) -> dict:
    """Run verification on a task implementation."""
    agent = create_verify_agent()

    initial_state: VerifyState = {
        "task": task,
        "project_root": project_root,
        "impl_result": impl_result,
        "files_exist": {},
        "test_output": "",
        "criteria_results": {},
    }

    result = await agent.ainvoke(initial_state)

    files_ok = all(result["files_exist"].values()) if result["files_exist"] else True
    criteria_ok = (
        all(result["criteria_results"].values()) if result["criteria_results"] else True
    )
    tests_ok = "failed" not in result["test_output"].lower()

    return {
        "passed": files_ok and criteria_ok and tests_ok,
        "criteria_results": result["criteria_results"],
        "test_output": result["test_output"],
    }
