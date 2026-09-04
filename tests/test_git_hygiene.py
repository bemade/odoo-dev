"""Tests for ``odoo-dev git``.

These build real throwaway repos rather than mocking git: every bug this
command exists to prevent is a bug about what git actually reports, so a mock
would test the assumption instead of the behaviour.
"""

import subprocess

import pytest
from typer.testing import CliRunner

from odoo_dev.cli import app

runner = CliRunner()


def _run(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """An origin plus a clone, with one commit on the default branch."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _run("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    _run("clone", str(origin), str(work), cwd=tmp_path)
    for k, v in (("user.email", "t@example.com"), ("user.name", "T")):
        _run("config", k, v, cwd=work)
    (work / "feature.py").write_text("MARKER_ALPHA = 1\n")
    _run("add", "-A", cwd=work)
    _run("commit", "-m", "feat: alpha", cwd=work)
    _run("push", "-u", "origin", "main", cwd=work)
    monkeypatch.chdir(work)
    return work


def test_prune_refs_is_dry_by_default(repo):
    """A stale ref is reported but survives without --apply."""
    _run("update-ref", "refs/remotes/task-999/feature/x", "HEAD", cwd=repo)
    res = runner.invoke(app, ["git", "prune-refs"])
    assert res.exit_code == 0
    assert "task-999" in res.stdout
    assert "DRY RUN" in res.stdout
    # still there
    out = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)", "refs/remotes"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout
    assert "task-999" in out


def test_prune_refs_apply_removes_only_orphans(repo):
    """--apply deletes the orphaned ref and leaves origin's refs untouched."""
    _run("update-ref", "refs/remotes/task-999/feature/x", "HEAD", cwd=repo)
    res = runner.invoke(app, ["git", "prune-refs", "--apply"])
    assert res.exit_code == 0
    out = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)", "refs/remotes"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout
    assert "task-999" not in out
    assert "refs/remotes/origin/main" in out


def test_shipped_sees_reapplied_work_that_ancestry_misses(repo):
    """The whole point: same content, different SHA -> ancestry lies, content does not."""
    # Branch off and add the feature there.
    _run("checkout", "-b", "side", cwd=repo)
    (repo / "feature.py").write_text("MARKER_ALPHA = 1\nMARKER_BETA = 2\n")
    _run("commit", "-am", "feat: beta", cwd=repo)
    side = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    # Re-apply the SAME content on main as an independent commit (what a squash
    # merge or a manual re-application produces), then move main on afterwards
    # so the two histories genuinely diverge.
    _run("checkout", "main", cwd=repo)
    (repo / "feature.py").write_text("MARKER_ALPHA = 1\nMARKER_BETA = 2\n")
    _run("commit", "-am", "feat: beta (reapplied)", cwd=repo)
    # main then moves on *within the same file* -- the real-world shape, where
    # the feature shipped months ago and the file has been edited since.
    (repo / "feature.py").write_text(
        "MARKER_ALPHA = 1\nMARKER_BETA = 2\nadded_later = True\n"
    )
    _run("commit", "-am", "chore: main moves on", cwd=repo)
    _run("push", "origin", "main", cwd=repo)

    # Ancestry says the side commit never landed...
    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", side, "origin/main"],
            cwd=repo,
            capture_output=True,
        ).returncode
        != 0
    )
    # ...but the marker is present, so shipped() must report SHIPPED.
    res = runner.invoke(
        app,
        [
            "git",
            "shipped",
            side,
            "feature.py",
            "--target",
            "origin/main",
            "--grep",
            "MARKER_BETA",
        ],
    )
    assert res.exit_code == 0
    assert "SHIPPED" in res.stdout
    assert "differs" in res.stdout


def test_shipped_reports_identical_paths_without_needing_markers(repo):
    """Byte-identical content is a sufficient answer when ancestry does not apply."""
    _run("checkout", "-b", "twin", cwd=repo)
    (repo / "note.txt").write_text("unrelated\n")  # diverge without touching feature.py
    _run("add", "-A", cwd=repo)
    _run("commit", "-m", "chore: diverge", cwd=repo)
    twin = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    _run("checkout", "main", cwd=repo)
    res = runner.invoke(
        app, ["git", "shipped", twin, "feature.py", "--target", "origin/main"]
    )
    assert res.exit_code == 0
    assert "identical" in res.stdout


def test_shipped_short_circuits_when_ancestry_is_conclusive(repo):
    """A true ancestry answer is proof; it must not fall through to a diff.

    Regression: comparing HEAD (already an ancestor) against a moved-on target
    reported "differs", which reads as doubt about something already settled.
    """
    _run("checkout", "-b", "later", cwd=repo)
    (repo / "feature.py").write_text("MARKER_ALPHA = 1\nmoved_on = True\n")
    _run("commit", "-am", "chore: target moves on", cwd=repo)
    _run("push", "origin", "later", cwd=repo)
    _run("checkout", "main", cwd=repo)

    res = runner.invoke(
        app, ["git", "shipped", "HEAD", "feature.py", "--target", "origin/later"]
    )
    assert res.exit_code == 0
    assert "shipped" in res.stdout
    assert "differs" not in res.stdout


