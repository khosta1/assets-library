"""Check for a newer published version of the app, and install it.

The window half of `assetlib/update.py`. Everything that touches the network or
the disk is in the core, with no Qt; this file asks, shows, and confirms.

**Shown before applied, always.** This writes over the running application's
own code, which is the most consequential button in the window - more so than
Delete, which at least only loses one asset. So the commit, its date and the
list of what changed are on screen before the button that does it is enabled,
and a copy with nothing recorded says plainly that it cannot tell what changed
rather than implying it checked.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QTextEdit, QVBoxLayout)

from assetlib import update


class _Signals(QObject):
    ready = Signal(dict)
    failed = Signal(str)
    progress = Signal(int, int)
    done = Signal(dict)


class _AskJob(QRunnable):
    """What is published, and what changed since this copy."""

    def __init__(self, cfg, signals: _Signals):
        super().__init__()
        self.cfg, self.signals = cfg, signals

    def run(self):
        try:
            head = update.latest()
            here = update.installed(self.cfg)
            head["installed"] = here
            head["changes"] = update.changes(here, head["sha"]) if here else []
            self.signals.ready.emit(head)
        except update.UpdateError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:                      # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class _ApplyJob(QRunnable):
    """Download, stage, verify, copy. In that order, and only that order."""

    def __init__(self, cfg, sha: str, signals: _Signals):
        super().__init__()
        self.cfg, self.sha, self.signals = cfg, sha, signals

    def run(self):
        staging = Path(self.cfg.state) / "update"
        try:
            archive = update.download(
                self.sha, staging,
                progress=lambda d, t: self.signals.progress.emit(d, t))
            root = update.extract(archive, staging / "tree")
            result = update.apply(self.cfg, self.cfg.base, root)
            update.write_state(self.cfg, self.sha, result.pop("config_hashes", {}))
            update.clean(staging)
            self.signals.done.emit(result)
        except update.UpdateError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:                      # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class UpdateDialog(QDialog):
    """Library ▸ Check for updates…"""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.head: dict = {}
        self.setWindowTitle("Check for updates")
        self.resize(560, 440)

        layout = QVBoxLayout(self)

        self.summary = QLabel("asking GitHub…")
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail, 1)

        # Said up front rather than in a FAQ nobody opens. The reason an update
        # is safe at all is that it cannot reach these, and a person about to
        # overwrite their app is entitled to see the list.
        note = QLabel(
            "Your assets, your index and the bundled runtime are never touched "
            "— they are not in the published archive. A config file you have "
            "edited is kept and the new one lands beside it as <code>.new</code>.")
        note.setWordWrap(True)
        note.setTextFormat(Qt.RichText)
        layout.addWidget(note)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        layout.addWidget(self.bar)

        row = QHBoxLayout()
        row.addStretch(1)
        self.apply_btn = QPushButton("Update")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        row.addWidget(self.apply_btn)
        row.addWidget(self.close_btn)
        layout.addLayout(row)

        self.signals = _Signals()
        self.signals.ready.connect(self._ready)
        self.signals.failed.connect(self._failed)
        self.signals.progress.connect(self._progress)
        self.signals.done.connect(self._done)
        QThreadPool.globalInstance().start(_AskJob(cfg, self.signals))

    # ----------------------------------------------------------- answers

    def _ready(self, head: dict) -> None:
        self.head = head
        here = head.get("installed") or ""
        there = head["sha"]

        if here and here == there:
            self.summary.setText(
                f"<b>Up to date.</b>  {head['short']} · {head['date']}")
            self.detail.setPlainText(head["message"])
            return

        if not here:
            # A copy that has never updated cannot know what it is running, and
            # saying "47 changes" would be a guess dressed as a count.
            self.summary.setText(
                f"<b>Published: {head['short']}</b> · {head['date']}<br>"
                "This copy has no record of which commit it is running, so "
                "what changed cannot be listed. Updating installs the "
                "published version.")
            self.detail.setPlainText(head["message"])
        else:
            lines = head.get("changes") or []
            self.summary.setText(
                f"<b>{len(lines) or 'Some'} change(s) available.</b><br>"
                f"here {here[:7]}  →  {head['short']} · {head['date']}")
            self.detail.setPlainText(
                "\n".join(f"· {line}" for line in reversed(lines))
                or head["message"])
        self.apply_btn.setEnabled(True)

    def _failed(self, message: str) -> None:
        self.summary.setText("<b>Could not check.</b>")
        self.detail.setPlainText(message)
        self.apply_btn.setEnabled(False)
        self.bar.setVisible(False)
        self.close_btn.setEnabled(True)

    # ------------------------------------------------------------ apply

    def _apply(self) -> None:
        self.apply_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.summary.setText("downloading…")
        QThreadPool.globalInstance().start(
            _ApplyJob(self.cfg, self.head["sha"], self.signals))

    def _progress(self, done: int, total: int) -> None:
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)

    def _done(self, result: dict) -> None:
        self.bar.setVisible(False)
        self.close_btn.setEnabled(True)
        kept = result.get("config_kept") or []
        text = [f"{result.get('written', 0)} file(s) written.",
                "",
                "Close and start the app again for it to take effect."]
        if kept:
            text[1:1] = [
                "",
                "Kept your edited config, new version beside it as .new:",
                *(f"    config/{name}" for name in kept),
            ]
        # Not restarted automatically. A process that has just had its own
        # modules replaced under it is the wrong thing to ask to relaunch
        # itself, and the failure would look like the update rather than like
        # the relaunch.
        self.summary.setText("<b>Updated.</b>")
        self.detail.setPlainText("\n".join(text))
