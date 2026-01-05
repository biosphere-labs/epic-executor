# Epic Executor

Execute tasks from epic/task markdown files in parallel using AI agents.

## Features

- **Parallel execution**: Runs independent tasks concurrently based on dependency graph
- **Git worktree integration**: Creates isolated worktrees for safe parallel work
- **Interactive CLI**: File browser, menus, and prompts powered by InquirerPy
- **Existing plan detection**: Reuses `parallel-analysis.md` or `execution-status.md` if present
- **Verification**: Checks acceptance criteria and runs tests after implementation

## Installation

```bash
# With pipx (recommended)
pipx install epic-executor

# With uv
uv tool install epic-executor

# From source
pip install -e .
```

## Usage

### Interactive Mode

```bash
epic-executor
```

This launches an interactive session where you can:
- Browse and select an epic folder
- Generate execution plans
- Set up git worktrees
- Execute tasks with progress tracking

### Command Line

```bash
# Execute an epic
epic-executor /path/to/epic

# Plan only (no execution)
epic-executor /path/to/epic --plan-only

# Without git worktree
epic-executor /path/to/epic --no-worktree

# Control parallelism
epic-executor /path/to/epic --max-concurrent 6
```

## Epic Format

An epic folder should contain:
- Numbered task files: `001.md`, `002.md`, etc.
- Optional `epic.md` with name and description
- Optional existing plan: `parallel-analysis.md` or `execution-status.md`

### Task File Format

```markdown
---
name: Implement Feature X
status: open
depends_on: [1, 2]
---

# Task: Implement Feature X

## Deliverables
- Create the feature module
- Add unit tests

## Acceptance Criteria
- [ ] Module handles edge cases
- [ ] Tests pass

## Files to Create
- `src/feature_x.py`

## Files to Modify
- `src/main.py`
```

## Configuration

On first run, epic-executor creates `~/.epic-executor/` with:
- `config.json` - Settings
- `plans/` - Generated execution plans
- `worktrees/` - Git worktrees for isolated execution

## Requirements

- Python 3.10+
- Git (for worktree features)
- [DeepInfra API key](https://deepinfra.com/) - Set `DEEPINFRA_API_KEY` environment variable

## License

MIT
