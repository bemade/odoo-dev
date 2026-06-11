"""Local Odoo runtime commands."""

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from odoo_dev.config import load_config
from odoo_dev.preflight import require_db
from odoo_dev.utils.console import error, info, success, warning


def run(
    db_name: Annotated[
        str | None, typer.Option("-d", "--database", help="Database name")
    ] = None,
    install: Annotated[
        str | None,
        typer.Option("-i", "--init", help="Modules to install (comma-separated)"),
    ] = None,
    update: Annotated[
        str | None,
        typer.Option("-u", "--update", help="Modules to update (comma-separated)"),
    ] = None,
    dev: Annotated[
        str | None,
        typer.Option("--dev", help="Dev mode options (e.g., 'reload,qweb,xml')"),
    ] = None,
    debug: Annotated[
        bool, typer.Option("--debug", help="Enable debugpy for VSCode debugging")
    ] = False,
    port: Annotated[int, typer.Option("-p", "--port", help="HTTP port")] = 8069,
) -> None:
    """Run Odoo locally."""
    cfg = load_config()

    # Verify setup
    if not cfg.venv_path.exists():
        error(f"Virtual environment not found at {cfg.venv_path}")
        error("Run 'odoo-dev setup' first.")
        raise typer.Exit(1)

    if not cfg.config_file.exists():
        error(f"Config file not found at {cfg.config_file}")
        error("Run 'odoo-dev setup' first.")
        raise typer.Exit(1)

    if not cfg.odoo_bin.exists():
        error(f"Odoo not found at {cfg.odoo_bin}")
        error("Run 'odoo-dev setup' first to clone Odoo repositories.")
        raise typer.Exit(1)

    require_db(cfg)

    venv_python = cfg.venv_path / "bin" / "python"

    # Build command
    cmd = [str(venv_python)]

    if debug:
        success("Debug mode enabled - attach VSCode to port 5678")
        cmd.extend(["-m", "debugpy", "--listen", "0.0.0.0:5678", "--wait-for-client"])

    cmd.extend([str(cfg.odoo_bin), "-c", str(cfg.config_file)])

    if db_name:
        cmd.extend(["-d", db_name])

    if install:
        cmd.extend(["-i", install])

    if update:
        cmd.extend(["-u", update])

    if dev:
        cmd.extend(["--dev", dev])

    cmd.extend(["--http-port", str(port)])

    success(f"Starting Odoo ({cfg.odoo_version}) on port {port}...")
    if debug:
        warning("Waiting for debugger to attach on port 5678...")

    info(f"Config: {cfg.config_file}")
    if db_name:
        info(f"Database: {db_name}")

    # Run Odoo, passing through signals
    try:
        process = subprocess.Popen(cmd, cwd=cfg.project_dir)

        def signal_handler(signum, frame):
            process.send_signal(signum)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        sys.exit(process.wait())
    except KeyboardInterrupt:
        process.terminate()
        process.wait()


def shell(
    db_name: Annotated[str, typer.Argument(help="Database name")],
) -> None:
    """Open a local Odoo shell with database context."""
    cfg = load_config()

    # Verify setup
    if not cfg.venv_path.exists():
        error(f"Virtual environment not found at {cfg.venv_path}")
        error("Run 'odoo-dev setup' first.")
        raise typer.Exit(1)

    require_db(cfg)

    venv_python = cfg.venv_path / "bin" / "python"

    success(f"Opening Odoo shell with database {db_name}...")

    cmd = [
        str(venv_python),
        str(cfg.odoo_bin),
        "shell",
        "-d",
        db_name,
        "-c",
        str(cfg.config_file),
        "--no-http",
    ]

    os.execv(str(venv_python), cmd)


def update(
    modules: Annotated[
        str, typer.Argument(help="Modules to update (comma-separated)")
    ] = "all",
    db_name: Annotated[
        str, typer.Option("-d", "--database", help="Database name")
    ] = "odoo",
) -> None:
    """Update specified modules."""
    cfg = load_config()

    if not cfg.venv_path.exists():
        error(f"Virtual environment not found at {cfg.venv_path}")
        error("Run 'odoo-dev setup' first.")
        raise typer.Exit(1)

    require_db(cfg)

    venv_python = cfg.venv_path / "bin" / "python"

    success(f"Updating modules: {modules} on database {db_name}...")

    result = subprocess.run(
        [
            str(venv_python),
            str(cfg.odoo_bin),
            "-c",
            str(cfg.config_file),
            "-d",
            db_name,
            "-u",
            modules,
            "--stop-after-init",
        ],
        cwd=cfg.project_dir,
    )

    if result.returncode == 0:
        success("Module update complete!")
    else:
        error(f"Module update failed with exit code {result.returncode}")
        raise typer.Exit(result.returncode)


