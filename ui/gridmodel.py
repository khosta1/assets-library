"""Grid model + threaded thumbnail loading.

Two rules decide whether this stays fast at 50k assets:

  * a model/view model, not one widget per asset - QListView only paints the
    tiles that are visible;
  * thumbnails decoded on a thread pool, never in the paint path.

The model holds plain dicts straight out of index.search() and never touches the
filesystem itself.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QByteArray, QMimeData,
                            QModelIndex, QObject, QRectF, QRunnable, QSize, Qt,
                            QThreadPool, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QIcon, QImage, QPainter,
                           QPainterPath, QPalette, QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate

from assetlib.model import res_label, res_width

from . import netpool, theme

UUID_ROLE = Qt.UserRole + 1
ROW_ROLE = Qt.UserRole + 2
# Answered by the model, not worked out in paint(). paint() runs for every
# visible tile on every repaint and on every scroll pixel; string work in there
# is the difference between a grid that glides and one that stutters.
CLOUD_ROLE = Qt.UserRole + 3
LOCAL_ONLY_ROLE = Qt.UserRole + 4
DETAIL_ROLE = Qt.UserRole + 5

# Unknown is not none. NULL in the index: row predates the column (local, F5
# fills it) or the server does not send it yet. '' or 0: looked, nothing there.
UNKNOWN = "?"
NONE = "—"

CHIP_TEXT = {"cloud": "server only", "local": "this disk only", "cache": "downloaded"}

# drag payload. marker: application/json is shared with every other drag, so
# the Houdini side claims only a payload carrying it.
DRAG_MARKER = "assetlib/assets"
DRAG_MIME = "application/json"

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


def is_local_only(row) -> bool:
    """On this disk and on no server. The one tile state that is about risk.

    False when `mirrored` is None, which means no catalogue is configured at
    all: "the server does not have this" and "there is no server" are different
    facts, and outlining every tile on a machine that never had one would be a
    warning about nothing.

    `cache` counts as mirrored by definition - a downloaded asset came FROM the
    server, so the server has it.
    """
    if is_cloud(row):
        return False
    mirrored = row["mirrored"] if "mirrored" in row.keys() else None
    return mirrored is False


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
        self._details: dict = {}            # uuid -> _detail(), built on first paint

    # ------------------------------------------------------------------ data

    def set_rows(self, rows: list) -> None:
        self.beginResetModel()
        self.rows = rows
        # The rows are new dicts from a new query - an edit or an F5 changed
        # what they say, and the cache is keyed by a uuid that survives both.
        self._details.clear()
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
            self._details.clear()
        else:
            self._icons.pop(uuid, None)
            self._pending.discard(uuid)
            self._details.pop(uuid, None)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    # ------------------------------------------------------------------ drag

    def flags(self, index):
        flags = super().flags(index)
        # A drag carries a package on THIS disk. A cloud row has none, so it
        # does not start one - dropping a promise of an asset into Houdini
        # would fail at the far end, where the reason is hardest to see.
        if index.isValid() and self.cfg.asset_path(self.rows[index.row()]) is not None:
            flags |= Qt.ItemIsDragEnabled
        return flags

    def mimeTypes(self):
        return [DRAG_MIME]

    def mimeData(self, indexes):
        """The dragged tiles as JSON: which packages, nothing else.

        JSON alone, measured: a probe in Houdini 21 (2026-10-14) offered three
        encodings and the network editor's `source.data()` returned the JSON
        and nothing for `application/x-assetlib` or `text/uri-list`, from this
        process and from Houdini's own. A file URL was also worse than useless:
        Explorer copied asset.json wherever a tile was dropped, and Houdini's
        own file drop tried to open it as a scene.

        An absolute `dir`, unlike request.json: a drag lives for a second on
        one machine, so the drive letter cannot change under it.
        """
        assets = []
        for index in indexes:
            row = self.rows[index.row()]
            path = self.cfg.asset_path(row)
            if path is not None:
                assets.append({"uuid": row["uuid"], "name": row["name"],
                               "type": row["type"], "dir": str(path)})
        data = QMimeData()
        data.setData(DRAG_MIME, QByteArray(
            json.dumps({"type": DRAG_MARKER, "assets": assets}).encode("utf-8")))
        return data

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
        if role == LOCAL_ONLY_ROLE:
            return is_local_only(row)
        if role == DETAIL_ROLE:
            detail = self._details.get(row["uuid"])
            if detail is None:
                detail = self._details[row["uuid"]] = _detail(row, self.cfg)
            return detail
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


def _listed(blob) -> str:
    """'ao diffuse normal' -> '3 · ao diffuse normal'. Count first: it survives
    the elision at a narrow zoom, the names after it do not."""
    if blob is None:
        return UNKNOWN
    items = str(blob).split()
    return f"{len(items)} · {' '.join(items)}" if items else NONE


def _detail(row, cfg) -> dict:
    """Everything the card prints, as finished strings. Once per row, cached.

    From the index row only. The window never reads asset.json to draw - that
    is why slots, variants and lods became index columns rather than something
    looked up when Details is switched on.
    """
    res = sorted(str(row.get("resolutions") or "").split(), key=res_width, reverse=True)
    if not res and row.get("resolution"):
        res = [res_label(row["resolution"])]

    origin = str(row.get("origin") or "")
    state = ("cloud" if is_cloud(row) else "local" if is_local_only(row)
             else "cache" if origin == "cache" else "")
    label = cfg.type_by_id.get(row.get("type"), {}).get("label") or row.get("type")
    lods = row.get("lods")
    return {
        "res": res,
        "subtitle": f"{label} / {row.get('category')}",
        "state": state,
        "rows": (
            ("MAPS", _listed(row.get("slots"))),
            ("VARIANTS", _listed(row.get("variants"))),
            ("LODS", UNKNOWN if lods is None else str(lods) if lods else NONE),
            ("SIZE", _human(row.get("size")) if row.get("size") else NONE),
        ),
    }


# ------------------------------------------------------------------- the tile

# The image well is as wide as the zoom and 9/16 as tall, because that is the
# shape the previews actually are - Megascans renders, HDRI equirects and vendor
# sheets are all wide. A SQUARE icon box (what this used to be) scaled a 16:9
# image to fit and then centred it, so every tile's image started at a
# different y depending on its source aspect. That was the misalignment. The
# well now carries the alignment: its edges line up across the grid whatever
# sits inside it.
#
# One aspect for the whole grid, not per tile: setUniformItemSizes(True) is what
# keeps the view fast at scale (gotcha 12), and it needs every item the same
# size. A square swatch in a wide box is simply narrower and centred, which
# reads fine; a per-tile aspect would cost the uniformity for nothing.
TILE_ASPECT = 9 / 16

# Two lines of name, always. Fixed: the old grid gave 46px, a 33-character
# Megascans name wrapped to three lines, and Qt clipped it - which is why some
# tiles showed a name and others showed none at all. Whether a name is visible
# must not depend on how long it is.
TEXT_LINES = 2
SPACING = 8          # must match view.setSpacing()
PAD_X, PAD_Y, ROW_GAP, RADIUS = 8, 6, 2, 5

# Details is a mode of the whole grid, not of one tile: uniform item sizes
# (gotcha 12) mean one height for everyone, so "open this one" would have to
# open them all anyway. Below 200px the label column leaves the values no room,
# so the mode raises the zoom to this and gives the slider its value back when
# switched off.
DETAIL_MIN_PX = 200
# Below this the badge covers too much of the image it is describing.
BADGE_MIN_PX = 160
DETAIL_ROWS = 5      # RES + the four in _detail()["rows"]


class _Fonts:
    """The card's fonts and their metrics. Built on first use, never at import:
    there is no QApplication yet when this module loads."""

    def __init__(self):
        # The application font throughout, as the grid always had. Felix,
        # 2026-10-14: the card layout, yes; a monospace name, no.
        base = QApplication.font()
        self.name = QFont(base)
        self.value = QFont(base)
        self.sub = QFont(base)
        self.label = _scaled(base, 0.82)
        self.label.setLetterSpacing(QFont.PercentageSpacing, 108)
        self.small = _scaled(base, 0.85)
        self.badge = _scaled(base, 0.9)

        self.name_fm = QFontMetrics(self.name)
        self.value_fm = QFontMetrics(self.value)
        self.sub_fm = QFontMetrics(self.sub)
        self.label_fm = QFontMetrics(self.label)
        self.small_fm = QFontMetrics(self.small)
        self.badge_fm = QFontMetrics(self.badge)

        self.name_h = self.name_fm.height()
        self.line_h = max(self.value_fm.height(), self.label_fm.height()) + 2
        self.chip_h = self.small_fm.height() + 4
        self.label_w = self.label_fm.horizontalAdvance("VARIANTS") + 10


def _scaled(font: QFont, factor: float) -> QFont:
    out = QFont(font)
    if out.pointSizeF() > 0:
        out.setPointSizeF(out.pointSizeF() * factor)
    else:                                   # font set in pixels
        out.setPixelSize(max(int(out.pixelSize() * factor), 8))
    return out


_FONTS = None


def _fonts() -> _Fonts:
    global _FONTS
    if _FONTS is None:
        _FONTS = _Fonts()
    return _FONTS


def _info_height(detailed: bool) -> int:
    """Height of the panel under the image. The ONE place it is worked out:
    tile_sizes() sizes the grid from it and paint() splits the card with it."""
    f = _fonts()
    h = PAD_Y + f.name_h * TEXT_LINES + PAD_Y
    if detailed:
        h += (f.sub_fm.height() + ROW_GAP + f.chip_h + ROW_GAP
              + DETAIL_ROWS * (f.line_h + ROW_GAP))
    return h


def tile_sizes(px: int, detailed: bool = False) -> tuple:
    """(icon size, grid size) for one zoom step."""
    if detailed:
        px = max(px, DETAIL_MIN_PX)
    icon_h = max(int(px * TILE_ASPECT), 32)
    # The trailing SPACING is what sizeHint() gives back to the view for the gap
    # between tiles. Without it here the delegate would hand the image eight
    # fewer pixels than the icon size promised, and every thumbnail would be
    # very slightly squashed for no visible reason.
    return QSize(px, icon_h), QSize(px + 16,
                                    icon_h + _info_height(detailed) + SPACING)


class TileDelegate(QStyledItemDelegate):
    """Draws a tile as a card: image well on top, name panel below, one outline.

    Painted by hand rather than left to the default delegate because the two
    things that were wrong - where the image sits, and whether the name is
    visible at all - are both decided inside the default paint and cannot be
    reached from outside it.

    The outline goes round image AND name. Before, the name floated under the
    picture with nothing joining them, and at a tight zoom a name read as
    belonging to the tile beside it as easily as to its own.
    """

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        # Set by the window with the grid size, never on its own: the two
        # must change together or the card is split at the wrong height.
        self.detailed = False

    def sizeHint(self, option, index):
        grid = self.view.gridSize()
        return QSize(grid.width() - SPACING, grid.height() - SPACING)

    def paint(self, painter, option, index):
        f = _fonts()
        detail = index.data(DETAIL_ROLE) or {}
        state = detail.get("state", "")
        selected = bool(option.state & QStyle.State_Selected)
        palette = option.palette

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        card = QRectF(option.rect)
        info_h = _info_height(self.detailed)
        well = QRectF(card.x(), card.y(), card.width(), card.height() - info_h)
        info = QRectF(card.x(), well.bottom(), card.width(), info_h)
        shape = QPainterPath()
        shape.addRoundedRect(card, RADIUS, RADIUS)

        # Everything inside the card is clipped to its rounded corners, once.
        painter.setClipPath(shape)
        painter.fillRect(well, theme.well_colour())
        icon = index.data(Qt.DecorationRole)
        if icon is not None:
            icon.paint(painter, well.toRect(), Qt.AlignCenter)

        # Selection and the cloud ground go on the name panel, never on the
        # image: the image is the colour-critical part, and a selected tile
        # tinted blue is a basecolor that cannot be judged. Selection wins over
        # cloud here because the outline below still carries the cloud.
        painter.fillRect(info, palette.highlight() if selected
                         else theme.cloud_fill() if state == "cloud"
                         else theme.card_fill())
        painter.fillRect(QRectF(info.x(), info.y(), info.width(), 1), theme.card_edge())
        painter.setClipping(False)

        if detail.get("res") and card.width() >= BADGE_MIN_PX:
            self._badge(painter, f, well, detail["res"][0])

        # dim = ink at lower alpha, not dim_colour(): PlaceholderText is the
        # host's in Houdini, and the card ground is fixed (theme._ground).
        ink = palette.color(QPalette.HighlightedText if selected else QPalette.Text)
        dim = QColor(ink)
        dim.setAlpha(170 if selected else 140)

        x, w = info.x() + PAD_X, info.width() - 2 * PAD_X
        y = info.y() + PAD_Y
        painter.setFont(f.name)
        painter.setPen(ink)
        name = str(index.data(Qt.DisplayRole) or "")
        for i, line in enumerate(_two_lines(name, f.name_fm, int(w))):
            painter.drawText(QRectF(x, y + i * f.name_h, w, f.name_h),
                             Qt.AlignLeft | Qt.AlignVCenter, line)
        y += f.name_h * TEXT_LINES

        if self.detailed and detail:
            self._details(painter, f, detail, x, y, w, ink, dim)

        # Last, over everything. At the smallest zoom a tile is 96px and the
        # image covers nearly all of it, so the outline is carrying the whole
        # message on its own.
        #
        # Mutually exclusive by construction, not by luck: is_local_only()
        # returns False for a cloud row, because an asset on the server is the
        # one thing that cannot also be on no server. A state outline beats the
        # selection outline: the panel fill already says "selected", and nothing
        # else on the card says "this exists nowhere else".
        if state == "cloud":
            pen = QPen(theme.cloud_edge(), 2)
        elif state == "local":
            pen = QPen(theme.local_only_edge(), 2)
        elif selected:
            pen = QPen(palette.highlight().color(), 2)
        elif option.state & QStyle.State_MouseOver:
            pen = QPen(theme.card_edge().lighter(140), 1)
        else:
            pen = QPen(theme.card_edge(), 1)
        # stroke centred half a pen inside the card: crisp at 1px and 2px.
        d = pen.widthF() / 2
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(card.adjusted(d, d, -d, -d), RADIUS - d, RADIUS - d)

        painter.restore()

    @staticmethod
    def _badge(painter, f, well, label):
        # biggest resolution, bottom-left on the image.
        bw = f.badge_fm.horizontalAdvance(label) + 10
        bh = f.badge_fm.height() + 2
        rect = QRectF(well.x() + 6, well.bottom() - 6 - bh, bw, bh)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.badge_fill())
        painter.drawRoundedRect(rect, 3, 3)
        painter.setFont(f.badge)
        painter.setPen(theme.badge_text())
        painter.drawText(rect, Qt.AlignCenter, label)

    @staticmethod
    def _details(painter, f, detail, x, y, w, ink, dim):
        """Subtitle, state chip, then fixed rows.

        Fixed: every card has every row, '—' or '?' when there is nothing, so a
        row sits at the same height on every card and can be read ACROSS the
        grid. Rows that collapse when empty would put SIZE at four different
        heights in one line of tiles.
        """
        painter.setFont(f.sub)
        painter.setPen(dim)
        painter.drawText(QRectF(x, y, w, f.sub_fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                         f.sub_fm.elidedText(detail["subtitle"], Qt.ElideRight, int(w)))
        y += f.sub_fm.height() + ROW_GAP

        # chip line kept when empty, for the same fixed-row reason.
        state = detail["state"]
        if state:
            fill, text = theme.chip_colours(state)
            label = CHIP_TEXT[state]
            chip = QRectF(x, y, min(f.small_fm.horizontalAdvance(label) + 12, w), f.chip_h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(chip, 3, 3)
            painter.setFont(f.small)
            painter.setPen(text)
            painter.drawText(chip, Qt.AlignCenter, label)
        y += f.chip_h + ROW_GAP

        vx, vw = x + f.label_w, w - f.label_w

        _label(painter, f, "RES", x, y, dim)
        _pills(painter, f, detail["res"], vx, y, vw, ink, dim)
        y += f.line_h + ROW_GAP

        for label, value in detail["rows"]:
            _label(painter, f, label, x, y, dim)
            painter.setFont(f.value)
            painter.setPen(dim if value in (UNKNOWN, NONE) else ink)
            painter.drawText(QRectF(vx, y, vw, f.line_h), Qt.AlignLeft | Qt.AlignVCenter,
                             f.value_fm.elidedText(value, Qt.ElideRight, int(vw)))
            y += f.line_h + ROW_GAP


def _label(painter, f, text, x, y, colour):
    painter.setFont(f.label)
    painter.setPen(colour)
    painter.drawText(QRectF(x, y, f.label_w, f.line_h), Qt.AlignLeft | Qt.AlignVCenter, text)


def _pills(painter, f, res, x, y, width, ink, dim):
    """Every resolution held, biggest first and filled, the rest outlined.

    Stops at the first pill that does not fit rather than eliding one: half a
    '16k' reads as '1'.
    """
    painter.setFont(f.value)
    if not res:
        painter.setPen(dim)
        painter.drawText(QRectF(x, y, width, f.line_h), Qt.AlignLeft | Qt.AlignVCenter, NONE)
        return
    left = x
    for i, label in enumerate(res):
        pw = f.value_fm.horizontalAdvance(label) + 8
        if left + pw > x + width:
            break
        pill = QRectF(left, y + 1, pw, f.line_h - 2)
        if i == 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.pill_fill())
        else:
            painter.setPen(QPen(theme.card_edge(), 1))
            painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        painter.setPen(ink if i == 0 else dim)
        painter.drawText(pill, Qt.AlignCenter, label)
        left += pw + 4


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
