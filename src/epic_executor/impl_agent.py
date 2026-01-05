"""Implementation agent for executing task definitions."""

import os
import subprocess
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from .parser import TaskDefinition


IMPL_SYSTEM_PROMPT = """You are an implementation agent that executes coding tasks.

You have access to file operations and code execution tools. Your job is to:
1. Read the task definition carefully
2. Implement the required deliverables
3. Ensure all acceptance criteria are met
4. Create or modify the specified files

Work methodically:
- First read any existing files you need to modify
- Plan your implementation
- Write/modify files as needed
- Test your changes if possible
- Report what you've done

Be precise and complete. Follow the acceptance criteria exactly."""


@tool
def read_file(file_path: str) -> str:
    """Read the contents of a file.

    Args:
        file_path: Path to the file to read.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"[Error: File not found: {file_path}]"
    except PermissionError:
        return f"[Error: Permission denied: {file_path}]"
    except Exception as e:
        return f"[Error reading file: {type(e).__name__}: {e}]"


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file, creating directories if needed.

    Args:
        file_path: Path to the file to write.
        content: The content to write.
    """
    try:
        parent_dir = os.path.dirname(file_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"[Successfully wrote to: {file_path}]"
    except PermissionError:
        return f"[Error: Permission denied: {file_path}]"
    except Exception as e:
        return f"[Error writing file: {type(e).__name__}: {e}]"


@tool
def list_directory(dir_path: str) -> str:
    """List files and directories in a path.

    Args:
        dir_path: Path to the directory to list.
    """
    try:
        entries = os.listdir(dir_path)
        if not entries:
            return f"[Directory is empty: {dir_path}]"
        return "\n".join(sorted(entries))
    except FileNotFoundError:
        return f"[Error: Directory not found: {dir_path}]"
    except PermissionError:
        return f"[Error: Permission denied: {dir_path}]"
    except Exception as e:
        return f"[Error listing directory: {type(e).__name__}: {e}]"


@tool
def execute_shell(command: str, cwd: str | None = None) -> str:
    """Execute a shell command.

    Args:
        command: The shell command to execute.
        cwd: Working directory for the command.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[Exit code: {result.returncode}]"
        return output or "[Command completed with no output]"
    except subprocess.TimeoutExpired:
        return "[Error: Command timed out after 120 seconds]"
    except Exception as e:
        return f"[Error executing command: {type(e).__name__}: {e}]"


def get_llm() -> ChatOpenAI:
    """Create the LLM instance."""
    return ChatOpenAI(
        model=os.environ.get("DEEPINFRA_MODEL", "deepseek-ai/DeepSeek-V3"),
        api_key=os.environ.get("DEEPINFRA_API_KEY", ""),
        base_url="https://api.deepinfra.com/v1/openai",
        temperature=0.3,
        max_tokens=8192,
    )


def get_impl_tools() -> list:
    """Get tools for the implementation agent."""
    return [read_file, write_file, list_directory, execute_shell]


def create_impl_agent(checkpointer=None):
    """Create the implementation agent."""
    llm = get_llm()
    tools = get_impl_tools()

    if checkpointer is None:
        checkpointer = MemorySaver()

    return create_react_agent(
        model=llm,
        tools=tools,
        checkpointer=checkpointer,
    )


def format_task_prompt(task: TaskDefinition, project_root: str) -> str:
    """Format the task definition into a prompt."""
    parts = [
        f"# Task {task.number}: {task.name}",
        "",
    ]

    if task.deliverables:
        parts.extend(["## Deliverables", task.deliverables, ""])

    if task.acceptance_criteria:
        parts.append("## Acceptance Criteria")
        for criterion in task.acceptance_criteria:
            parts.append(f"- {criterion}")
        parts.append("")

    if task.files_to_create:
        parts.append("## Files to Create")
        for f in task.files_to_create:
            parts.append(f"- {f}")
        parts.append("")

    if task.files_to_modify:
        parts.append("## Files to Modify")
        for f in task.files_to_modify:
            parts.append(f"- {f}")
        parts.append("")

    parts.extend([
        "## Project Root",
        f"All file paths should be relative to: {project_root}",
        "",
        "Please implement this task. Read any existing files first, "
        "then create or modify files as needed to meet all acceptance criteria.",
    ])

    return "\n".join(parts)


async def run_implementation(task: TaskDefinition, project_root: str) -> dict:
    """Run the implementation agent on a task."""
    agent = create_impl_agent()

    task_prompt = format_task_prompt(task, project_root)

    messages = [
        SystemMessage(content=IMPL_SYSTEM_PROMPT),
        HumanMessage(content=task_prompt),
    ]

    config = {"configurable": {"thread_id": f"task-{task.number}"}}

    try:
        result = await agent.ainvoke({"messages": messages}, config=config)

        ai_responses = []
        files_modified = []

        for msg in result.get("messages", []):
            if hasattr(msg, "content") and msg.content:
                ai_responses.append(str(msg.content))

            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    if tool_call.get("name") == "write_file":
                        args = tool_call.get("args", {})
                        file_path = args.get("file_path")
                        if file_path and file_path not in files_modified:
                            files_modified.append(file_path)

        output = "\n\n".join(ai_responses)
        success = bool(output) and "[Error" not in output

        return {
            "success": success,
            "files_modified": files_modified,
            "output": output,
        }

    except Exception as e:
        return {
            "success": False,
            "files_modified": [],
            "output": f"Implementation failed: {type(e).__name__}: {e}",
        }
