"""Convert textures without freezing Houdini, then build.

The first attempt at this blocked the main thread in a
`while not done: QApplication.processEvents()` loop. The progress bar animated
and **Houdini still froze**, which is the useful failure: `processEvents` pumps
*Qt widget* events, so this module's own dialog repainted, while Houdini's
viewport, cook and UI are driven by Houdini's event loop - and that loop cannot
run while a Python script is still on the main thread. Pumping Qt from inside a
script does not hand control back; only returning does.

So the shape is inverted. Nothing waits:

    needs baking?  no  -> build now, return the nodes, exactly as before
                   yes -> start the worker, show the window, RETURN to Houdini,
                          and build from an idle callback when it finishes

`hou.ui.addEventLoopCallback` is Houdini's own mechanism for this - "called
whenever Houdini's event loop is idle, approximately every 50 ms". Because the
script has returned, that loop is running, and Houdini is genuinely usable
rather than merely repainting one dialog.

The cost is a real contract change: an import that has to bake returns **no
nodes**, because they do not exist yet. The caller says "building…" instead of
counting them. That is honest, and the alternative - pretending to be
synchronous - is what produced a frozen application with a working progress bar.

Node creation always happens on the main thread: the worker only ever runs
subprocesses, and `assetlib.derived` imports no `hou`.
"""

from __future__ import annotations

from pathlib import Path

try:                                        # Houdini 20.5+ ships Qt6
    from PySide6 import QtCore, QtWidgets
except ImportError:                         # older builds ship Qt5
    from PySide2 import QtCore, QtWidgets   # type: ignore

import hou

from assetlib import derived
from assetlib.model import expand


def pending(asset, asset_dir: Path, rels, fmt: str = derived.DEFAULT_FORMAT) -> list:
    """The textures of this build that have no current bake yet.

    Asked before anything is shown, so an asset that is already baked opens no
    window and takes the fully synchronous path - which is every build after
    the first, and the common case.
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
    done = QtCore.Signal(list)


class _Worker(QtCore.QRunnable):
    """Subprocesses only. Touches no `hou` call and creates no node."""

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
    """Modeless, always-on-top. Modal would block the input this exists to preserve."""

    def __init__(self, name: str, count: int):
        super().__init__(hou.qt.mainWindow() if hasattr(hou, "qt") else None)
        self.setWindowTitle("Preparing textures")
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(430)
        self.cancelled = False

        self.label = QtWidgets.QLabel(
            f"Baking {count} texture(s) for <b>{name}</b> into "
            "<code>derived/</code>.<br>"
            "Carry on working — the nodes are built when this finishes.")
        self.label.setWordWrap(True)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, count)
        self.current = QtWidgets.QLabel("")

        stop = QtWidgets.QPushButton("Skip baking")
        stop.setToolTip("Stop converting and build now from the source "
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
        self.current.setText("stopping — the build will use the source textures")

    def closeEvent(self, event):
        # Closing means the same as Skip. A conversion nobody can see or stop
        # is what made the frozen version frightening rather than merely slow.
        self.cancelled = True
        super().closeEvent(event)


def run_when_baked(asset, asset_dir: Path, opts: dict, build_fn,
                   fmt: str = derived.DEFAULT_FORMAT):
    """Bake what this build needs, then call `build_fn()`.

    Returns `build_fn()`'s result when nothing had to be baked, and `None` when
    the build was deferred to an idle callback. A caller that needs to report
    what happened must handle both - see `import_houdini.send()`.
    """
    opts = opts or {}
    rels = list(_texture_rels(asset, opts).values())

    wanted = (opts.get("derived", True) and opts.get("bake", True)
              and derived.available(fmt))
    todo = pending(asset, asset_dir, rels, fmt) if wanted else []

    if not todo:
        return build_fn()

    app = QtWidgets.QApplication.instance()
    has_loop = app is not None and hasattr(hou, "ui")
    if not has_loop:
        # hython, or a Houdini without a UI. Convert inline - there is no event
        # loop to hand control back to, and nobody is watching a viewport.
        for rel in todo:
            if "<UDIM>" in rel:
                derived.ensure_udim(asset, asset_dir, rel, fmt)
            else:
                derived.ensure(asset_dir, rel, fmt)
        return build_fn()

    win = BakeProgress(asset.name, len(todo))
    signals = _Signals()
    state = {"done": False, "failed": []}

    signals.step.connect(lambda i, n: (win.bar.setValue(i),
                                       win.current.setText(n)))
    signals.done.connect(lambda failed: state.update(done=True, failed=failed))

    worker = _Worker(asset, asset_dir, todo, fmt, signals)
    # Held on the state dict: a QRunnable with autoDelete is owned by the pool,
    # but the signals object is not, and if it is collected the callback never
    # fires - the classic threadpool mistake in Qt.
    state["signals"] = signals

    def poll():
        if win.cancelled:
            worker.stop = True
        if not state["done"]:
            return
        # Unregister FIRST. A callback that raises while still registered gets
        # called again every 50 ms forever, and Houdini's own error dialog then
        # reopens faster than it can be dismissed.
        try:
            hou.ui.removeEventLoopCallback(poll)
        except Exception:                               # noqa: BLE001
            pass
        win.close()
        if state["failed"]:
            print("[assetlib] could not bake, rendering from source: "
                  + ", ".join(Path(r).name for r in state["failed"]))
        try:
            build_fn()
        except Exception as exc:                        # noqa: BLE001
            # Nothing is waiting to catch this - we are on Houdini's idle
            # callback, not on the caller's stack - so it has to be reported
            # here or it is lost entirely.
            print(f"[assetlib] build failed after baking: {exc}")
            if hasattr(hou.ui, "displayMessage"):
                hou.ui.displayMessage(f"Build failed after baking:\n\n{exc}",
                                      severity=hou.severityType.Error)

    win.show()
    QtCore.QThreadPool.globalInstance().start(worker)
    hou.ui.addEventLoopCallback(poll)
    # Returns to Houdini immediately. THIS is what unfreezes it: the event loop
    # can only run once this script is off the main thread's stack.
    return None


def _texture_rels(asset, opts):
    """Lazy, because build.py imports this module."""
    from . import build

    return build.texture_rels(asset, opts)
