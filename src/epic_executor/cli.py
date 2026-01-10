"""Interactive CLI for epic-executor using InquirerPy."""

import asyncio
import sys
from pathlib import Path

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console

from .config import Config, is_first_run, get_or_create_config, DEFAULT_CONFIG_DIR, AVAILABLE_MODELS
from .executor import plan_epic, execute_epic, setup_worktree, find_existing_plan, check_epic_dependency_graph
from .planner import parse_epic_info, has_existing_dependency_graph

console = Console()


async def first_run_setup() -> Config:
    """Interactive first-run configuration."""
    console.print()
    console.print("[bold blue]Welcome to Epic Executor![/bold blue]")
    console.print()
    console.print("This appears to be your first time running epic-executor.")
    console.print("Let's set up your configuration.")
    console.print()

    # Ask for base directory
    default_dir = str(DEFAULT_CONFIG_DIR)

    base_dir = await inquirer.text(
        message="Where should epic-executor store its data?",
        default=default_dir,
    ).execute_async()

    if not base_dir:
        base_dir = default_dir

    base_path = Path(base_dir)

    config = Config(
        base_dir=str(base_path),
        worktree_dir=str(base_path / "worktrees"),
        plans_dir=str(base_path / "plans"),
    )

    config.ensure_dirs()
    config.save()

    console.print()
    console.print(f"[green]✓[/green] Configuration saved to: {base_path / 'config.json'}")
    console.print(f"[green]✓[/green] Plans will be saved to: {config.plans_dir}")
    console.print(f"[green]✓[/green] Worktrees will be created in: {config.worktree_dir}")
    console.print()

    return config


async def browse_directory(start_path: Path, show_hidden: bool = False) -> Path | None:
    """Interactive directory browser."""
    current = start_path.resolve()

    while True:
        # Build choices: parent, subdirectories, and select current
        choices = []

        # Option to select current directory
        task_files = list(current.glob("[0-9]*.md"))
        if task_files:
            choices.append(Choice(
                value="__SELECT__",
                name=f"✓ Select this folder ({len(task_files)} task files found)"
            ))

        # Parent directory
        if current.parent != current:
            choices.append(Choice(value="__PARENT__", name=".. (parent directory)"))

        # Subdirectories
        try:
            if show_hidden:
                subdirs = sorted([d for d in current.iterdir() if d.is_dir()])
            else:
                subdirs = sorted([d for d in current.iterdir() if d.is_dir() and not d.name.startswith(".")])
            for subdir in subdirs[:25]:  # Limit to 25 to avoid huge lists
                icon = "📁" if not subdir.name.startswith(".") else "📂"
                choices.append(Choice(value=str(subdir), name=f"{icon} {subdir.name}/"))
            if len(subdirs) > 25:
                choices.append(Choice(value="__MORE__", name=f"... and {len(subdirs) - 25} more"))
        except PermissionError:
            pass

        # Toggle hidden files
        if show_hidden:
            choices.append(Choice(value="__HIDE_HIDDEN__", name="👁 Hide hidden folders"))
        else:
            choices.append(Choice(value="__SHOW_HIDDEN__", name="👁 Show hidden folders (.claude, etc.)"))

        # Type path manually
        choices.append(Choice(value="__TYPE__", name="⌨ Type path manually"))

        # Cancel option
        choices.append(Choice(value="__CANCEL__", name="✗ Cancel"))

        console.print(f"\n[dim]Current: {current}[/dim]")

        selection = await inquirer.select(
            message="Navigate to epic folder:",
            choices=choices,
        ).execute_async()

        if selection == "__SELECT__":
            return current
        elif selection == "__PARENT__":
            current = current.parent
        elif selection == "__CANCEL__":
            return None
        elif selection == "__SHOW_HIDDEN__":
            show_hidden = True
        elif selection == "__HIDE_HIDDEN__":
            show_hidden = False
        elif selection in ("__MORE__", "__TYPE__"):
            # Let user type path manually
            typed = await inquirer.text(
                message="Type path:",
                default=str(current),
            ).execute_async()
            if typed:
                typed_path = Path(typed)
                if typed_path.is_dir():
                    current = typed_path.resolve()
        else:
            current = Path(selection)


async def select_epic_folder() -> str | None:
    """Interactive epic folder selection with path autocomplete."""
    console.print("[dim]Type path and press Tab for autocomplete[/dim]")

    epic_path = await inquirer.filepath(
        message="Epic folder path:",
        default=str(Path.cwd()),
        only_directories=True,
    ).execute_async()

    if not epic_path:
        return None

    result = Path(epic_path)

    if not result.exists():
        console.print(f"[red]Error:[/red] Path does not exist: {result}")
        return None

    if not result.is_dir():
        console.print(f"[red]Error:[/red] Not a directory: {result}")
        return None

    # Verify it looks like an epic folder
    task_files = list(result.glob("[0-9]*.md"))

    if not task_files:
        console.print(f"[yellow]Warning:[/yellow] No task files found in {result}")
        proceed = await inquirer.confirm(
            message="This doesn't look like an epic folder. Continue anyway?",
            default=False,
        ).execute_async()

        if not proceed:
            return None

    return str(result)


