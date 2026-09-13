"""A small window that converts textures while Houdini stays usable.

The problem it solves: baking at build time froze Houdini. `iconvert` takes
~1 s on a 2K map and ~5 s on an 8K one, so the first import of a raw 8K scan
with seven maps locked the application for half a minute with nothing on screen
explaining why.

**Why this works rather than merely looking like it does.** The conversion is a
*subprocess*, and `assetlib.derived` imports no `hou`, so it is safe to run off
Houdini's main thread. The worker does the converting; the main thread does
nothing but pump events. Houdini is genuinely interactive - the viewport pans,
menus open - because the work is not on its thread, not because the wait has
been hidden.

What it is NOT is fire-and-forget. `karma_component()` returns the nodes it
built, and it cannot do that before the textures exist. So this blocks the
CALLER while leaving the APPLICATION responsive, which is the honest shape:
the import finishes when the bake finishes, and you can look around meanwhile.

Qt, not `hou.ui`: a progress window with a cancel button is a widget, and
Houdini's Python already has one of the two PySide bindings loaded.
"""

from __future__ import annotations

import time
from pathlib import Path

try:                                        # Houdini 20.5+ ships Qt6
    from PySide6 import QtCore, QtWidgets
except ImportError:                         # older builds ship Qt5
    from PySide2 import QtCore, QtWidgets   # type: ignore

from assetlib import derived
from assetlib.model import expand

POLL_MS = 30


def pending(asset, asset_dir: Path, rels, fmt: str = derived.DEFAULT_FORMAT) -> list:
    """The textures of this build that have no current bake yet.

    Asked before anything is shown, so an asset that is already baked opens no
    window at all - which is every build after the first, and the common case.
    """
    todo = []
    for rel in rels:
        if "<UDIM>" in rel:
            tiles = list(expand(asset, rel))
            if tiles and not all(
                derived.is_current(asset_dir / t,
                                   asset_dir / derived.derived_rel(t, fmt))
                for t in tiles
            ):
                todo.append(rel)
            continue
        src = asset_dir / rel
        if src.is_file() and not derived.is_current(
                src, asset_dir / derived.derived_rel(rel, fmt)):
            todo.append(rel)
    return todo


class _Signals(QtCore.QObject):
    step = QtCore.Signal(int, str)
    done = QtCore.Signal(list)              # rels that failed


class _Worker(QtCore.QRunnable):
    def __init__(self, asset, asset_dir, rels, fmt, signals):
        super().__init__()
        self.asset, self.asset_dir = asset, asset_dir
        self.rels, self.fmt, self.signals = rels, fmt, signals
        self.stop = False
        self.setAutoDelete(True)

    def run(self):
        failed = []
        for i, rel in enumerate(self.rels):
            if self.stop:
                break
            self.signals.step.emit(i, Path(rel).name)
            if "<UDIM>" in rel:
                out = derived.ensure_udim(self.asset, self.asset_dir, rel, self.fmt)
            else:
                out = derived.ensure(self.asset_dir, rel, self.fmt)
            if out is None:
                failed.append(rel)
        self.signals.done.emit(failed)


class BakeProgress(QtWidgets.QDialog):
    """Modeless on purpose - a modal dialog would block the very input this exists to preserve."""

    def __init__(self, name: str, count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preparing textures")
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(420)
        self.cancelled = False

        self.label = QtWidgets.QLabel(
            f"Baking {count} texture(s) for <b>{name}</b> into "
            "<code>derived/</code>.<br>"
            "Houdini stays usable — the nodes appear when this finishes.")
        self.label.setWordWrap(True)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, count)
        self.current = QtWidgets.QLabel("")

        stop = QtWidgets.QPushButton("Skip baking")
        stop.setToolTip("Stop converting and build now, using the source "
                        "textures. Anything already baked is kept.")
        stop.clicked.connect(self._stop)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(stop)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.label)
        lay.addWidget(self.bar)
        lay.addWidget(self.current)
        lay.addLayout(row)

    def _stop(self):
        self.cancelled = True
        self.current.setText("stopping…")

    def closeEvent(self, event):
        # Closing the window means the same as pressing the button. It must not
        # mean "carry on invisibly": a conversion nobody can see or stop is the
        # thing that made a frozen Houdini frightening rather than merely slow.
        self.cancelled = True
        super().closeEvent(event)


def bake_first(asset, asset_dir: Path, opts: dict,
               fmt: str = derived.DEFAULT_FORMAT) -> None:
    """Convert what this build needs, showing progress, before any node is made.

    Returns when the bakes are done, skipped or cancelled. `textures_for()`
    afterwards finds them current and binds them without converting anything
    itself, so the slow path runs here, once, with a window on it.

    Silent and instant when there is nothing to do, which is every build after
    the first.
    """
    opts = opts or {}
    if not opts.get("derived", True) or not opts.get("bake", True):
        return
    if not derived.available(fmt):
        return

    rels = list(texture_rels_for(asset, opts).values())
    todo = pending(asset, asset_dir, rels, fmt)
    if not todo:
        return

    app = QtWidgets.QApplication.instance()
    if app is None:                         # no Qt loop: convert quietly
        for rel in todo:
            if "<UDIM>" in rel:
                derived.ensure_udim(asset, asset_dir, rel, fmt)
            else:
                derived.ensure(asset_dir, rel, fmt)
        return

    win = BakeProgress(asset.name, len(todo))
    signals = _Signals()
    state = {"done": False, "failed": []}

    signals.step.connect(lambda i, n: (win.bar.setValue(i),
                                       win.current.setText(n)))

    def finished(failed):
        state["failed"] = failed
        state["done"] = True

    signals.done.connect(finished)

    worker = _Worker(asset, asset_dir, todo, fmt, signals)
    win.show()
    QtCore.QThreadPool.globalInstance().start(worker)

    # The main thread pumps events and nothing else. This is what keeps Houdini
    # alive; the converting is happening on the pool thread. ExcludeUserInput is
    # deliberately NOT passed - being able to use Houdini is the entire point -
    # but `worker.stop` is the only way back out, so a second import started
    # from the shelf mid-bake would queue behind this one rather than tangle.
    while not state["done"]:
        if win.cancelled:
            worker.stop = True
        app.processEvents(QtCore.QEventLoop.AllEvents, POLL_MS)
        time.sleep(0.005)

    win.close()
    if state["failed"]:
        print("[assetlib] could not bake, rendering from source: "
              + ", ".join(Path(r).name for r in state["failed"]))


def texture_rels_for(asset, opts):
    """Imported lazily to avoid a circular import - build.py imports this module."""
    from . import build

    return build.texture_rels(asset, opts)
