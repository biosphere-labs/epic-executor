"""Configuration management for epic-executor."""

import json
import os
from pathlib import Path
from dataclasses import dataclass, asdict, field

DEFAULT_CONFIG_DIR = Path.home() / ".epic-executor"

# DeepInfra models well-suited for code generation
AVAILABLE_MODELS = [
    ("deepseek-ai/DeepSeek-V3", "DeepSeek V3 - Best for complex coding"),
    ("deepseek-ai/DeepSeek-R1", "DeepSeek R1 - Reasoning model"),
    ("Qwen/Qwen2.5-Coder-32B-Instruct", "Qwen 2.5 Coder 32B - Code specialist"),
    ("Qwen/Qwen2.5-72B-Instruct", "Qwen 2.5 72B - General + code"),
    ("meta-llama/Llama-3.3-70B-Instruct-Turbo", "Llama 3.3 70B Turbo - Fast"),
    ("mistralai/Mixtral-8x22B-Instruct-v0.1", "Mixtral 8x22B - Efficient"),
]


@dataclass
class Config:
    """Epic executor configuration."""

    base_dir: str
    worktree_dir: str
    plans_dir: str
    model: str = "deepseek-ai/DeepSeek-V3"
    max_concurrent: int = 4
    api_key: str = ""  # Stored encrypted or use env var

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
        # Don't save api_key to file if it's from env
        data = asdict(self)
        if self.api_key == os.environ.get("DEEPINFRA_API_KEY", ""):
            data["api_key"] = ""  # Don't persist env var
        config_file.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls) -> "Config | None":
        """Load config from file if it exists."""
        config_file = DEFAULT_CONFIG_DIR / "config.json"
        if not config_file.exists():
            return None
        data = json.loads(config_file.read_text())
        config = cls(**data)
        # Use env var if no stored key
        if not config.api_key:
            config.api_key = os.environ.get("DEEPINFRA_API_KEY", "")
        return config

    def ensure_dirs(self) -> None:
        """Create all required directories."""
        Path(self.base_dir).mkdir(parents=True, exist_ok=True)
        Path(self.worktree_dir).mkdir(parents=True, exist_ok=True)
        Path(self.plans_dir).mkdir(parents=True, exist_ok=True)

    def get_api_key(self) -> str:
        """Get API key from config or environment."""
        return self.api_key or os.environ.get("DEEPINFRA_API_KEY", "")

    def set_env_vars(self) -> None:
        """Set environment variables for the agents."""
        api_key = self.get_api_key()
        if api_key:
            os.environ["DEEPINFRA_API_KEY"] = api_key
        os.environ["DEEPINFRA_MODEL"] = self.model


def get_or_create_config() -> Config:
    """Get existing config or return None if first run."""
    return Config.load()


def is_first_run() -> bool:
    """Check if this is the first run (no config exists)."""
    return not (DEFAULT_CONFIG_DIR / "config.json").exists()
