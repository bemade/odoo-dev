"""Main CLI entry point for odoo-dev."""

import typer

from odoo_dev.commands import db, docker, run, setup

app = typer.Typer(
    name="odoo-dev",
    help="Odoo Development Environment Helper",
    no_args_is_help=True,
)

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
