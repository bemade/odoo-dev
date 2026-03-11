"""Setup commands for initializing Odoo development environment."""

import importlib.resources
import os
import shutil
import subprocess
from pathlib import Path

import typer

from odoo_dev.config import (
    DEFAULT_ODOO_VERSION,
    DEFAULT_PYTHON_VERSION,
    find_project_root,
    load_config,
    load_dotenv,
)
from odoo_dev.utils.console import info, success, warning


def _prompt_for_versions() -> None:
    """Prompt for ODOO_VERSION and PYTHON_VERSION if not set.

    Checks environment and .env file. If not found, prompts interactively
    and optionally saves to .env.
    """
    project_dir = find_project_root()
    env_file = project_dir / ".env"

    # Load existing .env
    load_dotenv(env_file)

    odoo_version = os.getenv("ODOO_VERSION")
    python_version = os.getenv("PYTHON_VERSION")

    updates = {}

    if not odoo_version:
        odoo_version = typer.prompt(
            "Odoo version",
            default=DEFAULT_ODOO_VERSION,
        )
        os.environ["ODOO_VERSION"] = odoo_version
        updates["ODOO_VERSION"] = odoo_version

    if not python_version:
        python_version = typer.prompt(
            "Python version",
            default=DEFAULT_PYTHON_VERSION,
        )
        os.environ["PYTHON_VERSION"] = python_version
        updates["PYTHON_VERSION"] = python_version

    # Offer to save to .env if we prompted for anything
    if updates:
        if typer.confirm("Save these settings to .env?", default=True):
            _update_env_file(env_file, updates)
            success(f"Settings saved to {env_file}")


def _update_env_file(env_file: Path, updates: dict[str, str]) -> None:
    """Update or create .env file with new values."""
    existing = {}

    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                existing[key.strip()] = value.strip()

    # Merge updates
    existing.update(updates)

    # Write back
    content = "\n".join(f"{k}={v}" for k, v in sorted(existing.items()))
    env_file.write_text(content + "\n")


def _clean():
    cfg = load_config()
    success("Cleaning up current environment...")
    for name in ["odoo", "enterprise", "design-themes", "industry", ".venv"]:
        path = cfg.project_dir / name
        if path.exists():
            shutil.rmtree(path)
    success("Clean up complete.")


def setup(
    community: bool = typer.Option(
        False,
        "--community",
        help="Set up Community edition only (skip Enterprise repos)",
    ),
    clean: bool = typer.Option(
        False,
        "--clean",
        help="Clean up before setup (remove existing venv, etc.)",
    ),
) -> None:
    """Complete setup: clone Odoo repos, configure VSCode, build image."""
    # Prompt for versions if not configured
    _prompt_for_versions()

    cfg = load_config()

    if clean:
        _clean()
    success("Setting up complete Odoo development environment...")

    # Initialize/update git submodules first
    _init_submodules(cfg)

    # Clone/update Odoo repositories
    if community:
        warning("Setting up Community Edition")
    _clone_odoo_repos(cfg, community_only=community)

    # Set up VSCode configuration
    success("\nSetting up VSCode configuration...")
    vscode(cfg)

    # Set up local virtual environment
    success("\nSetting up local Python virtual environment...")
    warning(
        f"This will install system dependencies and Python {cfg.python_version} if needed"
    )
    setup_venv()

    # Prompt for Docker setup
    warning("\nDo you want to set up the Docker environment?")
    if typer.confirm("Continue with Docker setup?", default=True):
        # Set up Docker files first
        _setup_docker_files(cfg, community_only=community)

        success("\nBuilding Docker image...")
        from odoo_dev.commands.docker import build

        build(community=community)
    else:
        warning("Skipping Docker setup. Run 'odoo-dev build' later.")

    success("\nSetup complete! You can now:")
    success("  - Start Odoo with Docker: odoo-dev start")
    success("  - Use local Python environment: source .venv/bin/activate")
    success("  - Debug with VSCode: Use the configured launch profiles")


