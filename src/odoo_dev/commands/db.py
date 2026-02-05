"""Database management commands."""

import subprocess
from pathlib import Path
from typing import Annotated

import typer

from odoo_dev.config import load_config
from odoo_dev.utils.console import error, success, warning

app = typer.Typer(help="Database operations")


@app.command()
def restore(
    backup_file: Annotated[
        Path, typer.Argument(help="Path to backup file (.zip, .sql, .dump)")
    ],
    db_name: Annotated[
        str | None,
        typer.Argument(help="Database name (default: derived from filename)"),
    ] = None,
    no_neutralize: Annotated[
        bool, typer.Option("--no-neutralize", help="Skip neutralization")
    ] = False,
) -> None:
    """Restore database from backup file."""
    cfg = load_config()

    # Resolve to absolute path
    backup_file = backup_file.resolve()

    if not backup_file.exists():
        error(f"Backup file not found: {backup_file}")
        raise typer.Exit(1)

    # Derive db name from filename if not provided
    if db_name is None:
        db_name = backup_file.stem

    # Check config exists
    if not cfg.config_file.exists():
        error(f"Config file not found: {cfg.config_file}")
        error("Run 'odoo-dev setup' first to create the configuration.")
        raise typer.Exit(1)

    neutralize = not no_neutralize
    file_ext = backup_file.suffix.lower()

    success(f"Restoring database {db_name} from {backup_file}...")
    success(f"Format: {file_ext}")
    success(f"Neutralize: {neutralize}")

    # Parse database connection from config
    db_config = _parse_db_config(cfg.config_file)

    # Check if database exists
    if _database_exists(db_name, db_config):
        warning(f"Database {db_name} already exists.")
        if not typer.confirm(
            "Do you want to drop it and restore from backup?", default=False
        ):
            success("Restore cancelled.")
            raise typer.Exit(0)

    # Activate venv if needed
    venv_activate = cfg.venv_path / "bin" / "activate"
    if not venv_activate.exists():
        error(f"Virtual environment not found at {cfg.venv_path}")
        error("Run 'odoo-dev setup-venv' first.")
        raise typer.Exit(1)

    # Drop existing database
    warning(f"Dropping existing database {db_name}...")
    _run_odoo_cmd(cfg, ["db", "drop", db_name], check=False)

    # Restore based on file type
    neutralize_flag = ["-n"] if neutralize else []

    if file_ext == ".zip":
        success("Using odoo db load method...")
        result = _run_odoo_cmd(
            cfg, ["db", "load", *neutralize_flag, db_name, str(backup_file)]
        )
    elif file_ext == ".dump":
        success("Using pg_restore method...")
        _create_database(db_name, db_config)
        _pg_restore(backup_file, db_name, db_config)
        if neutralize:
            _run_neutralize(cfg, db_name, db_config)
    elif file_ext == ".sql":
        success("Using psql method...")
        _create_database(db_name, db_config)
        _psql_restore(backup_file, db_name, db_config)
        if neutralize:
            _run_neutralize(cfg, db_name, db_config)
    else:
        error(f"Unsupported backup format: {file_ext}")
        error("Supported formats: .zip, .sql, .dump")
        raise typer.Exit(1)

    success(f"Database {db_name} restored successfully!")


@app.command()
def drop(
    db_name: Annotated[str, typer.Argument(help="Database name to drop")],
) -> None:
    """Drop a database."""
    cfg = load_config()

    warning(f"You are about to drop database {db_name}. This cannot be undone.")
    if not typer.confirm("Continue?", default=False):
        success("Cancelled.")
        raise typer.Exit(0)

    success(f"Dropping database {db_name}...")
    _run_odoo_cmd(cfg, ["db", "drop", db_name])
    success(f"Database {db_name} dropped.")


@app.command(name="list")
def list_dbs() -> None:
    """List all databases."""
    cfg = load_config()
    success("Listing databases...")
    _run_odoo_cmd(cfg, ["db", "list"])


@app.command()
def neutralize(
    db_name: Annotated[str, typer.Argument(help="Database name to neutralize")],
) -> None:
    """Neutralize a database (disable emails, crons, etc.)."""
    cfg = load_config()

    success(f"Neutralizing database {db_name}...")
    _run_odoo_cmd(cfg, ["neutralize", "-d", db_name])
    success(f"Database {db_name} neutralized.")


def _parse_db_config(config_file: Path) -> dict[str, str]:
    """Parse database connection info from odoo.conf."""
    config: dict[str, str] = {
        "host": "localhost",
        "port": "5432",
        "user": "odoo",
        "password": "",
    }

    for line in config_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("db_host"):
            config["host"] = line.split("=", 1)[1].strip()
        elif line.startswith("db_port"):
            config["port"] = line.split("=", 1)[1].strip()
        elif line.startswith("db_user"):
            config["user"] = line.split("=", 1)[1].strip()
        elif line.startswith("db_password"):
            config["password"] = line.split("=", 1)[1].strip()

    return config