def test(
    modules: Annotated[
        str | None, typer.Argument(help="Modules to test (comma-separated)")
    ] = None,
    db_name: Annotated[
        str | None, typer.Option("-d", "--database", help="Test database name")
    ] = None,
    test_tags: Annotated[
        str | None,
        typer.Option(
            "--test-tags",
            help="Test tags to filter: \\[tag]\\[/module]\\[:class]\\[.method]",
        ),
    ] = None,
    coverage: Annotated[
        bool, typer.Option("--coverage/--no-coverage", help="Enable coverage reporting")
    ] = True,
    keep_db: Annotated[
        bool,
        typer.Option("--keep-db/--no-keep-db", help="Keep test database after tests"),
    ] = False,
    exclude: Annotated[
        str | None,
        typer.Option(
            "--exclude",
            help="Modules to exclude from auto-discovery (comma-separated). "
            "Defaults to the 'no_ci' list in repo_deps.yaml if present.",
        ),
    ] = None,
) -> None:
    """Run tests for specified modules."""
    import time

    cfg = load_config()

    # Find repo_deps.yaml (used for both exclusions and dependency cloning)
    repo_deps_file: Path | None = None
    candidates = [
        cfg.project_dir / "repo_deps.yaml",
        Path("repo_deps.yaml"),
    ]
    # Also check the real source dir of addons (handles symlinked addons dirs)
    addons_dir = cfg.project_dir / "addons"
    if addons_dir.is_dir():
        for entry in addons_dir.iterdir():
            if entry.is_symlink():
                candidates.append(entry.resolve().parent / "repo_deps.yaml")
                break
    for candidate in candidates:
        if candidate.exists():
            repo_deps_file = candidate
            break

    # Auto-load exclusions from repo_deps.yaml when not explicitly provided
    if exclude is None and repo_deps_file is not None:
        try:
            import yaml

            data = yaml.safe_load(repo_deps_file.read_text()) or {}
            no_ci = data.get("no_ci", [])
            if no_ci:
                exclude = ",".join(no_ci)
                info(f"Excluding (from {repo_deps_file} no_ci): {exclude}")
        except Exception:
            pass

    # Verify setup
    if not cfg.venv_path.exists():
        error(f"Virtual environment not found at {cfg.venv_path}")
        error("Run 'odoo-dev setup' first.")
        raise typer.Exit(1)

    if not cfg.config_file.exists():
        error(f"Config file not found: {cfg.config_file}")
        error("Run 'odoo-dev setup' first.")
        raise typer.Exit(1)

    # Generate test database name if not provided
    if db_name is None:
        db_name = f"test_{int(time.time())}"

    require_db(cfg)

    venv_python = cfg.venv_path / "bin" / "python"

    # Determine modules to test
    if modules is None:
        # Use manifestoo to list addons in the addons directory
        manifestoo_cmd = [
            str(venv_python),
            "-m",
            "manifestoo",
            "--select-addons-dir",
            str(cfg.addons_dir),
        ]
        if exclude:
            manifestoo_cmd.extend(["--select-exclude", exclude])
        manifestoo_cmd.extend(["list", "--separator=,"])
        result = subprocess.run(
            manifestoo_cmd,
            capture_output=True,
            text=True,
            env={**os.environ, "ODOO_VERSION": "", "ODOO_SERIES": ""},
        )
        modules = result.stdout.strip()
        if not modules:
            error(f"No addons found in {cfg.addons_dir}")
            raise typer.Exit(1)

    # Clone external repo dependencies declared in repo_deps.yaml and symlink into addons_dir
    if repo_deps_file is not None and repo_deps_file.exists():
        try:
            import yaml

            data = yaml.safe_load(repo_deps_file.read_text()) or {}
            for repo_url, addon_names in data.get("repos", {}).items():
                clone_dir = Path("/tmp") / f"odoo_dev_dep_{abs(hash(repo_url))}"
                if not clone_dir.exists():
                    branch = os.environ.get("ODOO_VERSION", cfg.odoo_version)
                    result = subprocess.run(
                        [
                            "git",
                            "clone",
                            "--depth=1",
                            "-b",
                            branch,
                            repo_url,
                            str(clone_dir),
                        ],
                        capture_output=True,
                    )
                    if result.returncode != 0:
                        subprocess.run(
                            ["git", "clone", "--depth=1", repo_url, str(clone_dir)],
                            capture_output=True,
                        )
                for addon in addon_names:
                    src = clone_dir / addon
                    dst = cfg.addons_dir / addon
                    if src.is_dir() and not dst.exists():
                        dst.symlink_to(src)
        except Exception as e:
            warning(f"Could not clone repo dependencies: {e}")

    # Get full addons path from config
    addons_path = _get_addons_path(cfg.config_file)

    # Calculate dependencies with manifestoo
    success("Calculating dependencies...")
    result = subprocess.run(
        [
            str(venv_python),
            "-m",
            "manifestoo",
            "--addons-path",
            addons_path,
            f"--select-include={modules}",
            "list-depends",
            "--separator=,",
            "--transitive",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "ODOO_VERSION": "", "ODOO_SERIES": ""},
    )
    deps = result.stdout.strip() or "base"

    # Find available port
    http_port = _find_available_port(8069)

    success("=== Test Run ===")
    info(f"Database: {db_name}")
    info(f"HTTP Port: {http_port}")
    info(f"Modules: {modules}")
    info(f"Dependencies: {deps}")

    # Step 1: Install dependencies without tests
    success("Installing dependencies...")
    result = subprocess.run(
        [
            str(venv_python),
            str(cfg.odoo_bin),
            "-c",
            str(cfg.config_file),
            "-d",
            db_name,
            "-i",
            deps,
            "--stop-after-init",
            "--http-port",
            str(http_port),
        ],
    )

    if result.returncode != 0:
        error("Failed to install dependencies")
        if not keep_db:
            _drop_database(cfg, db_name)
        raise typer.Exit(1)

    # Step 2: Run tests
    test_exit_code = 1
    try:
        success(f"Running tests: {modules}")

        if coverage:
            # Build coverage source paths
            coverage_source = ",".join(
                str(cfg.addons_dir / m) for m in modules.split(",")
            )

            test_cmd = [
                str(venv_python),
                "-m",
                "coverage",
                "run",
                "--branch",
                f"--source={coverage_source}",
                str(cfg.odoo_bin),
            ]
        else:
            test_cmd = [str(venv_python), str(cfg.odoo_bin)]

        test_cmd.extend(
            [
                "-c",
                str(cfg.config_file),
                "-d",
                db_name,
                "-i",
                modules,
                "-u",
                modules,
                "--test-enable",
                "--stop-after-init",
                "--http-port",
                str(http_port),
            ]
        )

        if test_tags:
            test_cmd.extend(["--test-tags", test_tags])

        result = subprocess.run(test_cmd)
        test_exit_code = result.returncode

        # Generate coverage report
        if coverage:
            success("Coverage report:")
            subprocess.run([str(venv_python), "-m", "coverage", "report"])
            subprocess.run(
                [
                    str(venv_python),
                    "-m",
                    "coverage",
                    "html",
                    "-d",
                    str(cfg.project_dir / "coverage_html"),
                ]
            )
            info(f"HTML report: {cfg.project_dir / 'coverage_html' / 'index.html'}")
    finally:
        # Clean up test database
        if not keep_db:
            _drop_database(cfg, db_name)
        else:
            info(f"Keeping test database: {db_name}")

    if test_exit_code == 0:
        success("=== All tests passed! ===")
    else:
        error(f"=== Tests failed (exit code: {test_exit_code}) ===")
        raise typer.Exit(test_exit_code)