def setup_venv() -> None:
    """Set up local Python virtual environment for development."""
    cfg = load_config()

    # Initialize submodules before anything else
    _init_submodules(cfg)

    # Create config file first
    _setup_odoo_config(cfg)

    success(f"Setting up Python virtual environment for Odoo {cfg.odoo_version}...")

    # Install system dependencies
    _install_system_dependencies()

    # Ensure uv is available
    if subprocess.run(["which", "uv"], capture_output=True).returncode != 0:
        success("Installing uv package manager...")
        subprocess.run(
            ["curl", "-LsSf", "https://astral.sh/uv/install.sh"],
            stdout=subprocess.PIPE,
        )
        # Would pipe to sh, but let's be explicit
        warning(
            "Please install uv manually: curl -LsSf https://astral.sh/uv/install.sh | sh"
        )

    # Create virtual environment
    if not cfg.venv_path.exists():
        success("Creating new Python virtual environment...")
        subprocess.run(
            ["uv", "venv", str(cfg.venv_path), "--python", cfg.python_version],
            check=True,
        )
    else:
        warning("Virtual environment already exists. Skipping creation.")

    # Update PYTHONPATH in activate script
    _update_python_path(cfg)

    # Install requirements
    venv_pip = [
        "uv",
        "pip",
        "install",
        "--python",
        str(cfg.venv_path / "bin" / "python"),
    ]

    # Install Odoo requirements
    odoo_requirements = cfg.project_dir / "odoo" / "requirements.txt"
    if odoo_requirements.exists():
        success("Installing Odoo requirements...")
        # Create temp requirements with psycopg2-binary substitution
        temp_req = cfg.project_dir / "temp_requirements.txt"
        content = odoo_requirements.read_text()
        content = content.replace("psycopg2==", "psycopg2-binary>=")
        temp_req.write_text(content)
        subprocess.run([*venv_pip, "-r", str(temp_req)])
        temp_req.unlink()

    # Install project requirements
    project_requirements = cfg.project_dir / "requirements.txt"
    if project_requirements.exists():
        success("Installing project requirements...")
        subprocess.run([*venv_pip, "-r", str(project_requirements)])

    # Install dev tools
    success("Installing development tools...")
    subprocess.run(
        [*venv_pip, "pytest", "pytest-odoo", "debugpy", "manifestoo", "coverage"]
    )

    success("\nVirtual environment setup complete!")
    success(f"To activate: source {cfg.venv_path}/bin/activate")


def vscode(cfg=None) -> None:
    """Set up VSCode configuration for debugging."""
    if cfg is None:
        cfg = load_config()

    vscode_dir = cfg.project_dir / ".vscode"
    vscode_dir.mkdir(exist_ok=True)

    # Get the templates directory from the package
    templates = importlib.resources.files("odoo_dev.templates.vscode")

    # Copy template files
    for template_file in ["launch.json", "tasks.json"]:
        template_content = templates.joinpath(template_file).read_text()
        dst = vscode_dir / template_file
        dst.write_text(template_content)
        success(f"Copied {template_file}")

    # Only copy settings.json if it doesn't exist
    settings_dst = vscode_dir / "settings.json"
    if not settings_dst.exists():
        settings_content = templates.joinpath("settings.json").read_text()
        settings_dst.write_text(settings_content)
        success("Copied settings.json")
    else:
        warning("settings.json already exists. Skipping.")

    success("VSCode configuration set up successfully!")


def _init_submodules(cfg) -> None:
    """Initialize and update git submodules if present."""
    gitmodules = cfg.project_dir / ".gitmodules"

    if not gitmodules.exists():
        return

    success("Initializing git submodules...")

    result = subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive"],
        cwd=cfg.project_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        success("Git submodules initialized.")
    else:
        warning(f"Submodule initialization had issues: {result.stderr}")


