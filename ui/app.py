"""The browser window: category sidebar, thumbnail grid, search, Open folder.

The sidebar shows the DECLARED taxonomy - every type and category from config,
including the empty ones. The tree is the fixed shape of the library, not
something that grows out of whatever happens to be on disk.

The window never walks the filesystem: everything comes from index.db.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt, QSize, QTimer
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListView, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QSlider, QSplitter,
                               QStatusBar, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from assetlib import catalog
from assetlib import index as idx
from assetlib import remote
from assetlib import shortcut
from assetlib import upgrade
from assetlib.edit import delete_asset
from assetlib.verify import verify

from . import theme
from . import thumbcache

from . import gridmodel
from .gridmodel import ROW_ROLE, AssetGridModel, TileDelegate, _human, tile_sizes

TYPE_ROLE = Qt.UserRole + 10
CAT_ROLE = Qt.UserRole + 11
ZOOM_SIZES = [96, 128, 160, 200, 256, 320]


class MainWindow(QMainWindow):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.conn = idx.connect(cfg)
        # Remote catalogues are opened at launch and NOT synced at launch. The
        # rows are already on this disk, so the window fills instantly and works
        # with the box switched off; a sync on the launch path would make
        # startup depend on a machine that is asleep most of the time.
        self.hosts = remote.load_hosts(cfg)
        self.remotes = catalog.open_all(cfg, self.hosts)
        # Costs one small file read when the library is already current, so it
        # can sit on the launch path. Only a code upgrade makes it walk.
        self._upgrade = upgrade.run_if_pending(cfg)
        # The path is in the title on purpose: the whole project is meant to be
        # copied onto an external disk, so several libraries exist and they look
        # identical from the inside. Launching the wrong one is otherwise
        # invisible until you notice your changes are missing.
        self.setWindowTitle(f"Asset Library  —  {cfg.base}")
        icon = shortcut.icon_path(cfg.base)
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1280, 820)

        self.search = QLineEdit(placeholderText="search…   try  type:texture  cat:concrete  res:8k  -src:megascans")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._queue_refresh)

        self.zoom = QSlider(Qt.Horizontal, minimum=0, maximum=len(ZOOM_SIZES) - 1, value=2)
        self.zoom.setFixedWidth(110)
        self.zoom.valueChanged.connect(self._apply_zoom)

        self.add_btn = QPushButton("Add asset…")
        self.add_btn.setToolTip("Declare one asset and drop its files in")
        self.add_btn.clicked.connect(self._add_asset)

        self.batch_btn = QPushButton("Import folder…")
        self.batch_btn.setToolTip(
            "A vendor dump: one row per subfolder, one asset each.\n"
            "For a single asset use Add.")
        self.batch_btn.clicked.connect(self._batch_add)

        self.cloud_btn = QPushButton("☁ Cloud")
        self.cloud_btn.setCheckable(True)
        self.cloud_btn.setChecked(True)
        self.cloud_btn.setToolTip(
            "Show assets that are on a server and not on this disk.\n"
            "Switch off to see only what you actually hold.")
        self.cloud_btn.toggled.connect(self._toggle_cloud)

        top = QHBoxLayout()
        top.addWidget(self.add_btn)
        top.addWidget(self.batch_btn)
        top.addWidget(self.search, 1)
        top.addWidget(self.cloud_btn)
        top.addWidget(QLabel("size"))
        top.addWidget(self.zoom)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(220)
        self.tree.itemSelectionChanged.connect(self._queue_refresh)

        self.model = AssetGridModel(cfg)
        self.model.set_hosts(self.hosts)
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setViewMode(QListView.IconMode)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setUniformItemSizes(True)      # required for smooth scrolling at scale
        self.view.setMovement(QListView.Static)
        self.view.setWordWrap(True)
        self.view.setSpacing(8)
        self.view.setItemDelegate(TileDelegate(self.view, self))
        self.view.setMouseTracking(True)   # so the delegate sees MouseOver
        # Extended so a whole shelf of assets can go to Houdini in one pass.
        # Everything else - Contents, Edit, Delete, Open folder - still acts on
        # the CURRENT asset only, and each of those names the asset it is about
        # to touch, so a wide selection cannot make one of them do more than it
        # says.
        self.view.setSelectionMode(QListView.ExtendedSelection)
        self.view.doubleClicked.connect(lambda *_: self._open_selected())
        self.view.selectionModel().selectionChanged.connect(self._update_detail)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)

        self.detail = QLabel("—")
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.view_btn = QPushButton("Contents…")
        self.view_btn.setEnabled(False)
        self.view_btn.setToolTip("Look inside the package - double-clicking a tile does the same")
        self.view_btn.clicked.connect(self._view_asset)

        self.edit_btn = QPushButton("Edit…")
        self.edit_btn.setEnabled(False)
        self.edit_btn.setToolTip("Change this asset - double-clicking a tile does the same")
        self.edit_btn.clicked.connect(self._edit_asset)

        self.open_btn = QPushButton("Open folder")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_folder)

        bottom = QHBoxLayout()
        bottom.addWidget(self.detail, 1)
        bottom.addWidget(self.view_btn)
        bottom.addWidget(self.edit_btn)
        bottom.addWidget(self.open_btn)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(top)
        rl.addWidget(self.view, 1)
        rl.addLayout(bottom)

        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([240, 1040])

        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.addWidget(split)
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())

        rescan = QAction("Rebuild index", self)
        rescan.setShortcut("F5")
        rescan.triggered.connect(self._rebuild)
        self.addAction(rescan)

        # The library menu carries what used to be CLI subcommands. verify is
        # the only way to learn that the library has drifted, so it must stay
        # reachable now that there is no command line.
        menu = self.menuBar().addMenu("Library")
        add = QAction("Add asset…", self)
        add.setShortcut("Ctrl+N")
        add.triggered.connect(self._add_asset)
        menu.addAction(add)
        batch = QAction("Import a folder of assets…", self)
        batch.setShortcut("Ctrl+Shift+N")
        batch.setToolTip("One row per subfolder - for a vendor dump, not a single asset")
        batch.triggered.connect(self._batch_add)
        menu.addAction(batch)
        contents = QAction("Contents of selected…", self)
        contents.setShortcut("Ctrl+I")
        contents.triggered.connect(self._view_asset)
        menu.addAction(contents)
        change = QAction("Edit selected…", self)
        change.setShortcut("Ctrl+E")
        change.triggered.connect(self._edit_asset)
        menu.addAction(change)
        scrap = QAction("Delete selected asset…", self)
        scrap.setShortcut("Shift+Del")
        scrap.triggered.connect(self._delete_asset)
        menu.addAction(scrap)
        menu.addSeparator()
        menu.addAction(rescan)
        check = QAction("Verify", self)
        check.triggered.connect(lambda: self._verify(False))
        menu.addAction(check)
        deep = QAction("Verify (deep - re-hash every file)", self)
        deep.triggered.connect(lambda: self._verify(True))
        menu.addAction(deep)
        upgrade_now = QAction("Migrate metadata…", self)
        upgrade_now.setToolTip("Rewrite any asset.json still on an older schema")
        upgrade_now.triggered.connect(self._migrate)
        menu.addAction(upgrade_now)
        menu.addSeparator()
        bake = QAction("Generate .rat textures for selected…", self)
        bake.setToolTip(
            "Pre-bake into derived/, so Karma does not convert at render time "
            "and does not write its own .rat into tex/")
        bake.triggered.connect(self._bake_selected)
        menu.addAction(bake)
        desktop = QAction("Put a shortcut on the Desktop", self)
        desktop.triggered.connect(self._make_shortcut)
        desktop.setEnabled(shortcut.available())
        menu.addAction(desktop)
        newlib = QAction("Create a new library…", self)
        newlib.setToolTip("A fresh empty copy of this app on another disk")
        newlib.triggered.connect(self._new_library)
        menu.addAction(newlib)
        servers = QAction("Remote libraries…", self)
        servers.setToolTip("Servers this library can browse, and their tokens")
        servers.triggered.connect(self._remote_libraries)
        menu.addAction(servers)
        sync_now = QAction("Refresh remote catalogue", self)
        sync_now.setShortcut("Shift+F5")
        sync_now.setToolTip("Ask every server what it holds. Files are not downloaded.")
        sync_now.triggered.connect(self._sync_catalogue)
        menu.addAction(sync_now)
        push = QAction("Push this library to a server…", self)
        push.setToolTip("Over SMB on the LAN: what is new, changed or moved here")
        push.triggered.connect(self._push_to_server)
        menu.addAction(push)

        self._timer = QTimer(self, singleShot=True, interval=150)
        self._timer.timeout.connect(self.refresh)

        self._apply_zoom()
        self._build_tree()
        self.refresh()

        # Housekeeping with no deadline: it runs once the window is already up.
        thumbcache.sweep_async(cfg)
        self._sync_on_launch()

        # Last, and only on a copy that has nothing. After the window is built,
        # not before: if the setup panel raised, a fresh install would show a
        # traceback instead of an app, and the one thing a first launch must do
        # is open.
        self._offer_setup()

    def _offer_setup(self) -> None:
        from .first_run import FirstRunDialog, mark_seen, needs_setup

        if not needs_setup(self.cfg, len(self.model.rows), self.hosts):
            return
        suggested = next((h for h in self.hosts if h.url and not h.token), None)
        dialog = FirstRunDialog(self.cfg, self, suggested)
        accepted = dialog.exec() == QDialog.Accepted
        # Marked whichever button was pressed. Skip is an answer, and an app
        # that re-asks a declined question is one you learn to click past.
        mark_seen(self.cfg)
        if not accepted:
            return
        if dialog.shortcut_requested:
            # quiet: a shortcut that could not be written must not be the first
            # thing a new user sees. The app works without it.
            self._make_shortcut(quiet=True)
        if not dialog.hosts:
            return

        self.hosts = dialog.hosts
        self._reopen_remotes()
        self._build_tree()
        self.refresh()
        if dialog.sync_requested:
            self._sync_catalogue()

    # ------------------------------------------------------------------ tree

    def _build_tree(self) -> None:
        # Types collapsed by default: 18 of them, 114 categories between them,
        # and the declared taxonomy is a place to go looking rather than a list
        # to read. Opened all at once it is a wall no one scans.
        #
        # What the user opened survives the rebuild, because _build_tree() also
        # runs after every add, edit, delete and F5. Without this, adding one
        # asset would fold the sidebar back up under you - which is exactly the
        # annoyance the old unconditional expand was hiding.
        counts = idx.counts_union(self.conn, self._active_remotes())
        open_types = {self.tree.topLevelItem(i).data(0, TYPE_ROLE)
                      for i in range(self.tree.topLevelItemCount())
                      if self.tree.topLevelItem(i).isExpanded()}

        self.tree.blockSignals(True)
        self.tree.clear()

        total = sum(n for (t, c), n in counts.items() if c is None)
        root = QTreeWidgetItem([f"All   {total}"])
        root.setData(0, TYPE_ROLE, None)
        root.setData(0, CAT_ROLE, None)
        self.tree.addTopLevelItem(root)

        bold = QFont()
        bold.setBold(True)
        for t in self.cfg.types:
            tid = t["id"]
            n = counts.get((tid, None), 0)
            node = QTreeWidgetItem([f"{t['label']}   {n}"])
            node.setData(0, TYPE_ROLE, tid)
            node.setData(0, CAT_ROLE, None)
            node.setFont(0, bold)
            node.setDisabled(False)
            if n == 0:
                node.setForeground(0, theme.dim_colour())
            self.tree.addTopLevelItem(node)

            for cat in self.cfg.categories_for(tid):
                cn = counts.get((tid, cat), 0)
                leaf = QTreeWidgetItem([f"{cat}   {cn}" if cn else cat])
                leaf.setData(0, TYPE_ROLE, tid)
                leaf.setData(0, CAT_ROLE, cat)
                if cn == 0:
                    leaf.setForeground(0, theme.dim_colour())
                node.addChild(leaf)
            # first build: open_types empty -> everything closed
            node.setExpanded(tid in open_types)

        self.tree.blockSignals(False)
        self.tree.setCurrentItem(root)

    # --------------------------------------------------------------- queries

    def _query(self) -> str:
        parts = [self.search.text().strip()]
        item = self.tree.currentItem()
        if item is not None:
            tid = item.data(0, TYPE_ROLE)
            cat = item.data(0, CAT_ROLE)
            if tid:
                parts.append(f"type:{tid}")
            if cat:
                parts.append(f"cat:{cat}")
        return " ".join(p for p in parts if p)

    def _queue_refresh(self) -> None:
        self._timer.start()

    def _active_remotes(self) -> list:
        """The catalogues search should look at right now.

        Switching the toggle off hands back an empty list rather than filtering
        the answer afterwards: the remote catalogue is simply not queried, so
        "hide the cloud" costs less work than showing it rather than more.
        """
        return self.remotes if self.cloud_btn.isChecked() else []

    def _toggle_cloud(self, _on: bool) -> None:
        self._build_tree()
        self.refresh()

    def refresh(self) -> None:
        rows = idx.search_union(self.conn, self._active_remotes(), self._query())
        self.model.set_rows(rows)
        size = sum(r.get("size", 0) for r in rows)
        message = f"{len(rows)} asset(s)   {_human(size)}"
        elsewhere = sum(1 for r in rows
                        if str(r.get("origin", "")).startswith("remote:"))
        if elsewhere:
            message += f"   ({elsewhere} on the server)"
        elif self.remotes and not self.cloud_btn.isChecked():
            # Says WHY the count is lower. A filter that silently removes rows
            # is a filter someone forgets is on, and then the library looks
            # like it lost assets.
            message += "   (cloud hidden)"

        # Counted rather than left to be tallied by eye across a scrolling
        # grid. This is the one number in the bar that is about risk: those
        # assets exist on this disk and nowhere else.
        unpushed = sum(1 for r in rows if gridmodel.is_local_only(r))
        if unpushed:
            message += f"   ·   {unpushed} not on the server"
            # The age goes WITH the number, not somewhere else. "43 not on the
            # server" is alarming and was wrong; "43 not on the server
            # (catalogue 6 h ago)" is the same number with the reason it might
            # be wrong attached to it.
            ages = [catalog.synced_age(h) for h in self.hosts if h.enabled]
            if ages:
                worst = max((a for a in ages if a is not None), default=None)
                if worst is None or worst > 900:
                    message += f"   (catalogue {catalog.describe_age(worst)})"
        # Whatever the startup migration did is worth saying once, on the first
        # refresh - after that the normal count takes the bar back.
        note = upgrade.describe(self._upgrade)
        self._upgrade = None
        self.statusBar().showMessage(f"{message}   ·   {note}" if note else message)
        self._update_detail()

    def _rebuild(self) -> None:
        """F5. Also migrates: it is already reading every asset.json, so the
        marginal cost is a write for the stale ones only."""
        self.statusBar().showMessage("rebuilding index…")
        QApplication.processEvents()
        migrated = upgrade.run(self.cfg)
        result = idx.rebuild(self.cfg)
        self.conn.close()
        self.conn = idx.connect(self.cfg)
        self.model.invalidate()
        self._build_tree()
        self.refresh()

        bits = [f"indexed {result['indexed']} asset(s)"]
        if migrated["upgraded"]:
            bits.append(f"upgraded {migrated['upgraded']} to the current schema")
        self.statusBar().showMessage("   ·   ".join(bits))
        self._report_unreadable(result["failed"] or migrated["failed"])

    def _report_unreadable(self, failed) -> None:
        """A package this build cannot read is never swallowed.

        It almost always means the library was written by a NEWER build - the
        external-disk copy running older code - and the old behaviour showed
        that as an empty library with no explanation anywhere.
        """
        if not failed:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Some assets could not be read")
        box.setText(f"{len(failed)} asset(s) could not be read and are missing "
                    "from the library.")
        box.setInformativeText(
            "This usually means they were written by a newer build of the app "
            "than the one you are running.")
        box.setDetailedText("\n".join(f"{path}: {reason}" for path, reason in failed))
        box.exec()

    def _migrate(self) -> None:
        self.statusBar().showMessage("migrating metadata…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            result = upgrade.run(self.cfg)
        finally:
            QApplication.restoreOverrideCursor()

        QMessageBox.information(
            self, "Migrate metadata",
            f"{result['upgraded']} asset(s) upgraded.\n"
            f"{result['current']} already current.\n"
            f"{len(result['failed'])} could not be read.")
        self._report_unreadable(result["failed"])
        if result["upgraded"]:
            self._rebuild()

    # ------------------------------------------------------------------ remote

    def _bake_selected(self) -> None:
        """Pre-bake .rat for the selected assets. Lazily imported, like the rest.

        Selection only, never the whole library by accident: baking all 111
        would be ~900 conversions and roughly +100 GB, which is not something a
        menu entry should be able to start without being asked for by name.
        """
        from .bake import BakeDialog

        rows = [r for r in self._selected_rows() if self._host_for(r) is None]
        if not rows:
            QMessageBox.information(
                self, "Generate .rat textures",
                "Select one or more assets that are on this disk.\n\n"
                "A cloud asset has to be imported before anything can be baked "
                "from it.")
            return
        BakeDialog(self.cfg, rows, self).exec()

    def _make_shortcut(self, quiet: bool = False) -> None:
        """Desktop shortcut for THIS copy, pointing at this folder's launcher.

        Reachable from the menu as well as from the setup panel, because an
        install that already had assets never sees that panel - and this one
        did, which is precisely the copy that has been launched from a pinned
        .bat by hand for weeks.
        """
        try:
            where = shortcut.create(self.cfg.base)
        except Exception as exc:                        # noqa: BLE001
            if not quiet:
                QMessageBox.warning(self, "Could not create the shortcut", str(exc))
            return
        self.statusBar().showMessage(f"shortcut created: {where}")

    def _new_library(self) -> None:
        """Copy the app - not the assets - somewhere else. Lazily imported."""
        from .new_library import NewLibraryDialog

        NewLibraryDialog(self.cfg, self.hosts, self).exec()

    def _remote_libraries(self) -> None:
        from .remote_libraries import RemoteLibrariesDialog

        dialog = RemoteLibrariesDialog(self.cfg, self.hosts, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.hosts = dialog.hosts
        self._reopen_remotes()
        self._build_tree()
        self.refresh()

    def _reopen_remotes(self) -> None:
        """Close what is open and open what is configured, in that order.

        A removed host whose connection stayed open would keep answering
        searches from a catalogue nothing can refresh any more.
        """
        for _, conn in self.remotes:
            try:
                conn.close()
            except Exception:                           # noqa: BLE001
                pass
        self.remotes = catalog.open_all(self.cfg, self.hosts)
        # The model fetches remote thumbnails itself, so it needs the tokens.
        # Also clears the cooldown, which is what makes "fix the token, sync,
        # and the pictures appear" work without restarting the window.
        self.model.set_hosts(self.hosts)

    def _sync_on_launch(self) -> None:
        """Refresh the catalogue in the background, once the window is up.

        The rule was "catalogues are opened at launch and NOT synced at launch",
        and it was right about the thing it was protecting: startup must not
        depend on a machine that is asleep most of the time. But "not ON the
        launch path" was read as "never", and nothing else ever synced - so the
        catalogue aged silently and the grid told a confident lie. Tonight it
        showed 43 assets as missing from the server when seven were.

        This is not on the launch path. The window is already built and filled
        from the stored catalogue; this starts afterwards, on netpool, and if
        the box is asleep it fails quietly and nothing changes. An ETag sync is
        one request that usually comes back 304 with no body, so the cost of
        being right is close to nothing.
        """
        if not self.hosts:
            return
        from .remote_libraries import sync_async

        sync_async(self.cfg, self.hosts, self._sync_finished_quietly)

    def _sync_finished_quietly(self, results: list) -> None:
        """Same as a manual sync, minus the dialogs.

        A launch-time sync must never open a window. The box being asleep is
        the normal state, not an error, and an app that greets you with a
        warning every time you open it away from home is an app you stop
        reading warnings from.
        """
        remote.save_hosts(self.cfg, self.hosts)
        self._reopen_remotes()
        self._build_tree()
        self.refresh()
        changed = [f"{name}: {msg}" for name, ok, msg in results if ok]
        if changed:
            self.statusBar().showMessage(
                self.statusBar().currentMessage()
                + ("   ·   " if self.statusBar().currentMessage() else "")
                + "   ·   ".join(changed))

    def _sync_catalogue(self) -> None:
        """Shift+F5. Ask every server what it holds; download no files."""
        from .remote_libraries import sync_async

        if not self.hosts:
            QMessageBox.information(
                self, "Refresh remote catalogue",
                "No servers are configured yet.\n\n"
                "Library ▸ Remote libraries… to add one.")
            return

        self.statusBar().showMessage("asking the server(s)…")
        sync_async(self.cfg, self.hosts, self._sync_finished)

    def _sync_finished(self, results: list) -> None:
        # Rewrite the hosts file here, on the GUI thread: the job updated each
        # host's ETag in memory and saved, but a host removed while the sync was
        # in flight must not be written back by it.
        remote.save_hosts(self.cfg, self.hosts)
        self._reopen_remotes()
        self._build_tree()
        self.refresh()

        bad = [f"{name}: {message}" for name, ok, message in results if not ok]
        good = [f"{name}: {message}" for name, ok, message in results if ok]
        if bad:
            QMessageBox.warning(
                self, "Some servers did not answer",
                "\n".join(bad) + ("\n\n" + "\n".join(good) if good else ""))
        self.statusBar().showMessage(
            "   ·   ".join(good) if good else "no server answered")

    def _push_to_server(self) -> None:
        """Send what this disk has that the master does not.

        Over SMB, not over the API: the API is read-only by decision, and the
        box is the master (`server/client-contract.md`). A host with no share
        recorded is one that is only ever browsed, so it is not offered.
        """
        from .sync_server import PushToServerDialog

        able = [h for h in self.hosts if h.share]
        if not able:
            QMessageBox.information(
                self, "Push to a server",
                "No server has a share recorded.\n\n"
                "Library ▸ Remote libraries… — fill in the Share column "
                "with the folder on the server that holds library/, "
                "for example\n\n"
                r"    \\192.168.1.13\data2\assets")
            return
        host = able[0]
        if len(able) > 1:
            name, ok = QInputDialog.getItem(
                self, "Push to a server", "Server:",
                [h.name for h in able], 0, False)
            if not ok:
                return
            host = next(h for h in able if h.name == name)

        dialog = PushToServerDialog(self.cfg, host, self)
        dialog.exec()
        if dialog.pushed:
            # The server's catalogue is what the grid shows for that host, and
            # it is now behind the share by however long the box takes to
            # re-index. Saying so beats a cloud tile that quietly does not
            # appear.
            self.statusBar().showMessage(
                "Sent. The server's catalogue updates when it re-indexes — "
                "then Shift+F5 here.")

    # ------------------------------------------------------------------ import

    def _add_asset(self) -> None:
        """Imported lazily so a fault in the add path can never stop the
        browser itself from opening."""
        from .add_asset import AddAssetDialog

        dialog = AddAssetDialog(self.cfg, self)
        dialog.exec()
        if dialog.added:
            self._build_tree()
            self.refresh()
            self.statusBar().showMessage(f"added {dialog.added} asset(s)")

    def _batch_add(self) -> None:
        """Import a whole folder. Lazily imported, like Add and Edit."""
        from .batch_add import BatchAddDialog

        dialog = BatchAddDialog(self.cfg, self)
        dialog.exec()
        if dialog.added:
            self._build_tree()
            self.refresh()
            self.statusBar().showMessage(f"imported {dialog.added} asset(s)")

    def _open_selected(self) -> None:
        """Double-click. Means "show me this asset" - which differs by origin.

        On a local asset that is Contents. On a cloud one there is nothing to
        show yet, and the useful answer to "show me this" is the window that
        says what it would cost to have it.
        """
        row = self._current_row()
        if row and self._host_for(row) is not None:
            self._import_remote()
            return
        self._view_asset()

    def _host_for(self, row):
        """The server a cloud row came from, or None if it is not a cloud row."""
        origin = str(row.get("origin") or "")
        if not origin.startswith("remote:"):
            return None
        return next((h for h in self.hosts
                     if h.name == origin[len("remote:"):]), None)

    def _import_remote(self) -> None:
        """Download the selected cloud asset. One at a time, deliberately.

        A multi-select download would queue gigabytes behind one click, and the
        thing that makes this bearable - seeing what it costs before it costs
        it - does not survive being applied to twelve assets at once.
        """
        from .import_remote import ImportRemoteDialog

        row = self._current_row()
        if not row:
            return
        host = self._host_for(row)
        if host is None:
            return

        dialog = ImportRemoteDialog(self.cfg, host, row, self)
        dialog.exec()
        if dialog.result_dir is None:
            return

        # Re-index from what actually landed. The download wrote asset.json
        # verbatim, so this reads the SERVER's uuid back and the row flips from
        # remote to cache - which is what stops the tile being blue.
        from assetlib.model import Asset

        try:
            idx.upsert(self.conn, Asset.read(dialog.result_dir),
                       dialog.result_dir, self.cfg.cache_root, "cache")
        except Exception as exc:                        # noqa: BLE001
            QMessageBox.warning(self, "Downloaded, but not indexed", str(exc))
        self.model.invalidate(row["uuid"])
        self._build_tree()
        self.refresh()

    def _view_asset(self) -> None:
        """Look inside the package: every file, with what asset.json says it is."""
        path = self._selected_dir()
        if path is None:
            return

        from .asset_view import AssetViewDialog

        try:
            dialog = AssetViewDialog(self.cfg, path, self)
        except Exception as exc:                        # noqa: BLE001
            QMessageBox.critical(self, "Cannot open this asset", str(exc))
            return
        dialog.exec()
        if dialog.edited:
            self.model.invalidate()
            self._build_tree()
            self.refresh()

    def _selected_dir(self):
        row = self._current_row()
        if not row:
            return None
        path = self.cfg.asset_path(row)
        if path is None:
            # Catalogued on a server and not downloaded. Not an error, and not
            # something to phrase as one - the asset is real, it is just not
            # here yet.
            self.statusBar().showMessage(
                f"{row['name']} is on {row.get('origin', '?')} - import it first")
            return None
        if not path.exists():
            self.statusBar().showMessage(f"missing on disk: {path}")
            return None
        return path

    def _edit_asset(self) -> None:
        """Open the selected asset for editing. Lazily imported, like Add."""
        row = self._current_row()
        path = self._selected_dir()
        if path is None:
            return

        from .edit_asset import EditAssetDialog

        try:
            dialog = EditAssetDialog(self.cfg, path, self)
        except Exception as exc:                        # noqa: BLE001
            QMessageBox.critical(self, "Cannot open this asset", str(exc))
            return
        dialog.exec()
        if dialog.added:
            thumbcache.forget(self.cfg, row["uuid"])
            self.model.invalidate()
            self._build_tree()
            self.refresh()
            self.statusBar().showMessage(f"updated {row['name']}")

    def _has_geometry(self, row) -> bool:
        """Does this asset hold a mesh? Answered from the index, never from disk.

        `has_geo` is computed when the asset is indexed. It is NULL for a row
        written before the column existed, and that is not the same as 0: an
        old index would otherwise claim every asset is mesh-free and the menu
        entry would vanish everywhere until someone pressed F5. So an unknown
        falls back to the type's ingest strategy, which is in memory already.
        """
        known = row.get("has_geo")
        if known is not None:
            return bool(known)
        tdef = self.cfg.type_by_id.get(row.get("type"), {})
        return tdef.get("ingest") == "mesh_plus_textures"

    def _import_houdini(self) -> None:
        """Ask what to build, then build it - or leave a request for the shelf.

        Lazily imported like Add and Edit, for the same reason: a fault on this
        path must not be able to stop the browser from opening.
        """
        from assetlib.model import Asset

        from .import_houdini import HoudiniImportDialog, send

        # Only the ones that hold a mesh. A selection dragged across a shelf
        # picks up HDRIs and texture sets, and silently skipping them is kinder
        # than refusing the whole thing.
        rows = [r for r in self._selected_rows() if self._has_geometry(r)]
        if not rows:
            return

        assets = []
        skipped_remote = 0
        for row in rows:
            path = self.cfg.asset_path(row)
            if path is None:
                # Not downloaded. Skipped like a non-mesh asset rather than
                # refusing the batch, but counted - silently building 3 of 12
                # is the failure people do not notice.
                skipped_remote += 1
                continue
            if not path.exists():
                continue
            try:
                assets.append((Asset.read(path), path))
            except Exception as exc:                    # noqa: BLE001
                QMessageBox.critical(self, "Cannot read this asset",
                                     f"{row['name']}: {exc}")
                return
        if not assets:
            if skipped_remote:
                # Every one of them was remote. A dialog that opens on nothing
                # and a window that does nothing look identical, so say which
                # it was.
                QMessageBox.information(
                    self, "Nothing to build",
                    f"{skipped_remote} selected asset(s) are catalogued but not "
                    "downloaded yet. Import them first.")
            return

        # The dialog is built from the FIRST asset and its answers are applied
        # to all of them. That is a real hazard when the selection is mixed -
        # see the note in ROADMAP.md - so the dialog says so rather than
        # pretending the options describe every asset.
        dialog = HoudiniImportDialog(assets[0][0], self.cfg, self,
                                     count=len(assets))
        if dialog.exec() != QDialog.Accepted:
            return

        opts = dialog.options()
        built, failed = 0, []
        for asset, path in assets:
            try:
                send(asset, path, self.cfg, opts)
                built += 1
            except Exception as exc:                    # noqa: BLE001
                failed.append(f"{asset.name}: {exc}")

        if failed:
            QMessageBox.warning(
                self, "Some assets did not build",
                f"{built} built, {len(failed)} failed.\n\n"
                + "\n".join(failed[:10]))
        self.statusBar().showMessage(
            f"sent {built} asset(s) to Houdini"
            + (f"   ·   {len(failed)} failed" if failed else "")
            + (f"   ·   {skipped_remote} not downloaded" if skipped_remote else ""))

    def _context_menu(self, point) -> None:
        """Right-click on a tile.

        Everything you can do to one asset, on the asset itself. Delete is here
        as well as in the Library menu because that is where a person looks for
        it - a menu bar is not somewhere you go hunting to remove a thing.
        """
        index = self.view.indexAt(point)
        if index.isValid():
            sm = self.view.selectionModel()
            if sm.isSelected(index):
                # Right-clicking INSIDE a selection must not collapse it. The
                # plain setCurrentIndex that used to be here cleared the
                # selection and selected the one tile under the cursor, so
                # "Import 12 to Houdini" turned into one asset between the
                # click and the menu opening. NoUpdate moves the current index
                # without touching what is selected.
                sm.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
            else:
                # Outside it, the click means "this one instead", which is what
                # replacing the selection is for.
                self.view.setCurrentIndex(index)
        row = self._current_row()
        if row is None:
            return

        menu = QMenu(self)
        if self._host_for(row) is not None:
            # First, and alone at the top: on a cloud asset it is the only
            # entry that can do anything. Contents and Edit need files.
            menu.addAction("Import from the server…", self._import_remote)
            menu.addSeparator()
        menu.addAction("Contents…", self._view_asset)
        menu.addAction("Edit…", self._edit_asset)
        with_geo = [r for r in self._selected_rows() if self._has_geometry(r)]
        if with_geo:
            menu.addSeparator()
            label = ("Import to Houdini…" if len(with_geo) == 1
                     else f"Import {len(with_geo)} to Houdini…")
            menu.addAction(label, self._import_houdini)
        menu.addSeparator()
        menu.addAction("Open folder", self._open_folder)
        menu.addSeparator()
        menu.addAction(f"Delete {row['name']}…", self._delete_asset)
        menu.exec(self.view.viewport().mapToGlobal(point))

    def _delete_asset(self) -> None:
        """Remove a whole package, files and index row alike. Irreversible."""
        row = self._current_row()
        path = self._selected_dir()
        if path is None:
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Delete asset")
        box.setText(f"Delete {row['name']} permanently?")
        box.setInformativeText(
            f"{row['type']} / {row['category']}   {_human(row.get('size', 0))}\n"
            f"{path}\n\n"
            "Every file in the package is destroyed. "
            "This cannot be undone.")
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Yes:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            summary = delete_asset(path, self.cfg)
        except Exception as exc:                        # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Could not delete the asset", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        idx.remove(self.conn, summary["uuid"])
        thumbcache.forget(self.cfg, summary["uuid"])
        self.model.invalidate(summary["uuid"])
        self._build_tree()
        self.refresh()
        self.statusBar().showMessage(
            f"deleted {summary['name']} - {summary['files']} file(s), "
            f"{_human(summary['bytes'])} freed")

    def _verify(self, deep: bool) -> None:
        self.statusBar().showMessage("verifying…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            problems = verify(self.cfg, deep=deep)
        finally:
            QApplication.restoreOverrideCursor()

        if not problems:
            self.statusBar().showMessage("library clean - all invariants hold")
            QMessageBox.information(self, "Verify", "Library clean - all invariants hold.")
            return
        # Counted separately: an info line - schema skew - is not a problem, and
        # showing it as "1 warning" would make a healthy library look damaged.
        errors = sum(1 for s, _, _ in problems if s == "error")
        warnings = sum(1 for s, _, _ in problems if s == "warn")
        notes = len(problems) - errors - warnings

        if not errors and not warnings:
            self.statusBar().showMessage("library clean - all invariants hold")
        headline = [f"{errors} error(s)", f"{warnings} warning(s)"]
        if notes:
            headline.append(f"{notes} note(s)")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning if errors or warnings else QMessageBox.Information)
        box.setWindowTitle("Verify")
        box.setText("Library clean - all invariants hold."
                    if not errors and not warnings else ", ".join(headline))
        box.setDetailedText(
            "\n".join(f"{s.upper():<5} {path}: {message}" for s, path, message in problems))
        box.exec()
        if errors or warnings:
            self.statusBar().showMessage(
                f"{errors + warnings} problem(s) - see the report")

    # ---------------------------------------------------------------- detail

    def _current_row(self):
        index = self.view.currentIndex()
        if index.isValid():
            return index.data(ROW_ROLE)
        sel = self.view.selectionModel().selectedIndexes()
        return sel[0].data(ROW_ROLE) if sel else None

    def _selected_rows(self) -> list:
        """Every selected asset, in grid order. The current one first.

        The current index leads because it is the one the options dialog is
        built from, and a dialog describing the third asset while the first is
        under the cursor would be its own kind of wrong.
        """
        rows = [i.data(ROW_ROLE) for i in self.view.selectionModel().selectedIndexes()]
        rows = [r for r in rows if r]
        current = self._current_row()
        if current and current in rows:
            rows.remove(current)
            rows.insert(0, current)
        return rows

    def _update_detail(self, *_) -> None:
        row = self._current_row()
        if not row:
            self.detail.setText("—")
            self.open_btn.setEnabled(False)
            self.edit_btn.setEnabled(False)
            self.view_btn.setEnabled(False)
            return
        res = f"{row['resolution']}px" if row.get("resolution") else ""
        bits = [row["name"], f"{row['type']} / {row['category']}", res,
                _human(row.get("size", 0))]
        path = self.cfg.asset_path(row)
        # A remote asset has no path to show, so it shows where it IS instead.
        # Blanking the line would read as "this asset has no files".
        where = str(path) if path is not None else f"on {row.get('origin', '?')}"
        self.detail.setText("   ·   ".join(b for b in bits if b) + f"\n{where}")
        here = path is not None
        self.open_btn.setEnabled(here)
        self.edit_btn.setEnabled(here)
        self.view_btn.setEnabled(here)

    def _open_folder(self) -> None:
        row = self._current_row()
        if not row:
            return
        path = self.cfg.asset_path(row)
        if path is None:
            self.statusBar().showMessage(
                f"{row['name']} is not downloaded - nothing to open")
            return
        if not path.exists():
            self.statusBar().showMessage(f"missing on disk: {path}")
            return
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - intentional shell-less open
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')

    # ------------------------------------------------------------------ zoom

    def _apply_zoom(self) -> None:
        # Sizes come from gridmodel, where the tile is drawn - two places
        # deciding the same geometry is how the text block ended up too short
        # for the names it had to hold.
        px = ZOOM_SIZES[self.zoom.value()]
        icon, grid = tile_sizes(px)
        self.view.setIconSize(icon)
        self.view.setGridSize(grid)

    def closeEvent(self, event):
        # Network jobs first, and before the databases they might want to
        # write to. Everything below is local and finishes immediately.
        drained = netpool.shutdown()

        self.conn.close()
        for _, conn in self.remotes:
            try:
                conn.close()
            except Exception:                           # noqa: BLE001
                pass
        super().closeEvent(event)

        if not drained:
            # A job is still blocked in a socket read and cannot be interrupted
            # from here. Qt will wait for it before the process can exit, which
            # is how a closed window left pythonw.exe alive - invisible, with
            # no console, holding its own folder open so it could not even be
            # deleted.
            #
            # _exit rather than sys.exit: sys.exit unwinds, and the unwinding
            # is exactly what blocks. Nothing is lost - every database was just
            # closed above, asset.json is written at commit time, and a partly
            # downloaded file is a .part that resumes.
            import os

            print("netpool did not drain; exiting hard", flush=True)
            os._exit(0)


def _install_logging(base: Path) -> None:
    """Give the app somewhere to write when it has no console.

    Launched through `Asset Library.vbs` the interpreter is `pythonw.exe`, which
    has no console AND no stdout: under it `sys.stdout` is None, so a stray
    print() raises and a traceback goes nowhere at all. That is the price of
    never flashing a cmd window, and this is what buys it back - the output goes
    to launch.log instead, silent when all is well and readable when it is not.

    Also an excepthook, because the expensive failure is the one BEFORE the
    window exists: with no console and no hook, a crash at import time is a
    program that starts and vanishes with nothing anywhere saying why.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return                          # a real console: leave it alone

    try:
        stream = open(base / "launch.log", "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    sys.stdout = sys.stderr = stream

    def _log_crash(kind, value, tb):
        import traceback
        traceback.print_exception(kind, value, tb, file=stream)
        stream.flush()

    sys.excepthook = _log_crash


def main(cfg=None) -> int:
    if cfg is None:
        from assetlib.config import find_config

        cfg = find_config(Path(__file__).parent)
    _install_logging(cfg.base)
    # There is no `init` command any more: the tree is materialised on start.
    cfg.ensure_roots()
    cfg.ensure_tree()
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)                    # before the first widget, see theme.py
    win = MainWindow(cfg)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
