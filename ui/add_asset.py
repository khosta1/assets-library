"""Add one asset by hand.

You declare what the asset IS - type, place in the hierarchy, name - and drop
its files in. The library does not guess any of that. What it still does is the
part worth automating: reading the dropped files and working out which is the
basecolor, which is the normal, which format of a slot wins, and what each file
must be renamed to. Every one of those decisions is shown as a row you can
override.

The window is identical for every type. `types.json` says which extensions are
primary, `texture_slots.json` says how images map to slots, and the destination
follows from those - so supporting a new type stays a config edit.

Nothing is written until Add is pressed; commit.py remains the only writer.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QObject, QRunnable,
                            Qt, Signal)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QProgressDialog, QPushButton,
                               QStyledItemDelegate, QTableView, QVBoxLayout)

from assetlib import index as idx
from assetlib.analyse import (BONUS, PREVIEW_TARGET, SKIP, _walk, analyse, conflicts,
                              current_target, derive_name, rebind, set_key,
                              set_lod, set_variant, targets_for)
from assetlib.commit import commit
from assetlib.model import Asset, to_token
from assetlib.naming import normalise
from assetlib.thumbnail import thumb_bytes, why_not

from . import theme
from . import writepool
from .gridmodel import _human

ACTION_ROLE = Qt.UserRole + 30
COL_FILE, COL_DEST, COL_TARGET, COL_LOD, COL_VAR, COL_RES, COL_SIZE = range(7)
HEADERS = ["File", "Goes to", "Binding", "LOD", "Var", "Res", "Size"]
NO_LOD = "—"
MAX_LOD = 9


# ------------------------------------------------------------------ drop zone


class DropZone(QFrame):
    """A rectangle that accepts files and folders.

    Dropping a folder takes its WHOLE tree, because this window is one asset and
    a dropped folder means "all of this is it". A folder holding several assets
    side by side is Import folder…, which makes one row per subfolder.

    It took one level until 2026-09-13, which was invisible while every asset
    was a flat texture folder and wrong the moment a tool arrived - see
    dropEvent.
    """

    dropped = Signal(list)

    def __init__(self, title: str, hint: str, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumHeight(64)
        self._title = title
        self.label = QLabel(f"{title}\n{hint}")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        self._normal = self.styleSheet()

    def set_count(self, n: int, hint: str) -> None:
        suffix = f"{n} file(s)" if n else hint
        self.label.setText(f"{self._title}\n{suffix}")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("QFrame { border: 2px solid palette(highlight); }")

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._normal)

    def dropEvent(self, event):
        self.setStyleSheet(self._normal)
        paths = []
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                # RECURSIVE, and through analyse's own walker so there is one
                # definition of "the files in this folder" rather than two that
                # can disagree - it also skips .git and __MACOSX for free.
                #
                # This was p.iterdir(), one level, which was invisible while
                # every asset was a flat texture folder. Dropping the
                # Manager_tool suite collected exactly ONE file: install.json is
                # the only thing at its root and all ten tools are in
                # subfolders. The import succeeded, the asset held its manifest
                # and no code, and the failure surfaced three steps later as
                # "src/Main_ui/manager_ui.py is not in the package".
                #
                # Dropping a folder on the Add window means "all of this is one
                # asset" - that is what this window is for. A folder holding
                # several assets side by side is Import folder..., which makes
                # one row per subfolder.
                paths.extend(sorted(_walk(p)))
            elif p.is_file():
                paths.append(p)
        if paths:
            self.dropped.emit(paths)
            event.acceptProposedAction()


class PreviewZone(DropZone):
    """The icon. Drop an image on it, or click it to browse.

    It shows the image it holds rather than a file count - the whole point of a
    preview is seeing it before you commit the asset.
    """

    clicked = Signal()

    EMPTY = "drop an image\nor click to choose"
    SIDE = 128

    def __init__(self, parent=None):
        super().__init__("Preview", self.EMPTY, parent)
        self.setFixedSize(self.SIDE + 16, self.SIDE + 16)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Becomes preview/thumb.jpg")

    def show_image(self, path) -> None:
        """Render through the same decoder that writes preview/thumb.jpg.

        Qt cannot read EXR or HDR at all, so asking QPixmap directly would show
        nothing for an HDRI. Going through thumbnail.py means the box shows
        exactly the icon that will be committed - tone mapping included.
        """
        if path is None:
            self.label.setPixmap(QPixmap())
            self.label.setText(f"{self._title}\n{self.EMPTY}")
            return

        reason = why_not(path)
        data = None if reason else thumb_bytes(path, self.SIDE)
        if data is None:
            self.label.setPixmap(QPixmap())
            self.label.setText(f"{path.name}\n({reason or 'could not be decoded'})")
            return

        pix = QPixmap()
        pix.loadFromData(data, "JPEG")
        self.label.setPixmap(pix.scaled(self.SIDE, self.SIDE,
                                        Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------- file table


class Row:
    """What one line of the table stands for: a file, or a whole UDIM set.

    A human-scan set is thirty files that are really three maps. Listing them
    one per line buries the decisions worth checking, and rebinding a map would
    mean changing the same dropdown ten times.
    """

    __slots__ = ("actions",)

    def __init__(self, actions):
        self.actions = actions

    @property
    def lead(self):
        return self.actions[0]

    @property
    def tiles(self) -> list:
        return sorted(a.udim for a in self.actions if a.udim)

    @property
    def size(self) -> int:
        return sum(a.size for a in self.actions)

    def label(self) -> str:
        tiles = self.tiles
        if len(self.actions) == 1 or not tiles:
            return self.lead.src.name
        return f"{self.lead.src.name}   +{len(tiles) - 1} tiles"

    def destination(self) -> str:
        dest = self.lead.dest
        if dest and self.lead.udim:
            return to_token(dest, self.lead.udim)
        return dest


def group_rows(actions) -> list:
    """One row per file, except a UDIM set which becomes a single row."""
    rows, seen = [], {}
    for action in actions:
        key = set_key(action)
        if key is None:
            rows.append(Row([action]))
            continue
        row = seen.get(key)
        if row is None:
            row = seen[key] = Row([])
            rows.append(row)
        row.actions.append(action)
    return rows


class FileTableModel(QAbstractTableModel):
    """One row per dropped file, showing where it lands and why."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list = []
        self.preview_src = None

    def set_actions(self, actions: list, preview_src=None) -> None:
        self.beginResetModel()
        self.rows = group_rows(actions)
        self.preview_src = preview_src
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        a = row.lead
        col = index.column()

        if role in (Qt.DisplayRole, Qt.EditRole):
            if col == COL_FILE:
                return row.label()
            if col == COL_DEST:
                dest = row.destination()
                if not dest:
                    return "—"
                # A file can be both a texture and the icon; say so, otherwise
                # the row looks like the icon choice was silently ignored.
                if a.src == self.preview_src and a.action != "preview":
                    return f"{dest}    + icon"
                return dest
            if col == COL_TARGET:
                return current_target(a)
            if col == COL_LOD:
                return str(a.lod) if a.lod else NO_LOD
            if col == COL_VAR:
                # Pre-filled from the filename, blank when nothing matched.
                # Editable, because a token that looks like a variant and is
                # part of the real name is a mistake only a person catches.
                return a.variant or ""
            if col == COL_RES:
                # Blank, not a dash, when the slot holds one size: a token is
                # only assigned when there is something to tell apart, and an
                # em-dash in every row would read as "no resolution known".
                return a.res or ""
            if col == COL_SIZE:
                return _human(row.size)
        if role == Qt.ForegroundRole and a.action == "reject":
            return theme.dim_colour()
        if role == Qt.ToolTipRole:
            tiles = row.tiles
            head = (f"{len(tiles)} tiles: {tiles[0]}-{tiles[-1]}\n" if len(tiles) > 1 else "")
            return head + (f"{a.src}\n{a.reason}" if a.reason else str(a.src))
        if role == ACTION_ROLE:
            return row
        return None

    def flags(self, index):
        base = super().flags(index)
        if index.column() in (COL_TARGET, COL_LOD, COL_VAR):
            return base | Qt.ItemIsEditable
        return base


