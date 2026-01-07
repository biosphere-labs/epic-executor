"""Implementation agent for executing task definitions."""

import os
import re
import subprocess
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from rich.console import Console

from .parser import TaskDefinition

console = Console()


IMPL_SYSTEM_PROMPT = """You are an autonomous implementation agent that executes coding tasks.

You MUST use your tools to complete tasks. You have these tools:
- read_file: Read existing files before modifying
- write_file: Create or modify files (YOU MUST USE THIS TO COMPLETE TASKS)
- search_code: Search codebase with ripgrep
- find_files: Find files by pattern
- list_directory: List directory contents
- execute_shell: Run shell commands

CRITICAL: You must actually USE the write_file tool to create/modify code. Do not just describe what you would write - actually write it using write_file.

Your job is to:
1. Read the task definition carefully
2. Use read_file to examine existing code
3. Use write_file to implement ALL required deliverables
4. Use write_file to create tests where appropriate

RULES:
- NEVER describe what you would do - USE THE TOOLS to do it
- NEVER ask questions - just implement
- ALWAYS use write_file for every file you need to create or modify
- Complete ALL acceptance criteria in one pass
- After using write_file, confirm what you wrote

Work process:
1. read_file to understand existing code
2. write_file to implement each file
3. Summarize what files you created (in past tense)

If you don't use write_file, your task will fail. You MUST write actual code to files."""


RESEARCH_SYSTEM_PROMPT = """You are a research agent that answers technical questions to help implementation agents.

Your job is to:
1. Search the codebase for relevant patterns and examples
2. Read documentation and existing code
3. Provide clear, actionable answers

When answering:
- Be concise and specific
- Provide code examples when helpful
- Reference specific files and line numbers
- If something requires a library or pattern, explain how to use it

Do NOT ask follow-up questions. Provide the best answer you can with available information."""


def _resolve_path(file_path: str, project_root: str) -> str:
    """Resolve a path against project_root if it's relative."""
    if os.path.isabs(file_path):
        return file_path
    return os.path.join(project_root, file_path)


def _validate_file_path(file_path: str) -> str | None:
    """Validate a file path and return an error message if invalid."""
    basename = os.path.basename(file_path)
    if not basename:
        return f"Invalid path - missing filename: {file_path}"
    if basename.startswith('.') and '.' not in basename[1:]:
        # Hidden file with no extension is okay, but ".js" alone is not
        if len(basename) <= 4:  # e.g., ".js", ".py", ".ts"
            return f"Invalid path - filename appears to be just an extension: {file_path}"
    return None


