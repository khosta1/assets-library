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
import subprocess
import sys
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


def _unsafe(files, root: Path) -> list:
    out = []
    for path in files:
        parts = path.relative_to(root).parts
        if any(p in FORBIDDEN for p in parts[:-1]) or parts[0] in FORBIDDEN:
            out.append(path)
    return out


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return ""


def build(dry_run: bool = False, out_dir: Path | None = None) -> int:
    files, total = deploy.plan(ROOT, include_dev=False)
    if not files:
        print("nothing to pack - is this the project root?")
        return 1

    bad = _unsafe(files, ROOT)
    if bad:
        # Loud and fatal. This is the check that matters: everything else here
        # is packaging, and this is the one that stops a credential or 44 GB of
        # assets reaching a public URL.
        print(f"REFUSING: {len(bad)} file(s) under {FORBIDDEN} would be packed.")
        for path in bad[:10]:
            print("   ", path.relative_to(ROOT))
        print("\nassetlib/deploy.py SKIP_DIRS is supposed to exclude these. "
              "Fix it there, not here.")
        return 2

    tag = version()
    print(f"{len(files)} files, {human(total)} uncompressed, from {tag}")
    if tag.endswith("-dirty"):
        print("  the working tree has uncommitted changes - the archive will "
              "not match any commit")

    runtime = sum(f.stat().st_size for f in files
                  if f.relative_to(ROOT).parts[0] == "runtime")
    print(f"  of which runtime/: {human(runtime)} "
          f"({100 * runtime / total:.0f}%)")

    if dry_run:
        print("\ndry run - nothing written. Top-level entries:")
        tops = sorted({f.relative_to(ROOT).parts[0] for f in files})
        for name in tops:
            size = sum(f.stat().st_size for f in files
                       if f.relative_to(ROOT).parts[0] == name)
            print(f"   {name:<28} {human(size)}")
        print(f"\n   plus empty: {', '.join(EMPTY_ROOTS)}")
        return 0

    out_dir = Path(out_dir) if out_dir else ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"AssetLibrary-{tag}.zip"

    # ZIP_DEFLATED, not stored: the runtime is mostly already-compressed .pyd
    # and .dll, but config, docs and the Python source do compress, and a
    # reader on a slow link pays for every megabyte once.
    done = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as zf:
        for path in files:
            zf.write(path, f"{FOLDER}/{path.relative_to(ROOT).as_posix()}")
            done += 1
            if done % 500 == 0:
                print(f"   {done}/{len(files)}")
        for name in EMPTY_ROOTS:
            zf.writestr(zipfile.ZipInfo(f"{FOLDER}/{name}/"), b"")

    print(f"\nwrote {target}  ({human(target.stat().st_size)})")
    print("Attach it to a GitHub release. A reader unzips it, runs "
          "'Asset Library.vbs', and types the address and their token.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would be packed, write nothing")
    ap.add_argument("--out", default="", help="directory for the zip")
    args = ap.parse_args()
    return build(dry_run=args.dry_run, out_dir=Path(args.out) if args.out else None)


if __name__ == "__main__":
    raise SystemExit(main())
