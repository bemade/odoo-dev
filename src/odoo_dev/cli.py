"""Main CLI entry point for odoo-dev."""

from typing import Optional

import typer

from odoo_dev import __version__
from odoo_dev.commands import db, docker, run, setup


def _version_callback(value: bool) -> None:
    if value:
        print(f"odoo-dev {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="odoo-dev",
    help="Odoo Development Environment Helper",
    no_args_is_help=True,
)


@app.callback()
def _main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Odoo Development Environment Helper."""
    pass


# Command groups
app.add_typer(db.app, name="db")
app.add_typer(docker.app, name="docker")

# Setup commands
app.command()(setup.setup)
app.command(name="setup-venv")(setup.setup_venv)
app.command()(setup.vscode)

# Local runtime commands (the defaults)
app.command()(run.run)
app.command()(run.shell)
app.command()(run.update)
app.command()(run.test)
app.command()(run.scaffold)


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