def create_read_file_tool(project_root: str):
    """Create a read_file tool bound to a project root."""
    @tool
    def read_file(file_path: str) -> str:
        """Read the contents of a file.

        Args:
            file_path: Path to the file to read (relative to project root or absolute).
        """
        resolved = _resolve_path(file_path, project_root)
        try:
            with open(resolved, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return f"[Error: File not found: {resolved}]"
        except PermissionError:
            return f"[Error: Permission denied: {resolved}]"
        except Exception as e:
            return f"[Error reading file: {type(e).__name__}: {e}]"
    return read_file


def create_write_file_tool(project_root: str):
    """Create a write_file tool bound to a project root."""
    @tool
    def write_file(file_path: str, content: str) -> str:
        """Write content to a file, creating directories if needed.

        Args:
            file_path: Path to the file to write (relative to project root or absolute).
            content: The content to write.
        """
        # Validate the path before attempting to write
        validation_error = _validate_file_path(file_path)
        if validation_error:
            return f"[Error: {validation_error}]"

        resolved = _resolve_path(file_path, project_root)
        try:
            parent_dir = os.path.dirname(resolved)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
            return f"[Successfully wrote to: {resolved}]"
        except PermissionError:
            return f"[Error: Permission denied: {resolved}]"
        except Exception as e:
            return f"[Error writing file: {type(e).__name__}: {e}]"
    return write_file


def create_list_directory_tool(project_root: str):
    """Create a list_directory tool bound to a project root."""
    @tool
    def list_directory(dir_path: str) -> str:
        """List files and directories in a path.

        Args:
            dir_path: Path to the directory to list (relative to project root or absolute).
        """
        resolved = _resolve_path(dir_path, project_root)
        try:
            entries = os.listdir(resolved)
            if not entries:
                return f"[Directory is empty: {resolved}]"
            return "\n".join(sorted(entries))
        except FileNotFoundError:
            return f"[Error: Directory not found: {resolved}]"
        except PermissionError:
            return f"[Error: Permission denied: {resolved}]"
        except Exception as e:
            return f"[Error listing directory: {type(e).__name__}: {e}]"
    return list_directory


def create_search_code_tool(project_root: str):
    """Create a search_code tool bound to a project root."""
    @tool
    def search_code(pattern: str, path: str = ".", file_type: str | None = None) -> str:
        """Search for a pattern in code files using ripgrep.

        Args:
            pattern: The regex pattern to search for.
            path: The directory to search in (relative to project root or absolute). Defaults to project root.
            file_type: Optional file type filter (e.g., 'ts', 'py', 'js').
        """
        resolved = _resolve_path(path, project_root)
        try:
            cmd = ["rg", "--max-count=50", "--line-number", "--context=2"]

            if file_type:
                cmd.extend(["--type", file_type])

            cmd.extend([pattern, resolved])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            output = result.stdout
            if not output:
                return f"[No matches found for '{pattern}' in {resolved}]"

            # Truncate if too long
            if len(output) > 10000:
                output = output[:10000] + "\n...[truncated]"

            return output
        except FileNotFoundError:
            return "[Error: ripgrep (rg) not installed. Install with: brew install ripgrep]"
        except subprocess.TimeoutExpired:
            return "[Error: Search timed out after 30 seconds]"
        except Exception as e:
            return f"[Error searching: {type(e).__name__}: {e}]"
    return search_code


def create_find_files_tool(project_root: str):
    """Create a find_files tool bound to a project root."""
    @tool
    def find_files(pattern: str, path: str = ".") -> str:
        """Find files matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g., '*.ts', '**/*.test.js').
            path: The directory to search in (relative to project root or absolute). Defaults to project root.
        """
        resolved = _resolve_path(path, project_root)
        try:
            cmd = ["find", resolved, "-type", "f", "-name", pattern]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            output = result.stdout.strip()
            if not output:
                return f"[No files found matching '{pattern}' in {resolved}]"

            # Limit to 100 files
            lines = output.split('\n')
            if len(lines) > 100:
                output = '\n'.join(lines[:100]) + f"\n...[{len(lines) - 100} more files]"

            return output
        except subprocess.TimeoutExpired:
            return "[Error: Find timed out after 30 seconds]"
        except Exception as e:
            return f"[Error finding files: {type(e).__name__}: {e}]"
    return find_files


@tool
def fetch_docs(query: str, framework: str | None = None) -> str:
    """Search for documentation about a framework or library.

    Args:
        query: What you want to learn about (e.g., 'NestJS guards', 'React hooks').
        framework: Optional specific framework (e.g., 'nestjs', 'react', 'typescript').
    """
    try:
        import urllib.request
        import urllib.parse
        import json

        # Use DuckDuckGo instant answers API for quick docs lookup
        search_query = f"{framework} {query}" if framework else query
        encoded = urllib.parse.quote(search_query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1"

        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())

        results = []

        # Abstract (main answer)
        if data.get("Abstract"):
            results.append(f"## Summary\n{data['Abstract']}")
            if data.get("AbstractURL"):
                results.append(f"Source: {data['AbstractURL']}")

        # Related topics
        if data.get("RelatedTopics"):
            results.append("\n## Related")
            for topic in data["RelatedTopics"][:5]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append(f"- {topic['Text'][:200]}")

        if not results:
            return f"[No documentation found for '{search_query}'. Try searching the codebase instead.]"

        return "\n".join(results)

    except Exception as e:
        return f"[Error fetching docs: {type(e).__name__}: {e}]"


def create_execute_shell_tool(project_root: str):
    """Create an execute_shell tool bound to a project root."""
    @tool
    def execute_shell(command: str, cwd: str | None = None) -> str:
        """Execute a shell command.

        Args:
            command: The shell command to execute.
            cwd: Working directory for the command (relative to project root or absolute). Defaults to project root.
        """
        # Default to project_root if cwd not specified
        resolved_cwd = _resolve_path(cwd, project_root) if cwd else project_root
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=resolved_cwd,
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
    return execute_shell


def get_llm() -> ChatOpenAI:
    """Create the LLM instance."""
    return ChatOpenAI(
        model=os.environ.get("DEEPINFRA_MODEL", "deepseek-ai/DeepSeek-V3"),
        api_key=os.environ.get("DEEPINFRA_API_KEY", ""),
        base_url="https://api.deepinfra.com/v1/openai",
        temperature=0.3,
        max_tokens=8192,
    )


def get_impl_tools(project_root: str) -> list:
    """Get tools for the implementation agent, bound to a project root."""
    return [
        create_read_file_tool(project_root),
        create_write_file_tool(project_root),
        create_list_directory_tool(project_root),
        create_search_code_tool(project_root),
        create_find_files_tool(project_root),
        fetch_docs,  # No path resolution needed
        create_execute_shell_tool(project_root),
    ]


def create_impl_agent(project_root: str, checkpointer=None):
    """Create the implementation agent with tools bound to the project root."""
    llm = get_llm()
    tools = get_impl_tools(project_root)

    if checkpointer is None:
        checkpointer = MemorySaver()

    return create_react_agent(
        model=llm,
        tools=tools,
        checkpointer=checkpointer,
    )


def format_task_prompt(task: TaskDefinition, project_root: str, project_context: str = "") -> str:
    """Format the task definition into a prompt."""
    parts = [
        f"# Task {task.number}: {task.name}",
        "",
    ]

    # Add project context if provided
    if project_context:
        parts.append(project_context)

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


# Patterns that indicate the agent is asking for clarification (not polite closings)
QUESTION_PATTERNS = [
    "would you like me to proceed",
    "shall i proceed with",
    "do you want me to implement",
    "should i implement this",
    "which approach would you prefer",
    "do you have a preference for",
    "please confirm if",
    "please clarify",
]

# Patterns that are just polite closings, not actual questions
POLITE_ENDINGS = [
    "let me know if you have any",
    "let me know if you need any",
    "i hope this helps",
    "please review",
    "please let me know",
]


def detect_question(output: str) -> tuple[bool, str | None]:
    """Detect if the agent asked a question and extract it."""
    output_lower = output.lower()

    # Check for polite endings first - these are not real questions
    for ending in POLITE_ENDINGS:
        if ending in output_lower:
            return False, None

    for pattern in QUESTION_PATTERNS:
        if pattern in output_lower:
            # Extract the question context (last few lines before the question)
            lines = output.strip().split('\n')
            question_lines = []
            for line in reversed(lines[-10:]):
                question_lines.insert(0, line)
                if '?' in line or any(p in line.lower() for p in QUESTION_PATTERNS):
                    break
            return True, '\n'.join(question_lines)

    return False, None


async def run_research(question: str, project_root: str) -> str:
    """Run a research agent to answer a question."""
    console.print(f"  [yellow]Researching:[/yellow] {question[:100]}...")

    # Create tools bound to project_root
    research_tools = [
        create_read_file_tool(project_root),
        create_list_directory_tool(project_root),
        create_search_code_tool(project_root),
        create_find_files_tool(project_root),
        fetch_docs,
        create_execute_shell_tool(project_root),
    ]

    agent = create_react_agent(
        model=get_llm(),
        tools=research_tools,
        checkpointer=MemorySaver(),
    )

    messages = [
        SystemMessage(content=RESEARCH_SYSTEM_PROMPT),
        HumanMessage(content=f"""Answer this question about the codebase at {project_root}:

{question}

Search the codebase for relevant patterns, read files, and provide a clear answer."""),
    ]

    config = {"configurable": {"thread_id": "research"}}

    try:
        result = await agent.ainvoke({"messages": messages}, config=config)

        for msg in reversed(result.get("messages", [])):
            if hasattr(msg, "content") and msg.content and not hasattr(msg, "tool_calls"):
                return str(msg.content)

        return "Could not find a clear answer."
    except Exception as e:
        return f"Research failed: {e}"


async def run_implementation(
    task: TaskDefinition,
    project_root: str,
    max_retries: int = 2,
    project_context: str = "",
) -> dict:
    """Run the implementation agent on a task with question handling."""
    agent = create_impl_agent(project_root)

    task_prompt = format_task_prompt(task, project_root, project_context)

    messages = [
        SystemMessage(content=IMPL_SYSTEM_PROMPT),
        HumanMessage(content=task_prompt),
    ]

    config = {"configurable": {"thread_id": f"task-{task.number}"}}
    all_files_modified = []
    all_outputs = []

    for attempt in range(max_retries + 1):
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
                                if file_path not in all_files_modified:
                                    all_files_modified.append(file_path)

            output = "\n\n".join(ai_responses)
            all_outputs.append(output)

            # Also detect files from output (fallback for XML-style tool calls)
            for match in re.finditer(r'\[Successfully wrote to: ([^\]]+)\]', output):
                file_path = match.group(1)
                if file_path not in all_files_modified:
                    all_files_modified.append(file_path)

            # Check if agent asked a question
            asked_question, question = detect_question(output)

            if asked_question and attempt < max_retries:
                console.print(f"  [dim]Task {task.number:03d} asked a question, researching...[/dim]")

                # Run research to answer the question
                research_answer = await run_research(question, project_root)
                console.print(f"  [dim]Research complete, continuing implementation...[/dim]")

                # Continue the conversation with the answer
                messages = result.get("messages", [])
                messages.append(HumanMessage(content=f"""Based on research, here's the answer:

{research_answer}

Please continue and complete the implementation. Do not ask any more questions."""))

                continue  # Retry with the answer

            # Check for success
            has_output = bool(output)
            wrote_files = len(all_files_modified) > 0

            # Only consider fatal errors (write failures, permission issues)
            # Ignore benign errors like file-not-found when reading
            fatal_errors = [
                "[Error: Permission denied",
                "[Error writing file",
                "[Error executing command",
                "Implementation failed:",
            ]
            has_fatal_errors = any(err in output for err in fatal_errors)

            # Success if we wrote files and no fatal errors
            success = has_output and wrote_files and not has_fatal_errors and not asked_question

            return {
                "success": success,
                "files_modified": all_files_modified,
                "output": "\n\n---\n\n".join(all_outputs),
            }

        except Exception as e:
            return {
                "success": False,
                "files_modified": all_files_modified,
                "output": f"Implementation failed: {type(e).__name__}: {e}",
            }

    # Exhausted retries
    return {
        "success": False,
        "files_modified": all_files_modified,
        "output": "\n\n---\n\n".join(all_outputs) + "\n\n[Exhausted retries - agent kept asking questions]",
    }
