"""Import a folder of assets in one pass.

The Add window imports ONE asset and shows every file it will touch. That is
right for a vendor zip you have never seen, and wrong for the seventeenth
Megascans plant in a row, where the per-file decisions are identical and the
only things that differ are the name and which folder it came from.

So this is the same pipeline at a coarser grain: one ROW per folder instead of
one row per file. `analyse()` still runs per asset, `commit()` is still the only
writer, and nothing is written until Import is pressed. What is batched is the
confirming, not the deciding - type, category and name are still declared, just
declared for twenty assets at once with per-row overrides for the ones that
differ.

`analyse()` is read-only, so the scan can run ahead of any decision and be
thrown away if the folder was the wrong one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (QAbstractTableModel, QItemSelectionModel, QModelIndex,
                            QObject, QRunnable, Qt, Signal)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QProgressDialog,
                               QPushButton, QStyledItemDelegate, QTableView,
                               QVBoxLayout)

from assetlib import index as idx
from assetlib.analyse import analyse, conflicts
from assetlib.commit import commit
from assetlib.model import Asset
from assetlib.naming import normalise, unique_name

from . import theme, writepool
from .gridmodel import _human

COL_ON, COL_FOLDER, COL_NAME, COL_TYPE, COL_CAT, COL_FILES, COL_SIZE, COL_STATUS = range(8)
HEADERS = ["", "Folder", "Name", "Type", "Category", "Files", "Size", "Status"]


@dataclass
class Candidate:
    """One folder, and what analysing it produced."""
    folder: Path
    plan: object = None
    name: str = ""
    type_id: str = ""
    category: str | None = None
    status: str = ""
    on: bool = True
    error: str = ""

    @property
    def files(self) -> int:
        return len(self.plan.kept) if self.plan else 0

    @property
    def size(self) -> int:
        return self.plan.size_out if self.plan else 0


# ----------------------------------------------------------------- the scan


class _ScanSignals(QObject):
    one = Signal(int, object)
    done = Signal()


class ScanWorker(QRunnable):
    """analyse() every subfolder, off the GUI thread.

    It reads the header of every texture to measure resolution, so seventeen
    Megascans plants is a few thousand file opens - fast, but not fast enough to
    do between two paint events.
    """

    def __init__(self, folders, cfg, signals):
        super().__init__()
        self.folders, self.cfg, self.signals = folders, cfg, signals
        self.setAutoDelete(True)

    def run(self):
        for i, folder in enumerate(self.folders):
            cand = Candidate(folder=folder)
            try:
                plan = analyse(folder, self.cfg)
                cand.plan = plan
                cand.name = plan.name
                cand.type_id = plan.type_id
                cand.category = plan.category
                if conflicts(plan):
                    cand.error = "two files claim one destination"
                elif not plan.kept:
                    cand.error = "nothing to import"
            except Exception as exc:                   # noqa: BLE001
                cand.error = str(exc)
                cand.on = False
            self.signals.one.emit(i, cand)
        self.signals.done.emit()


# ----------------------------------------------------------------- the model


class BatchModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def bind_view(self, dialog) -> None:
        """The model spreads an edit across the selection, and only the dialog
        knows what that is - Qt collapses the live selection on the click that
        starts an edit, so the dialog keeps the memory. Handed over once rather
        than reached for through parent chains, which break the moment the
        table is reparented.
        """
        self._dialog = dialog

    def _selected_or(self, row) -> list:
        """Rows an edit on `row` applies to. One row when nothing is selected,
        which is what makes editing an unselected row safe."""
        dialog = getattr(self, "_dialog", None)
        return dialog.rows_for(row) if dialog else [row]

    def top_left_changed(self, index) -> None:
        """Repaint everything: a spread edit touches rows far from the cursor."""
        self.dataChanged.emit(self.index(0, 0),
                              self.index(max(len(self.rows) - 1, 0), len(HEADERS) - 1))

    def replace(self, at, cand):
        self.rows[at] = cand
        self.dataChanged.emit(self.index(at, 0), self.index(at, len(HEADERS) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        c = self.rows[index.row()]
        col = index.column()

        if role == Qt.CheckStateRole and col == COL_ON:
            return Qt.Checked if c.on else Qt.Unchecked
        if role in (Qt.DisplayRole, Qt.EditRole):
            if col == COL_FOLDER:
                return c.folder.name
            if col == COL_NAME:
                return c.name
            if col == COL_TYPE:
                return c.type_id
            if col == COL_CAT:
                return c.category or "—"
            if col == COL_FILES:
                return str(c.files) if c.plan else ""
            if col == COL_SIZE:
                return _human(c.size) if c.plan else ""
            if col == COL_STATUS:
                return c.error or c.status or ("ready" if c.plan else "…")
        if role == Qt.ForegroundRole and (c.error or not c.on):
            return theme.dim_colour()
        if role == Qt.ToolTipRole:
            return str(c.folder) + (f"\n{c.error}" if c.error else "")
        return None

    def setData(self, index, value, role=Qt.EditRole):
        c = self.rows[index.row()]
        col = index.column()
        if role == Qt.CheckStateRole and col == COL_ON:
            on = (Qt.CheckState(value) == Qt.Checked)
            # Ticking one row of a selection ticks the selection. Twenty rows
            # toggled one at a time is the tedium this window exists to remove.
            rows = self._selected_or(index.row())
            for at in rows:
                self.rows[at].on = on
            self.top_left_changed(index)
            dialog = getattr(self, "_dialog", None)
            if dialog:
                dialog.reselect(rows)
            return True
        elif col == COL_NAME:
            # Taken as typed. Normalising here would rewrite the name under the
            # cursor while it is being edited; it is normalised once on import,
            # where the result can be shown before anything is written.
            c.name = str(value).strip()
        elif col == COL_TYPE:
            c.type_id = str(value)
        elif col == COL_CAT:
            c.category = str(value) or None
        else:
            return False
        self.dataChanged.emit(index, index)
        return True

    def flags(self, index):
        base = super().flags(index)
        if index.column() == COL_ON:
            return base | Qt.ItemIsUserCheckable
        if index.column() in (COL_NAME, COL_TYPE, COL_CAT):
            return base | Qt.ItemIsEditable
        return base


class ChoiceDelegate(QStyledItemDelegate):
    """A closed list, per row. Type and category are vocabularies, not free text
    - the same rule the Add window obeys, applied one column over."""

    def __init__(self, dialog, which):
        super().__init__(dialog)
        self.dialog, self.which = dialog, which

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        row = self.dialog.model.rows[index.row()]
        if self.which == "type":
            for t in self.dialog.cfg.types:
                combo.addItem(t["label"], t["id"])
        else:
            for cat in self.dialog.cfg.categories_for(row.type_id):
                combo.addItem(cat, cat)
        return combo

    def setEditorData(self, editor, index):
        at = editor.findData(index.data(Qt.EditRole))
        editor.setCurrentIndex(max(at, 0))

    def setModelData(self, editor, model, index):
        self.dialog.set_on_selection(index, editor.currentData())


# ---------------------------------------------------------------- the dialog


class _CommitSignals(QObject):
    done = Signal(int, str)
    failed = Signal(int, str)


class BatchCommitWorker(QRunnable):
    """Commit the checked rows, one after another, on the write pool.

    Sequential on purpose. The write pool is single-threaded because two things
    mutating library/ at once is not a situation worth supporting (gotcha 7),
    and copying twenty assets in parallel off one disk is slower anyway.
    """

    def __init__(self, jobs, cfg, tags, move, signals):
        super().__init__()
        self.jobs, self.cfg, self.tags, self.move = jobs, cfg, tags, move
        self.signals = signals
        self.setAutoDelete(True)

    def run(self):
        try:
            conn = idx.connect(self.cfg)
        except Exception:                              # noqa: BLE001
            conn = None

        for at, plan in self.jobs:
            try:
                asset_dir = commit(plan, self.cfg, tags=self.tags, move=self.move)
            except Exception as exc:                   # noqa: BLE001
                self.signals.failed.emit(at, str(exc))
                continue
            try:
                if conn is not None:
                    idx.upsert(conn, Asset.read(asset_dir), asset_dir, self.cfg.library)
            except Exception as exc:                   # noqa: BLE001
                self.signals.failed.emit(at, f"written but not indexed: {exc}")
                continue
            self.signals.done.emit(at, str(asset_dir))

        if conn is not None:
            conn.close()


class BatchAddDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.added = 0
        self._pending = 0
        self.setWindowTitle("Import a folder of assets")
        self.resize(1040, 640)

        self.folder_label = QLabel("no folder chosen")
        browse = QPushButton("Choose folder...")
        browse.clicked.connect(self._choose)

        self.type_all = QComboBox()
        for t in cfg.types:
            self.type_all.addItem(t["label"], t["id"])
        set_type = QPushButton("set all")
        set_type.clicked.connect(self._apply_type)

        self.cat_all = QComboBox()
        set_cat = QPushButton("set all")
        set_cat.clicked.connect(self._apply_cat)
        self.type_all.currentIndexChanged.connect(self._reload_cats)

        top = QHBoxLayout()
        top.addWidget(browse)
        top.addWidget(self.folder_label, 1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Type"))
        row2.addWidget(self.type_all)
        row2.addWidget(set_type)
        row2.addSpacing(16)
        row2.addWidget(QLabel("Category"))
        row2.addWidget(self.cat_all)
        row2.addWidget(set_cat)
        row2.addStretch(1)

        self.tags = QLineEdit(
            placeholderText="tags applied to every asset in this batch   e.g. src:megascans")

        self.model = BatchModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # NOT AllEditTriggers. A bare single click would open the editor and,
        # being a plain click, collapse a multi-row selection to the row under
        # the cursor - so the edit that was meant for twenty rows arrived with
        # one row selected. Editing now needs a second click on an already
        # selected cell, a double click, or F2.
        self.table.setEditTriggers(QAbstractItemView.SelectedClicked
                                   | QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.model.bind_view(self)
        self.table.selectionModel().selectionChanged.connect(self._remember)
        self.table.setItemDelegateForColumn(COL_TYPE, ChoiceDelegate(self, "type"))
        self.table.setItemDelegateForColumn(COL_CAT, ChoiceDelegate(self, "cat"))
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(COL_FOLDER, QHeaderView.Stretch)
        head.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        self.table.setColumnWidth(COL_ON, 28)

        self.status = QLabel("choose a folder holding one subfolder per asset")
        self.move_box = QCheckBox("Move files (do not keep a copy)")
        self.move_box.setToolTip(
            "Same drive: renamed into the library, instant.\n"
            "Different drive: copied, verified, then the originals removed.")

        self.go = QPushButton("Import checked")
        self.go.setEnabled(False)
        self.go.clicked.connect(self._commit)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)

        foot = QHBoxLayout()
        foot.addWidget(self.go)
        foot.addWidget(self.move_box)
        foot.addStretch(1)
        foot.addWidget(close)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(row2)
        lay.addWidget(self.tags)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)
        lay.addLayout(foot)

        self._reload_cats()

    # ------------------------------------------------------------------ scan

    def _choose(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Folder holding one subfolder per asset")
        if folder:
            self.scan(Path(folder))

    def scan(self, root: Path) -> None:
        subs = sorted(p for p in root.iterdir() if p.is_dir())
        if not subs:
            QMessageBox.information(
                self, "Nothing to scan",
                f"{root} holds no subfolders.\n\n"
                "This window expects one subfolder per asset. For a single "
                "asset use Add (Ctrl+N).")
            return

        self.folder_label.setText(str(root))
        self.model.set_rows([Candidate(folder=p) for p in subs])
        self.status.setText(f"analysing {len(subs)} folder(s)...")
        self.go.setEnabled(False)

        signals = _ScanSignals()
        signals.one.connect(self._scanned)
        signals.done.connect(self._scan_done)
        # Held on the dialog: a Signals object that goes out of scope takes its
        # connections with it and the worker emits into nothing.
        self._scan_signals = signals
        writepool.start(ScanWorker(subs, self.cfg, signals))

    def _scanned(self, at, cand) -> None:
        self.model.replace(at, cand)

    def _scan_done(self) -> None:
        ready = [c for c in self.model.rows if c.plan and not c.error]
        self.status.setText(
            f"{len(ready)} of {len(self.model.rows)} ready   -   "
            f"{_human(sum(c.size for c in ready))}   -   "
            "set type and category, then Import")
        self.go.setEnabled(bool(ready))

    # --------------------------------------------------------------- set all

    def _reload_cats(self) -> None:
        self.cat_all.clear()
        for cat in self.cfg.categories_for(self.type_all.currentData()):
            self.cat_all.addItem(cat, cat)

    def _remember(self, *_) -> None:
        """Keep the last selection that covered more than one row.

        Qt collapses a multi-row selection the moment a cell is clicked, which
        is exactly the click that starts an edit. Without a memory of what was
        selected a beat earlier, every spread would arrive with a single row.
        Only multi-row selections are remembered: a one-row selection is not a
        batch and must not resurrect an older one.
        """
        rows = [i.row() for i in self.table.selectionModel().selectedRows()]
        if len(rows) > 1:
            self._remembered = rows

    def rows_for(self, row) -> list:
        """Which rows an edit on `row` applies to."""
        live = [i.row() for i in self.table.selectionModel().selectedRows()]
        if row in live and len(live) > 1:
            return live
        remembered = getattr(self, "_remembered", [])
        return remembered if row in remembered else [row]

    def reselect(self, rows) -> None:
        """Put the selection back after a spread, so it is visible that the edit
        applied to all of them and the next edit hits the same set."""
        if len(rows) < 2:
            return
        sm = self.table.selectionModel()
        sm.blockSignals(True)
        sm.clearSelection()
        for at in rows:
            sm.select(self.model.index(at, 0),
                      QItemSelectionModel.Select | QItemSelectionModel.Rows)
        sm.blockSignals(False)

    def set_on_selection(self, index, value) -> None:
        """Write one combo's value to every selected row.

        Type goes through the same category re-check `set all` does, because a
        category chosen under the old type may not exist under the new one and
        the closed vocabulary would refuse it at commit - hours later, in a
        batch of twenty, with nothing saying which row.
        """
        col = index.column()
        rows = self.rows_for(index.row())
        for at in rows:
            row = self.model.rows[at]
            if col == COL_TYPE:
                row.type_id = value
                if row.category not in self.cfg.categories_for(value):
                    row.category = None
            elif col == COL_CAT:
                if value in self.cfg.categories_for(row.type_id):
                    row.category = value
        self.model.top_left_changed(index)
        self.reselect(rows)

    def _apply_type(self) -> None:
        tid = self.type_all.currentData()
        for c in self.model.rows:
            c.type_id = tid
            # The category vocabulary is per type, so one chosen under the old
            # type may not exist under the new. Cleared rather than carried into
            # a value the closed list would reject at commit.
            if c.category not in self.cfg.categories_for(tid):
                c.category = None
        self.model.set_rows(self.model.rows)

    def _apply_cat(self) -> None:
        cat = self.cat_all.currentData()
        for c in self.model.rows:
            if cat in self.cfg.categories_for(c.type_id):
                c.category = cat
        self.model.set_rows(self.model.rows)

    # ---------------------------------------------------------------- commit

    def _commit(self) -> None:
        jobs, bad, taken = [], [], set()
        for at, c in enumerate(self.model.rows):
            if not c.on or c.error or not c.plan:
                continue
            if not c.category:
                bad.append(f"{c.folder.name}: no category")
                continue

            plan = c.plan
            plan.type_id = c.type_id
            plan.category = c.category

            # Normalised here, and made unique against what is ALREADY on disk
            # AND what this batch is about to write. Two folders normalising to
            # one name is ordinary in a vendor dump, and unique_name alone would
            # not see the collision because the first asset is not written yet.
            base = normalise(c.name, self.cfg) or "unnamed"
            parent = self.cfg.library / c.type_id / c.category
            parent.mkdir(parents=True, exist_ok=True)
            name = unique_name(base, parent)
            while name in taken:
                name = unique_name(name + "_02", parent)
            taken.add(name)
            plan.name = name
            jobs.append((at, plan))

        if bad:
            QMessageBox.warning(self, "Not ready", "\n".join(bad[:12]))
            return
        if not jobs:
            return

        self._pending = len(jobs)
        self._progress = QProgressDialog(f"Importing {len(jobs)} asset(s)...", None,
                                         0, len(jobs), self)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setValue(0)

        signals = _CommitSignals()
        signals.done.connect(self._one_done)
        signals.failed.connect(self._one_failed)
        self._commit_signals = signals
        tags = [t for t in self.tags.text().split() if t]
        writepool.start(BatchCommitWorker(jobs, self.cfg, tags,
                                          self.move_box.isChecked(), signals))

    def _one_done(self, at, asset_dir) -> None:
        row = self.model.rows[at]
        row.status, row.on = "imported", False
        self.model.replace(at, row)
        self.added += 1
        self._step()

    def _one_failed(self, at, message) -> None:
        self.model.rows[at].error = message
        self.model.replace(at, self.model.rows[at])
        self._step()

    def _step(self) -> None:
        self._pending -= 1
        self._progress.setValue(self._progress.maximum() - self._pending)
        if self._pending <= 0:
            self._progress.close()
            failed = [c for c in self.model.rows if c.error]
            self.status.setText(
                f"imported {self.added}"
                + (f"   -   {len(failed)} failed" if failed else ""))
            self.go.setEnabled(False)
