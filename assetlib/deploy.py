"""Making a second copy of this app somewhere else.

The project is portable by design - code, bundled runtime and library travel
together - but "portable" has so far meant "copy the folder and know which
subfolders to leave behind". That knowledge lived in one person's head and in a
robocopy line in a chat window, which is exactly the kind of thing that is
wrong the third time it is done.

What a new copy is:

    runtime/        the bundled Python. Without it nothing launches at all.
    assetlib/ ui/ houdini/ config/      the app
    library/ _cache/ _inbox/ _quarantine/       created, empty

What it is NOT: the assets, the index, the thumbnails, the git history, the
token. Those are either enormous, rebuildable, or a credential.

No Qt here, so the decision about what travels is testable and lives beside the
config it reads rather than inside a dialog.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Directories never copied, matched at any depth.
#
# library/ and _cache/ hold the assets and are the whole point of not copying -
# 39 GB here. .assetlib/ is a cache that rebuilds itself and holds the token.
# .git/ is this project's history and has no business on a working drive.
SKIP_DIRS = {
    "library", "_cache", "_inbox", "_quarantine", ".assetlib",
    ".git", "__pycache__", "context", "logs", ".claude", ".pytest_cache",
}

# Developer scaffolding. Useful in a working copy, noise in one handed to
# somebody who just wants to browse assets.
#
# server/ is in here because it is the OTHER half of the system: it is deployed
# by hand to /opt/assetlib on the box and has no business running on a client.
# Shipping it with a copy handed to someone would be shipping them the
# machinery of a service they are only ever a reader of.
DEV_DIRS = {"docs", "tools", "Build_docs", "server"}
DEV_FILES = {"CLAUDE.md", "ROADMAP.md", "packs.json", ".gitignore"}

SKIP_FILES = {"seed.log", "launch.log", "desktop.ini", "Thumbs.db"}
SKIP_SUFFIXES = {".pyc", ".lnk"}

# Created empty in the new copy. ensure_roots() would make them on first launch
# anyway; making them here means the folder looks finished when it is handed
# over, rather than sprouting directories the first time it runs.
EMPTY_ROOTS = ("library", "_cache", "_inbox", "_quarantine")


def _skipped(path: Path, root: Path, include_dev: bool) -> bool:
    rel = path.relative_to(root)
    for part in rel.parts[:-1] if path.is_file() else rel.parts:
        if part in SKIP_DIRS or (not include_dev and part in DEV_DIRS):
            return True
    if path.is_file():
        if path.name in SKIP_FILES or path.suffix.lower() in SKIP_SUFFIXES:
            return True
        if not include_dev and rel.parts[0] in DEV_FILES and len(rel.parts) == 1:
            return True
    return False


def plan(src: Path, include_dev: bool = False) -> tuple:
    """(files, total_bytes) that a copy would move. Reads nothing but names."""
    src = Path(src).resolve()
    files, total = [], 0
    for path in src.rglob("*"):
        if not path.is_file() or _skipped(path, src, include_dev):
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
        files.append(path)
    return files, total


def check_destination(src: Path, dest: Path) -> str:
    """'' when the destination is usable, otherwise why it is not.

    Checked before a single byte moves. Copying a folder into itself is the
    mistake that has no undo - it recurses until the disk is full - and it is
    easy to make with a file picker, because `H:/Code/Assets_library/new` looks
    like a perfectly ordinary empty folder.
    """
    src = Path(src).resolve()
    dest = Path(dest).resolve()
    if dest == src:
        return "That is this library itself."
    if src in dest.parents:
        return ("That folder is inside this library. Copying a folder into "
                "itself never finishes - pick somewhere outside it.")
    if dest.exists() and any(dest.iterdir()):
        return "That folder is not empty. Pick an empty or a new folder."
    return ""


def copy_install(src: Path, dest: Path, include_dev: bool = False,
                 on_file=None, should_stop=None) -> dict:
    """Copy the app to `dest` and create its empty roots.

    `on_file(done, total, name)` is called per file so a dialog can show
    progress; `should_stop()` is polled so it can be cancelled. Both optional,
    and both are the caller's problem to make thread-safe.
    """
    src = Path(src).resolve()
    dest = Path(dest).resolve()
    files, total_bytes = plan(src, include_dev)

    dest.mkdir(parents=True, exist_ok=True)
    done = 0
    for path in files:
        if should_stop is not None and should_stop():
            return {"copied": done, "of": len(files), "bytes": total_bytes,
                    "cancelled": True, "dest": dest}
        target = dest / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        # copy2 keeps mtimes, which is what makes a later robocopy or a sync
        # tool see the copy as identical rather than as 900 changed files.
        shutil.copy2(path, target)
        done += 1
        if on_file is not None:
            on_file(done, len(files), path.name)

    for name in EMPTY_ROOTS:
        (dest / name).mkdir(exist_ok=True)

    return {"copied": done, "of": len(files), "bytes": total_bytes,
            "cancelled": False, "dest": dest}


def suggest_host(dest: Path, name: str, url: str) -> None:
    """Leave the server's ADDRESS in the new copy, and never its token.

    So the person receiving it is asked for one thing instead of three, and the
    credential is handed over separately - by voice, by message, by anything
    that is not a drive left on a desk. `first_run` treats a host with no token
    as "not configured yet" for exactly this reason, so the setup panel still
    appears with the address already filled in.
    """
    from . import remote

    class _Base:
        pass

    cfg = _Base()
    cfg.state = Path(dest) / ".assetlib"
    cfg.remote_dir = lambda: cfg.state / "remote"
    remote.save_hosts(cfg, [remote.Host(name=name, url=url, token="")])
