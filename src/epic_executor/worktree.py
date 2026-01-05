"""Git worktree management for epic execution."""

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorktreeInfo:
    """Information about a git worktree."""

    path: Path
    branch: str
    commit: str
    is_new: bool


def get_repo_root(path: Path) -> Path | None:
    """Find the git repository root from a path."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return None


def branch_exists(repo_root: Path, branch_name: str) -> bool:
    """Check if a branch exists (local or remote)."""
    result = subprocess.run(
        ["git", "branch", "-a", "--list", branch_name, f"*/{branch_name}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def get_current_branch(repo_root: Path) -> str:
    """Get the current branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_worktree_list(repo_root: Path) -> list[tuple[Path, str]]:
    """List existing worktrees."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    worktrees = []
    current_path = None

    for line in result.stdout.split("\n"):
        if line.startswith("worktree "):
            current_path = Path(line[9:])
        elif line.startswith("branch "):
            branch = line[7:].replace("refs/heads/", "")
            if current_path:
                worktrees.append((current_path, branch))
            current_path = None

    return worktrees


def get_head_commit(worktree_path: Path) -> str:
    """Get the HEAD commit hash for a worktree."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()[:8]


def create_worktree(
    epic_source_path: Path,
    branch_name: str,
    worktree_base: Path,
) -> WorktreeInfo:
    """Create a git worktree for the epic."""
    # Find repository root from epic path
    repo_root = get_repo_root(epic_source_path)
    if repo_root is None:
        for parent in epic_source_path.parents:
            repo_root = get_repo_root(parent)
            if repo_root:
                break

    if repo_root is None:
        raise ValueError(f"Could not find git repository for {epic_source_path}")

    worktree_base.mkdir(parents=True, exist_ok=True)

    safe_name = branch_name.replace("feature/", "").replace("/", "-")
    worktree_path = worktree_base / safe_name

    # Check if worktree already exists
    existing = get_worktree_list(repo_root)
    for path, branch in existing:
        if path == worktree_path:
            return WorktreeInfo(
                path=worktree_path,
                branch=branch,
                commit=get_head_commit(worktree_path),
                is_new=False,
            )

    is_new_branch = not branch_exists(repo_root, branch_name)

    if is_new_branch:
        subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, str(worktree_path)],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    else:
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), branch_name],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )

    return WorktreeInfo(
        path=worktree_path,
        branch=branch_name,
        commit=get_head_commit(worktree_path),
        is_new=True,
    )


def remove_worktree(worktree_path: Path, force: bool = False) -> bool:
    """Remove a worktree."""
    if not worktree_path.exists():
        return False

    cmd = ["git", "worktree", "remove", str(worktree_path)]
    if force:
        cmd.append("--force")

    try:
        subprocess.run(cmd, cwd=worktree_path.parent, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False


def commit_changes(
    worktree_path: Path,
    message: str,
    files: list[str] | None = None,
) -> str | None:
    """Commit changes in a worktree."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )

    if not result.stdout.strip():
        return None

    if files:
        subprocess.run(
            ["git", "add"] + files,
            cwd=worktree_path,
            check=True,
            capture_output=True,
        )
    else:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=worktree_path,
            check=True,
            capture_output=True,
        )

    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=worktree_path,
        check=True,
        capture_output=True,
    )

    return get_head_commit(worktree_path)


def push_branch(worktree_path: Path, set_upstream: bool = True) -> bool:
    """Push the branch to remote."""
    branch = get_current_branch(worktree_path)

    cmd = ["git", "push"]
    if set_upstream:
        cmd.extend(["-u", "origin", branch])

    try:
        subprocess.run(cmd, cwd=worktree_path, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False