async def select_action() -> str:
    """Select main action."""
    choices = [
        Choice(value="execute", name="Execute epic (plan + run tasks)"),
        Choice(value="plan", name="Generate execution plan only"),
        Choice(value="worktree", name="Set up git worktree only"),
        Choice(value="config", name="Settings (model, API key, etc.)"),
        Choice(value="quit", name="Quit"),
    ]

    return await inquirer.select(
        message="What would you like to do?",
        choices=choices,
        default="execute",
    ).execute_async()


async def select_execution_options(epic_path: Path, epic_info=None) -> dict:
    """Select execution options."""
    options = {}

    # Check for existing plan
    existing_plan = find_existing_plan(epic_path)
    if existing_plan:
        console.print(f"[green]Found existing plan:[/green] {existing_plan.name}")
        use_existing = await inquirer.confirm(
            message="Use existing execution plan?",
            default=True,
        ).execute_async()
        options["use_existing_plan"] = use_existing

    # Max concurrent agents
    max_concurrent = await inquirer.number(
        message="Maximum concurrent agents:",
        default=4,
        min_allowed=1,
        max_allowed=10,
    ).execute_async()
    options["max_concurrent"] = int(max_concurrent)

    # Check if worktree is already configured (from epic.md or execution-status.json)
    if epic_info and epic_info.worktree_path:
        console.print(f"[green]✓[/green] Using existing worktree: {epic_info.worktree_path}")
        options["create_worktree"] = False
        options["existing_worktree_path"] = epic_info.worktree_path
    else:
        # Create worktree?
        options["create_worktree"] = await inquirer.confirm(
            message="Create a git worktree for isolated execution?",
            default=True,
        ).execute_async()

    # Confirm execution
    options["confirm"] = await inquirer.confirm(
        message="Ready to execute. Proceed?",
        default=True,
    ).execute_async()

    return options


async def edit_config(config: Config) -> Config:
    """View and edit configuration settings."""
    while True:
        console.print()
        console.print("[bold]Current Configuration:[/bold]")
        console.print(f"  Base directory: {config.base_dir}")
        console.print(f"  Worktree directory: {config.worktree_dir}")
        console.print(f"  Plans directory: {config.plans_dir}")
        console.print(f"  Model: {config.model}")
        console.print(f"  Max concurrent: {config.max_concurrent}")
        api_key_display = "****" + config.api_key[-4:] if config.api_key and len(config.api_key) > 4 else ("Set" if config.api_key else "Not set")
        console.print(f"  API key: {api_key_display}")
        console.print()

        choices = [
            Choice(value="model", name="Change model"),
            Choice(value="api_key", name="Set DeepInfra API key"),
            Choice(value="max_concurrent", name="Change max concurrent agents"),
            Choice(value="back", name="Back to main menu"),
        ]

        action = await inquirer.select(
            message="What would you like to change?",
            choices=choices,
            default="back",
        ).execute_async()

        if action == "back":
            return config

        if action == "model":
            model_choices = [
                Choice(value=model_id, name=f"{description} ({model_id})")
                for model_id, description in AVAILABLE_MODELS
            ]

            new_model = await inquirer.select(
                message="Select a model:",
                choices=model_choices,
                default=config.model,
            ).execute_async()

            config.model = new_model
            config.save()
            console.print(f"[green]✓[/green] Model updated to: {new_model}")

        elif action == "api_key":
            new_key = await inquirer.secret(
                message="Enter your DeepInfra API key:",
                validate=lambda x: len(x) > 0 or "API key cannot be empty",
            ).execute_async()

            if new_key:
                config.api_key = new_key
                config.save()
                console.print("[green]✓[/green] API key saved")

        elif action == "max_concurrent":
            new_max_str = await inquirer.number(
                message="Maximum concurrent agents:",
                default=config.max_concurrent,
                min_allowed=1,
                max_allowed=10,
            ).execute_async()

            config.max_concurrent = int(new_max_str)
            config.save()
            console.print(f"[green]✓[/green] Max concurrent updated to: {config.max_concurrent}")


