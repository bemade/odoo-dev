"""``odoo-dev git`` — ref hygiene and honest "did this ship?" answers.

Three questions this repeatedly gets wrong in a multi-branch Odoo project, and
the traps behind each:

**"Is this branch merged?"**  ``git branch --no-merged`` reads *local* refs. A
local branch that is behind its origin counterpart is reported as merged while
origin's tip is not, so the local form is the optimistic lie. Always fetch and
ask against remote refs.

**"Did this feature ship?"**  ``--contains`` / ``--no-merged`` answer a question
about *object identity*, not content. Anything squashed, cherry-picked or
re-created reads as unmerged forever even when the code is live. The only
honest answer diffs the files.

**"What are these stale refs?"**  Per-task clone workflows leave orphaned
remote-tracking refs behind. ``fetch --prune`` cannot clean them, because there
is no configured remote left to prune against -- they simply persist, and show
up in every ref listing as branches that do not exist.
"""

import subprocess
from typing import Annotated, Optional

import typer

from odoo_dev.utils.console import error, info, success, warning

app = typer.Typer(
    name="git", help="Git ref hygiene and merge-state answers.", no_args_is_help=True
)


def _git(*args: str, check: bool = True) -> str:
    """Run a git command and return stripped stdout."""
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return r.stdout.strip()


def _ok(*args: str) -> bool:
    """True when the git command exits 0 (for --is-ancestor and friends)."""
    return (
        subprocess.run(["git", *args], capture_output=True, text=True).returncode == 0
    )


def _configured_remotes() -> set[str]:
    return {ln for ln in _git("remote").splitlines() if ln}


@app.command(name="prune-refs")
def prune_refs(
    apply: Annotated[
        bool, typer.Option("--apply", help="Actually delete. Default is a dry run.")
    ] = False,
    namespaces: Annotated[
        Optional[str],
        typer.Option(
            "--namespaces",
            help="Comma-separated extra ref namespaces to sweep, e.g. 'refs/test,refs/wip'.",
        ),
    ] = None,
) -> None:
    """Delete remote-tracking refs whose remote no longer exists, plus custom namespaces.

    Per-task clone workflows leave refs like
    ``refs/remotes/task-3629/feature/...`` behind. ``git fetch --prune`` never
    removes them: pruning happens per configured remote, and that remote is
    gone, so nothing owns them. They then show up forever in ref listings and
    in any script that walks ``refs/remotes``.

    Dry-run by default. Deletion of a ref is not recoverable through the reflog
    once the objects are gc'd, so nothing is removed without ``--apply``.
    """
    remotes = _configured_remotes()
    if not remotes:
        error("no configured remotes -- refusing to guess what is stale")
        raise typer.Exit(2)

    info(f"configured remotes: {', '.join(sorted(remotes))}")

    doomed: list[str] = []
    for ref in _git("for-each-ref", "--format=%(refname)", "refs/remotes").splitlines():
        # refs/remotes/<remote>/<branch...>
        parts = ref.split("/", 3)
        if len(parts) < 4:
            continue
        if parts[2] not in remotes:
            doomed.append(ref)

    for ns in (n.strip() for n in (namespaces or "").split(",") if n.strip()):
        doomed.extend(
            r for r in _git("for-each-ref", "--format=%(refname)", ns).splitlines() if r
        )

    if not doomed:
        success("nothing stale -- every ref belongs to a configured remote")
        return

    warning(f"{len(doomed)} stale ref(s):")
    for r in doomed:
        info(f"  {r}")

    if not apply:
        info("\nDRY RUN -- nothing deleted. Re-run with --apply.")
        return

    # update-ref requires FULLY-QUALIFIED refnames. It deliberately will not
    # DWIM-shorten the way checkout/log/branch do, because deleting the wrong
    # ref is unrecoverable -- so it refuses anything that is not already a
    # valid ref path rather than guessing the namespace.
    for r in doomed:
        _git("update-ref", "-d", r)
        success(f"deleted {r}")
    info("\nRun `git gc --prune=now` to reclaim the objects.")


