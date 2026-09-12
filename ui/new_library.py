"""Create a second copy of this app somewhere else - a laptop, a portable disk.

In the window rather than as a script, because `docs/History/cli-removed.md`
settled that: everything the old command line did lives here now, and a
`new_library.bat` would be a command line growing back one file at a time.

The copy is ~320 MB of bundled runtime and about 1.5 MB of code. It carries no
assets, no index, no thumbnails and no token - `assetlib/deploy.py` owns that
decision and this window only presents it.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QVBoxLayout)

from assetlib import deploy


def _human(n) -> str:
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


class _CopyJob(QRunnable):
    def __init__(self, src, dest, include_dev, host, signals: _Signals):
        super().__init__()
        self.src, self.dest = src, dest
        self.include_dev, self.host = include_dev, host
        self.signals = signals
        self._stop = False
        self.setAutoDelete(True)

    def cancel(self):
        self._stop = True

    def run(self):
        try:
            result = deploy.copy_install(
                self.src, self.dest, self.include_dev,
                on_file=lambda d, t, n: self.signals.progress.emit(d, t, n),
                should_stop=lambda: self._stop)
            if self.host is not None and not result["cancelled"]:
                deploy.suggest_host(self.dest, self.host.name, self.host.url)
        except Exception as exc:                        # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.signals.finished.emit(result)


class NewLibraryDialog(QDialog):
    def __init__(self, cfg, hosts: list, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.hosts = hosts
        self.job = None
        self.setWindowTitle("Create a new library")
        self.setMinimumWidth(640)

        intro = QLabel(
            "Makes a fresh, empty copy of this app somewhere else — a portable "
            "drive, a laptop, or a folder to hand to somebody.\n\n"
            "It copies the app and its bundled Python. It does not copy your "
            "assets, your index, or your server token.")
        intro.setWordWrap(True)

        self.dest = QLineEdit()
        self.dest.setPlaceholderText(r"J:\Assets_library")
        self.dest.textChanged.connect(self._revalidate)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("New copy in"))
        dest_row.addWidget(self.dest, 1)
        dest_row.addWidget(browse)

        self.dev_box = QCheckBox("Include developer files (docs, tools, ROADMAP)")
        self.dev_box.setToolTip(
            "On for a working copy of your own. Off for one you hand to "
            "somebody who just wants to browse assets.")
        self.dev_box.toggled.connect(self._revalidate)

        self.host_box = QCheckBox("Include the server address (never the token)")
        self.host_box.setChecked(bool(self._first_host()))
        self.host_box.setEnabled(bool(self._first_host()))
        self.host_box.setToolTip(
            "The new copy will ask for the token on first launch, with the "
            "address already filled in. Give the token separately.")

        self.size_label = QLabel("")
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.buttons = QDialogButtonBox()
        self.create_btn = self.buttons.addButton("Create", QDialogButtonBox.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._create)
        self.buttons.rejected.connect(self._cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(dest_row)
        layout.addWidget(self.dev_box)
        layout.addWidget(self.host_box)
        layout.addWidget(self.size_label)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addStretch(1)
        layout.addWidget(self.buttons)

        self._measure()

    # ------------------------------------------------------------------ size

    def _first_host(self):
        return next((h for h in self.hosts if h.url), None)

    def _measure(self) -> None:
        files, total = deploy.plan(self.cfg.base, self.dev_box.isChecked())
        self.size_label.setText(
            f"{len(files)} file(s), {_human(total)} — mostly the bundled Python.")

    def _browse(self) -> None:
        picked = QFileDialog.getExistingDirectory(self, "Where to put the new copy")
        if picked:
            self.dest.setText(str(Path(picked)))

    def _revalidate(self) -> None:
        self._measure()
        text = self.dest.text().strip()
        if not text:
            self.status.setText("")
            self.create_btn.setEnabled(False)
            return
        problem = deploy.check_destination(self.cfg.base, Path(text))
        self.status.setText(problem)
        self.create_btn.setEnabled(not problem)

    # ---------------------------------------------------------------- action

    def _create(self) -> None:
        dest = Path(self.dest.text().strip())
        problem = deploy.check_destination(self.cfg.base, dest)
        if problem:
            # Re-checked at the moment of the click, not only as you type. The
            # folder can have been filled by something else in between, and
            # this is the check that stops a copy into itself.
            self.status.setText(problem)
            return

        signals = _Signals()
        signals.progress.connect(self._progress)
        signals.finished.connect(self._finished)
        signals.failed.connect(self._failed)

        host = self._first_host() if self.host_box.isChecked() else None
        self.job = _CopyJob(self.cfg.base, dest, self.dev_box.isChecked(),
                            host, signals)
        self.job._signals_ref = signals
        self.create_btn.setEnabled(False)
        self.dest.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.status.setText("copying…")
        # The global pool is right here, unlike for a network fetch: this is one
        # long job on a pool with one thread per core, so the grid behind the
        # dialog keeps decoding thumbnails on the others. What must never go
        # there is something that BLOCKS without working - see netpool.py.
        QThreadPool.globalInstance().start(self.job)

    def _cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.status.setText("stopping…")
            return
        self.reject()

    def _progress(self, done: int, total: int, name: str) -> None:
        self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.status.setText(f"{done} / {total}   {name}")

    def _finished(self, result: dict) -> None:
        self.job = None
        if result["cancelled"]:
            self.status.setText(
                f"Stopped after {result['copied']} file(s). "
                f"{result['dest']} is incomplete — delete it.")
            self.create_btn.setEnabled(True)
            self.dest.setEnabled(True)
            return
        self.bar.setValue(self.bar.maximum())
        self.status.setText(
            f"Done. {result['copied']} file(s), {_human(result['bytes'])}.\n\n"
            f"Open {result['dest']} and double-click “Asset Library.vbs”. "
            "It will ask how to set itself up.")
        self.buttons.clear()
        close = self.buttons.addButton(QDialogButtonBox.Close)
        close.clicked.connect(self.accept)

    def _failed(self, message: str) -> None:
        self.job = None
        self.status.setText(message)
        self.create_btn.setEnabled(True)
        self.dest.setEnabled(True)
