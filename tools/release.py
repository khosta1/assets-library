"""Build the distributable archive — the app and its runtime, ready to unzip.

The missing step between "the library is reachable" and "a stranger can use
it". The Funnel removes the network setup; per-reader tokens decide who may;
and this removes the USB stick. A reader downloads one zip, unpacks it, opens
`Asset Library.vbs` and types two things.

**GitHub cannot do this job on its own.** `runtime/` is gitignored - correctly,
it is 300 MB of bundled Python - so a clone gets the code and nothing that runs
it. A release asset can carry both.

**What travels is not decided here.** `assetlib/deploy.py` already owns that
question for *Create a new library…*, and a second list in this file would be
the same mistake twice over: it would agree on the day it was written and drift
the first time someone adds a generated folder. So this calls `deploy.plan()`
and packs exactly what the dialog would have copied.

**One thing this file does own, because the consequence is different.** A copy
made by the dialog goes onto a disk Felix is holding; this archive goes onto a
public download page, where a mistake is permanent - caches, forks and mirrors
outlive any deletion. So it refuses to write an archive containing anything
under `.assetlib/` or `library/`, by inspecting the file list rather than by
trusting that the rules upstream are still right.

Run:
    tools\\release.bat --dry-run     what would go in, and what the zip costs
    tools\\release.bat               write it into dist\\
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assetlib import deploy                                      # noqa: E402

# The folder a reader ends up with. Named inside the zip so unpacking gives one
# directory rather than four thousand loose files in Downloads.
FOLDER = "Assets_library"

# Created as directory entries so the unpacked folder looks finished rather
# than sprouting directories on first launch. `ensure_roots()` would make them
# anyway; this is the same argument deploy.EMPTY_ROOTS makes.
EMPTY_ROOTS = deploy.EMPTY_ROOTS

# Never, whatever the rules upstream say. Checked against the assembled file
# list, not assumed: `.assetlib/` holds the server token and `library/` holds
# the assets, and either one on a public download page cannot be recalled.
FORBIDDEN = (".assetlib", "library", "_cache", ".git")


def _git(*args) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                             text=True, timeout=20)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def version() -> str:
    """The commit this archive is built from, plus a warning if it is not one.

    A release built from a dirty tree is not reproducible from the repository,
    and someone will eventually ask which code is in it. `-dirty` in the
    filename answers that honestly instead of implying a commit that does not
    describe the contents.
    """
    sha = _git("rev-parse", "--short", "HEAD") or "nogit"
    dirty = bool(_git("status", "--porcelain"))
    return f"{sha}-dirty" if dirty else sha


def _checkout(ref: str):
    """A clean tree at `ref`, so an archive never carries somebody's edits.

    The first version of this packed the working tree, and on the day it was
    written that tree held four modified files and two untracked modules from
    another session. A release built then would have published unreviewed code
    to a public download page - and `-dirty` in the filename would have been
    honest about it without making it any less wrong.

    A detached worktree rather than `git archive`, because the point of this
    whole file is that `deploy.plan()` decides what travels; a tar would have to
    be filtered by hand and the rules would start drifting immediately.

    `runtime/` is gitignored, so it is not in any commit and has to come from
    the real root. That is the one thing an archive carries which no commit
    describes, which is also why a copy of the app can never be rebuilt from
    GitHub alone.
    """
    tmp = Path(tempfile.mkdtemp(prefix="assetlib-release-"))
    tree = tmp / "tree"
    out = subprocess.run(["git", "worktree", "add", "--detach", str(tree), ref],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SystemExit(f"could not check out {ref}:\n{out.stderr.strip()}")
    return tmp, tree


def _release_worktree(tmp: Path, tree: Path) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(tree)],
                   cwd=ROOT, capture_output=True, text=True)
    shutil.rmtree(tmp, ignore_errors=True)


def _unsafe(names) -> list:
    """Archive paths that must never be published, whatever the rules upstream say."""
    out = []
    for name in names:
        parts = name.split("/")
        if any(p in FORBIDDEN for p in parts[:-1]) or parts[0] in FORBIDDEN:
            out.append(name)
    return out


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return ""


def _entries(ref: str, working_tree: bool):
    """[(source, archive path)], plus the worktree to clean up afterwards.

    Two sources, and only one of them is a commit. Everything tracked comes from
    a clean checkout; `runtime/` comes from this folder, because it is
    gitignored and therefore in no commit at all. That split is the whole reason
    a reader cannot be served by GitHub alone.
    """
    if working_tree:
        files, total = deploy.plan(ROOT, include_dev=False)
        return ([(f, f.relative_to(ROOT).as_posix()) for f in files],
                total, None, None)

    tmp, tree = _checkout(ref)
    files, total = deploy.plan(tree, include_dev=False)

    # In a worktree `.git` is a FILE holding a gitdir: pointer, not a directory.
    # deploy.SKIP_DIRS lists it, but _skipped() matches a file against its
    # PARENT components only, so a plain file of that name slips through - a
    # case deploy.py never meets, because Create a new library... always runs
    # against a normal checkout. Dropped here, where the worktree knowledge is.
    # The refusal in _unsafe() caught it first, which is the only reason this
    # was found before an archive was published rather than after.
    pairs = [(f, f.relative_to(tree).as_posix()) for f in files
             if f.relative_to(tree).parts[0] != ".git"]
    total = sum(src.stat().st_size for src, _ in pairs)

    # plan() over the real root and keep only runtime/ - the public call rather
    # than deploy's private filter, so __pycache__ inside site-packages is
    # dropped by the same rules as everything else.
    here, _ = deploy.plan(ROOT, include_dev=False)
    for f in here:
        rel = f.relative_to(ROOT)
        if rel.parts[0] == "runtime":
            pairs.append((f, rel.as_posix()))
            total += f.stat().st_size
    return pairs, total, tmp, tree


def build(dry_run: bool = False, out_dir=None, ref: str = "HEAD",
          working_tree: bool = False) -> int:
    pairs, total, tmp, tree = _entries(ref, working_tree)
    try:
        if not pairs:
            print("nothing to pack - is this the project root?")
            return 1

        bad = _unsafe(name for _, name in pairs)
        if bad:
            # Loud and fatal. Everything else here is packaging; this is the
            # check that stops a credential or 44 GB of assets reaching a
            # public URL, and it is checked against the assembled list rather
            # than trusted from upstream.
            print(f"REFUSING: {len(bad)} path(s) under {FORBIDDEN} would be packed.")
            for name in bad[:10]:
                print("   ", name)
            print("\nassetlib/deploy.py SKIP_DIRS is supposed to exclude these. "
                  "Fix it there, not here.")
            return 2

        if working_tree:
            tag = version()
        else:
            tag = _git("rev-parse", "--short", ref) or "nogit"

        print(f"{len(pairs)} files, {human(total)} uncompressed, from {tag}")
        if working_tree:
            print("  packing the WORKING TREE - whatever is on disk right now, "
                  "including anything another session is mid-edit on")

        runtime = sum(src.stat().st_size for src, name in pairs
                      if name.split("/")[0] == "runtime")
        print(f"  of which runtime/: {human(runtime)} "
              f"({100 * runtime / total:.0f}%)")

        if dry_run:
            print("\ndry run - nothing written. Top-level entries:")
            tops = sorted({name.split("/")[0] for _, name in pairs})
            for top in tops:
                size = sum(src.stat().st_size for src, name in pairs
                           if name.split("/")[0] == top)
                print(f"   {top:<34} {human(size)}")
            print(f"\nplus empty: {', '.join(EMPTY_ROOTS)}")
            return 0

        out_dir = Path(out_dir) if out_dir else ROOT / "dist"
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"AssetLibrary-{tag}.zip"

        # ZIP_DEFLATED, not stored: the runtime is mostly already-compressed
        # .pyd and .dll, but the Python source, config and icons do compress,
        # and a reader on a slow link pays for every megabyte once.
        done = 0
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            for src, name in pairs:
                zf.write(src, f"{FOLDER}/{name}")
                done += 1
                if done % 1000 == 0:
                    print(f"   {done}/{len(pairs)}")
            for name in EMPTY_ROOTS:
                zf.writestr(zipfile.ZipInfo(f"{FOLDER}/{name}/"), b"")

        print(f"\nwrote {target}  ({human(target.stat().st_size)})")
        print("Attach it to a GitHub release. A reader unzips it, runs "
              "'Asset Library.vbs', and types the address and their token.")
        return 0
    finally:
        if tree is not None:
            _release_worktree(tmp, tree)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would be packed, write nothing")
    ap.add_argument("--ref", default="HEAD",
                    help="commit to pack (default HEAD, via a clean checkout)")
    ap.add_argument("--working-tree", action="store_true",
                    help="pack what is on disk instead of a commit - for a "
                         "local look, never for a release")
    ap.add_argument("--out", default="", help="directory for the zip")
    args = ap.parse_args()
    return build(dry_run=args.dry_run,
                 out_dir=Path(args.out) if args.out else None,
                 ref=args.ref, working_tree=args.working_tree)


if __name__ == "__main__":
    raise SystemExit(main())
