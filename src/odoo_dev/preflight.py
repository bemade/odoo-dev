"""Fast PostgreSQL connectivity preflight for commands that need a database.

odoo-dev does not own the PostgreSQL server lifecycle (you bring your own:
a local service, Docker, or a remote/managed DB). Instead, commands that need
a database call :func:`require_db` first, which connects exactly the way
odoo-bin will and, on failure, prints a specific, actionable diagnostic rather
than letting Odoo fail later with a noisy stack trace.
"""

import os
import subprocess
from dataclasses import dataclass

import typer

from odoo_dev.config import DbConfig, read_db_config
from odoo_dev.utils.console import error, warning


@dataclass
class PreflightResult:
    """Outcome of a connectivity check."""

    ok: bool
    category: str  # ok | client_missing | unreachable | auth | role_missing | db_missing | unknown
    message: str  # raw stderr (or short note), for context


def psql_argv(
    db: DbConfig, dbname: str = "postgres", sql: str = "SELECT 1"
) -> list[str]:
    """Build a psql argv that connects the way odoo-bin would.

    Host/port are only passed when set, so an unset host uses the local socket
    (libpq default) rather than forcing TCP to localhost.
    """
    # -w / --no-password: never prompt interactively (would hang a preflight);
    # fail fast instead so we can classify the failure.
    argv = ["psql", "-w"]
    if db.host:
        argv += ["-h", db.host]
    if db.port:
        argv += ["-p", db.port]
    argv += ["-U", db.user, "-d", dbname, "-tAc", sql]
    return argv


def classify_psql_failure(returncode: int, stderr: str) -> str:
    """Map a failed psql attempt to a category for actionable guidance."""
    s = stderr.lower()
    # Order matters: the "does not exist" variants must be checked before the
    # generic connection failures.
    if "does not exist" in s and "role" in s:
        return "role_missing"
    if "does not exist" in s and "database" in s:
        return "db_missing"
    if "authentication failed" in s or "no password supplied" in s:
        return "auth"
    if (
        "could not connect" in s
        or "connection refused" in s
        or "could not translate host" in s
        or "no such file or directory" in s
        or "is the server running" in s
    ):
        return "unreachable"
    return "unknown"


def check_db_connection(db: DbConfig, dbname: str = "postgres") -> PreflightResult:
    """Attempt a trivial query and report whether (and why) it failed."""
    env = os.environ.copy()
    if db.password:
        env["PGPASSWORD"] = db.password
    try:
        proc = subprocess.run(
            psql_argv(db, dbname=dbname),
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        return PreflightResult(
            False,
            "client_missing",
            "psql executable not found on PATH",
        )
    if proc.returncode == 0:
        return PreflightResult(True, "ok", "")
    return PreflightResult(
        False,
        classify_psql_failure(proc.returncode, proc.stderr),
        proc.stderr.strip(),
    )


def _target(db: DbConfig) -> str:
    """Human-readable connection target for messages."""
    where = f"{db.host}:{db.port or '5432'}" if db.host else "the local socket"
    return f"PostgreSQL as user '{db.user}' on {where}"


def _guidance(category: str, db: DbConfig) -> str:
    """Actionable next step for a failure category."""
    if category == "client_missing":
        return (
            "The psql client isn't on your PATH. Install the PostgreSQL client "
            "(macOS: `brew install libpq` and add it to PATH; Debian/Ubuntu: "
            "`sudo apt-get install postgresql-client`)."
        )
    if category == "unreachable":
        return (
            "Could not reach a PostgreSQL server. Start one (macOS: "
            "`brew services start postgresql@18`; Debian/Ubuntu: "
            "`sudo systemctl start postgresql`), or set db_host/db_port in "
            "conf/odoo.conf (or DB_HOST/DB_PORT in .env) to point at an "
            "existing / remote / Docker PostgreSQL."
        )
    if category == "auth":
        return (
            f"Authentication failed for role '{db.user}'. Check db_user/"
            "db_password in conf/odoo.conf, or adjust the server's pg_hba.conf "
            "(peer vs. password auth). A ~/.pgpass entry can supply the password."
        )
    if category == "role_missing":
        return (
            f"The role '{db.user}' does not exist. Create it once: "
            f"`createuser -s {db.user}` (Debian/Ubuntu: prefix with "
            "`sudo -u postgres`)."
        )
    if category == "db_missing":
        return (
            "The maintenance database is missing — unusual; your PostgreSQL "
            "install may be incomplete."
        )
    return "See the PostgreSQL error above."


def require_db(cfg, dbname: str = "postgres") -> None:
    """Ensure the configured database server is reachable, or exit with guidance.

    Args:
        cfg: ProjectConfig (only ``config_file`` is used).
        dbname: Database to connect to for the check (default: ``postgres``).

    Raises:
        typer.Exit: if the server cannot be reached / authenticated.
    """
    db = read_db_config(cfg.config_file)
    result = check_db_connection(db, dbname=dbname)
    if result.ok:
        return

    error(f"Cannot connect to {_target(db)}.")
    if result.message:
        warning(result.message)
    error(_guidance(result.category, db))
    raise typer.Exit(1)
