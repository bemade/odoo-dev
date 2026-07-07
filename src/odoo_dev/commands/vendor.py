"""``odoo-dev vendor`` — per-addon vendoring of shared Odoo addons.

Shared addons are committed as real files under ``vendored/<addon>/`` and pinned
per-addon in ``addons.lock``. This deploys as plain files (what Odoo.sh needs) and
makes each promotion a normal reviewable file diff instead of a repo-granular
submodule-pointer bump.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from odoo_dev.config import load_config
from odoo_dev.utils.console import error, info, success
from odoo_dev.vendor.develop import (
    DevelopError,
    develop_state,
    start_develop,
    stop_develop,
)
from odoo_dev.vendor.edit import EditError, add_addon, bump_addon
from odoo_dev.vendor.lock import Lockfile
from odoo_dev.vendor.migrate import migrate_repo, plan_migration
from odoo_dev.vendor.sync import sync_addons
from odoo_dev.vendor.verify import verify

app = typer.Typer(
    name="vendor",
    help="Vendor shared addons as committed real files, pinned by addons.lock.",
    no_args_is_help=True,
)


@app.command("sync")
def sync_cmd(
    addon: Annotated[
        Optional[list[str]],
        typer.Argument(help="Only sync these addons (default: all in addons.lock)."),
    ] = None,
) -> None:
    """Materialize vendored/<addon>/ from addons.lock (fetching pinned commits)."""
    cfg = load_config()
    lock = Lockfile.load(cfg.lockfile_path)
    if not lock.entries:
        info(f"No entries in {cfg.lockfile_path.name}; nothing to sync.")
        return
    synced = sync_addons(cfg.project_dir, lock, names=addon or None)
    for name in synced:
        success(f"synced vendored/{name}")
    info(f"{len(synced)} addon(s) synced.")


@app.command("check")
def check_cmd(
    no_hybrid: Annotated[
        bool,
        typer.Option(
            "--no-hybrid",
            help="Also fail if the repo is a hybrid (addons/ still symlinks into "
            ".repos/). Use in CI for repos that declare themselves fully vendored.",
        ),
    ] = False,
) -> None:
    """Verify vendored/ matches addons.lock exactly (the CI gate). Exit 1 on any problem."""
    cfg = load_config()
    lock = Lockfile.load(cfg.lockfile_path)
    problems = verify(cfg.project_dir, lock, allow_hybrid=not no_hybrid)
    if problems:
        for p in problems:
            error(p)
        error(f"vendor check FAILED: {len(problems)} problem(s).")
        raise typer.Exit(1)
    success(f"vendor check OK: {len(lock.entries)} addon(s) match their pins.")


@app.command("add")
def add_cmd(
    name: Annotated[
        str, typer.Argument(help="Addon name (== its dir in the source repo).")
    ],
    source: Annotated[
        str,
        typer.Option(
            "--source", help="Source repo, e.g. github.com/bemade/bemade-addons."
        ),
    ],
    version: Annotated[
        Optional[str], typer.Option("--version", help="Pin to tag <addon>/<version>.")
    ] = None,
    commit: Annotated[
        Optional[str], typer.Option("--commit", help="Pin to an explicit commit/ref.")
    ] = None,
    branch: Annotated[
        Optional[str],
        typer.Option("--branch", help="Track this branch (pin to its HEAD)."),
    ] = None,
) -> None:
    """Add a new vendored addon: resolve the pin, write addons.lock, materialize it."""
    cfg = load_config()
    try:
        entry = add_addon(cfg.project_dir, name, source, version, commit, branch)
    except EditError as exc:
        error(str(exc))
        raise typer.Exit(2)
    success(f"added {name} @ {entry.commit[:12]} -> vendored/{name}")


@app.command("bump")
def bump_cmd(
    name: Annotated[str, typer.Argument(help="Addon already in addons.lock.")],
    version: Annotated[
        Optional[str], typer.Option("--version", help="Bump to tag <addon>/<version>.")
    ] = None,
    commit: Annotated[
        Optional[str], typer.Option("--commit", help="Bump to an explicit commit/ref.")
    ] = None,
) -> None:
    """Move an addon's pin to a new version/commit (or its tracked branch HEAD) and re-sync."""
    cfg = load_config()
    try:
        entry = bump_addon(cfg.project_dir, name, version, commit)
    except EditError as exc:
        error(str(exc))
        raise typer.Exit(2)
    success(f"bumped {name} -> {entry.commit[:12]}")


