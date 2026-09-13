"""Pushing this library onto a server, and what that would change.

The plan is shown before anything moves, grouped by what the push would do,
with the destructive group last and separate. Nothing in a sync run deletes an
asset: removing one from the server is a second, single, deliberate act with
its own confirmation, and it moves the package into `_trash/` rather than
removing it.

**Everything here runs off the GUI thread.** The scan reads `asset.json` out of
every package on both sides, and the remote side of that is SMB: an unmounted
share does not refuse, it stalls, and a copy is minutes. `assetlib/sync.py`
holds the decisions; this file is the window onto them.

Whether the Send button is a push or a drop into the inbox is decided by the
share, not here - see `sync.probe()`.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QHBoxLayout, QInputDialog, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from assetlib import sync

from . import netpool
from .import_remote import human
from .theme import dim_colour

ITEM_ROLE = Qt.UserRole + 1


class _Signals(QObject):
    step = Signal(int, str)             # scanned so far, what it is reading
    scanned = Signal(object)            # a sync.Plan
    progress = Signal(int, int, str)    # bytes done, total, current asset
    finished = Signal(dict)
    failed = Signal(str)


class _ScanJob(QRunnable):
    def __init__(self, cfg, share, signals: _Signals):
        super().__init__()
        self.cfg, self.share, self.signals = cfg, share, signals
        self._stop = False
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._stop = True

    def _stopped(self) -> bool:
        return self._stop or netpool.stopping()

    def run(self):
        try:
            plan = sync.diff(self.cfg, self.share,
                             on_progress=lambda n, rel: self.signals.step.emit(n, rel),
                             should_stop=self._stopped)
        except Exception as exc:                        # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.signals.scanned.emit(plan)


class _PushJob(QRunnable):
    """The copy itself. `drop` picks the inbox instead of the library."""

    def __init__(self, plan, items, drop: bool, signals: _Signals):
        super().__init__()
        self.plan, self.items, self.drop = plan, items, drop
        self.signals = signals
        self._stop = False
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._stop = True

    def _stopped(self) -> bool:
        # Cancelled from the dialog, OR the window is closing. The second one
        # matters more: a 38 GB transfer would otherwise hold the process open
        # long after the user believes they quit (gotcha 18).
        return self._stop or netpool.stopping()

    def run(self):
        send = sync.drop if self.drop else sync.push
        try:
            result = send(self.plan, self.items,
                          on_progress=lambda d, t, n: self.signals.progress.emit(d, t, n),
                          should_stop=self._stopped)
        except Exception as exc:                        # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.signals.finished.emit(result)


class _ReindexJob(QRunnable):
    def __init__(self, ssh: str, signals: _Signals):
        super().__init__()
        self.ssh, self.signals = ssh, signals
        self.setAutoDelete(True)

    def run(self):
        ok, message = sync.reindex(self.ssh)
        (self.signals.finished if ok else self.signals.failed).emit(
            {"reindexed": message} if ok else message)


# ------------------------------------------------------------------ the window


class PushToServerDialog(QDialog):
    """Show what a push would change, then carry out the part that was ticked."""

    def __init__(self, cfg, host, parent=None):
        super().__init__(parent)
        self.cfg, self.host = cfg, host
        self.plan = None
        self.job = None
        self.pushed = False
        self.setWindowTitle(f"Push to {host.name}")
        self.resize(860, 620)

        self.header = QLabel(f"<b>{cfg.library}</b>  →  {host.share}")
        self.header.setWordWrap(True)
        self.rights = QLabel("looking at the share…")
        self.rights.setWordWrap(True)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(("Asset", "Where", "Size"))
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setRootIsDecorated(True)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.setColumnWidth(0, 380)
        self.tree.setColumnWidth(1, 320)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.remove = QPushButton("Remove from the server…")
        self.remove.setToolTip("Moves the package into _trash/ on the server. "
                               "One asset, and never part of a push.")
        self.remove.setEnabled(False)
        self.remove.clicked.connect(self._remove)

        self.reindex = QPushButton("Re-index the box")
        self.reindex.setToolTip("Ask the server to rebuild its catalogue over SSH")
        self.reindex.setEnabled(False)
        self.reindex.clicked.connect(self._reindex)

        self.buttons = QDialogButtonBox()
        self.go = self.buttons.addButton("Send", QDialogButtonBox.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._start)
        self.buttons.rejected.connect(self._cancel)
        self.go.setEnabled(False)

        row = QHBoxLayout()
        row.addWidget(self.remove)
        row.addWidget(self.reindex)
        row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(self.rights)
        layout.addWidget(self.tree, 1)
        layout.addLayout(row)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)

        self._scan()

    # ------------------------------------------------------------------ scan

    def _scan(self) -> None:
        signals = _Signals()
        signals.step.connect(self._step)
        signals.scanned.connect(self._scanned)
        signals.failed.connect(self._failed)
        self.job = _ScanJob(self.cfg, self.host.share, signals)
        self.job._signals_ref = signals
        self.status.setText("reading both libraries…")
        netpool.start(self.job)

    def _step(self, n: int, rel: str) -> None:
        self.status.setText(f"{n} packages read   ·   {rel}")

    def _scanned(self, plan) -> None:
        self.job = None
        self.plan = plan
        self.status.setText("")

        if plan.admin:
            self.rights.setText(
                "This account may write to the library share — "
                "assets can be added, changed, moved and removed.")
            self.go.setText("Send")
        else:
            # Not a failure and not a lecture: an ordinary state for anyone who
            # is not on Samba's write list, and the drop box is the answer.
            self.rights.setText(f"⚠ {plan.reason}")
            self.rights.setStyleSheet(f"color: {dim_colour().name()}")
            self.go.setText("Copy into the drop box")

        self._fill()
        self.reindex.setEnabled(bool(self.host.ssh) and plan.admin)

    def _fill(self) -> None:
        # Signals off while the tree is built: every setCheckState emits
        # itemChanged, and recounting the ticked rows once per row turns
        # filling a plan into quadratic work for no answer anyone reads.
        self.tree.blockSignals(True)
        self.tree.clear()
        sendable = self.plan.admin
        for verdict in sync.VERDICTS:
            items = self.plan.of(verdict)
            if not items:
                continue
            # ADD is the only thing a drop box takes: an update or a move is an
            # edit to the master, and an edit is not an addition.
            allowed = (verdict != sync.MISSING
                       and (sendable or verdict == sync.ADD))
            group = QTreeWidgetItem(self.tree, [
                f"{sync.LABELS[verdict]}  ({len(items)})", "",
                human(sum(i.bytes for i in items)) if verdict != sync.MISSING else ""])
            group.setExpanded(True)
            if allowed:
                group.setFlags(group.flags() | Qt.ItemIsUserCheckable
                               | Qt.ItemIsAutoTristate)
                group.setCheckState(0, Qt.Checked)
            for item in items:
                where = item.local_rel
                if verdict == sync.MOVE:
                    where = f"{item.remote_rel}  →  {item.local_rel}"
                elif verdict == sync.MISSING:
                    where = item.remote_rel
                size = human(item.bytes) if item.bytes else ""
                if verdict == sync.MOVE and not item.also_changed:
                    size = "rename only"
                leaf = QTreeWidgetItem(group, [item.name, where, size])
                leaf.setData(0, ITEM_ROLE, item)
                if allowed:
                    leaf.setFlags(leaf.flags() | Qt.ItemIsUserCheckable)
                    leaf.setCheckState(0, Qt.Checked)
                else:
                    leaf.setForeground(0, dim_colour())
                    leaf.setForeground(1, dim_colour())
                if item.gone:
                    leaf.setToolTip(
                        0, f"{len(item.gone)} file(s) no longer in the package "
                           "will be moved into _trash/ on the server")
        if self.plan.failed:
            # Its own group, not a status line. These are the packages the
            # diff had to skip, and the one that actually happens - a uuid
            # found at two paths on the server, left there by an earlier
            # robocopy that had no way to express a move - is invisible in the
            # verdict groups by definition: the asset was skipped, so it
            # produces no verdict at all.
            group = QTreeWidgetItem(self.tree, [
                f"Skipped — needs a look  ({len(self.plan.failed)})", "", ""])
            group.setExpanded(True)
            for rel, why in self.plan.failed:
                leaf = QTreeWidgetItem(group, [rel, why, ""])
                leaf.setForeground(0, dim_colour())
                leaf.setForeground(1, dim_colour())
        self.tree.blockSignals(False)
        self._update_go()

    # --------------------------------------------------------------- ticking

    def _item_changed(self, *_) -> None:
        self._update_go()

    def _ticked(self) -> list:
        out = []
        for g in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(g)
            for c in range(group.childCount()):
                leaf = group.child(c)
                if leaf.flags() & Qt.ItemIsUserCheckable and leaf.checkState(0) == Qt.Checked:
                    out.append(leaf.data(0, ITEM_ROLE))
        return out

    def _update_go(self) -> None:
        picked = self._ticked()
        self.go.setEnabled(bool(picked) and self.job is None)
        if picked:
            self.status.setText(
                f"{len(picked)} asset(s), {human(sum(i.bytes for i in picked))} to copy")

    def _selection_changed(self) -> None:
        item = self._selected_item()
        self.remove.setEnabled(
            bool(self.plan) and self.plan.admin and item is not None
            and item.verdict == sync.MISSING)

    def _selected_item(self):
        rows = self.tree.selectedItems()
        return rows[0].data(0, ITEM_ROLE) if rows else None

    # --------------------------------------------------------------- sending

    def _start(self) -> None:
        picked = self._ticked()
        if not picked:
            return
        signals = _Signals()
        signals.progress.connect(self._progress)
        signals.finished.connect(self._finished)
        signals.failed.connect(self._failed)
        self.job = _PushJob(self.plan, picked, not self.plan.admin, signals)
        self.job._signals_ref = signals
        self.go.setEnabled(False)
        self.tree.setEnabled(False)
        self.remove.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.status.setText("starting…")
        netpool.start(self.job)

    def _cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.status.setText("stopping — what has already been sent stays sent")
            return
        self.reject()

    def _progress(self, done: int, total: int, name: str) -> None:
        # Scaled to KB: a QProgressBar takes ints, and 38 GB in bytes is well
        # past the useful range of one.
        self.bar.setRange(0, max(1, total // 1024))
        self.bar.setValue(done // 1024)
        self.status.setText(f"{human(done)} / {human(total)}   {name}")

    def _finished(self, result: dict) -> None:
        if "reindexed" in result:
            self.status.setText(result["reindexed"])
            self.reindex.setEnabled(True)
            return

        self.job = None
        self.pushed = self.pushed or bool(result["sent"])
        self.bar.setVisible(False)
        self.tree.setEnabled(True)
        lines = [f"{len(result['sent'])} asset(s) sent, {human(result['bytes'])}"]
        if result["cancelled"]:
            lines.append("stopped early — the rest is still here and can be sent again")
        if result["failed"]:
            lines.append(f"{len(result['failed'])} failed: "
                         + "; ".join(f"{n} ({w})" for n, w in result["failed"][:3]))
        if result["sent"] and not result["failed"]:
            lines.append("the box will not show them until it re-indexes")
        self.status.setText("\n".join(lines))
        # Re-scanned rather than patched: the plan that is on screen described
        # the share as it was before the copy, and a second push built on a
        # stale plan is how an asset gets sent twice or moved from a path it no
        # longer occupies.
        self._scan()

    def _failed(self, message) -> None:
        self.job = None
        self.bar.setVisible(False)
        self.tree.setEnabled(True)
        self.status.setText(str(message))
        self._update_go()

    # -------------------------------------------------------------- removing

    def _remove(self) -> None:
        item = self._selected_item()
        if item is None or item.verdict != sync.MISSING:
            return
        typed, ok = QInputDialog.getText(
            self, "Remove from the server",
            f"“{item.name}” is on the server and not on this disk.\n\n"
            f"It will be moved to _trash/ on the server, not deleted — nothing "
            f"is lost, but it leaves the library and the catalogue.\n\n"
            f"Type the asset's name to confirm:")
        if not ok or typed.strip() != item.name:
            if ok:
                self.status.setText("name did not match — nothing was removed")
            return
        try:
            dest = sync.discard(self.plan, item)
        except (sync.SyncError, OSError) as exc:
            QMessageBox.warning(self, "Remove from the server", str(exc))
            return
        self.pushed = True
        self.status.setText(f"moved to {dest}")
        self._scan()

    # ------------------------------------------------------------ re-indexing

    def _reindex(self) -> None:
        signals = _Signals()
        signals.finished.connect(self._finished)
        signals.failed.connect(self._reindex_failed)
        self.reindex.setEnabled(False)
        self.status.setText("asking the box to re-index…")
        job = _ReindexJob(self.host.ssh, signals)
        job._signals_ref = signals
        netpool.start(job)

    def _reindex_failed(self, message) -> None:
        self.reindex.setEnabled(True)
        # The command, spelt out. Starting a system unit needs root, and
        # whether that is a NOPASSWD exception on this box is not something the
        # app can find out - so the fallback is telling the user exactly what
        # to run there.
        QMessageBox.warning(
            self, "Re-index", f"{message}\n\nOn the box:\n\n"
            f"    sudo systemctl start {sync.REINDEX_UNIT}")
