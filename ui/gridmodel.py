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

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, QRect,
                            QRunnable, QSize, Qt, QThreadPool, Signal)
from PySide6.QtGui import QIcon, QImage, QPalette, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from . import theme

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
        pix.fill(theme.tile_colour())
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


# ------------------------------------------------------------------- the tile

# A tile is as wide as the zoom and 9/16 as tall, because that is the shape the
# previews actually are - Megascans renders, HDRI equirects and vendor sheets
# are all wide. A SQUARE icon box (what this used to be) scaled a 16:9 image to
# fit and then centred it, so every tile's image started at a different y
# depending on its source aspect. That was the misalignment.
#
# One aspect for the whole grid, not per tile: setUniformItemSizes(True) is what
# keeps the view fast at scale (gotcha 12), and it needs every item the same
# size. A square swatch in a wide box is simply narrower and centred, which
# reads fine; a per-tile aspect would cost the uniformity for nothing.
TILE_ASPECT = 9 / 16

# Two lines of name plus breathing room. Fixed: the old grid gave 46px, a
# 33-character Megascans name wrapped to three lines, and Qt clipped it - which
# is why some tiles showed a name and others showed none at all. Whether a name
# is visible must not depend on how long it is.
TEXT_LINES = 2
TEXT_PAD = 8
SPACING = 8          # must match view.setSpacing()


def tile_sizes(px: int) -> tuple:
    """(icon size, grid size) for one zoom step."""
    icon_h = max(int(px * TILE_ASPECT), 32)
    # The trailing SPACING is what sizeHint() gives back to the view for the gap
    # between tiles. Without it here the delegate would hand the image eight
    # fewer pixels than the icon size promised, and every thumbnail would be
    # very slightly squashed for no visible reason.
    return QSize(px, icon_h), QSize(px + 16,
                                    icon_h + _text_height() + TEXT_PAD + SPACING)


def _text_height() -> int:
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication

    return QFontMetrics(QApplication.font()).height() * TEXT_LINES


class TileDelegate(QStyledItemDelegate):
    """Draws a tile: image on top, exactly two lines of name below.

    Painted by hand rather than left to the default delegate because the two
    things that were wrong - where the image sits, and whether the name is
    visible at all - are both decided inside the default paint and cannot be
    reached from outside it.
    """

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view

    def sizeHint(self, option, index):
        grid = self.view.gridSize()
        return QSize(grid.width() - SPACING, grid.height() - SPACING)

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect

        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, option.palette.highlight())
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, option.palette.alternateBase())

        text_h = _text_height()
        icon_rect = QRect(rect.x(), rect.y(),
                          rect.width(), rect.height() - text_h - TEXT_PAD)

        icon = index.data(Qt.DecorationRole)
        if icon is not None:
            # Qt.AlignHCenter | Qt.AlignBottom: the image sits ON the text
            # block. Any slack from an unusually tall thumbnail ends up above,
            # in one place, instead of split around the image and different per
            # tile.
            icon.paint(painter, icon_rect, Qt.AlignHCenter | Qt.AlignBottom)

        painter.setPen(option.palette.color(
            QPalette.HighlightedText if option.state & QStyle.State_Selected
            else QPalette.Text))

        text_rect = QRect(rect.x() + 3, icon_rect.bottom() + TEXT_PAD,
                          rect.width() - 6, text_h)
        for i, line in enumerate(_two_lines(str(index.data(Qt.DisplayRole) or ""),
                                            option.fontMetrics, text_rect.width())):
            line_rect = QRect(text_rect.x(), text_rect.y() + i * (text_h // TEXT_LINES),
                              text_rect.width(), text_h // TEXT_LINES)
            painter.drawText(line_rect, Qt.AlignHCenter | Qt.AlignVCenter, line)

        painter.restore()


def _two_lines(text: str, fm, width: int) -> list:
    """Split a name over at most two lines, eliding the MIDDLE if it will not fit.

    Middle rather than end, because the ends are what identify these names:
    `barren_brome_bromussterilis_x0460` needs its species at the front and its
    Megascans hash at the back - two plants in this library differ by the hash
    alone, so eliding the tail would make them look identical.
    """
    if fm.horizontalAdvance(text) <= width:
        return [text]

    text = fm.elidedText(text, Qt.ElideMiddle, width * TEXT_LINES)

    # Break at the last separator that still fits on line one, so a name splits
    # between words rather than mid-token wherever the pixel count happened to
    # land.
    cut = len(text)
    while cut > 0 and fm.horizontalAdvance(text[:cut]) > width:
        cut -= 1
    nice = text.rfind("_", 0, cut + 1)
    if nice > len(text) // 4:
        cut = nice + 1
    return [text[:cut], text[cut:]]
