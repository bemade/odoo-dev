"""Configuration loading and project detection."""

import os
from dataclasses import dataclass
from pathlib import Path

# Default versions
DEFAULT_ODOO_VERSION = "19.0"
DEFAULT_PYTHON_VERSION = "3.12"


@dataclass
class ProjectConfig:
    """Configuration for an Odoo development project."""

    project_dir: Path
    script_dir: Path
    odoo_version: str
    python_version: str
    project_name: str

    @property
    def venv_path(self) -> Path:
        """Path to the Python virtual environment."""
        return self.project_dir / ".venv"

    @property
    def config_file(self) -> Path:
        """Path to the local odoo.conf file."""
        return self.project_dir / "conf" / "odoo.conf"

    @property
    def docker_config_file(self) -> Path:
        """Path to the Docker odoo.conf file."""
        return self.script_dir / "odoo.conf"

    @property
    def odoo_bin(self) -> Path:
        """Path to the odoo-bin executable."""
        return self.project_dir / "odoo" / "odoo-bin"

    @property
    def addons_dir(self) -> Path:
        """Path to the project's custom addons directory."""
        return self.project_dir / "addons"


def find_project_root(start: Path | None = None) -> Path:
    """Walk up directory tree to find git repository root.

    Args:
        start: Starting directory. Defaults to current working directory.

    Returns:
        Path to the git repository root, or current directory if not found.
    """
    current = start or Path.cwd()
    while current != current.parent:
        git_path = current / ".git"
        # .git can be a directory (normal repo) or a file (submodule/worktree)
        if git_path.is_dir() or git_path.is_file():
            return current
        current = current.parent
    return Path.cwd()


def load_dotenv(path: Path) -> None:
    """Load environment variables from a .env file.

    Args:
        path: Path to the .env file.
    """
    if not path.exists():
        return

    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            # Don't override existing environment variables
            os.environ.setdefault(key.strip(), value.strip())


def load_config(project_dir: Path | None = None) -> ProjectConfig:
    """Load configuration from environment and .env file.

    Args:
        project_dir: Optional project directory override.

    Returns:
        ProjectConfig with all settings loaded.
    """
    if project_dir is None:
        project_dir = find_project_root()

    # Load .env if it exists
    load_dotenv(project_dir / ".env")

    return ProjectConfig(
        project_dir=project_dir,
        script_dir=project_dir / ".odoo-deploy",
        odoo_version=os.getenv("ODOO_VERSION", DEFAULT_ODOO_VERSION),
        python_version=os.getenv("PYTHON_VERSION", DEFAULT_PYTHON_VERSION),
        project_name=project_dir.name,
    )
