"""Migrate a real submodule+symlink client repo to vendored form, then verify."""

import os
import subprocess
from pathlib import Path

import pytest

from odoo_dev.vendor.migrate import migrate_repo, plan_migration, MigrateError
from odoo_dev.vendor.lock import Lockfile
from odoo_dev.vendor.verify import verify


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _source_repo(tmp_path: Path, *, tag: str | None = None) -> tuple[Path, str]:
    repo = tmp_path / "sale-workflow"
    (repo / "shared_addon" / "models").mkdir(parents=True)
    (repo / "shared_addon" / "__manifest__.py").write_text(
        "{'name': 'shared', 'version': '18.0.2.0.0'}\n"
    )
    (repo / "shared_addon" / "models" / "m.py").write_text("z = 3\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    sha = _git(repo, "rev-parse", "HEAD")
    if tag:
        _git(repo, "tag", tag, sha)
    return repo, sha


def _client_repo(tmp_path: Path, source: Path) -> Path:
    client = tmp_path / "client"
    client.mkdir()
    _git(client, "init", "-q")
    _git(client, "config", "user.email", "t@t")
    _git(client, "config", "user.name", "t")
    # add the source as a submodule under .repos/ (file transport must be allowed)
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "-C",
            str(client),
            "submodule",
            "add",
            str(source),
            ".repos/sale-workflow",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # symlink the one addon we use into addons/ (relative symlink, as in real repos)
    (client / "addons").mkdir()
    os.symlink(
        "../.repos/sale-workflow/shared_addon", client / "addons" / "shared_addon"
    )
    # a client-private real addon that must be left untouched
    (client / "addons" / "client_addon").mkdir()
    (client / "addons" / "client_addon" / "__manifest__.py").write_text(
        "{'name': 'c'}\n"
    )
    _git(client, "add", "-A")
    _git(client, "commit", "-qm", "init client")
    return client


def test_plan_derives_pin_from_submodule(tmp_path):
    source, sha = _source_repo(tmp_path, tag="shared_addon/18.0.2.0.0")
    client = _client_repo(tmp_path, source)
    plans = plan_migration(client)
    assert len(plans) == 1
    p = plans[0]
    assert p["name"] == "shared_addon"
    assert p["commit"] == sha
    assert p["source"] == str(source)
    assert p["version"] == "18.0.2.0.0"  # derived because the tag exists


def test_plan_leaves_version_none_when_no_tag(tmp_path):
    source, sha = _source_repo(tmp_path)  # no tag
    client = _client_repo(tmp_path, source)
    plans = plan_migration(client)
    assert plans[0]["version"] is None


def test_migrate_materializes_removes_symlink_and_verifies(tmp_path):
    source, sha = _source_repo(tmp_path, tag="shared_addon/18.0.2.0.0")
    client = _client_repo(tmp_path, source)

    lock, unused = migrate_repo(client, cache_dir=tmp_path / "cache")

    # lockfile written with the pin
    assert (client / "addons.lock").exists()
    reloaded = Lockfile.load(client / "addons.lock")
    assert reloaded.entries["shared_addon"].commit == sha

    # vendored materialized byte-identically
    assert (
        client / "vendored" / "shared_addon" / "models" / "m.py"
    ).read_text() == "z = 3\n"

    # the symlink is gone; the client-private addon stays
    assert not (client / "addons" / "shared_addon").exists()
    assert (client / "addons" / "client_addon" / "__manifest__.py").exists()

    # the submodule is now unused and reported
    assert ".repos/sale-workflow" in unused

    # and the vendored copy passes the gate against its pin
    assert verify(client, reloaded, cache_dir=tmp_path / "cache") == []


def test_migrate_is_idempotent(tmp_path):
    source, _ = _source_repo(tmp_path)
    client = _client_repo(tmp_path, source)
    migrate_repo(client, cache_dir=tmp_path / "cache")
    # second run: symlink already gone -> nothing to plan, no error
    lock, unused = migrate_repo(client, cache_dir=tmp_path / "cache")
    assert unused == []
