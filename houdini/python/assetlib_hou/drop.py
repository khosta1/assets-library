"""Tiles dropped from the library onto a network editor.

Called from `houdini/scripts/nodegraph/dragdrop.py`, which Houdini's network
editor calls for every drag over it. The drag comes from either window - the
standalone browser in its own process or the panel in this one - and arrives
the same way: JSON text under `application/json`, carrying the marker below.

What a drop does is what right-click -> Import to Houdini does, plus a place:
the same options window (`ui.import_houdini.ask_and_send`), the same builder,
and the nodes put where the mouse let go. Everything after the drop runs HERE,
in Houdini's interpreter; the window the tile came from only supplied the JSON.

Measured, not assumed - a probe in Houdini 21.0.512 on 2026-10-14:

  * `source.data("application/json")` yields the payload as one string.
    `text/uri-list` and custom MIME types report hasData and yield nothing.
  * `position` is SCREEN pixels, e.g. (2886, 623). `pane.cursorPosition()`
    is the same point in network coordinates, and is what nodes are placed by.
  * Claiming the drag in dropTest stops Houdini's own file drop. Left to it,
    a dragged asset.json was opened as a scene and failed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

MARKER = "assetlib/assets"                  # = ui.gridmodel.DRAG_MARKER
MIME = "application/json"                   # = ui.gridmodel.DRAG_MIME
TOKEN = "import"

# Material library selected while our drag hovers: (path, when last seen).
# Read on hover, not at the drop: by the time the deferred build ran, the
# selection no longer held it and a texture set made a new library instead
# (build.dropped_matlib). Kept HOVER_KEEP seconds after it was last seen -
# long enough to outlive whatever the release does to the selection, short
# enough that a cancelled drag cannot hand its library to the next one.
_hover = (None, 0.0)
HOVER_KEEP = 1.0


def payload(source) -> dict | None:
    """Our drag's JSON, or None when the drag is anybody else's.

    Read on every hover move while a drag crosses the editor, so it must stay
    cheap and must never raise: a raise here would be a broken drop for
    whatever else is being dragged.
    """
    try:
        if not source.hasData(MIME):
            return None
        for text in source.data(MIME):
            data = json.loads(text)
            if isinstance(data, dict) and data.get("type") == MARKER and data.get("assets"):
                return data
    except Exception:                               # noqa: BLE001
        return None
    return None


def test(pane, source, position):
    """(handled here, allow Houdini's default). Ours: (True, False) - see top."""
    if not payload(source):
        return False, True
    global _hover
    path = _selected_matlib()
    if path:
        _hover = (path, time.monotonic())
    return True, False


def _recent_matlib():
    path, seen = _hover
    return path if path and time.monotonic() - seen < HOVER_KEEP else None


def _selected_matlib():
    try:
        from . import build

        lib = build.selected_matlib()
        return lib.path() if lib is not None else None
    except Exception:                               # noqa: BLE001
        return None


def choices(pane, source, position):
    # One entry: Houdini shows no menu for a single choice.
    return [TOKEN], ["Import to Houdini…"], ["Build with the library's import options"]


def accept(pane, source, position, token):
    data = payload(source)
    if data is None:
        return False

    import hdefereval

    # Read NOW: the options window opens after this returns, and by then the
    # cursor is wherever the user moved it to click OK.
    global _hover
    matlib, _hover = _selected_matlib() or _recent_matlib(), (None, 0.0)
    try:
        at = pane.cursorPosition()
        drop = {"network": pane.pwd().path(), "pos": [at[0], at[1]],
                "matlib": matlib}
    except Exception:                               # noqa: BLE001
        # still builds, placed as before - and still into the chosen library
        drop = {"matlib": matlib} if matlib else None
    dirs = [Path(a["dir"]) for a in data["assets"] if a.get("dir")]

    # Deferred, never opened from in here. This runs inside the drag: from
    # the standalone window, the OS holds that window's drag open until this
    # returns, so a modal dialog here would freeze it until OK was pressed.
    hdefereval.executeDeferred(_run, dirs, drop)
    return True


def _run(dirs, drop) -> None:
    import hou
    from PySide6.QtWidgets import QMessageBox

    from assetlib.config import find_config
    from assetlib.model import Asset
    from ui.import_houdini import ask_and_send, buildable

    parent = hou.qt.mainWindow()
    cfg = find_config()
    assets, unreadable, skipped = [], [], 0
    for path in dirs:
        try:
            asset = Asset.read(path)
        except Exception as exc:                    # noqa: BLE001
            unreadable.append(f"{path.name}: {exc}")
            continue
        if buildable(asset):
            assets.append((asset, path))
        else:
            # Same rule as right-click: an IES profile or a script in a
            # dragged batch is skipped, not a reason to refuse the batch.
            skipped += 1

    if not assets:
        QMessageBox.information(
            parent, "Nothing to build",
            "None of the dropped assets is something Houdini builds - a mesh, "
            "an HDRI or a texture set." + _lines(unreadable))
        return

    result = ask_and_send(assets, cfg, parent, drop=drop)
    if result is None:
        return
    built, failed = result
    failed += unreadable
    if failed:
        QMessageBox.warning(parent, "Some assets did not build",
                            f"{built} built, {len(failed)} failed." + _lines(failed))
    note = f"assetlib: sent {built} asset(s)"
    if skipped:
        note += f", skipped {skipped} Houdini does not build"
    hou.ui.setStatusMessage(note)


def _lines(items) -> str:
    return ("\n\n" + "\n".join(items[:10])) if items else ""