def scaffold(
    module_name: Annotated[str, typer.Argument(help="Name for the new module")],
    dest: Annotated[
        str | None,
        typer.Option("-d", "--dest", help="Destination directory (default: addons/)"),
    ] = None,
) -> None:
    """Create a new Odoo module from template."""
    cfg = load_config()

    if not cfg.venv_path.exists():
        error(f"Virtual environment not found at {cfg.venv_path}")
        error("Run 'odoo-dev setup' first.")
        raise typer.Exit(1)

    venv_python = cfg.venv_path / "bin" / "python"
    destination = dest or str(cfg.addons_dir)

    success(f"Creating module '{module_name}' in {destination}...")

    result = subprocess.run(
        [
            str(venv_python),
            str(cfg.odoo_bin),
            "scaffold",
            module_name,
            destination,
        ],
        cwd=cfg.project_dir,
    )

    if result.returncode == 0:
        success(f"Module '{module_name}' created successfully!")
    else:
        error("Failed to create module")
        raise typer.Exit(result.returncode)


def _drop_database(cfg, db_name: str) -> None:
    """Drop a test database, trying odoo-bin first, then falling back to dropdb."""
    success(f"Cleaning up: {db_name}")
    venv_python = cfg.venv_path / "bin" / "python"

    # Try odoo-bin db drop first
    try:
        result = subprocess.run(
            [
                str(venv_python),
                str(cfg.odoo_bin),
                "-c",
                str(cfg.config_file),
                "db",
                "drop",
                db_name,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
    except OSError:
        pass

    # Fallback to dropdb
    warning("odoo-bin db drop failed, falling back to dropdb...")
    from odoo_dev.commands.db import _parse_db_config

    db_config = _parse_db_config(cfg.config_file)
    env = {**os.environ, "PGPASSWORD": db_config["password"]}

    # Terminate active connections first — dropdb will fail if any remain
    _terminate_connections(db_name, db_config)

    result = subprocess.run(
        [
            "dropdb",
            "-h",
            db_config["host"],
            "-p",
            db_config["port"],
            "-U",
            db_config["user"],
            "--if-exists",
            db_name,
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        warning(f"Failed to drop test database {db_name}")
        if result.stderr:
            warning(result.stderr.strip())


def _terminate_connections(db_name: str, db_config: dict[str, str]) -> None:
    """Terminate all active connections to a database."""
    env = {**os.environ, "PGPASSWORD": db_config["password"]}
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
            "postgres",
            "-c",
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid()",
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def _get_addons_path(config_file) -> str:
    """Extract addons_path from odoo.conf."""
    for line in config_file.read_text().splitlines():
        if line.strip().startswith("addons_path"):
            return line.split("=", 1)[1].strip()
    return ""


def _find_available_port(start: int = 8069) -> int:
    """Find an available port starting from the given port."""
    import socket

    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    import random

    return random.randint(49152, 65535)