@app.command()
def unmerged(
    target: Annotated[
        str, typer.Argument(help="Target branch, e.g. 19.0-prod")
    ] = "19.0-prod",
    remote: Annotated[str, typer.Option("--remote", help="Remote name")] = "origin",
    no_fetch: Annotated[
        bool, typer.Option("--no-fetch", help="Skip the fetch --prune first")
    ] = False,
) -> None:
    """List remote branches not merged into TARGET, using remote refs only.

    This is the form that tells the truth. ``git branch --no-merged`` consults
    local refs, which are only as good as your last fetch: a local branch
    sitting behind its origin counterpart is reported as merged while origin's
    tip is not, and nothing warns you. That discrepancy is how a stale tip gets
    merged into a release and quietly drops commits.

    Object identity only, so treat the output as candidates. A squashed or
    cherry-picked branch appears here forever -- confirm with ``git shipped``.
    """
    if not no_fetch:
        info(f"fetching {remote} --prune ...")
        _git("fetch", "--prune", "--quiet", remote)

    tgt = f"{remote}/{target}"
    if not _ok("rev-parse", "--verify", tgt):
        error(f"{tgt} does not exist")
        raise typer.Exit(2)

    rows: list[tuple[str, str, str]] = []
    for line in _git(
        "for-each-ref",
        "--format=%(refname:short)%09%(committerdate:short)%09%(authorname)",
        f"refs/remotes/{remote}",
    ).splitlines():
        ref, date, author = (line.split("\t") + ["", ""])[:3]
        short = ref[len(remote) + 1 :]
        if short in ("HEAD", target):
            continue
        if _ok("merge-base", "--is-ancestor", ref, tgt):
            continue
        rows.append((short, date, author))

    if not rows:
        success(f"every {remote} branch is merged into {target}")
        return

    warning(f"{len(rows)} branch(es) not merged into {target} (by object identity):")
    for short, date, author in sorted(rows, key=lambda r: r[1], reverse=True):
        info(f"  {date}  {short:<52} {author}")
    info(
        "\nSquashed/cherry-picked work also lands here. Verify with `odoo-dev git shipped`."
    )