def _setup_odoo_config(cfg, community_only: bool = False) -> None:
    """Create odoo.conf configuration file."""
    conf_dir = cfg.project_dir / "conf"
    conf_file = conf_dir / "odoo.conf"

    # Create conf directory
    conf_dir.mkdir(exist_ok=True)

    if conf_file.exists():
        warning(f"Config file already exists at {conf_file}")
        return

    success("Creating Odoo configuration file...")

    # Build addons path
    addons_paths = [
        str(cfg.project_dir / "odoo" / "addons"),
        str(cfg.project_dir / "odoo" / "odoo" / "addons"),
    ]

    if not community_only:
        addons_paths.append(str(cfg.project_dir / "enterprise"))

    addons_paths.extend(
        [
            str(cfg.project_dir / "design-themes"),
            str(cfg.project_dir / "addons"),
        ]
    )

    # Filter to only existing paths
    addons_paths = [p for p in addons_paths if Path(p).exists()]

    config_content = f"""[options]
addons_path = {",".join(addons_paths)}
admin_passwd = admin
db_user = odoo
db_password = odoo
"""

    conf_file.write_text(config_content)
    conf_file.chmod(0o600)
    success(f"Config file created at {conf_file}")


def _setup_docker_files(cfg, community_only: bool = False) -> None:
    """Copy Docker templates to .odoo-deploy directory."""
    success("Setting up Docker files...")

    # Create .odoo-deploy directory
    cfg.script_dir.mkdir(exist_ok=True)

    # Get the templates directory from the package
    templates = importlib.resources.files("odoo_dev.templates.docker")

    # Copy Dockerfile and docker-entrypoint.sh
    for filename in ["Dockerfile", "docker-entrypoint.sh"]:
        template_content = templates.joinpath(filename).read_text()
        dest = cfg.script_dir / filename
        dest.write_text(template_content)
        if filename.endswith(".sh"):
            dest.chmod(0o755)
        success(f"Copied {filename}")

    # Create Docker odoo.conf
    _setup_docker_odoo_config(cfg, community_only=community_only)


def _generate_docker_odoo_conf(community_only: bool = False) -> str:
    """Generate Docker-specific odoo.conf content."""
    # Build addons path for Docker (using /opt/project paths)
    addons_paths = [
        "/opt/project/odoo/addons",
        "/opt/project/odoo/odoo/addons",
    ]

    if not community_only:
        addons_paths.append("/opt/project/enterprise")

    addons_paths.extend(
        [
            "/opt/project/design-themes",
            "/opt/project/industry",
            "/opt/project/addons",
        ]
    )

    return f"""[options]
addons_path = {",".join(addons_paths)}
admin_passwd = admin
db_host = db
db_port = 5432
db_user = odoo
db_password = odoo
http_port = 8069
gevent_port = 8072
proxy_mode = True
dev_mode = True
log_level = info
list_db = True
limit_memory_hard = 0
limit_memory_soft = 2147483648
limit_time_cpu = 600
limit_time_real = 1200
workers = 0
max_cron_threads = 1
data_dir = /opt/odoo-filestore
"""


def _setup_docker_odoo_config(cfg, community_only: bool = False) -> None:
    """Create Docker-specific odoo.conf configuration file."""
    conf_file = cfg.docker_config_file

    if conf_file.exists():
        warning(f"Docker config file already exists at {conf_file}")
        return

    success("Creating Docker Odoo configuration file...")
    conf_file.write_text(_generate_docker_odoo_conf(community_only=community_only))
    conf_file.chmod(0o600)
    success(f"Docker config file created at {conf_file}")