def _database_exists(db_name: str, db_config: dict[str, str]) -> bool:
    """Check if a database exists."""
    env = subprocess.os.environ.copy()
    env["PGPASSWORD"] = db_config["password"]

    result = subprocess.run(
        [
            "psql",
            "-h",
            db_config["host"],
            "-p",
            db_config["port"],
            "-U",
            db_config["user"],
            "-lqt",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    for line in result.stdout.splitlines():
        if db_name == line.split("|")[0].strip():
            return True
    return False


def _create_database(db_name: str, db_config: dict[str, str]) -> None:
    """Create a new database."""
    env = subprocess.os.environ.copy()
    env["PGPASSWORD"] = db_config["password"]

    subprocess.run(
        [
            "createdb",
            "-h",
            db_config["host"],
            "-p",
            db_config["port"],
            "-U",
            db_config["user"],
            db_name,
        ],
        env=env,
        check=True,
    )


def _pg_restore(backup_file: Path, db_name: str, db_config: dict[str, str]) -> None:
    """Restore using pg_restore."""
    env = subprocess.os.environ.copy()
    env["PGPASSWORD"] = db_config["password"]

    subprocess.run(
        [
            "pg_restore",
            "-h",
            db_config["host"],
            "-p",
            db_config["port"],
            "-U",
            db_config["user"],
            "-d",
            db_name,
            "--no-owner",
            str(backup_file),
        ],
        env=env,
    )


def _psql_restore(backup_file: Path, db_name: str, db_config: dict[str, str]) -> None:
    """Restore using psql."""
    env = subprocess.os.environ.copy()
    env["PGPASSWORD"] = db_config["password"]

    subprocess.run(
        [
            "psql",
            "-h",
            db_config["host"],
            "-p",
            db_config["port"],
            "-U",
            db_config["user"],
            "-d",
            db_name,
            "-f",
            str(backup_file),
        ],
        env=env,
    )


def _run_neutralize(
    cfg: "ProjectConfig", db_name: str, db_config: dict[str, str]
) -> None:
    """Run Odoo neutralization and re-init db params."""
    from odoo_dev.config import ProjectConfig

    # Re-init database parameters
    _reinit_db_params(db_name, db_config)

    # Run odoo neutralize
    _run_odoo_cmd(cfg, ["neutralize", "-d", db_name])


def _reinit_db_params(db_name: str, db_config: dict[str, str]) -> None:
    """Re-initialize database parameters after restore."""
    env = subprocess.os.environ.copy()
    env["PGPASSWORD"] = db_config["password"]

    sql = """
DO $$
DECLARE
    new_secret TEXT := gen_random_uuid()::text;
    new_uuid TEXT := gen_random_uuid()::text;
BEGIN
    DELETE FROM ir_config_parameter WHERE key IN (
        'database.secret',
        'database.uuid',
        'database.create_date',
        'web.base.url',
        'base.login_cooldown_after',
        'base.login_cooldown_duration'
    );

    INSERT INTO ir_config_parameter (key, value, create_uid, create_date, write_uid, write_date) VALUES
        ('database.secret', new_secret, 1, LOCALTIMESTAMP, 1, LOCALTIMESTAMP),
        ('database.uuid', new_uuid, 1, LOCALTIMESTAMP, 1, LOCALTIMESTAMP),
        ('database.create_date', LOCALTIMESTAMP::text, 1, LOCALTIMESTAMP, 1, LOCALTIMESTAMP),
        ('web.base.url', 'http://localhost:8069', 1, LOCALTIMESTAMP, 1, LOCALTIMESTAMP),
        ('base.login_cooldown_after', '10', 1, LOCALTIMESTAMP, 1, LOCALTIMESTAMP),
        ('base.login_cooldown_duration', '60', 1, LOCALTIMESTAMP, 1, LOCALTIMESTAMP);
END $$;
"""

    subprocess.run(
        [
            "psql",
            "-h",
            db_config["host"],
            "-p",
            db_config["port"],
            "-U",
            db_config["user"],
            "-d",
            db_name,
            "-c",
            sql,
        ],
        env=env,
    )


def _run_odoo_cmd(
    cfg: "ProjectConfig", args: list[str], check: bool = True
) -> subprocess.CompletedProcess:
    """Run an odoo-bin command in the project's venv."""
    from odoo_dev.config import ProjectConfig

    # Build command to run in venv
    venv_python = cfg.venv_path / "bin" / "python"

    cmd = [str(venv_python), str(cfg.odoo_bin), "-c", str(cfg.config_file), *args]

    return subprocess.run(cmd, check=check)
