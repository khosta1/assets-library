"""Look inside an asset package.

Every file the package holds, each shown as what `asset.json` says it IS -
`diffuse`, `LOD2 normal`, `bonus`, `derived` - rather than as a filename. That
turns this window into a check on whether an import bound things the way you
meant, which is the thing you actually want to see after adding an asset.

Images preview, including the EXR and HDR that Qt cannot read on its own, since
everything goes through `assetlib.thumbnail`. Text files show their text.
Meshes and other binaries show what is known about them and open in whatever
Windows uses for them on a double-click.

Nothing here writes into the package. The only thing it writes at all is the
bounded preview cache in .assetlib/thumbs/.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, QRunnable,
                            QSize, Qt, QThreadPool, Signal)
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel,
                               QListView, QPlainTextEdit, QPushButton,
                               QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from assetlib.edit import package_files
from assetlib.model import ASSET_FILE, Asset, role_of, roles
from assetlib.thumbnail import render, why_not

from . import thumbcache
from .gridmodel import _human

ENTRY_ROLE = Qt.UserRole + 40

# Files worth showing as text. Anything else binary is described, not opened.
TEXT_EXTS = {".txt", ".json", ".mtl", ".mtlx", ".usda", ".xml", ".csv", ".md",
             ".log", ".ini", ".cfg", ".yaml", ".yml", ".abc_txt", ".rib"}
TEXT_LIMIT = 64 * 1024
DETAIL_PX = 1024
TILE_PX = 148
# 8K decodes are memory-hungry; a few at a time fills the grid fast
# enough without three of them fighting over a gigabyte.
MAX_DECODERS = 3


class Entry:
    __slots__ = ("path", "rel", "role", "size", "kind")

    def __init__(self, path: Path, rel: str, role: str, size: int, kind: str):
        self.path, self.rel, self.role = path, rel, role
        self.size, self.kind = size, kind


def _classify(path: Path) -> str:
    if not why_not(path):
        return "image"
    if path.suffix.lower() in TEXT_EXTS:
        return "text"
    return "binary"


# ----------------------------------------------------------------- thumbnails


class _Gate:
    """Shared 'stop what you are doing' flag.

    A running decode cannot be interrupted, but it can be told that nobody
    wants the answer any more - so it returns instead of finishing an 8K TIFF
    for a window that has already closed.
    """

    __slots__ = ("cancelled",)

    def __init__(self):
        self.cancelled = False


class _TileSignals(QObject):
    done = Signal(str, bytes)


class _TileJob(QRunnable):
    def __init__(self, cfg, uuid: str, entry: Entry, signals: _TileSignals, gate: _Gate):
        super().__init__()
        self.cfg, self.uuid, self.entry = cfg, uuid, entry
        self.signals, self.gate = signals, gate
        self.setAutoDelete(True)

    def run(self):
        if self.gate.cancelled:
            return
        data = thumbcache.get(self.cfg, self.uuid, self.entry.path, self.entry.rel)
        if data and not self.gate.cancelled:
            self.signals.done.emit(self.entry.rel, data)


class _DetailSignals(QObject):
    done = Signal(str, bytes)


class _DetailJob(QRunnable):
    """The big preview, rendered once on selection and never cached - one image
    at a time is cheap, and caching a full-window render is not."""

    def __init__(self, entry: Entry, signals: _DetailSignals, gate: _Gate):
        super().__init__()
        self.entry, self.signals, self.gate = entry, signals, gate
        self.setAutoDelete(True)

    def run(self):
        if self.gate.cancelled:
            return
        image = render(self.entry.path, DETAIL_PX)
        if image is None or self.gate.cancelled:
            return
        import io

        buffer = io.BytesIO()
        try:
            image.save(buffer, "JPEG", quality=90)
        except Exception:                              # noqa: BLE001
            return
        if not self.gate.cancelled:
            self.signals.done.emit(self.entry.rel, buffer.getvalue())


class PackageModel(QAbstractListModel):
    """One tile per file. Decoding happens on the pool, never in paint."""

    def __init__(self, cfg, uuid: str, parent=None):
        super().__init__(parent)
        self.cfg, self.uuid = cfg, uuid
        self.entries: list = []
        self._icons: dict = {}
        self._pending: set = set()
        self.gate = _Gate()
        # Its OWN pool, not the global one. Closing the window can then throw
        # away everything still queued, so the next window starts decoding
        # immediately instead of waiting behind a package nobody is looking at.
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(MAX_DECODERS)
        self._signals = _TileSignals()
        self._signals.done.connect(self._tile_ready)
        self._placeholder = self._badge("")

    def set_entries(self, entries: list) -> None:
        self.beginResetModel()
        self.entries = entries
        self._icons.clear()
        self._pending.clear()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        entry = self.entries[index.row()]
        if role == Qt.DisplayRole:
            label = Path(entry.rel).name
            return f"{label}\n{entry.role}" if entry.role else label
        if role == Qt.DecorationRole:
            return self._icon_for(entry)
        if role == Qt.ToolTipRole:
            return f"{entry.rel}\n{entry.role or 'not referenced by asset.json'}\n{_human(entry.size)}"
        if role == ENTRY_ROLE:
            return entry
        return None

    # ------------------------------------------------------------------ icons

    @staticmethod
    def _badge(text: str) -> QIcon:
        pix = QPixmap(TILE_PX, TILE_PX)
        pix.fill(QColor(58, 58, 62))
        return QIcon(pix)

    def _icon_for(self, entry: Entry) -> QIcon:
        icon = self._icons.get(entry.rel)
        if icon is not None:
            return icon
        if entry.kind == "image" and entry.rel not in self._pending:
            self._pending.add(entry.rel)
            self._pool.start(
                _TileJob(self.cfg, self.uuid, entry, self._signals, self.gate))
        return self._placeholder

    def start(self, job) -> None:
        """Queue a decode on this window's own pool."""
        self._pool.start(job)

    def shutdown(self) -> None:
        """Abandon every decode this window asked for."""
        self.gate.cancelled = True
        self._pool.clear()          # drops everything not yet started
        self._pending.clear()

    def _tile_ready(self, rel: str, data: bytes) -> None:
        pix = QPixmap()
        if not pix.loadFromData(data, "JPEG"):
            return
        self._icons[rel] = QIcon(pix)
        self._pending.discard(rel)
        for i, entry in enumerate(self.entries):
            if entry.rel == rel:
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [Qt.DecorationRole])
                break


