"""Console output helpers with colored formatting."""

from rich.console import Console

console = Console()


def success(msg: str) -> None:
    """Print a success message in green."""
    console.print(f"[green]{msg}[/green]")


def warning(msg: str) -> None:
    """Print a warning message in yellow."""
    console.print(f"[yellow]{msg}[/yellow]")


def error(msg: str) -> None:
    """Print an error message in red."""
    console.print(f"[red]{msg}[/red]")


def info(msg: str) -> None:
    """Print an info message."""
    console.print(msg)