@app.command("migrate")
def migrate_cmd(
    addon: Annotated[
        Optional[list[str]],
        typer.Argument(help="Only migrate these addons (default: all symlinked)."),
    ] = None,
    deinit: Annotated[
        bool,
        typer.Option("--deinit", help="Also git-rm submodules left with no symlinks."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show the planned pins; change nothing."),
    ] = False,
) -> None:
    """Convert addons/ symlinks into .repos submodules to vendored/ + addons.lock."""
    cfg = load_config()
    if dry_run:
        plans = plan_migration(cfg.project_dir, addon or None)
        if not plans:
            info("Nothing to migrate (no symlinked submodule addons found).")
            return
        for p in plans:
            ver = p["version"] or f"@{p['commit'][:12]}"
            info(f"  {p['name']}  {ver}  <- {p['source']}  ({p['sub_path']})")
        info(f"{len(plans)} addon(s) would be vendored. Re-run without --dry-run.")
        return

    lock, unused = migrate_repo(cfg.project_dir, addons=addon or None, deinit=deinit)
    success(f"Migrated {len(lock.entries)} addon(s) to vendored/ (see addons.lock).")
    if unused:
        info("")
        if deinit:
            info(f"Removed now-unused submodules: {', '.join(unused)}")
        else:
            info("Submodules now unused (remove with --deinit or by hand):")
            for s in unused:
                info(f"  {s}")


@app.command("develop")
def develop_cmd(
    name: Annotated[
        str, typer.Argument(help="Vendored addon to edit against its source repo.")
    ],
    branch: Annotated[
        Optional[str],
        typer.Option("--branch", "-b", help="Work branch (default vendor-dev/<addon>)."),
    ] = None,
    base: Annotated[
        Optional[str],
        typer.Option("--base", help="Base the branch on this ref (default: the pin)."),
    ] = None,
    stop: Annotated[
        bool,
        typer.Option("--stop", help="Leave develop mode: drop the overlay, keep clone."),
    ] = False,
) -> None:
    """Edit a vendored addon against a live source clone, overlaid onto the addons path.

    Clones the source into .vendor-dev/, checks out a work branch, and prepends an
    overlay to the LOCAL odoo.conf so Odoo loads the live tree instead of vendored/.
    vendored/ stays pristine. Edit, run/test here, commit+push upstream, then bump.
    """
    cfg = load_config()
    try:
        if stop:
            stop_develop(cfg.project_dir, name)
            success(f"stopped developing {name} (clone kept under .vendor-dev/)")
            return
        entry = start_develop(cfg.project_dir, name, branch=branch, base=base)
    except DevelopError as exc:
        error(str(exc))
        raise typer.Exit(2)
    success(f"developing {name} on branch {entry.branch}")
    info(f"  clone: {entry.repo}")
    info("  edit there, run/test in this project's Odoo, then commit + push upstream.")
    info(f"  once the new version is tagged:  odoo-dev vendor bump {name} --version <v>")


@app.command("status")
def status_cmd() -> None:
    """Show vendored addons (with pins) and any remaining addons/ symlinks (hybrid)."""
    cfg = load_config()
    lock = Lockfile.load(cfg.lockfile_path)
    vendored = cfg.vendored_dir
    present = (
        {p.name for p in vendored.iterdir() if p.is_dir()}
        if vendored.exists()
        else set()
    )

    if not lock.entries:
        info("No addons.lock entries.")
    for name in sorted(lock.entries):
        e = lock.entries[name]
        mark = "ok " if name in present else "MISSING"
        ver = e.version or f"@{e.commit[:12]}"
        info(f"  [{mark}] {name}  {ver}  <- {e.source}")

    # Hybrid transition: addons/ dirs/symlinks not yet vendored.
    if cfg.addons_dir.exists():
        symlinks = sorted(p.name for p in cfg.addons_dir.iterdir() if p.is_symlink())
        if symlinks:
            info("")
            info(f"addons/ still symlinked (not yet vendored): {', '.join(symlinks)}")

    # Addons currently overlaid from a live source clone (vendor develop).
    dev = develop_state(cfg.project_dir)
    if dev:
        info("")
        info("develop mode (overlaid from a live source clone; vendored/ shadowed):")
        for n in sorted(dev):
            d = dev[n]
            info(f"  {n}  branch {d.branch}  <- {d.repo}")