# --------------------------------------------------------------------- dialog


class AssetViewDialog(QDialog):
    def __init__(self, cfg, asset_dir, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.asset_dir = Path(asset_dir).resolve()
        self.asset = Asset.read(self.asset_dir)
        self.edited = False
        self._detail_rel = None

        self.setWindowTitle(f"{self.asset.name}")
        self.resize(1080, 800)

        self.header = QLabel()
        self.header.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.header.setWordWrap(True)

        self.model = PackageModel(cfg, self.asset.uuid, self)
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setViewMode(QListView.IconMode)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setUniformItemSizes(True)
        self.view.setMovement(QListView.Static)
        self.view.setWordWrap(True)
        self.view.setSpacing(8)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setIconSize(QSize(TILE_PX, TILE_PX))
        self.view.setGridSize(QSize(TILE_PX + 26, TILE_PX + 56))
        self.view.selectionModel().selectionChanged.connect(self._selected)
        self.view.doubleClicked.connect(self._open_file)

        # --- detail pane ---------------------------------------------------
        self.image = QLabel(alignment=Qt.AlignCenter)
        self.image.setMinimumHeight(200)
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.blank = QLabel("select a file", alignment=Qt.AlignCenter)

        self.pane = QStackedWidget()
        self.pane.addWidget(self.blank)
        self.pane.addWidget(self.image)
        self.pane.addWidget(self.text)

        self.caption = QLabel()
        self.caption.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.caption.setWordWrap(True)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.addWidget(self.pane, 1)
        lower_layout.addWidget(self.caption)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.view)
        split.addWidget(lower)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([440, 320])

        self.edit_btn = QPushButton("Edit…")
        self.edit_btn.clicked.connect(self._edit)
        self.open_btn = QPushButton("Open folder")
        self.open_btn.clicked.connect(self._open_folder)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)

        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(self.edit_btn)
        foot.addWidget(self.open_btn)
        foot.addWidget(self.close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(split, 1)
        layout.addLayout(foot)

        self._detail_signals = _DetailSignals()
        self._detail_signals.done.connect(self._detail_ready)
        self.reload()

    # ------------------------------------------------------------------ load

    def reload(self) -> None:
        self.asset = Asset.read(self.asset_dir)
        table = roles(self.asset)

        entries = []
        meta = self.asset_dir / ASSET_FILE
        if meta.is_file():
            entries.append(Entry(meta, ASSET_FILE, "metadata",
                                 meta.stat().st_size, "text"))
        # payload_only=False: an edit does not own derived/ or preview/, but
        # this window shows what is on disk and that includes both.
        for path in package_files(self.asset_dir, payload_only=False):
            rel = str(path.relative_to(self.asset_dir)).replace("\\", "/")
            entries.append(Entry(path, rel, role_of(self.asset, rel, table),
                                 path.stat().st_size, _classify(path)))

        self.model.set_entries(entries)

        total = sum(e.size for e in entries)
        bits = [f"<b>{self.asset.name}</b>",
                f"{self.asset.type} / {self.asset.category}",
                f"{len(entries)} files", _human(total)]
        if self.asset.lods:
            bits.append(f"{len(self.asset.lods)} LODs")
        if self.asset.tags:
            bits.append(" ".join(self.asset.tags))
        self.header.setText("&nbsp; &middot; &nbsp;".join(bits) + f"<br>{self.asset_dir}")

    # -------------------------------------------------------------- selection

    def _current(self):
        rows = self.view.selectionModel().selectedIndexes()
        return rows[0].data(ENTRY_ROLE) if rows else None

    def _selected(self, *_) -> None:
        entry = self._current()
        if entry is None:
            self.pane.setCurrentWidget(self.blank)
            self.caption.clear()
            return

        digest = self.asset.hashes.get(entry.rel, "")
        bits = [entry.rel, entry.role or "not referenced by asset.json",
                _human(entry.size)]
        self.caption.setText("   ·   ".join(b for b in bits if b)
                             + (f"\n{digest}" if digest else ""))

        if entry.kind == "text":
            self.text.setPlainText(_read_text(entry.path))
            self.pane.setCurrentWidget(self.text)
            return
        if entry.kind == "image":
            self._detail_rel = entry.rel
            self.image.setText("decoding…")
            self.pane.setCurrentWidget(self.image)
            self.model.start(_DetailJob(entry, self._detail_signals, self.model.gate))
            return

        self.image.setPixmap(QPixmap())
        self.image.setText(f"{entry.path.suffix.lstrip('.').upper() or 'file'}"
                           f"\nno preview for this format")
        self.pane.setCurrentWidget(self.image)

    def _detail_ready(self, rel: str, data: bytes) -> None:
        if rel != self._detail_rel:
            return                                     # selection moved on
        pix = QPixmap()
        if not pix.loadFromData(data, "JPEG"):
            return
        self.image.setText("")
        self.image.setPixmap(pix.scaled(self.image.size(), Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation))

    # ---------------------------------------------------------------- actions

    def done(self, result: int) -> None:
        """Every exit route passes through here - Close, Esc and the window X
        alike, which closeEvent does not, because accept() never raises it.

        Dropping the queue matters: a package of twenty 8K maps leaves most of
        its decodes unstarted, and without this the next Contents window would
        sit waiting behind pictures nobody asked for any more.
        """
        self.model.shutdown()
        super().done(result)

    def _open_file(self, *_) -> None:
        entry = self._current()
        if entry is not None:
            _reveal(entry.path)

    def _open_folder(self) -> None:
        _reveal(self.asset_dir)

    def _edit(self) -> None:
        from .edit_asset import EditAssetDialog

        dialog = EditAssetDialog(self.cfg, self.asset_dir, self)
        dialog.exec()
        if dialog.added:
            self.edited = True
            thumbcache.forget(self.cfg, self.asset.uuid)
            self.accept()       # the package may have moved; the browser reopens it


def _read_text(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            raw = fh.read(TEXT_LIMIT)
    except OSError as exc:
        return f"cannot read: {exc}"
    if b"\0" in raw[:4096]:
        return "(binary file)"
    text = raw.decode("utf-8", errors="replace")
    if path.stat().st_size > TEXT_LIMIT:
        text += f"\n\n... truncated at {_human(TEXT_LIMIT)}"
    return text


def _reveal(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - intentional shell-less open
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}"')