@app.command()
def shipped(
    ref: Annotated[str, typer.Argument(help="Branch or commit that may have shipped")],
    paths: Annotated[
        Optional[list[str]],
        typer.Argument(
            help="Files/dirs to compare. Omit to use the files REF itself changed."
        ),
    ] = None,
    target: Annotated[
        str, typer.Option("--target", help="Where it should have landed")
    ] = "origin/19.0-prod",
    grep: Annotated[
        Optional[list[str]],
        typer.Option(
            "--grep",
            help="Marker string that must appear in TARGET's copy. Repeatable. "
            "This is what actually settles 'did it ship' when paths differ.",
        ),
    ] = None,
) -> None:
    """Did REF's work reach TARGET? Answered by content, never by ancestry.

    ``--contains`` and ``--no-merged`` compare commit objects, so a squashed,
    cherry-picked or re-created branch reads as unmerged even when its code is
    live in production -- and as a result people go looking for "missing"
    features that shipped months ago.

    With no paths given it derives them -- the files REF itself changed -- which
    is almost always the right set. It then diffs those between REF and TARGET
    and reports what actually differs. An empty diff means the content is identical. A non-empty diff is
    not proof of absence either: the target may simply have moved on since,
    which is why the per-path detail is printed rather than a verdict.
    """
    for r in (ref, target):
        if not _ok("rev-parse", "--verify", r):
            error(f"{r} does not exist")
            raise typer.Exit(2)

    # Ancestry is ASYMMETRIC evidence, which is the whole subtlety here.
    #
    #   True  -> conclusive. Every commit in REF is reachable from TARGET, so
    #            the work is there by definition. A content diff can only muddy
    #            a settled answer, because the target may have moved on and
    #            "differs" would then read as doubt.
    #   False -> proves nothing. Squashed, cherry-picked or re-created work is
    #            never an ancestor even when it is live in production. Fall
    #            through to content, which is the only honest test.
    is_ancestor = _ok("merge-base", "--is-ancestor", ref, target)

    if is_ancestor:
        success(
            f"{ref} IS an ancestor of {target} -- every commit is reachable, "
            f"so this work shipped."
        )
        if not grep:
            info("  Ancestry is conclusive in this direction; no content check needed.")
            return
        # `--grep` is an explicit content question, so honour it anyway: the
        # caller may be checking that a marker SURVIVED, not merely that the
        # commits landed. Reachable does not mean un-reverted.
        info(
            "  Ancestry settles reachability; checking your markers anyway, "
            "since a later commit can still have removed them."
        )
    else:
        info(f"ancestry: {ref} is NOT an ancestor of {target}")
        info("  (proves nothing on its own -- content below is what counts)")

    # Deriving the paths is almost always what you want: git already knows
    # which files REF touched, and naming them by hand risks checking the wrong
    # ones. A whole-tree path such as `.` always differs against a target that
    # has moved on, which cannot distinguish "did not ship" from "shipped, then
    # the repo continued".
    if not paths:
        if is_ancestor:
            # merge-base(REF, TARGET) == REF here, so that diff is empty by
            # construction. What REF *introduced* is the diff against its first
            # parent -- which for a merge commit is the branch it merged in.
            spec = (f"{ref}^1", ref)
        else:
            base = _git("merge-base", ref, target, check=False)
            if not base:
                error(
                    f"no common ancestor between {ref} and {target} -- pass paths explicitly"
                )
                raise typer.Exit(2)
            spec = (base, ref)
        paths = [
            p for p in _git("diff", "--name-only", *spec, check=False).splitlines() if p
        ]
        if not paths:
            success(f"{ref} changes no files -- nothing to compare.")
            return
        info(
            f"comparing the {len(paths)} file(s) {ref} changed "
            f"(derived; pass paths to override)"
        )
    elif any(p in (".", "./", "") for p in paths):
        warning(
            "  '.' compares the entire tree and will always differ -- omit the "
            "path argument to compare only what REF changed."
        )

    identical, differs, missing = [], [], []
    for p in paths:
        in_ref = _ok("cat-file", "-e", f"{ref}:{p}")
        in_tgt = _ok("cat-file", "-e", f"{target}:{p}")
        if in_ref and not in_tgt:
            missing.append(p)
        elif not _git("diff", "--name-only", ref, target, "--", p, check=False):
            identical.append(p)
        else:
            differs.append(p)

    for p in identical:
        success(f"  identical   {p}")
    for p in differs:
        warning(f"  differs     {p}")
    for p in missing:
        error(f"  ABSENT from {target}: {p}")

    # Markers are the decisive test when paths differ. A file that has moved on
    # still contains the feature's fingerprints if the feature shipped; if the
    # markers are gone, the work was reverted or never landed.
    missing_markers: list[str] = []
    if grep:
        info("")
        for pat in grep:
            hits = 0
            for p in paths:
                if not _ok("cat-file", "-e", f"{target}:{p}"):
                    continue
                body = _git("show", f"{target}:{p}", check=False)
                hits += sum(1 for ln in body.splitlines() if pat in ln)
            if hits:
                success(f"  marker present in {target}: {pat!r} ({hits} line(s))")
            else:
                error(f"  marker ABSENT from {target}: {pat!r}")
                missing_markers.append(pat)

    if missing:
        info(
            "\nPaths absent from the target are the real signal -- that work did not ship."
        )
        raise typer.Exit(1)
    if missing_markers:
        info(
            "\nMarkers absent -- this work is NOT in the target, whatever ancestry says."
        )
        raise typer.Exit(1)
    if grep and differs:
        if is_ancestor:
            success(
                "\nPaths differ because the target moved on, but every marker "
                "survived: the work is reachable AND still present."
            )
        else:
            success(
                "\nPaths differ but every marker is present: the work SHIPPED and "
                "the target has since moved on. This is exactly the case ancestry "
                "reports wrongly."
            )
        return
    if differs:
        info("\nDiffering paths may just mean the target moved on. Inspect with:")
        for p in differs:
            info(f"  git diff {ref} {target} -- {p}")
    else:
        success("\nEvery path matches -- this work is present in the target.")