class TargetDelegate(QStyledItemDelegate):
    """The override dropdown: send this file somewhere else."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        for value, label in self.dialog.targets():
            combo.addItem(label, value)
        return combo

    def setEditorData(self, editor, index):
        current = index.data(Qt.EditRole)
        pos = editor.findData(current)
        editor.setCurrentIndex(pos if pos >= 0 else 0)

    def setModelData(self, editor, model, index):
        self.dialog.rebind_one(model.rows[index.row()], editor.currentData())


class LodDelegate(QStyledItemDelegate):
    """Which level of detail a file belongs to.

    A second dimension alongside the slot: four LODs of one asset each carry
    their own maps, so 'diffuse' alone does not identify a destination.
    """

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItem(NO_LOD, None)
        for n in range(1, MAX_LOD + 1):
            combo.addItem(f"LOD{n}", n)
        return combo

    def setEditorData(self, editor, index):
        current = index.data(Qt.EditRole)
        pos = editor.findText(current if current == NO_LOD else f"LOD{current}")
        editor.setCurrentIndex(max(pos, 0))

    def setModelData(self, editor, model, index):
        self.dialog.set_lod_one(model.rows[index.row()], editor.currentData())


class VariantDelegate(QStyledItemDelegate):
    """Which VERSION of the asset a file belongs to.

    A third dimension beside slot and LOD. Megascans ships a Big and a Small
    mesh of one plant across three levels each, sharing one texture set; the two
    are one asset and both have to be kept.

    Editable rather than a fixed list: the vendor words are unbounded (Big,
    Small, Var01, alt2) and the pre-fill is a guess. Values already present in
    the plan are offered so a typed one cannot drift from a detected one.
    """

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.addItem("")
        for value in self.dialog.variants_seen():
            combo.addItem(value)
        return combo

    def setEditorData(self, editor, index):
        editor.setEditText(index.data(Qt.EditRole) or "")

    def setModelData(self, editor, model, index):
        self.dialog.set_variant_one(model.rows[index.row()],
                                    editor.currentText().strip())


# -------------------------------------------------------------- commit worker


class _CommitSignals(QObject):
    done = Signal(str)
    failed = Signal(str)


class CommitWorker(QRunnable):
    """Copying can be hundreds of megabytes; it never runs on the GUI thread.

    The worker opens its own sqlite connection - connections are not shareable
    across threads - and indexes the asset it just wrote.
    """

    def __init__(self, plan, cfg, tags, move=False):
        super().__init__()
        self.plan, self.cfg, self.tags = plan, cfg, tags
        self.move = move
        self.signals = _CommitSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            asset_dir = commit(self.plan, self.cfg, tags=self.tags, move=self.move)
        except Exception as exc:                       # noqa: BLE001 - surfaced to the user
            self.signals.failed.emit(str(exc))
            return
        try:
            conn = idx.connect(self.cfg)
            idx.upsert(conn, Asset.read(asset_dir), asset_dir, self.cfg.library)
            conn.close()
        except Exception as exc:                       # noqa: BLE001
            self.signals.failed.emit(f"written to {asset_dir} but not indexed: {exc}")
            return
        self.signals.done.emit(str(asset_dir))


# --------------------------------------------------------------------- dialog


class AddAssetDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.plan = None
        self.added = 0
        self._files: list = []
        self._bonus: list = []
        self._overrides: dict = {}      # src path -> target, survives a replan
        self._lods: dict = {}           # src path -> level, survives a replan
        self._variants: dict = {}       # src path -> variant, survives a replan
        self._preview: Path | None = None
        self._worker = None
        self._name_touched = False      # once you type a name, we stop guessing
        self._progress = None

        self.setWindowTitle("Add asset")
        self.resize(940, 720)

        # --- what the asset is ------------------------------------------
        self.type_box = QComboBox()
        for t in cfg.types:
            self.type_box.addItem(t["label"], t["id"])
        self.type_box.currentIndexChanged.connect(self._type_changed)

        self.cat_box = QComboBox()
        self.cat_box.currentIndexChanged.connect(self._replan)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("asset name (lower_snake)")
        self.name_edit.editingFinished.connect(self._name_edited)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("tags, space separated   e.g.  src:renderman res:8k")

        head = QHBoxLayout()
        head.addWidget(QLabel("Type"))
        head.addWidget(self.type_box, 1)
        head.addWidget(QLabel("Location"))
        head.addWidget(self.cat_box, 1)
        head.addWidget(QLabel("Name"))
        head.addWidget(self.name_edit, 1)

        # --- the icon ----------------------------------------------------
        self.icon_zone = PreviewZone()
        self.icon_zone.dropped.connect(self._preview_dropped)
        self.icon_zone.clicked.connect(self._choose_preview)
        self.icon_clear = QPushButton("Clear preview")
        self.icon_clear.clicked.connect(lambda: self._set_preview(None))

        icon_col = QVBoxLayout()
        icon_col.addWidget(self.icon_zone)
        icon_col.addWidget(self.icon_clear)
        icon_col.addStretch(1)

        # --- the drop zones ----------------------------------------------
        self.drop = DropZone("Drop the asset's files here",
                             "the library sorts them - override any row below")
        self.drop.dropped.connect(self._add_files)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._browse_files)

        self.bonus_drop = DropZone("Bonus files",
                                   "kept as-is under extra/, never examined")
        self.bonus_drop.dropped.connect(self._add_bonus)

        drops = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(self.drop, 1)
        left.addWidget(self.browse_btn)
        drops.addLayout(left, 2)
        drops.addWidget(self.bonus_drop, 1)
        drops.addLayout(icon_col)

        # --- the result table ---------------------------------------------
        self.model = FileTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setItemDelegateForColumn(COL_TARGET, TargetDelegate(self))
        self.table.setItemDelegateForColumn(COL_LOD, LodDelegate(self))
        self.table.setItemDelegateForColumn(COL_VAR, VariantDelegate(self))
        self.table.setColumnWidth(COL_FILE, 280)
        self.table.setColumnWidth(COL_DEST, 300)
        self.table.setColumnWidth(COL_TARGET, 150)
        self.table.setColumnWidth(COL_LOD, 60)
        self.table.setColumnWidth(COL_VAR, 80)
        self.table.setColumnWidth(COL_RES, 60)

        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.clear_btn = QPushButton("Clear all files")
        self.clear_btn.clicked.connect(self._clear_files)

        row_tools = QHBoxLayout()
        row_tools.addWidget(self.remove_btn)
        row_tools.addWidget(self.clear_btn)
        row_tools.addStretch(1)

        # --- footer --------------------------------------------------------
        self.status = QLabel("drop some files to begin")
        self.status.setWordWrap(True)
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(lambda: self._commit(keep_going=False))
        self.again_btn = QPushButton("Add and keep going")
        self.again_btn.setToolTip("Add it, then clear the files but keep type, "
                                  "location and tags for the next one")
        self.again_btn.clicked.connect(lambda: self._commit(keep_going=True))
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)

        # Off by default, and per import. Moving breaks the promise that a
        # source sits untouched until you clear it - worth it for a 12 GB scan
        # on one volume, where it becomes a rename, but never silently.
        self.move_box = QCheckBox("Move files (do not keep a copy)")
        self.move_box.setToolTip(
            "Same drive: the files are renamed into the library - instant, and "
            "no second copy has to fit.\n"
            "Different drive: copied, verified, then the originals are removed.")

        foot = QHBoxLayout()
        foot.addWidget(self.add_btn)
        foot.addWidget(self.again_btn)
        foot.addWidget(self.move_box)
        foot.addStretch(1)
        foot.addWidget(self.close_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self.tags_edit)
        layout.addLayout(drops)
        layout.addWidget(self.table, 1)
        layout.addLayout(row_tools)
        layout.addWidget(self.status)
        layout.addLayout(foot)

        self._type_changed()

    # ------------------------------------------------------------- the model

    def type_id(self) -> str:
        return self.type_box.currentData()

    def category(self):
        return self.cat_box.currentData()

    def targets(self) -> list:
        return targets_for(self.plan, self.cfg) if self.plan else []

    def _type_changed(self, *_) -> None:
        """A new type means a new closed category vocabulary."""
        self.cat_box.blockSignals(True)
        self.cat_box.clear()
        for cat in self.cfg.categories_for(self.type_id()):
            self.cat_box.addItem(cat, cat)
        self.cat_box.blockSignals(False)
        self._replan()

    def _name_edited(self) -> None:
        """A typed name is final - it stops being re-derived from the files.

        Clearing the field hands control back, so the name follows the files
        again on the next drop.
        """
        cleaned = normalise(self.name_edit.text(), self.cfg) if self.name_edit.text() else ""
        if cleaned != self.name_edit.text():
            self.name_edit.setText(cleaned)
        self._name_touched = bool(cleaned)
        self._replan()

    def _sync_name(self, files: list) -> str:
        """Keep the name in step with the files until the user overrides it."""
        if self._name_touched:
            return self.name_edit.text()
        derived = derive_name(files, self.cfg, self.type_id())
        if derived != self.name_edit.text():
            self.name_edit.setText(derived)
        return derived

    # ------------------------------------------------------------------ files

    def _add_files(self, paths: list) -> None:
        known = set(self._files) | set(self._bonus)
        self._files.extend(p for p in paths if p not in known)
        self._replan()

    def _add_bonus(self, paths: list) -> None:
        known = set(self._files) | set(self._bonus)
        for p in paths:
            if p not in known:
                self._bonus.append(p)
                self._overrides[p] = BONUS
        self._replan()

    def _browse_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose the asset's files")
        if paths:
            self._add_files([Path(p) for p in paths])

    def _remove_selected(self) -> None:
        for index in self.table.selectionModel().selectedRows():
            # A row can stand for a whole UDIM set; removing it removes the set.
            for action in index.data(ACTION_ROLE).actions:
                src = action.src
                self._files = [f for f in self._files if f != src]
                self._bonus = [f for f in self._bonus if f != src]
                self._overrides.pop(src, None)
                self._lods.pop(src, None)
                self._variants.pop(src, None)
        self._replan()

    def _clear_files(self) -> None:
        self._files, self._bonus = [], []
        self._overrides, self._lods, self._variants = {}, {}, {}
        self._replan()

    # ---------------------------------------------------------------- preview

    def _choose_preview(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose the preview image", "",
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.exr *.bmp *.webp)")
        if path:
            self._set_preview(Path(path))

    def _preview_dropped(self, paths: list) -> None:
        """Anything we can decode may be the preview - png, exr, hdr, psd, dds.

        The test is "can thumbnail.py read it", not an extension whitelist, so
        the zone accepts exactly what it can actually turn into an icon.
        Dropping a folder picks the first usable image inside it.
        """
        usable = [p for p in paths if not why_not(p)]
        if not usable:
            reason = why_not(paths[0]) if paths else "nothing dropped"
            self.status.setText(f"cannot use that as a preview: {reason}")
            return
        self._set_preview(usable[0])

    def _set_preview(self, path) -> None:
        previous = self._preview
        self._preview = path
        if previous is not None and previous != path:
            self._overrides.pop(previous, None)
        self.icon_zone.show_image(path)
        self._replan()

    # ----------------------------------------------------------------- replan

    def _all_files(self) -> list:
        files = list(self._files) + list(self._bonus)
        if self._preview and self._preview not in files:
            files.append(self._preview)
        return files

    def _plan_source(self, files: list) -> Path:
        """The base that in-package relative paths are resolved against.

        Adding an asset there is no package yet, so any folder will do. The
        editor overrides this with the package itself, which is what lets a
        file already sitting in extra/ round-trip to extra/.
        """
        return files[0].parent

    def _replan(self, *_) -> None:
        """Rebuild the plan, then re-apply the user's overrides on top.

        Analysis is cheap and total: it is easier to reason about one plan built
        from scratch plus a list of explicit overrides than a plan patched in
        place across a type change.
        """
        files = self._all_files()
        if not files:
            self.plan = None
            self.model.set_actions([])
            if not self._name_touched:
                self.name_edit.clear()
            self._refresh_status()
            return

        # The name follows the files - a 3D object first, then a texture, then
        # whatever is left - unless you have typed one of your own.
        name = self._sync_name(self._files or files) or normalise(files[0].stem, self.cfg)
        try:
            self.plan = analyse(
                self._plan_source(files), self.cfg,
                type_hint=self.type_id(),
                category_hint=self.category(),
                files=files,
                name_hint=name,
            )
        except Exception as exc:                        # noqa: BLE001
            self.plan = None
            self.model.set_actions([])
            self.status.setText(f"cannot plan this: {exc}")
            self._refresh_buttons()
            return

        for action in self.plan.actions:
            # LOD and variant first: both feed into the destination the binding
            # computes, so patching them after the rebind would leave the row
            # showing one thing and the file going somewhere else.
            if action.src in self._lods:
                action.lod = self._lods[action.src] or None
            if action.src in self._variants:
                action.variant = self._variants[action.src] or None
            target = self._overrides.get(action.src)
            if target is None and (action.src in self._lods
                                   or action.src in self._variants):
                target = current_target(action)
            if target:
                try:
                    rebind(self.plan, action, target, self.cfg)
                except ValueError:
                    self._overrides.pop(action.src, None)

        if self._preview is not None:
            # The icon is RENDERED from this file, not moved to it. Choosing the
            # basecolor as the icon must leave the basecolor in tex/ - so only a
            # file with no other job gets bound to preview/thumb.jpg.
            self.plan.preview_src = self._preview
            chosen = next((a for a in self.plan.actions
                           if a.src == self._preview), None)
            if (chosen is not None
                    and chosen.action in ("bonus", "reject")
                    and self._preview not in self._overrides):
                rebind(self.plan, chosen, PREVIEW_TARGET, self.cfg)

            # You picked the icon, so a preview the planner found on its own
            # steps aside rather than fighting it for preview/thumb.jpg.
            for action in self.plan.actions:
                if action.action == "preview" and action.src != self._preview:
                    rebind(self.plan, action, SKIP, self.cfg)

        self.model.set_actions(self.plan.actions, self._preview)
        self._refresh_status()

    def rebind_one(self, row, target: str) -> None:
        """Called by the delegate when a row's dropdown changes.

        A row may stand for a whole UDIM set, and every tile of it moves
        together - a set with half its tiles bound one way is not a state worth
        being able to reach.

        Only the touched row is refreshed - resetting the whole model here
        would pull the table out from under the editor Qt is still closing.
        """
        if self.plan is None:
            return
        for action in row.actions:
            self._overrides[action.src] = target
            if target == BONUS:
                if action.src in self._files:
                    self._files.remove(action.src)
                    self._bonus.append(action.src)
            elif action.src in self._bonus:
                self._bonus.remove(action.src)
                self._files.append(action.src)
            rebind(self.plan, action, target, self.cfg)
        self._row_changed(row)

    def variants_seen(self) -> list:
        """Variant names already in the plan, for the dropdown."""
        if self.plan is None:
            return []
        return sorted({a.variant for a in self.plan.actions if a.variant})

    def set_variant_one(self, row, variant) -> None:
        """Called by the delegate when a row's variant changes."""
        if self.plan is None:
            return
        for action in row.actions:
            self._variants[action.src] = variant or None
            set_variant(self.plan, action, variant, self.cfg)
        self._row_changed(row)

    def set_lod_one(self, row, lod) -> None:
        """Called by the delegate when a row's LOD changes."""
        if self.plan is None:
            return
        for action in row.actions:
            self._lods[action.src] = lod
            set_lod(self.plan, action, lod, self.cfg)
        self._row_changed(row)

    def _row_changed(self, row) -> None:
        try:
            at = self.model.rows.index(row)
        except ValueError:
            return
        left = self.model.index(at, 0)
        right = self.model.index(at, len(HEADERS) - 1)
        self.model.dataChanged.emit(left, right)
        self._refresh_status()

    # ----------------------------------------------------------------- status

    def _refresh_status(self) -> None:
        self.drop.set_count(len(self._files), "the library sorts them")
        self.bonus_drop.set_count(len(self._bonus), "kept as-is under extra/")

        if self.plan is None:
            self.status.setText("drop some files to begin")
            self._refresh_buttons()
            return

        clashes = conflicts(self.plan)
        dest = f"library/{self.type_id()}/{self.category()}/{self.plan.name}/"
        bits = [dest,
                f"{len(self.plan.kept)} kept, {len(self.plan.rejected)} skipped",
                f"{_human(self.plan.size_in)} → {_human(self.plan.size_out)}"]
        text = "   ·   ".join(bits)
        for target, names in clashes:
            text += f"\nCLASH  {target}  <-  {', '.join(names)}"
        for warning in self.plan.warnings:
            text += f"\n! {warning}"
        self.status.setText(text)
        self._refresh_buttons(bool(clashes))

    def _refresh_buttons(self, clash: bool = False) -> None:
        ok = bool(self.plan and self.plan.ready and not clash)
        self.add_btn.setEnabled(ok)
        self.again_btn.setEnabled(ok)

    # ----------------------------------------------------------------- commit

    def _commit(self, keep_going: bool) -> None:
        if self.plan is None or not self.plan.ready:
            return
        tags = sorted({t for t in self.tags_edit.text().split() if t})

        self._progress = QProgressDialog("Copying files…", "", 0, 0, self)
        self._progress.setWindowTitle("Adding asset")
        self._progress.setCancelButton(None)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.show()

        # Never the global pool: thumbnail decoding lives there and would keep
        # a write job queued behind it, with the progress dialog stuck waiting.
        self._worker = CommitWorker(self.plan, self.cfg, tags,
                                    move=self.move_box.isChecked())
        self._worker.signals.done.connect(lambda p: self._commit_done(p, keep_going))
        self._worker.signals.failed.connect(self._commit_failed)
        writepool.start(self._worker)

    def _commit_done(self, asset_dir: str, keep_going: bool) -> None:
        if self._progress:
            self._progress.close()
            self._progress = None
        self.added += 1
        if not keep_going:
            self.accept()
            return
        # Keep type, location and tags; clear everything that is per-asset.
        self._name_touched = False
        self._clear_files()
        self._set_preview(None)
        self.name_edit.clear()
        self.status.setText(f"added {Path(asset_dir).name} — ready for the next one")

    def _commit_failed(self, message: str) -> None:
        if self._progress:
            self._progress.close()
            self._progress = None
        QMessageBox.critical(self, "Could not add the asset", message)
