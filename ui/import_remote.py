"""Downloading a remote asset onto this disk - what it will cost, then doing it.

The cost is shown BEFORE anything starts, and both costs are shown together:
the whole package and the light version, side by side, as numbers. On a
Megascans asset that is 40 MB against 1 GB, and a person cannot choose between
them if only one of the two is on screen.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QProgressBar, QRadioButton,
                               QVBoxLayout)

from assetlib import materialise, remote

from . import netpool


def human(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class _Signals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(dict)
    failed = Signal(str)


class _ImportJob(QRunnable):
    def __init__(self, cfg, host, uuid, mode, resolution, signals: _Signals):
        super().__init__()
        self.cfg, self.host, self.uuid = cfg, host, uuid
        self.mode, self.resolution = mode, resolution
        self.signals = signals
        self._stop = False
        self.setAutoDelete(True)

    def cancel(self):
        self._stop = True

    def _stopped(self) -> bool:
        # Cancelled from the dialog, OR the window is closing. The second one
        # matters more: a 1 GB transfer would otherwise hold the process open
        # long after the user believes they quit.
        return self._stop or netpool.stopping()

    def run(self):
        try:
            result = materialise.materialise(
                self.cfg, self.host, self.uuid, self.mode, self.resolution,
                on_progress=lambda d, t, n: self.signals.progress.emit(d, t, n),
                should_stop=self._stopped)
        except remote.RemoteError as exc:
            self.signals.failed.emit(str(exc))
            return
        except Exception as exc:                        # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.signals.finished.emit(result)


class ImportRemoteDialog(QDialog):
    """Ask full or light, then fetch. One asset at a time, deliberately."""

    def __init__(self, cfg, host, row, parent=None):
        super().__init__(parent)
        self.cfg, self.host, self.row = cfg, host, row
        self.job = None
        self.result_dir = None
        self.setWindowTitle(f"Import “{row['name']}”")
        self.setMinimumWidth(560)

        self.header = QLabel(f"<b>{row['name']}</b><br>"
                             f"{row['type']} / {row['category']}  ·  from {host.name}")
        self.header.setWordWrap(True)

        self.full = QRadioButton("Everything in the package")
        self.hero = QRadioButton("Hero LOD and one resolution")
        self.full.setChecked(True)
        self.res = QComboBox()
        self.res.setEnabled(False)
        self.hero.toggled.connect(self.res.setEnabled)
        self.hero.toggled.connect(self._resize_estimate)
        self.res.currentTextChanged.connect(self._resize_estimate)

        res_row = QHBoxLayout()
        res_row.addWidget(self.hero)
        res_row.addWidget(self.res)
        res_row.addStretch(1)

        self.cost = QLabel("asking the server what this costs…")
        self.cost.setWordWrap(True)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.buttons = QDialogButtonBox()
        self.go = self.buttons.addButton("Download", QDialogButtonBox.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._start)
        self.buttons.rejected.connect(self._cancel)
        self.go.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(self.full)
        layout.addLayout(res_row)
        layout.addWidget(self.cost)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addStretch(1)
        layout.addWidget(self.buttons)

        self.manifest = None
        self.asset = None
        self._ask_manifest()

    # -------------------------------------------------------------- manifest

    def _ask_manifest(self) -> None:
        """The manifest is one small request, but it is still a request.

        Off the GUI thread like every other call to the box: this dialog opens
        the instant it is asked for, and fills in when the server answers.
        """
        signals = _Signals()
        signals.finished.connect(self._manifest_ready)
        signals.failed.connect(self._manifest_failed)

        class _Ask(QRunnable):
            def __init__(self, host, uuid):
                super().__init__()
                self.host, self.uuid = host, uuid
                self.setAutoDelete(True)

            def run(self):
                try:
                    signals.finished.emit(remote.asset(self.host, self.uuid))
                except remote.RemoteError as exc:
                    signals.failed.emit(str(exc))
                except Exception as exc:                # noqa: BLE001
                    signals.failed.emit(f"{type(exc).__name__}: {exc}")

        job = _Ask(self.host, self.row["uuid"])
        job._signals_ref = signals
        netpool.start(job)

    def _manifest_ready(self, payload: dict) -> None:
        self.manifest = payload["files"]
        self.asset = payload["asset"]

        found = materialise.resolutions(self.manifest)
        self.res.addItems(found)
        if found:
            # Default to 4k when the asset has one: big enough to render with,
            # small enough that the point of a light copy survives. Otherwise
            # the smallest available, which is the same intent.
            self.res.setCurrentText("4k" if "4k" in found else found[-1])
        else:
            self.hero.setEnabled(bool(self.asset.get("lods")))
        self.go.setEnabled(True)
        self._resize_estimate()

    def _manifest_failed(self, message: str) -> None:
        self.cost.setText(message)
        self.go.setEnabled(False)

    def _resize_estimate(self, *_) -> None:
        if not self.manifest:
            return
        full = materialise.total_bytes(self.manifest)
        light = materialise.total_bytes(materialise.subset(
            self.asset, self.manifest, materialise.HERO, self.res.currentText()))
        # Both numbers, always, whichever is selected. The choice is only
        # meaningful as a comparison.
        self.cost.setText(
            f"Everything: <b>{human(full)}</b>   ·   "
            f"Hero + {self.res.currentText() or '—'}: <b>{human(light)}</b>"
            f"   →  into {self.cfg.cache_root}")

    # --------------------------------------------------------------- running

    def _start(self) -> None:
        signals = _Signals()
        signals.progress.connect(self._progress)
        signals.finished.connect(self._finished)
        signals.failed.connect(self._failed)

        mode = materialise.HERO if self.hero.isChecked() else materialise.FULL
        self.job = _ImportJob(self.cfg, self.host, self.row["uuid"], mode,
                              self.res.currentText(), signals)
        self.job._signals_ref = signals
        self.go.setEnabled(False)
        self.full.setEnabled(False)
        self.hero.setEnabled(False)
        self.res.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.status.setText("starting…")
        netpool.start(self.job)

    def _cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.status.setText("stopping — what has arrived is kept and will "
                                "resume next time")
            return
        self.reject()

    def _progress(self, done: int, total: int, name: str) -> None:
        # Scaled to KB: a QProgressBar takes ints and a 1 GB asset overflows
        # the useful range of one long before it finishes.
        self.bar.setRange(0, max(1, total // 1024))
        self.bar.setValue(done // 1024)
        self.status.setText(f"{human(done)} / {human(total)}   {name}")

    def _finished(self, result: dict) -> None:
        self.job = None
        if result["cancelled"]:
            self.status.setText(
                f"Stopped at {human(result['bytes'])}. Partial files are kept — "
                "importing again resumes where this left off.")
            self.go.setEnabled(True)
            return
        self.result_dir = result["dir"]
        if result["failed"]:
            self.status.setText(
                f"{len(result['failed'])} file(s) failed:\n"
                + "\n".join(result["failed"][:6]))
        else:
            self.status.setText(f"Done. {human(result['bytes'])} in {result['dir']}")
        self.buttons.clear()
        close = self.buttons.addButton(QDialogButtonBox.Close)
        close.clicked.connect(self.accept)

    def _failed(self, message: str) -> None:
        self.job = None
        self.status.setText(message)
        self.go.setEnabled(True)
