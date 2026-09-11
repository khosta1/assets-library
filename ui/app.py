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

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit,
                               QListView, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSlider, QSplitter, QStatusBar,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from assetlib import index as idx
from assetlib import upgrade
from assetlib.edit import delete_asset
from assetlib.verify import verify

from . import thumbcache

from .gridmodel import ROW_ROLE, AssetGridModel, _human

TYPE_ROLE = Qt.UserRole + 10
CAT_ROLE = Qt.UserRole + 11
ZOOM_SIZES = [96, 128, 160, 200, 256, 320]


class MainWindow(QMainWindow):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.conn = idx.connect(cfg)
        # Costs one small file read when the library is already current, so it
        # can sit on the launch path. Only a code upgrade makes it walk.
        self._upgrade = upgrade.run_if_pending(cfg)
        # The path is in the title on purpose: the whole project is meant to be
        # copied onto an external disk, so several libraries exist and they look
        # identical from the inside. Launching the wrong one is otherwise
        # invisible until you notice your changes are missing.
        self.setWindowTitle(f"Asset Library  —  {cfg.base}")
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

        top = QHBoxLayout()
        top.addWidget(self.add_btn)
        top.addWidget(self.search, 1)
        top.addWidget(QLabel("size"))
        top.addWidget(self.zoom)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(220)
        self.tree.itemSelectionChanged.connect(self._queue_refresh)

        self.model = AssetGridModel(cfg)
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setViewMode(QListView.IconMode)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setUniformItemSizes(True)      # required for smooth scrolling at scale
        self.view.setMovement(QListView.Static)
        self.view.setWordWrap(True)
        self.view.setSpacing(8)
        self.view.setSelectionMode(QListView.SingleSelection)
        self.view.doubleClicked.connect(lambda *_: self._view_asset())
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

        self._timer = QTimer(self, singleShot=True, interval=150)
        self._timer.timeout.connect(self.refresh)

        self._apply_zoom()
        self._build_tree()
        self.refresh()

        # Housekeeping with no deadline: it runs once the window is already up.
        thumbcache.sweep_async(cfg)

    # ------------------------------------------------------------------ tree

    def _build_tree(self) -> None:
        counts = idx.counts(self.conn)
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
                node.setForeground(0, Qt.gray)
            self.tree.addTopLevelItem(node)

            for cat in self.cfg.categories_for(tid):
                cn = counts.get((tid, cat), 0)
                leaf = QTreeWidgetItem([f"{cat}   {cn}" if cn else cat])
                leaf.setData(0, TYPE_ROLE, tid)
                leaf.setData(0, CAT_ROLE, cat)
                if cn == 0:
                    leaf.setForeground(0, Qt.gray)
                node.addChild(leaf)
            if n:
                node.setExpanded(True)

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

    def refresh(self) -> None:
        rows = idx.search(self.conn, self._query())
        self.model.set_rows(rows)
        size = sum(r.get("size", 0) for r in rows)
        message = f"{len(rows)} asset(s)   {_human(size)}"
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
        path = self.cfg.library / row["path"]
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

    def _context_menu(self, point) -> None:
        """Right-click on a tile.

        Everything you can do to one asset, on the asset itself. Delete is here
        as well as in the Library menu because that is where a person looks for
        it - a menu bar is not somewhere you go hunting to remove a thing.
        """
        index = self.view.indexAt(point)
        if index.isValid():
            self.view.setCurrentIndex(index)
        row = self._current_row()
        if row is None:
            return

        menu = QMenu(self)
        menu.addAction("Contents…", self._view_asset)
        menu.addAction("Edit…", self._edit_asset)
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
        sel = self.view.selectionModel().selectedIndexes()
        return sel[0].data(ROW_ROLE) if sel else None

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
        path = self.cfg.library / row["path"]
        self.detail.setText("   ·   ".join(b for b in bits if b) + f"\n{path}")
        self.open_btn.setEnabled(True)
        self.edit_btn.setEnabled(True)
        self.view_btn.setEnabled(True)

    def _open_folder(self) -> None:
        row = self._current_row()
        if not row:
            return
        path = self.cfg.library / row["path"]
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
        px = ZOOM_SIZES[self.zoom.value()]
        self.view.setIconSize(QSize(px, px))
        self.view.setGridSize(QSize(px + 26, px + 46))

    def closeEvent(self, event):
        self.conn.close()
        super().closeEvent(event)


def main(cfg=None) -> int:
    if cfg is None:
        from assetlib.config import find_config

        cfg = find_config(Path(__file__).parent)
    # There is no `init` command any more: the tree is materialised on start.
    cfg.ensure_roots()
    cfg.ensure_tree()
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow(cfg)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
