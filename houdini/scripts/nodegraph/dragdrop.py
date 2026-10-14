"""Drops onto the network editor: library tiles, then everyone else's.

Houdini's network editor calls the FIRST scripts/nodegraph/dragdrop.py on the
path, so this file REPLACES SideFX's - deliberately, and only safely because
of how it answers when the drag is not ours:

  * 21.0.512: SideFX's file is a stub (`_EXPERIMENTAL_DRAG_AND_DROP = False`,
    every call answers "not mine"). Answering "not mine" here is identical.
  * 22.0.368: SideFX's file is a thin delegator to the `nodegraphdrop`
    registry, and their docstring warns that replacing the file opts out of
    the registry - every other package's drop handlers would go dark. So a
    drag that is not ours is handed to the registry exactly as theirs does.

If a later build's SideFX file does more than either, this one is stale: diff
it against $HFS/houdini/scripts/nodegraph/dragdrop.py on every Houdini update.

Ours is checked FIRST, and claims only a payload carrying the library's marker
(assetlib_hou/drop.py). Measured in Houdini 21, 2026-10-14: both the
standalone window and the panel reach this file, and claiming the drag here is
what stops Houdini opening a dragged asset.json as a scene.
"""

try:
    import nodegraphdrop                    # 22+
except ImportError:
    nodegraphdrop = None                    # 21

from assetlib_hou import drop


def dropTest(pane, source, position):
    if drop.payload(source):
        return True, False
    if nodegraphdrop is not None and nodegraphdrop.dispatchTest(pane, source, position):
        return True, False
    return False, True


def dropGetChoices(pane, source, position):
    if drop.payload(source):
        return drop.choices(pane, source, position)
    if nodegraphdrop is not None:
        return nodegraphdrop.dispatchChoices(pane, source, position)
    return [], [], []


def dropAccept(pane, source, position, token):
    if drop.payload(source):
        return drop.accept(pane, source, position, token)
    if nodegraphdrop is not None:
        return nodegraphdrop.dispatchAccept(pane, source, position, token)
    return False
