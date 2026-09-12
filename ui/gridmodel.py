"""Grid model + threaded thumbnail loading.

Two rules decide whether this stays fast at 50k assets:

  * a model/view model, not one widget per asset - QListView only paints the
    tiles that are visible;
  * thumbnails decoded on a thread pool, never in the paint path.

The model holds plain dicts straight out of index.search() and never touches the
filesystem itself.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, QRect,
                            QRunnable, QSize, Qt, QThreadPool, Signal)
from PySide6.QtGui import QIcon, QImage, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from . import netpool, theme

UUID_ROLE = Qt.UserRole + 1
ROW_ROLE = Qt.UserRole + 2
# Answered by the model, not worked out in paint(). paint() runs for every
# visible tile on every repaint and on every scroll pixel; string work in there
# is the difference between a grid that glides and one that stutters.
CLOUD_ROLE = Qt.UserRole + 3

# How long a host that failed is left alone. Long enough that a scroll through
# a few hundred tiles makes one doomed request rather than one per tile, short
# enough that waking the box and scrolling back is answered by pictures.
COOLDOWN_SECONDS = 60


def is_cloud(row) -> bool:
    """On a server and not on this disk.

    `cache` is deliberately NOT cloud. A downloaded asset is here, opens
    instantly and costs nothing to use - marking it would tell the user to
    worry about the one case there is nothing to worry about.
    """
    origin = row["origin"] if "origin" in row.keys() else ""
    return str(origin or "").startswith("remote:")


class _ThumbSignals(QObject):
    done = Signal(str, QImage)
    failed = Signal(str, str)           # host name, message - the HOST is at fault
    missing = Signal(str)               # uuid - this ONE asset has no thumbnail


class _ThumbJob(QRunnable):
    def __init__(self, uuid: str, path: Path, signals: _ThumbSignals):
        super().__init__()
        self.uuid, self.path, self.signals = uuid, path, signals
        self.setAutoDelete(True)

    def run(self):
        image = QImage(str(self.path))
        if not image.isNull():
            self.signals.done.emit(self.uuid, image)


class _RemoteThumbJob(QRunnable):
    """Fetch one tile's thumbnail from a server and keep it.

    Written to disk before it is shown, and read from disk ever after: a
    thumbnail changes only when the asset is re-imported, the uuid is a safe
    cache key, and the server sends a week of max-age saying exactly that. The
    picture is decoded here rather than on the GUI thread for the usual reason,
    and the bytes land on disk even if the decode fails - a file that will not
    decode is worth keeping so it is not fetched again every time the view
    scrolls past it.
    """

    def __init__(self, uuid: str, host, target: Path, signals: _ThumbSignals):
        super().__init__()
        self.uuid, self.host, self.target = uuid, host, target
        self.signals = signals
        self.setAutoDelete(True)

    def run(self):
        from assetlib import remote

        if netpool.stopping():
            # Queued before the close, started after it. Cheapest possible
            # place to notice, and it is the difference between a window that
            # shuts and a process that lingers.
            return
        try:
            data = remote.thumb(self.host, self.uuid)
        except remote.RemoteError as exc:
            # Two very different failures wear the same coat here, and telling
            # them apart is the whole point of this branch.
            #
            # 404 means THIS asset has no preview/thumb.jpg - a real and normal
            # state, 2 of the 75 packages on the box are like that. 410 means
            # the catalogue is stale and this one asset is gone. Neither says
            # anything about the server.
            #
            # Anything else - refused, timed out, token rejected - is the host,
            # and every other tile queued behind it will fail the same way.
            #
            # Getting this wrong is not subtle: feed a thumbnail 404 into the
            # host cooldown and one thumbnail-less asset scrolling into view
            # freezes every remote tile behind it for a minute.
            if exc.status in (404, 410):
                self.signals.missing.emit(self.uuid)
            else:
                self.signals.failed.emit(self.host.name, str(exc))
            return
        except Exception as exc:                        # noqa: BLE001
            self.signals.failed.emit(self.host.name, str(exc))
            return
        try:
            self.target.parent.mkdir(parents=True, exist_ok=True)
            self.target.write_bytes(data)
        except OSError:
            pass                    # a cache that cannot be written is not an error

        image = QImage()
        if image.loadFromData(data) and not image.isNull():
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
        self._signals.failed.connect(self._thumb_failed)
        self._signals.missing.connect(self._thumb_missing)
        self._placeholder = self._make_placeholder()

        # {host name: Host}. Empty until the window hands them over, and an
        # empty map simply means no remote tile ever fetches anything.
        self._hosts: dict = {}
        # A host that just failed, and until when. Without it, scrolling a
        # remote catalogue while the box is asleep queues one doomed request
        # per tile - and each of those costs the full TCP timeout, so the
        # queue outlives the scroll by minutes.
        self._cold: dict = {}
        self._pending_remote: dict = {}     # host name -> uuids in flight
        # Assets the server has no thumbnail for. Remembered so the view does
        # not ask again on every repaint - it is a permanent answer about the
        # asset, not a transient one about the link.
        self._missing: set = set()

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
        if role == CLOUD_ROLE:
            return is_cloud(row)
        return None

    # ------------------------------------------------------------- thumbnails

    @staticmethod
    def _make_placeholder() -> QIcon:
        pix = QPixmap(512, 512)
        pix.fill(theme.tile_colour())
        return QIcon(pix)

    def set_hosts(self, hosts) -> None:
        """The servers remote tiles may be fetched from. Clears any cooldown.

        _missing is deliberately NOT cleared: whether an asset has a thumbnail
        is a fact about the package on the server, and fixing a token or waking
        the box does not give one to an asset that never had one.
        """
        self._hosts = {h.name: h for h in hosts}
        self._cold.clear()

    def _icon_for(self, row) -> QIcon:
        uuid = row["uuid"]
        icon = self._icons.get(uuid)
        if icon is not None:
            return icon
        if uuid in self._pending:
            return self._placeholder

        path = self.cfg.asset_path(row)
        if path is not None:
            thumb = path / "preview" / "thumb.jpg"
            if thumb.is_file():
                self._pending.add(uuid)
                self._pool.start(_ThumbJob(uuid, thumb, self._signals))
            return self._placeholder

        # Catalogued on a server and not downloaded. The tile still gets a
        # picture: a thumbnail is ~40 KB against a package that can be a
        # gigabyte, which is the whole reason the three tiers are kept apart.
        cached = self.cfg.remote_thumbs_dir() / f"{uuid}.jpg"
        if cached.is_file():
            self._pending.add(uuid)
            self._pool.start(_ThumbJob(uuid, cached, self._signals))
            return self._placeholder

        if uuid in self._missing:
            return self._placeholder

        origin = str(row["origin"] if "origin" in row.keys() else "")
        host = self._hosts.get(origin[len("remote:"):]) if origin.startswith("remote:") else None
        if host is not None and not self._cooling(host.name):
            self._pending.add(uuid)
            self._pending_remote.setdefault(host.name, set()).add(uuid)
            # netpool, not the global pool: a fetch that never answers must not
            # occupy a decode thread, or the LOCAL library stops painting while
            # the remote one is unreachable.
            netpool.start(_RemoteThumbJob(uuid, host, cached, self._signals))
        return self._placeholder

    def _cooling(self, host_name: str) -> bool:
        until = self._cold.get(host_name, 0)
        return until > time.monotonic()

    def _thumb_failed(self, host_name: str, _message: str) -> None:
        """Stop asking this host for a while.

        Silent on purpose. A thumbnail that did not arrive is a grey tile, and
        a grey tile is already the message; a dialog per tile would be three
        hundred dialogs, and a status-bar line would overwrite whatever the
        user was actually reading.
        """
        self._cold[host_name] = time.monotonic() + COOLDOWN_SECONDS
        # Release only the tiles that were waiting on THIS host, so they can be
        # retried once the cooldown lapses. Clearing all of _pending would also
        # release local decodes that are still in flight, and every one of them
        # would be queued a second time on the next repaint.
        for uuid in self._pending_remote.pop(host_name, ()):
            self._pending.discard(uuid)

    def _thumb_missing(self, uuid: str) -> None:
        """This asset has no thumbnail on the server. The host is fine.

        Kept apart from _thumb_failed on purpose: the host is healthy, nothing
        should be cooled, and the other tiles must keep loading. The tile shows
        the placeholder, which is what a package with no preview/thumb.jpg looks
        like locally too - so it is consistent rather than special.
        """
        self._missing.add(uuid)
        self._pending.discard(uuid)
        for uuids in self._pending_remote.values():
            uuids.discard(uuid)

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

        # Cloud ground goes down FIRST, so selection and hover paint over it as
        # they do over any other tile - a selected cloud asset must look
        # selected, not like a third state nobody has seen before. The outline
        # at the end is what keeps the signal in all three cases.
        cloud = bool(index.data(CLOUD_ROLE))
        if cloud:
            painter.fillRect(rect, theme.cloud_fill())

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

        if cloud:
            # Last, over everything including the thumbnail. At the smallest
            # zoom a tile is 96px and the image covers nearly all of it, so the
            # fill is a few pixels of ground at the edges and the outline is
            # carrying the whole message on its own.
            painter.setPen(QPen(theme.cloud_edge(), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

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