async def run_interactive() -> int:
    """Run the interactive CLI."""
    # Check for first run
    if is_first_run():
        config = await first_run_setup()
    else:
        config = get_or_create_config()
        if config is None:
            config = Config.default()
            config.ensure_dirs()
            config.save()

    while True:
        console.print()
        action = await select_action()

        if action == "quit":
            console.print("Goodbye!")
            return 0

        if action == "config":
            config = await edit_config(config)
            continue

        # All other actions need an epic folder
        epic_folder = await select_epic_folder()
        if not epic_folder:
            continue

        epic_path = Path(epic_folder)
        epic_info = parse_epic_info(epic_path)

        console.print()
        console.print(f"[bold]Epic:[/bold] {epic_info.name}")
        console.print(f"[bold]Source:[/bold] {epic_folder}")

        # Check for existing dependency graph in epic.md
        has_graph, graph_content = check_epic_dependency_graph(epic_path)
        if has_graph:
            console.print("[green]✓[/green] Found dependency graph in epic.md")
            console.print("[dim]Using task file depends_on fields for execution order[/dim]")
        else:
            console.print("[yellow]![/yellow] No dependency graph found in epic.md")
            generate = await inquirer.confirm(
                message="Generate execution plan? (saves to separate file)",
                default=True,
            ).execute_async()
            if generate and action in ("plan", "execute"):
                await plan_epic(epic_folder, Path(config.plans_dir))
                console.print()

        console.print()

        if action == "plan":
            if not has_graph:
                # Already generated above if user confirmed
                pass
            else:
                await plan_epic(epic_folder, Path(config.plans_dir))

        elif action == "worktree":
            await setup_worktree(epic_folder, Path(config.worktree_dir))

        elif action == "execute":
            options = await select_execution_options(epic_path, epic_info)

            if not options.get("confirm", False):
                console.print("[yellow]Execution cancelled.[/yellow]")
                continue

            # Determine project root - use existing worktree or create new one
            if options.get("existing_worktree_path"):
                project_root = options["existing_worktree_path"]
                console.print(f"[bold]Project root:[/bold] {project_root}")
            elif options.get("create_worktree", False):
                worktree = await setup_worktree(epic_folder, Path(config.worktree_dir))
                project_root = str(worktree.path)
                console.print()
            else:
                project_root = str(epic_path.parent.parent.parent)

            # Set environment variables for agents
            config.set_env_vars()

            # Execute
            status = await execute_epic(
                epic_folder,
                project_root,
                max_concurrent=options.get("max_concurrent", 4),
            )

            # Summary
            console.print()
            if status.failed:
                console.print(f"[red]Failed tasks: {sorted(status.failed)}[/red]")
                return 1
            else:
                console.print("[green]All tasks completed successfully![/green]")

        # Ask to continue
        continue_prompt = await inquirer.confirm(
            message="Do another operation?",
            default=False,
        ).execute_async()

        if not continue_prompt:
            console.print("Goodbye!")
            return 0


def run_cli_with_args() -> int:
    """Run CLI with command-line arguments (non-interactive mode)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Execute tasks from epic markdown files in parallel"
    )
    parser.add_argument(
        "epic_folder",
        nargs="?",
        help="Path to the epic folder containing task files",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Generate plan without executing",
    )
    parser.add_argument(
        "--no-worktree",
        action="store_true",
        help="Don't create a git worktree",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=4,
        help="Maximum concurrent agents (default: 4)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Run in interactive mode",
    )

    args = parser.parse_args()

    # Interactive mode if requested or no epic folder provided
    if args.interactive or not args.epic_folder:
        return asyncio.run(run_interactive())

    # Non-interactive mode
    config = get_or_create_config()
    if config is None:
        config = Config.default()
        config.ensure_dirs()
        config.save()

    epic_folder = args.epic_folder

    async def run():
        if args.plan_only:
            await plan_epic(epic_folder, Path(config.plans_dir))
            return 0

        epic_path = Path(epic_folder)
        epic_info = parse_epic_info(epic_path)

        # Determine project root - use existing worktree if available
        if epic_info.worktree_path:
            project_root = epic_info.worktree_path
            console.print(f"[green]✓[/green] Using existing worktree: {project_root}")
        elif not args.no_worktree:
            worktree = await setup_worktree(epic_folder, Path(config.worktree_dir))
            project_root = str(worktree.path)
            console.print()
        else:
            project_root = str(epic_path.parent.parent.parent)

        # Set environment variables for agents
        config.set_env_vars()

        # Generate plan
        await plan_epic(epic_folder, Path(config.plans_dir))
        console.print()

        # Execute
        status = await execute_epic(
            epic_folder,
            project_root,
            max_concurrent=args.max_concurrent,
        )

        return 1 if status.failed else 0

    return asyncio.run(run())


def main():
    """Main entry point."""
    try:
        sys.exit(run_cli_with_args())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)
    except Exception as e:
        import traceback
        console.print(f"[red]Error:[/red] {e}")
        console.print("[dim]" + traceback.format_exc() + "[/dim]")
        sys.exit(1)


if __name__ == "__main__":
    main()
