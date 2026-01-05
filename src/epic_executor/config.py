"""Configuration management for epic-executor."""

import json
from pathlib import Path
from dataclasses import dataclass, asdict

DEFAULT_CONFIG_DIR = Path.home() / ".epic-executor"


@dataclass
class Config:
    """Epic executor configuration."""

    base_dir: str
    worktree_dir: str
    plans_dir: str
    default_model: str = "deepseek-ai/DeepSeek-V3"
    max_concurrent: int = 4

    @classmethod
    def default(cls) -> "Config":
        base = DEFAULT_CONFIG_DIR
        return cls(
            base_dir=str(base),
            worktree_dir=str(base / "worktrees"),
            plans_dir=str(base / "plans"),
        )

    def save(self) -> None:
        """Save config to file."""
        config_file = Path(self.base_dir) / "config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "Config | None":
        """Load config from file if it exists."""
        config_file = DEFAULT_CONFIG_DIR / "config.json"
        if not config_file.exists():
            return None
        data = json.loads(config_file.read_text())
        return cls(**data)

    def ensure_dirs(self) -> None:
        """Create all required directories."""
        Path(self.base_dir).mkdir(parents=True, exist_ok=True)
        Path(self.worktree_dir).mkdir(parents=True, exist_ok=True)
        Path(self.plans_dir).mkdir(parents=True, exist_ok=True)


def get_or_create_config() -> Config:
    """Get existing config or return None if first run."""
    return Config.load()


def is_first_run() -> bool:
    """Check if this is the first run (no config exists)."""
    return not (DEFAULT_CONFIG_DIR / "config.json").exists()