def test_shipped_warns_that_a_whole_tree_path_is_uninformative(repo):
    """'.' always differs against a moved-on target, so say so rather than imply doubt."""
    _run("checkout", "-b", "side2", cwd=repo)
    (repo / "feature.py").write_text("MARKER_ALPHA = 1\nbeta = 2\n")
    _run("commit", "-am", "feat: side2", cwd=repo)
    side = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    _run("checkout", "main", cwd=repo)
    (repo / "other.py").write_text("z = 1\n")
    _run("add", "-A", cwd=repo)
    _run("commit", "-m", "chore: diverge", cwd=repo)
    _run("push", "origin", "main", cwd=repo)

    res = runner.invoke(app, ["git", "shipped", side, ".", "--target", "origin/main"])
    assert "entire tree" in res.stdout


def test_shipped_derives_paths_when_none_are_given(repo):
    """Omitting paths must compare exactly the files REF changed."""
    # Pre-existing file on BOTH sides: derivation must ignore it, because REF
    # does not change it.
    (repo / "untouched.py").write_text("irrelevant = True\n")
    _run("add", "-A", cwd=repo)
    _run("commit", "-m", "chore: unrelated file", cwd=repo)
    _run("push", "origin", "main", cwd=repo)

    _run("checkout", "-b", "derive", cwd=repo)
    (repo / "feature.py").write_text("MARKER_ALPHA = 1\nMARKER_GAMMA = 3\n")
    _run("commit", "-am", "feat: gamma", cwd=repo)
    ref = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    _run("checkout", "main", cwd=repo)
    (repo / "feature.py").write_text("MARKER_ALPHA = 1\nMARKER_GAMMA = 3\nlater = 1\n")
    _run("commit", "-am", "chore: main moves on", cwd=repo)
    _run("push", "origin", "main", cwd=repo)

    res = runner.invoke(
        app,
        ["git", "shipped", ref, "--target", "origin/main", "--grep", "MARKER_GAMMA"],
    )
    assert res.exit_code == 0
    assert "derived" in res.stdout
    assert "comparing the 1 file(s)" in res.stdout
    assert "feature.py" in res.stdout
    assert "untouched.py" not in res.stdout


def test_shipped_derives_paths_for_an_ancestor_ref(repo):
    """For an ancestor, merge-base==REF, so paths come from REF's first parent."""
    (repo / "feature.py").write_text("MARKER_ALPHA = 1\nMARKER_DELTA = 4\n")
    _run("commit", "-am", "feat: delta", cwd=repo)
    ref = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    (repo / "feature.py").write_text("MARKER_ALPHA = 1\nMARKER_DELTA = 4\nafter = 1\n")
    _run("commit", "-am", "chore: after", cwd=repo)
    _run("push", "origin", "main", cwd=repo)

    res = runner.invoke(
        app,
        ["git", "shipped", ref, "--target", "origin/main", "--grep", "MARKER_DELTA"],
    )
    assert res.exit_code == 0
    # Derivation must not collapse to "nothing to compare" for an ancestor.
    assert "nothing to compare" not in res.stdout
    assert "feature.py" in res.stdout


def test_shipped_flags_a_marker_reverted_after_it_landed(repo):
    """Reachable is not the same as still present -- a later revert must fail."""
    (repo / "feature.py").write_text("MARKER_ALPHA = 1\nMARKER_EPSILON = 5\n")
    _run("commit", "-am", "feat: epsilon", cwd=repo)
    ref = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    (repo / "feature.py").write_text("MARKER_ALPHA = 1\n")  # reverted later
    _run("commit", "-am", "revert: drop epsilon", cwd=repo)
    _run("push", "origin", "main", cwd=repo)

    res = runner.invoke(
        app,
        ["git", "shipped", ref, "--target", "origin/main", "--grep", "MARKER_EPSILON"],
    )
    assert res.exit_code == 1
    assert "ABSENT" in res.stdout


def test_shipped_fails_when_the_marker_never_landed(repo):
    """A marker absent from the target is a real negative, and exits non-zero."""
    res = runner.invoke(
        app,
        [
            "git",
            "shipped",
            "HEAD",
            "feature.py",
            "--target",
            "origin/main",
            "--grep",
            "MARKER_NEVER",
        ],
    )
    assert res.exit_code == 1
    assert "ABSENT" in res.stdout


def test_unmerged_reads_remote_refs_not_stale_local_ones(repo):
    """The bug this exists for: a stale local ref makes a branch look merged."""
    _run("checkout", "-b", "wip", cwd=repo)
    (repo / "other.py").write_text("x = 1\n")
    _run("add", "-A", cwd=repo)
    _run("commit", "-m", "feat: wip", cwd=repo)
    _run("push", "-u", "origin", "wip", cwd=repo)
    _run("checkout", "main", cwd=repo)

    res = runner.invoke(app, ["git", "unmerged", "main", "--no-fetch"])
    assert res.exit_code == 0
    assert "wip" in res.stdout


