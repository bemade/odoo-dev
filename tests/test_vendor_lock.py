"""Tests for the addons.lock model (parse / dump / validate)."""

import textwrap
from pathlib import Path

import pytest

from odoo_dev.vendor.lock import LockEntry, Lockfile, LockError


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "addons.lock"
    p.write_text(textwrap.dedent(body))
    return p


def test_load_tagged_and_shaonly_entries(tmp_path):
    lock = Lockfile.load(
        _write(
            tmp_path,
            """\
            bemade_fsm:
              source: github.com/bemade/bemade-addons
              version: 18.0.1.3.2
              commit: a1b2c3d4e5f6
            stock_something:
              source: github.com/bemade/stock-logistics-warehouse
              branch: "18.0"
              commit: 4c4c4c4c4c4c
            """,
        )
    )
    assert set(lock.entries) == {"bemade_fsm", "stock_something"}

    fsm = lock.entries["bemade_fsm"]
    assert fsm.source == "github.com/bemade/bemade-addons"
    assert fsm.commit == "a1b2c3d4e5f6"
    assert fsm.version == "18.0.1.3.2"
    assert fsm.branch is None

    st = lock.entries["stock_something"]
    assert st.version is None
    assert st.branch == "18.0"


def test_commit_is_required(tmp_path):
    with pytest.raises(LockError, match="commit"):
        Lockfile.load(
            _write(
                tmp_path,
                """\
                bemade_fsm:
                  source: github.com/bemade/bemade-addons
                  version: 18.0.1.3.2
                """,
            )
        )


def test_source_is_required(tmp_path):
    with pytest.raises(LockError, match="source"):
        Lockfile.load(
            _write(
                tmp_path,
                """\
                bemade_fsm:
                  commit: a1b2c3d4e5f6
                """,
            )
        )


def test_missing_file_is_empty_lock(tmp_path):
    lock = Lockfile.load(tmp_path / "nope.lock")
    assert lock.entries == {}


def test_roundtrip_dump_load_is_stable(tmp_path):
    lock = Lockfile(
        entries={
            "b_addon": LockEntry(
                name="b_addon",
                source="github.com/bemade/bemade-addons",
                commit="deadbeef",
                version="18.0.1.0.0",
            ),
            "a_addon": LockEntry(
                name="a_addon",
                source="github.com/bemade/x",
                commit="cafef00d",
                branch="18.0",
            ),
        }
    )
    path = tmp_path / "addons.lock"
    lock.dump(path)
    reloaded = Lockfile.load(path)
    assert reloaded.entries.keys() == lock.entries.keys()
    assert reloaded.entries["a_addon"].branch == "18.0"
    assert reloaded.entries["b_addon"].version == "18.0.1.0.0"
    # entries are serialized sorted by addon name for stable diffs
    assert list(yaml_keys(path)) == ["a_addon", "b_addon"]


def yaml_keys(path: Path):
    import yaml

    return list(yaml.safe_load(path.read_text()).keys())
