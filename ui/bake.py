"""Pre-baking `.rat` textures for a shelf of assets, before a job rather than during it.

The on-demand path in `houdini/build.py` covers the normal case: the first build
of an asset pays the conversion and every build after it is free. This window is
for the other case — a shelf of forty assets about to be dropped into a scene,
where paying 5 s each at build time is forty pauses instead of one wait.

Nothing here decides anything. `assetlib/derived.py` owns what a bake is and
where it goes; this is a progress bar and a cancel button.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QProgressBar,
                               QVBoxLayout)

from assetlib import derived
from assetlib.model import Asset


class _Signals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(dict)


class _BakeJob(QRunnable):
    def __init__(self, cfg, rows: list, signals: _Signals):
        super().__init__()
        self.cfg, self.rows, self.signals = cfg, rows, signals
        self._stop = False
        self.setAutoDelete(True)

    def cancel(self):
        self._stop = True

    def run(self):
        made = skipped = 0
        failed, unreadable = [], []
        for i, row in enumerate(self.rows):
            if self._stop:
                break
            path = self.cfg.asset_path(row)
            if path is None or not path.is_dir():
                continue
            self.signals.progress.emit(i + 1, len(self.rows), row["name"])
            try:
                asset = Asset.read(path)
            except Exception as exc:                    # noqa: BLE001
                # Reported, never skipped in silence - the same rule rebuild()
                # follows. An asset that cannot be read is a fact worth knowing.
                unreadable.append(f"{row['name']}: {exc}")
                continue
            result = derived.bake_asset(asset, path,
                                        should_stop=lambda: self._stop)
            made += result["made"]
            skipped += result["skipped"]
            failed += [f"{row['name']}/{Path(r).name}" for r in result["failed"]]
        self.signals.finished.emit({
            "made": made, "skipped": skipped, "failed": failed,
            "unreadable": unreadable, "cancelled": self._stop,
            "assets": len(self.rows)})


class BakeDialog(QDialog):
    def __init__(self, cfg, rows: list, parent=None):
        super().__init__(parent)
        self.cfg, self.rows = cfg, rows
        self.job = None
        self.setWindowTitle("Generate .rat textures")
        self.setMinimumWidth(560)

        maps = sum(len(r.get("_slots") or []) for r in rows) or None
        intro = QLabel(
            f"Bakes every bound texture of <b>{len(rows)}</b> asset(s) into "
            "<code>derived/</code>, so Karma reads a <code>.rat</code> instead "
            "of converting one itself.<br><br>"
            "Roughly 1 s per 2K map and 5 s per 8K, and a <code>.rat</code> is "
            "about 3× the size of its source. <code>derived/</code> is "
            "deletable and is never sent to the server.")
        intro.setWordWrap(True)

        self.bar = QProgressBar()
        self.bar.setRange(0, len(rows))
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.buttons = QDialogButtonBox()
        self.go = self.buttons.addButton("Generate", QDialogButtonBox.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._start)
        self.buttons.rejected.connect(self._cancel)

        if not derived.available():
            self.go.setEnabled(False)
            self.status.setText(
                "iconvert was not found. It ships with Houdini — set "
                "ASSETLIB_ICONVERT to its full path if Houdini is installed "
                "somewhere unusual.")

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addStretch(1)
        layout.addWidget(self.buttons)

    def _start(self) -> None:
        signals = _Signals()
        signals.progress.connect(self._progress)
        signals.finished.connect(self._finished)
        self.job = _BakeJob(self.cfg, self.rows, signals)
        self.job._signals_ref = signals
        self.go.setEnabled(False)
        self.status.setText("starting…")
        # Global pool: one long job on a pool with one thread per core, so the
        # grid behind this keeps painting. iconvert is a subprocess, so the GIL
        # is not the constraint - the disk is.
        QThreadPool.globalInstance().start(self.job)

    def _cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.status.setText("stopping — what is already baked is kept")
            return
        self.reject()

    def _progress(self, done: int, total: int, name: str) -> None:
        self.bar.setValue(done)
        self.status.setText(f"{done} / {total}   {name}")

    def _finished(self, result: dict) -> None:
        self.job = None
        bits = [f"{result['made']} baked", f"{result['skipped']} already current"]
        if result["failed"]:
            bits.append(f"{len(result['failed'])} failed")
        if result["unreadable"]:
            bits.append(f"{len(result['unreadable'])} unreadable")
        if result["cancelled"]:
            bits.append("stopped early")
        self.status.setText("   ·   ".join(bits))
        detail = (result["failed"][:6] + result["unreadable"][:4])
        if detail:
            self.status.setText(self.status.text() + "\n\n" + "\n".join(detail))
        self.bar.setValue(self.bar.maximum())
        self.buttons.clear()
        close = self.buttons.addButton(QDialogButtonBox.Close)
        close.clicked.connect(self.accept)
