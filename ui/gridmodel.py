"""Grid model + threaded thumbnail loading.

Two rules decide whether this stays fast at 50k assets:

  * a model/view model, not one widget per asset - QListView only paints the
    tiles that are visible;
  * thumbnails decoded on a thread pool, never in the paint path.

The model holds plain dicts straight out of index.search() and never touches the
filesystem itself.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, QRunnable,
                            QSize, Qt, QThreadPool, Signal)
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap

UUID_ROLE = Qt.UserRole + 1
ROW_ROLE = Qt.UserRole + 2


class _ThumbSignals(QObject):
    done = Signal(str, QImage)


class _ThumbJob(QRunnable):
    def __init__(self, uuid: str, path: Path, signals: _ThumbSignals):
        super().__init__()
        self.uuid, self.path, self.signals = uuid, path, signals
        self.setAutoDelete(True)

    def run(self):
        image = QImage(str(self.path))
        if not image.isNull():
            self.signals.done.emit(self.uuid, image)


class AssetGridModel(QAbstractListModel):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.rows: list = []
        self._icons: dict = {}
        self._pending: set = set()
        self._pool = QThreadPool.globalInstance()
        self._signals = _ThumbSignals()
        self._signals.done.connect(self._thumb_ready)
        self._placeholder = self._make_placeholder()

    # ------------------------------------------------------------------ data

    def set_rows(self, rows: list) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def invalidate(self, uuid: str | None = None) -> None:
        """Forget cached icons so an edited asset stops showing its old one.

        The cache is keyed by uuid, and a uuid deliberately survives an edit -
        so without this an asset keeps the thumbnail it had at launch no matter
        what happens to it on disk.
        """
        if uuid is None:
            self._icons.clear()
            self._pending.clear()
        else:
            self._icons.pop(uuid, None)
            self._pending.discard(uuid)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.DisplayRole:
            return row["name"]
        if role == Qt.DecorationRole:
            return self._icon_for(row)
        if role == Qt.ToolTipRole:
            res = f"{row['resolution']}px" if row.get("resolution") else "-"
            return (f"{row['name']}\n{row['type']} / {row['category']}\n"
                    f"{res}   {_human(row.get('size', 0))}\n{row['path']}")
        if role == UUID_ROLE:
            return row["uuid"]
        if role == ROW_ROLE:
            return row
        return None

    # ------------------------------------------------------------- thumbnails

    @staticmethod
    def _make_placeholder() -> QIcon:
        pix = QPixmap(512, 512)
        pix.fill(QColor(58, 58, 62))
        return QIcon(pix)

    def _icon_for(self, row) -> QIcon:
        uuid = row["uuid"]
        icon = self._icons.get(uuid)
        if icon is not None:
            return icon
        if uuid not in self._pending:
            thumb = self.cfg.library / row["path"] / "preview" / "thumb.jpg"
            if thumb.is_file():
                self._pending.add(uuid)
                self._pool.start(_ThumbJob(uuid, thumb, self._signals))
        return self._placeholder

    def _thumb_ready(self, uuid: str, image: QImage) -> None:
        self._icons[uuid] = QIcon(QPixmap.fromImage(image))
        self._pending.discard(uuid)
        for i, row in enumerate(self.rows):
            if row["uuid"] == uuid:
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [Qt.DecorationRole])
                break


def _human(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return str(n)
