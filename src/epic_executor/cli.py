"""Interactive CLI for epic-executor using InquirerPy."""

import asyncio
import sys
from pathlib import Path

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.validator import PathValidator
from rich.console import Console

from .config import Config, is_first_run, get_or_create_config, DEFAULT_CONFIG_DIR, AVAILABLE_MODELS
from .executor import plan_epic, execute_epic, setup_worktree, find_existing_plan
from .planner import parse_epic_info

console = Console()


def first_run_setup() -> Config:
    """Interactive first-run configuration."""
    console.print()
    console.print("[bold blue]Welcome to Epic Executor![/bold blue]")
    console.print()
    console.print("This appears to be your first time running epic-executor.")
    console.print("Let's set up your configuration.")
    console.print()

    # Ask for base directory
    default_dir = str(DEFAULT_CONFIG_DIR)

    base_dir = inquirer.filepath(
        message="Where should epic-executor store its data?",
        default=default_dir,
        validate=PathValidator(is_dir=True, message="Please enter a valid directory"),
        only_directories=True,
    ).execute()

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


def select_epic_folder() -> str | None:
    """Interactive epic folder selection."""
    # First ask for a starting directory
    start_dir = inquirer.filepath(
        message="Select the epic folder:",
        default=str(Path.cwd()),
        validate=PathValidator(is_dir=True, message="Please select a directory"),
        only_directories=True,
    ).execute()

    if not start_dir:
        return None

    # Verify it looks like an epic folder
    epic_path = Path(start_dir)
    task_files = list(epic_path.glob("[0-9]*.md"))

    if not task_files:
        console.print(f"[yellow]Warning:[/yellow] No task files found in {start_dir}")
        proceed = inquirer.confirm(
            message="This doesn't look like an epic folder. Continue anyway?",
            default=False,
        ).execute()

        if not proceed:
            return None

    return start_dir


def select_action() -> str:
    """Select main action."""
    choices = [
        Choice(value="execute", name="Execute epic (plan + run tasks)"),
        Choice(value="plan", name="Generate execution plan only"),
        Choice(value="worktree", name="Set up git worktree only"),
        Choice(value="config", name="Settings (model, API key, etc.)"),
        Choice(value="quit", name="Quit"),
    ]

    return inquirer.select(
        message="What would you like to do?",
        choices=choices,
        default="execute",
    ).execute()


def select_execution_options(epic_path: Path) -> dict:
    """Select execution options."""
    options = {}

    # Check for existing plan
    existing_plan = find_existing_plan(epic_path)
    if existing_plan:
        console.print(f"[green]Found existing plan:[/green] {existing_plan.name}")
        use_existing = inquirer.confirm(
            message="Use existing execution plan?",
            default=True,
        ).execute()
        options["use_existing_plan"] = use_existing

    # Max concurrent agents
    options["max_concurrent"] = inquirer.number(
        message="Maximum concurrent agents:",
        default=4,
        min_allowed=1,
        max_allowed=10,
    ).execute()

    # Create worktree?
    options["create_worktree"] = inquirer.confirm(
        message="Create a git worktree for isolated execution?",
        default=True,
    ).execute()

    # Confirm execution
    options["confirm"] = inquirer.confirm(
        message="Ready to execute. Proceed?",
        default=True,
    ).execute()

    return options


def edit_config(config: Config) -> Config:
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

        action = inquirer.select(
            message="What would you like to change?",
            choices=choices,
            default="back",
        ).execute()

        if action == "back":
            return config

        if action == "model":
            model_choices = [
                Choice(value=model_id, name=f"{description} ({model_id})")
                for model_id, description in AVAILABLE_MODELS
            ]

            new_model = inquirer.select(
                message="Select a model:",
                choices=model_choices,
                default=config.model,
            ).execute()

            config.model = new_model
            config.save()
            console.print(f"[green]✓[/green] Model updated to: {new_model}")

        elif action == "api_key":
            new_key = inquirer.secret(
                message="Enter your DeepInfra API key:",
                validate=lambda x: len(x) > 0 or "API key cannot be empty",
            ).execute()

            if new_key:
                config.api_key = new_key
                config.save()
                console.print("[green]✓[/green] API key saved")

        elif action == "max_concurrent":
            new_max = inquirer.number(
                message="Maximum concurrent agents:",
                default=config.max_concurrent,
                min_allowed=1,
                max_allowed=10,
            ).execute()

            config.max_concurrent = int(new_max)
            config.save()
            console.print(f"[green]✓[/green] Max concurrent updated to: {new_max}")


async def run_interactive() -> int:
    """Run the interactive CLI."""
    # Check for first run
    if is_first_run():
        config = first_run_setup()
    else:
        config = get_or_create_config()
        if config is None:
            config = Config.default()
            config.ensure_dirs()
            config.save()

    while True:
        console.print()
        action = select_action()

        if action == "quit":
            console.print("Goodbye!")
            return 0

        if action == "config":
            config = edit_config(config)
            continue

        # All other actions need an epic folder
        epic_folder = select_epic_folder()
        if not epic_folder:
            continue

        epic_path = Path(epic_folder)
        epic_info = parse_epic_info(epic_path)

        console.print()
        console.print(f"[bold]Epic:[/bold] {epic_info.name}")
        console.print(f"[bold]Source:[/bold] {epic_folder}")
        console.print()

        if action == "plan":
            await plan_epic(epic_folder, Path(config.plans_dir))

        elif action == "worktree":
            await setup_worktree(epic_folder, Path(config.worktree_dir))

        elif action == "execute":
            options = select_execution_options(epic_path)

            if not options.get("confirm", False):
                console.print("[yellow]Execution cancelled.[/yellow]")
                continue

            # Set up worktree if requested
            project_root = epic_folder
            if options.get("create_worktree", False):
                worktree = await setup_worktree(epic_folder, Path(config.worktree_dir))
                project_root = str(worktree.path)
                console.print()

            # Generate plan
            await plan_epic(epic_folder, Path(config.plans_dir))
            console.print()

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
        continue_prompt = inquirer.confirm(
            message="Do another operation?",
            default=False,
        ).execute()

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

        # Set up worktree unless disabled
        project_root = epic_folder
        if not args.no_worktree:
            worktree = await setup_worktree(epic_folder, Path(config.worktree_dir))
            project_root = str(worktree.path)
            console.print()

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
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