def _clone_odoo_repos(cfg, community_only: bool = False) -> None:
    """Clone or update Odoo repositories."""
    success("Setting up Odoo repositories...")

    if community_only:
        warning("Community edition mode: Enterprise repositories will be skipped")

    # Use HTTPS for odoo (public), SSH for all others (private)
    repos = [
        ("https://github.com/odoo/odoo.git", "odoo", cfg.odoo_version),
    ]

    # Private repos require SSH
    repos.append(
        ("git@github.com:odoo/design-themes.git", "design-themes", cfg.odoo_version)
    )

    # Add enterprise if not community only (private repo, needs SSH)
    if not community_only:
        repos.append(
            ("git@github.com:odoo/enterprise.git", "enterprise", cfg.odoo_version)
        )

    # Add industry for Odoo 18+ (private repo)
    if cfg.odoo_version.startswith("18") or cfg.odoo_version.startswith("19"):
        repos.append(("git@github.com:odoo/industry.git", "industry", cfg.odoo_version))

    for repo_url, repo_dir, branch in repos:
        repo_path = cfg.project_dir / repo_dir

        if repo_path.exists():
            warning(f"Updating {repo_dir} repository...")
            subprocess.run(
                ["git", "fetch", "--depth", "1", "origin", branch],
                cwd=repo_path,
            )
            subprocess.run(["git", "checkout", branch], cwd=repo_path)
            subprocess.run(
                ["git", "pull", "--ff-only", "origin", branch],
                cwd=repo_path,
            )
        else:
            warning(f"Cloning {repo_dir} repository...")
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    branch,
                    repo_url,
                    str(repo_path),
                ],
                cwd=cfg.project_dir,
            )

    success("Odoo repositories setup complete.")


def _can_sudo_without_password() -> bool:
    """Check if sudo can run without prompting for password."""
    result = subprocess.run(
        ["sudo", "-n", "true"],
        capture_output=True,
    )
    return result.returncode == 0


def _install_system_dependencies() -> None:
    """Install system dependencies based on OS."""
    import platform

    system = platform.system()

    if system == "Darwin":
        success("Installing dependencies for macOS...")
        subprocess.run(
            [
                "brew",
                "install",
                "postgresql",
                "libpq",
                "openssl",
                "libxml2",
                "libxslt",
            ],
            check=False,
        )
    elif system == "Linux":
        if not _can_sudo_without_password():
            warning(
                "Cannot run sudo without password. "
                "Please install system dependencies manually or run with sudo."
            )
            return

        success("Installing dependencies for Linux...")
        subprocess.run(
            [
                "sudo",
                "apt-get",
                "update",
            ],
            check=False,
        )
        subprocess.run(
            [
                "sudo",
                "apt-get",
                "install",
                "-y",
                "--no-install-recommends",
                "build-essential",
                "libldap2-dev",
                "libpq-dev",
                "libsasl2-dev",
                "libssl-dev",
                "libxml2-dev",
                "libxslt1-dev",
                "postgresql-client",
            ],
            check=False,
        )
    else:
        warning(f"Unsupported OS: {system}. Please install dependencies manually.")


def _update_python_path(cfg) -> None:
    """Update PYTHONPATH in venv activate script."""
    activate_script = cfg.venv_path / "bin" / "activate"

    if not activate_script.exists():
        return

    content = activate_script.read_text()

    # Check if already modified
    if "# Odoo PYTHONPATH setup" in content:
        return

    pythonpath_setup = """
# Odoo PYTHONPATH setup
if [ -z "$_OLD_VIRTUAL_PYTHONPATH" ]; then
    _OLD_VIRTUAL_PYTHONPATH="$PYTHONPATH"
fi

ODOO_PYTHONPATH=""
for dir in "odoo" "enterprise" "design-themes" "industry" "addons"; do
    if [ -d "$VIRTUAL_ENV/../$dir" ]; then
        if [ -z "$ODOO_PYTHONPATH" ]; then
            ODOO_PYTHONPATH="$VIRTUAL_ENV/../$dir"
        else
            ODOO_PYTHONPATH="$ODOO_PYTHONPATH:$VIRTUAL_ENV/../$dir"
        fi
    fi
done

if [ -n "$ODOO_PYTHONPATH" ]; then
    PYTHONPATH="$ODOO_PYTHONPATH${_OLD_VIRTUAL_PYTHONPATH:+:$_OLD_VIRTUAL_PYTHONPATH}"
    export PYTHONPATH
fi
# End Odoo PYTHONPATH setup
"""

    content += pythonpath_setup
    activate_script.write_text(content)
    success("PYTHONPATH updated in virtual environment activation script.")
