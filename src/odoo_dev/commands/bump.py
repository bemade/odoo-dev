"""Bump an Odoo module's manifest version."""

import subprocess
from pathlib import Path
from typing import Annotated

import typer

from odoo_dev.config import load_config
from odoo_dev.utils.console import error, info, success
from odoo_dev.utils.manifest import (
    bump_version_string,
    find_module_root,
    manifest_path,
    read_version,
    set_version,
)


def bump(
    module: Annotated[
        str,
        typer.Argument(help="Module name (under addons/) or path to a module dir"),
    ],
    level: Annotated[
        str, typer.Argument(help="Bump level: patch | minor | major")
    ] = "patch",
    no_stage: Annotated[
        bool, typer.Option("--no-stage", help="Do not git add the changed manifest")
    ] = False,
) -> None:
    """Bump a module's __manifest__.py version (patch | minor | major).

    Series-agnostic: only the trailing major.minor.patch segments move, never the
    Odoo series prefix. Edits the manifest in place and stages it, so the bump
    lands in the commit you're about to make (which the version-bump check
    requires for any module you've changed).
    """
    if level not in ("patch", "minor", "major"):
        error(f"level must be one of patch|minor|major (got {level!r})")
        raise typer.Exit(2)

    # Resolve the module: an explicit path, else a name under addons/.
    candidate = Path(module)
    root = find_module_root(candidate) if candidate.exists() else None
    if root is None and candidate.is_dir():
        root = candidate
    if root is None:
        cfg = load_config()
        under_addons = cfg.addons_dir / module
        if under_addons.exists():
            root = under_addons
        else:
            error(
                f"No module found for {module!r} "
                f"(checked the path and {cfg.addons_dir}/{module})"
            )
            raise typer.Exit(1)

    mf = manifest_path(root)
    if mf is None:
        error(f"No __manifest__.py in {root}")
        raise typer.Exit(1)

    # Resolve through any addons/ -> .repos/ symlink so we edit and stage the
    # real file in whichever repo (parent or submodule) actually owns it.
    real_mf = mf.resolve()
    text = real_mf.read_text()
    current = read_version(text)
    if current is None:
        error(f"No version string in {real_mf}")
        raise typer.Exit(1)

    try:
        new_version = bump_version_string(current, level)
    except ValueError as exc:
        error(str(exc))
        raise typer.Exit(1)

    real_mf.write_text(set_version(text, new_version))
    success(f"{root.name}: {current} -> {new_version}")

    if not no_stage:
        result = subprocess.run(
            ["git", "add", real_mf.name], cwd=real_mf.parent, check=False
        )
        if result.returncode != 0:
            info(f"(could not git add {real_mf}; stage it yourself)")
