"""Parse epic and task markdown files."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TaskDefinition:
    """Represents a parsed task from a markdown file."""

    task_number: int
    name: str
    title: str | None = None
    status: str = "open"
    deliverables: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    files_to_create: list[str] = field(default_factory=list)
    files_to_modify: list[str] = field(default_factory=list)
    dependencies: list[int] = field(default_factory=list)
    frontmatter: dict = field(default_factory=dict)
    full_content: str = ""  # Complete task markdown for detailed instructions

    @property
    def number(self) -> int:
        return self.task_number


def parse_task_file(path: Path) -> TaskDefinition:
    """Parse a single task markdown file."""
    content = path.read_text()

    task_number = int(path.stem)

    frontmatter = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            body = parts[2]

    name = frontmatter.get("name", "")
    title = frontmatter.get("title")
    status = frontmatter.get("status", "open")

    deliverables = extract_section(body, "Deliverables")
    acceptance_criteria = extract_checklist(body, "Acceptance Criteria")
    files_to_create = extract_file_list(body, "Files to Create")
    files_to_modify = extract_file_list(body, "Files to Modify")
    dependencies = extract_dependencies(frontmatter, task_number)

    return TaskDefinition(
        task_number=task_number,
        name=name,
        title=title,
        status=status,
        deliverables=deliverables,
        acceptance_criteria=acceptance_criteria,
        files_to_create=files_to_create,
        files_to_modify=files_to_modify,
        dependencies=dependencies,
        frontmatter=frontmatter,
        full_content=body.strip(),  # Pass complete task content to LLM
    )


def extract_section(body: str, section_name: str) -> str:
    """Extract content from a markdown section."""
    pattern = rf"^##\s+{re.escape(section_name)}\s*\n(.*?)(?=^##\s|\Z)"
    match = re.search(pattern, body, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_checklist(body: str, section_name: str) -> list[str]:
    """Extract checklist items from a section."""
    section = extract_section(body, section_name)
    items = []
    for line in section.split("\n"):
        match = re.match(r"^\s*-\s*\[[ xX]\]\s*(.+)$", line)
        if match:
            items.append(match.group(1).strip())
    return items


def extract_file_list(body: str, section_name: str) -> list[str]:
    """Extract file paths from a section."""
    section = extract_section(body, section_name)
    files = []
    for line in section.split("\n"):
        match = re.match(r"^\s*-\s*`?([^`\n]+)`?\s*$", line)
        if match:
            files.append(match.group(1).strip())
    return files


def _to_int(value) -> int | None:
    """Try to convert a value to int."""
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def extract_dependencies(frontmatter: dict, self_task_num: int) -> list[int]:
    """Extract dependencies from frontmatter depends_on field only."""
    deps: set[int] = set()

    if "depends_on" in frontmatter:
        depends_on = frontmatter["depends_on"]
        # Handle single value or list
        if not isinstance(depends_on, list):
            depends_on = [depends_on]
        for d in depends_on:
            val = _to_int(d)
            if val is not None:
                deps.add(val)

    deps.discard(self_task_num)
    return sorted(deps)


def parse_epic_folder(path: str) -> list[TaskDefinition]:
    """Parse all task files in an epic folder."""
    folder = Path(path)
    tasks = []

    for md_file in folder.glob("[0-9]*.md"):
        if md_file.stem.isdigit():
            tasks.append(parse_task_file(md_file))

    return sorted(tasks, key=lambda t: t.task_number)