# --- sweep -------------------------------------------------------------------


def _sweep_repo(repo):
    """Add branches covering each class sweep must distinguish."""
    # contained: merged into main
    _run("checkout", "-q", "-b", "done", cwd=repo)
    (repo / "done.py").write_text("x = 1\n")
    _run("add", "-A", cwd=repo)
    _run("commit", "-m", "feat: done", cwd=repo)
    _run("checkout", "-q", "main", cwd=repo)
    _run("merge", "--no-ff", "-m", "merge done", "done", cwd=repo)
    # unknown: real unmerged work, same era as main
    _run("checkout", "-q", "-b", "live", cwd=repo)
    (repo / "live.py").write_text("y = 2\n")
    _run("add", "-A", cwd=repo)
    _run("commit", "-m", "feat: live", cwd=repo)
    _run("checkout", "-q", "main", cwd=repo)
    _run("push", "-q", "origin", "main", "done", "live", cwd=repo)
    _run("fetch", "-q", "--prune", "origin", cwd=repo)


def test_sweep_classifies_contained_and_unknown(repo):
    _sweep_repo(repo)
    res = runner.invoke(app, ["git", "sweep", "--no-check-requests", "--no-fetch"])
    assert res.exit_code == 0, res.stdout
    assert "CONTAINED" in res.stdout
    assert "UNKNOWN" in res.stdout
    assert "DRY RUN" in res.stdout


def test_sweep_is_dry_by_default(repo):
    """Nothing is deleted without --apply, even the provably safe class."""
    _sweep_repo(repo)
    res = runner.invoke(
        app, ["git", "sweep", "--no-check-requests", "--no-fetch", "--non-interactive"]
    )
    assert res.exit_code == 0
    out = subprocess.run(
        ["git", "ls-remote", "--heads", "origin"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout
    assert "refs/heads/done" in out


def test_sweep_apply_deletes_only_contained(repo):
    """--non-interactive takes exactly CONTAINED; unmerged work survives."""
    _sweep_repo(repo)
    res = runner.invoke(
        app,
        [
            "git",
            "sweep",
            "--no-check-requests",
            "--no-fetch",
            "--non-interactive",
            "--apply",
        ],
    )
    assert res.exit_code == 0, res.stdout
    out = subprocess.run(
        ["git", "ls-remote", "--heads", "origin"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout
    assert "refs/heads/done" not in out
    assert "refs/heads/live" in out
    assert "refs/heads/main" in out


def test_sweep_writes_manifest_with_shas(repo):
    """The manifest exists before deletion and carries a restorable SHA."""
    _sweep_repo(repo)
    sha = subprocess.run(
        ["git", "rev-parse", "origin/done"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout.strip()
    runner.invoke(
        app,
        [
            "git",
            "sweep",
            "--no-check-requests",
            "--no-fetch",
            "--non-interactive",
            "--apply",
        ],
    )
    manifests = list((repo / ".git" / "odoo-dev").glob("sweep-*.tsv"))
    assert len(manifests) == 1
    body = manifests[0].read_text()
    assert sha in body
    assert "done\t" in body
    # and that SHA really does bring it back
    _run("push", "origin", f"{sha}:refs/heads/done", cwd=repo)
    out = subprocess.run(
        ["git", "ls-remote", "--heads", "origin"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout
    assert "refs/heads/done" in out


def test_sweep_flags_stale_by_base(repo):
    """A branch cut before a mass tree change is STALE-BY-BASE, not UNKNOWN.

    This is the class that age cannot detect: the branch below is the newest in
    the repo and still must never be merged, because it predates files main
    owns.
    """
    for i in range(60):
        (repo / f"vendored_{i}.py").write_text(f"V = {i}\n")
    _run("add", "-A", cwd=repo)
    _run("commit", "-m", "chore: vendor the tree", cwd=repo)
    _run("push", "-q", "origin", "main", cwd=repo)
    # branch from BEFORE that commit, then add something new to it
    _run("checkout", "-q", "-b", "oldbase", "HEAD~1", cwd=repo)
    (repo / "late.py").write_text("late = True\n")
    _run("add", "-A", cwd=repo)
    _run("commit", "-m", "feat: late work on an old base", cwd=repo)
    _run("push", "-q", "origin", "oldbase", cwd=repo)
    _run("checkout", "-q", "main", cwd=repo)
    _run("fetch", "-q", "--prune", "origin", cwd=repo)

    res = runner.invoke(app, ["git", "sweep", "--no-check-requests", "--no-fetch"])
    assert res.exit_code == 0, res.stdout
    assert "STALE-BY-BASE" in res.stdout
    # and it is never auto-selected
    res2 = runner.invoke(
        app, ["git", "sweep", "--no-check-requests", "--no-fetch", "--non-interactive"]
    )
    assert "oldbase" not in res2.stdout.split("selected:")[-1]
