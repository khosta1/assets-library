"""Open the browser window, out of process.

The window is PySide6 and Houdini 20.5 ships PySide2. Importing the bundled
PySide6 into Houdini's process puts two Qt libraries in one address space, which
does not raise - it crashes the host, usually later and somewhere unrelated. A
subprocess makes that impossible rather than unlikely.

It costs nothing: the browser never needed `hou`. What it does need is a way to
hand a choice back, and that is a file on disk rather than a socket - same rule
as everything else here, disk is the thing both sides agree on.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import hou

PICK_FILE = "pick.json"


def _root() -> Path:
    """The repo, from the env var the package file sets.

    Not derived from this file's location: the adapter has to keep working when
    the whole folder moves to another disk, which is the one thing this project
    promises. $ASSETLIB is set in packages/assets_library.json.
    """
    root = hou.text.expandString("$ASSETLIB")
    if not root or not Path(root).is_dir():
        raise hou.Error("$ASSETLIB is not set or does not exist - check "
                        "$HOUDINI_USER_PREF_DIR/packages/assets_library.json")
    return Path(root)


def browser() -> None:
    """Launch the library window and return immediately."""
    root = _root()
    python = root / "runtime" / "python.exe"
    if not python.is_file():
        raise hou.Error(f"no bundled runtime at {python} - runtime/ must travel "
                        "with the repo, it is gitignored but not optional")

    # CREATE_NO_WINDOW: a console flashing up in front of Houdini is the kind of
    # thing that makes a tool feel broken even when it works.
    flags = 0x08000000 if sys.platform == "win32" else 0
    subprocess.Popen([str(python), "-m", "ui.app"], cwd=str(root),
                     creationflags=flags)


def last_pick() -> dict | None:
    """What the browser last asked to be built, or None.

    Written by the window, read here. Not consumed: re-running the build tool
    on the same pick is a thing someone will want to do.
    """
    import json

    path = _root() / ".assetlib" / PICK_FILE
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                # noqa: BLE001
        return None
