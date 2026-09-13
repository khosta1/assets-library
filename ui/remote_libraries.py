"""The servers this library can browse, and the catalogue sync that fills them.

Two things live here because they are the same subject from two directions: the
window where a host is declared, and the job that goes and asks it what it
holds.

**The sync runs off the GUI thread.** A sleeping box does not refuse a
connection, it fails to answer one, so the wait is the full TCP timeout - about
twenty seconds on Windows, which is long enough to look like a crash. Every
other long operation in this app is local and fast enough to block; this one is
the first that depends on another machine being awake, and it is the reason the
job exists rather than a plain function call.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from assetlib import catalog, remote

from . import netpool

NOTE = ("Catalogue only — no asset files are downloaded here.   "
        "Share and SSH are needed only to push this library onto a server.")

# Name/URL/Token are the browse half; Share/SSH are the push half. One row per
# BOX, not per protocol: the same machine answers HTTP over ZeroTier, SMB on
# the LAN and ssh for the re-index, and three records for one address is three
# places for it to go stale.
COLUMNS = ("Name", "URL", "Token", "Share (SMB)", "SSH")

HINTS = {
    3: ("The folder on the server that HOLDS library/ - "
        r"e.g. \\192.168.1.13\data2\assets"),
    4: "felix@192.168.1.13 - used only to ask the box to re-index after a push",
}


# ------------------------------------------------------------------- the job


class SyncSignals(QObject):
    done = Signal(list)         # [(host_name, ok, message)]


class SyncJob(QRunnable):
    """Ask every enabled host for its catalogue and store what comes back.

    Failures are collected, never raised: one unreachable server must not stop
    the others from syncing, and "the box is asleep" is an ordinary state here
    rather than an error condition.
    """

    def __init__(self, cfg, hosts: list, signals: SyncSignals):
        super().__init__()
        self.cfg, self.hosts, self.signals = cfg, hosts, signals
        self.setAutoDelete(True)

    def run(self):
        results = []
        for host in self.hosts:
            if not host.enabled or netpool.stopping():
                continue
            try:
                outcome = catalog.sync(self.cfg, host, self.hosts)
            except remote.RemoteError as exc:
                results.append((host.name, False, str(exc)))
                continue
            except Exception as exc:                    # noqa: BLE001
                results.append((host.name, False, f"{type(exc).__name__}: {exc}"))
                continue
            if outcome["changed"]:
                results.append((host.name, True, f"{outcome['count']} asset(s)"))
            else:
                # 304. Worth saying, because after an import on the box this is
                # the message that means "it has not re-indexed yet" rather than
                # "nothing happened" - /api/health carries indexed_at for the
                # same reason.
                results.append((host.name, True,
                                f"unchanged ({outcome['count']} asset(s))"))
        self.signals.done.emit(results)


def sync_async(cfg, hosts: list, on_done) -> None:
    signals = SyncSignals()
    signals.done.connect(on_done)
    job = SyncJob(cfg, hosts, signals)
    # The signals object must outlive the job or the connection dies with it and
    # the callback never fires - the classic threadpool mistake in Qt.
    job._signals_ref = signals
    netpool.start(job)


class HealthSignals(QObject):
    done = Signal(list)         # [(host_name, ok, message)]


class HealthJob(QRunnable):
    """Ask each host /api/health and say what came back, in words.

    Off the GUI thread for the same reason the sync is: an unreachable box does
    not refuse the connection, it never answers, and the wait is the full TCP
    timeout. A "Test connection" button that freezes the window for twenty
    seconds teaches the user that the app is broken, not that the box is.
    """

    def __init__(self, hosts: list, signals: HealthSignals):
        super().__init__()
        self.hosts, self.signals = hosts, signals
        self.setAutoDelete(True)

    def run(self):
        results = []
        for host in self.hosts:
            if netpool.stopping():
                continue
            try:
                info = remote.health(host)
            except remote.RemoteError as exc:
                results.append((host.name, False, str(exc)))
                continue
            except Exception as exc:                    # noqa: BLE001
                results.append((host.name, False, f"{type(exc).__name__}: {exc}"))
                continue
            # library_mounted is its own state, and collapsing it into "up"
            # would be a lie: /srv/data2 is fstab'd nofail, so an unmounted disk
            # answers every request happily and reports an empty library.
            if info.get("library_mounted") is False:
                results.append((host.name, False,
                                "connected, but the library disk is NOT mounted"))
                continue
            results.append((host.name, True,
                            f"{info.get('assets', '?')} asset(s), indexed "
                            f"{info.get('indexed_at') or 'never'}"))
        self.signals.done.emit(results)


def health_async(hosts: list, on_done) -> None:
    signals = HealthSignals()
    signals.done.connect(on_done)
    job = HealthJob(hosts, signals)
    job._signals_ref = signals
    netpool.start(job)


# ---------------------------------------------------------------- the window


class RemoteLibrariesDialog(QDialog):
    """Declare a server: a label, a base URL, a bearer token.

    The token is a credential, so it is stored in .assetlib/remote/hosts.json
    and never in config/ - config/ is committed, and a secret in a tracked file
    is published the next time anyone pushes.
    """

    def __init__(self, cfg, hosts: list, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.hosts = list(hosts)
        self.setWindowTitle("Remote libraries")
        self.resize(980, 320)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        for column, hint in HINTS.items():
            self.table.horizontalHeaderItem(column).setToolTip(hint)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # Same rule as the Add window: a bare click must not start an editor,
        # or selecting a row to delete it opens a cell instead (gotcha 16).
        self.table.setEditTriggers(QAbstractItemView.SelectedClicked
                                   | QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        for host in self.hosts:
            self._append_row(host)

        add = QPushButton("Add server")
        add.clicked.connect(self._add)
        drop = QPushButton("Remove")
        drop.clicked.connect(self._remove)
        test = QPushButton("Test connection")
        test.setToolTip("Ask /api/health. Downloads nothing.")
        test.clicked.connect(self._test)

        self.note = QLabel(NOTE)
        self.note.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(drop)
        row.addWidget(test)
        row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addLayout(row)
        layout.addWidget(self.note)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ rows

    def _append_row(self, host: remote.Host) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        for column, value in enumerate((host.name, host.url, host.token,
                                        host.share, host.ssh)):
            self.table.setItem(r, column, QTableWidgetItem(value))

    def _add(self) -> None:
        self._append_row(remote.Host(name="rocky", url="http://10.209.73.177:8083"))

    def _remove(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _collect(self) -> list:
        out = []
        existing = {h.name: h for h in self.hosts}
        for r in range(self.table.rowCount()):
            def cell(c):
                item = self.table.item(r, c)
                return (item.text() if item else "").strip()

            name, url, token = cell(0), cell(1), cell(2)
            share, ssh = cell(3), cell(4)
            if not name or not url:
                continue
            was = existing.get(name)
            # Carry the ETag across a save. Dropping it would make the next
            # sync re-download a catalogue the client already has, every time
            # anyone opened this window.
            out.append(remote.Host(name=name, url=url, token=token,
                                   share=share, ssh=ssh,
                                   etag=was.etag if was else "",
                                   enabled=was.enabled if was else True))
        return out

    # --------------------------------------------------------------- actions

    def _test(self) -> None:
        hosts = self._collect()
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        picked = [hosts[r] for r in rows if r < len(hosts)] or hosts
        if not picked:
            return
        self.note.setText("asking…")
        health_async(picked, self._tested)

    def _tested(self, results: list) -> None:
        self.note.setText(NOTE)
        lines = [f"{'✓' if ok else '✗'}  {name}: {message}"
                 for name, ok, message in results]
        QMessageBox.information(self, "Remote libraries", "\n".join(lines))

    def _save(self) -> None:
        hosts = self._collect()
        clash = self._duplicate_name(hosts)
        if clash:
            # Refused rather than silently de-duplicated. Two rows called the
            # same thing is someone meaning two servers, and the name is the
            # catalogue's filename - letting it through gives both of them one
            # database to fight over.
            QMessageBox.warning(
                self, "Two servers share a name",
                f"More than one server is called “{clash}”.\n\n"
                "The name is the catalogue's filename, so they would overwrite "
                "each other's assets.\n\nGive them different names — or, if "
                "these are two addresses for the same machine, keep one.")
            return
        self.hosts = hosts
        remote.save_hosts(self.cfg, self.hosts)
        self.accept()

    @staticmethod
    def _duplicate_name(hosts: list) -> str:
        seen = set()
        for host in hosts:
            if host.name in seen:
                return host.name
            seen.add(host.name)
        return ""
