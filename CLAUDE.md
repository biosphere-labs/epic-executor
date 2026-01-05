# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Development Commands

```bash
# Install in development mode
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"

# Run the CLI
epic-executor                      # Interactive mode
epic-executor /path/to/epic        # Direct execution
epic-executor /path/to/epic --plan-only

# Run tests
pytest
pytest -v --tb=short

# Lint
ruff check src/
ruff format src/
```

## Architecture Overview

Epic Executor is a parallel task execution tool that reads task definitions from markdown files and executes them using AI agents (LangGraph/LangChain with DeepInfra).

### Core Flow

```
cli.py → executor.py → parser.py + scheduler.py + pool.py
                              ↓
                    impl_agent.py + verify_agent.py
```

1. **CLI** (`cli.py`): Interactive InquirerPy menus or argparse CLI. Handles first-run setup and config editing.

2. **Executor** (`executor.py`): Main orchestrator. Calls `plan_epic()` to generate execution plan, optionally sets up git worktree, then calls `execute_epic()` to run tasks through the pool.

3. **Parser** (`parser.py`): Parses numbered markdown files (001.md, 002.md) with YAML frontmatter. Extracts `TaskDefinition` dataclasses with dependencies, acceptance criteria, and file lists.

4. **Scheduler** (`scheduler.py`): Builds dependency graph and creates `ExecutionPlan` using Kahn's algorithm for topological sort. Groups tasks into parallel levels.

5. **Pool** (`pool.py`): Async task pool with semaphore-controlled concurrency. Calls impl_fn then verify_fn for each task, tracking completed/failed/in_progress.

6. **Implementation Agent** (`impl_agent.py`): LangGraph ReAct agent with file/shell tools. Uses DeepInfra API (OpenAI-compatible). System prompt guides methodical implementation.

7. **Verification Agent** (`verify_agent.py`): LangGraph StateGraph that checks file existence, runs language-appropriate tests (pytest/npm test), and validates acceptance criteria.

8. **Worktree** (`worktree.py`): Git worktree management for isolated parallel execution. Creates feature branches from epic names.

### Data Flow

- Epic folder contains numbered `.md` files with YAML frontmatter (`depends_on`, `status`, `name`)
- `parse_epic_folder()` returns sorted `list[TaskDefinition]`
- `create_execution_plan()` returns `ExecutionPlan` with levels (parallel task groups)
- `run_pool()` executes tasks respecting dependencies, returns `PoolStatus`

### Configuration

Stored in `~/.epic-executor/config.json`:
- Model selection (DeepSeek, Qwen, Llama via DeepInfra)
- API key (or via `DEEPINFRA_API_KEY` env var)
- Worktree and plans directories

### Task File Format

```markdown
---
name: Task Name
status: open
depends_on: [1, 2]
---

## Deliverables
...

## Acceptance Criteria
- [ ] Criterion 1

## Files to Create
- `path/to/file.py`

## Files to Modify
- `existing/file.py`
```
