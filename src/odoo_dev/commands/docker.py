"""Docker container management commands (optional)."""

import subprocess

import typer

from odoo_dev.config import load_config
from odoo_dev.utils.console import error, success

app = typer.Typer(help="Docker container management (optional)")


@app.command()
def start() -> None:
    """Start Odoo and PostgreSQL containers."""
    cfg = load_config()
    success(f"Starting Odoo ({cfg.odoo_version}) with Python {cfg.python_version}...")

    # Check if odoo.conf exists
    if not cfg.docker_config_file.exists():
        error(f"Config file not found at {cfg.docker_config_file}")
        error("Run 'odoo-dev setup' first to create the configuration.")
        raise typer.Exit(1)

    result = subprocess.run(
        ["docker", "compose", "--project-name", cfg.project_name, "up", "-d"],
        cwd=cfg.script_dir,
    )
    if result.returncode != 0:
        error("Failed to start containers. Check the logs for more information.")
        raise typer.Exit(1)

    success("Odoo is starting up...")
    success("Web interface: http://localhost:8069")
    success("Debug port: localhost:5678")


@app.command()
def stop() -> None:
    """Stop all containers."""
    cfg = load_config()
    success("Stopping containers...")
    subprocess.run(
        ["docker", "compose", "--project-name", cfg.project_name, "down"],
        cwd=cfg.script_dir,
    )


@app.command()
def restart() -> None:
    """Restart all containers."""
    stop()
    start()


@app.command()
def logs() -> None:
    """Show logs from the Odoo container."""
    cfg = load_config()
    success("Showing logs from Odoo container...")
    subprocess.run(
        ["docker", "compose", "--project-name", cfg.project_name, "logs", "-f", "odoo"],
        cwd=cfg.script_dir,
    )


@app.command()
def build(
    community: bool = typer.Option(
        False, "--community", help="Build for Community edition only"
    ),
) -> None:
    """Rebuild the Odoo Docker image."""
    import shutil

    cfg = load_config()
    success(f"Rebuilding Odoo image ({cfg.project_name}-odoo:{cfg.odoo_version})...")

    # Create temporary build context
    build_context = cfg.project_dir / f".odoo-build-{subprocess.os.getpid()}"
    build_context.mkdir(parents=True, exist_ok=True)

    try:
        # Copy necessary files to build context
        shutil.copy(cfg.script_dir / "Dockerfile", build_context)
        shutil.copy(cfg.script_dir / "docker-entrypoint.sh", build_context)
        shutil.copy(cfg.docker_config_file, build_context / "odoo.conf")

        # Copy requirements files
        if (cfg.project_dir / "requirements.txt").exists():
            shutil.copy(cfg.project_dir / "requirements.txt", build_context)
        if (cfg.project_dir / "odoo" / "requirements.txt").exists():
            shutil.copy(
                cfg.project_dir / "odoo" / "requirements.txt",
                build_context / "odoo-requirements.txt",
            )

        # Create minimal docker-compose for build
        compose_content = """name: ${PROJECT_NAME:-odoo}

services:
  odoo:
    image: ${PROJECT_NAME:-odoo-deploy}-odoo:${ODOO_VERSION:-17.0}
    build:
      context: .
      dockerfile: Dockerfile
      args:
        - ODOO_VERSION=${ODOO_VERSION:-17.0}
        - PYTHON_VERSION=${PYTHON_VERSION:-3.12}
      platforms:
        - linux/amd64
"""
        (build_context / "docker-compose.yml").write_text(compose_content)

        # Build the image
        env = subprocess.os.environ.copy()
        env["PROJECT_NAME"] = cfg.project_name
        env["ODOO_VERSION"] = cfg.odoo_version
        env["PYTHON_VERSION"] = cfg.python_version

        result = subprocess.run(
            [
                "docker",
                "compose",
                "build",
                "--build-arg",
                f"ODOO_VERSION={cfg.odoo_version}",
                "--build-arg",
                f"PYTHON_VERSION={cfg.python_version}",
                "odoo",
            ],
            cwd=build_context,
            env=env,
        )

        if result.returncode != 0:
            error("Failed to build Docker image.")
            raise typer.Exit(1)

        success("Docker image built successfully!")

    finally:
        shutil.rmtree(build_context, ignore_errors=True)


@app.command()
def shell(
    db_name: str = typer.Argument(..., help="Database name"),
) -> None:
    """Open an Odoo shell in the Docker container."""
    cfg = load_config()

    success(f"Opening Docker shell with database {db_name}...")

    subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            cfg.project_name,
            "exec",
            "odoo",
            "python",
            "/opt/project/odoo/odoo-bin",
            "shell",
            "-d",
            db_name,
            "-c",
            "/etc/odoo/odoo.conf",
            "--no-http",
        ],
        cwd=cfg.script_dir,
    )


@app.command()
def psql() -> None:
    """Open a PostgreSQL shell in the Docker container."""
    cfg = load_config()

    success("Opening PostgreSQL shell...")
    subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            cfg.project_name,
            "exec",
            "db",
            "psql",
            "-U",
            "odoo",
            "postgres",
        ],
        cwd=cfg.script_dir,
    )
