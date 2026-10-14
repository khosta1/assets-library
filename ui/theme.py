"""The one place that decides a colour.

Dark is forced, not followed. The content of this window is images, and much of
it is colour-critical - a basecolor you are judging, an HDRI you are checking
the exposure of, a normal map you are inspecting for a green-channel mistake. A
light chrome around those shifts how they read, which is why every DCC this
library feeds ships dark. Following the OS instead would also make the same
library look different depending on which machine the external disk is plugged
into, and the window title carries that path precisely because that confusion
is expensive.

Colours are read from the palette at call time, never cached at import: there
is no QApplication yet when this module is first imported, and a colour grabbed
then would be Qt's default rather than the scheme applied in main().
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply(app: QApplication) -> None:
    """Force the dark scheme. Call once, BEFORE the first widget is built.

    Qt propagates the palette to a widget when the widget is constructed, so a
    scheme set after the main window exists leaves that window on the old one.
    """
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)


def _ground() -> QColor:
    """The grey every card step is taken from: #2d2d2d, Base of the forced
    dark scheme, held as a VALUE rather than read from the palette.

    It used to be read, and it broke the first time the grid ran as a guest.
    Inside Houdini the panel deliberately skips apply(), so the palette is
    Houdini's - and Houdini's Base is black. lighter() multiplies the HSV value,
    and black times anything is black, so every card, well and outline came out
    #000000 (2026-10-14). Tracking a palette only helps when the palette is
    ours; a host's can be anything, and the window is dark in both places.
    """
    return QColor(45, 45, 45)


def tile_colour() -> QColor:
    """Placeholder tile, drawn until the real thumbnail arrives.

    A step above the ground, not QPalette.Mid. Mid resolves to #282828 under
    the forced dark scheme, which is DARKER than Base (#2d2d2d) - the tile
    would be a hole in the grid rather than a shape in it. The literal this
    replaced was #3a3a3e, deliberately a step lighter than its ground, and
    lighter(130) lands in the same place.
    """
    return _ground().lighter(130)


def cloud_fill() -> QColor:
    """Ground behind a tile that is on a server and not on this disk.

    Blue, and blue specifically because it is the one hue this window does not
    otherwise use: the chrome is greys, the selection is the palette's
    highlight, and the tiles themselves are photographs. A tint that appears
    nowhere else cannot be mistaken for a thumbnail that happens to be blueish.

    Dark and low-saturation on purpose. It sits UNDER colour-critical images -
    a basecolor being judged, a normal map being checked - and a strong ground
    shifts how those read. It has to be unmistakable across a grid and almost
    invisible against any single image.
    """
    return QColor(28, 52, 84)


def cloud_edge() -> QColor:
    """Outline of the same tile. Carries the signal the fill is too quiet for.

    Bright enough to survive a 96px tile at the smallest zoom, where the fill is
    a few pixels of ground around the edge of a photograph and nothing else.
    """
    return QColor(78, 142, 222)


def local_only_edge() -> QColor:
    """Outline of a tile that exists HERE and nowhere else.

    The mirror of cloud_edge, and the more useful of the two: a blue tile is an
    asset you could fetch, a red one is an asset that would be gone if this
    disk died. It is the only state in the grid that is about risk rather than
    about location.

    Outline only, with no fill - a fill would compete with the thumbnail on
    every tile of a library that has not been pushed yet, which early on is all
    of them. Red because it is the one hue that reads as "attend to this"
    without a legend, and the window uses it nowhere else.
    """
    return QColor(214, 84, 79)


def dim_colour() -> QColor:
    # de-emphasised text: empty categories, rejected rows. PlaceholderText is
    # Qt's own role for this and stays legible on either ground - a literal
    # Qt.gray is a fixed mid-grey and goes muddy the moment the ground darkens.
    return QApplication.palette().color(QPalette.PlaceholderText)


# ------------------------------------------------------------------- the card
#
# A tile is a card: image well on top, name panel below, one outline around
# both, so a name can never be read as belonging to the picture beside it.
# Every step is taken from _ground(), never from the palette - see there.

def card_fill() -> QColor:
    """Name panel. A step above the grid ground, a step below the placeholder."""
    return _ground().lighter(118)


def card_edge() -> QColor:
    # outline of an ordinary card. hover: lighter(140) of this.
    return _ground().lighter(165)


def well_colour() -> QColor:
    """Ground behind the thumbnail: the placeholder's own grey, on purpose.

    Thumbnails are FITTED into the well, never cropped - an HDRI equirect or a
    vendor sheet would lose content to a crop - so the well shows wherever the
    image is narrower than 16:9. Colourless, for the same reason the window is
    dark: anything with a hue shifts how the image beside it reads.

    The same grey, not merely a similar one, because tool icons are composited
    onto (58,58,58) at import to match tile_colour() (decisions.md, Rejected) -
    any other well would draw a square round every icon with transparency. A
    tile still loading then reads as an empty well, not a shape inside one.
    """
    return tile_colour()


def badge_fill() -> QColor:
    """Pill under the resolution on the image. Translucent black, deliberately.

    It sits on arbitrary pixels, so it cannot borrow a palette colour that
    assumes a known ground; black at this alpha keeps light text legible on a
    white plaster swatch and disappears on a dark one.
    """
    return QColor(0, 0, 0, 170)


def badge_text() -> QColor:
    return QColor(235, 235, 235)


def chip_colours(kind: str) -> tuple:
    """(fill, text) of the state chip under the name. Detail mode only.

    The chip is the legend the outline never had: the same blue and the same
    red, with the word next to them.
    """
    if kind == "cloud":
        return cloud_fill(), cloud_edge().lighter(130)
    if kind == "local":
        edge = local_only_edge()
        return QColor(edge.red(), edge.green(), edge.blue(), 55), edge.lighter(125)
    # cached: here AND on the server, the state with nothing to worry about,
    # so it is drawn in the card's own greys.
    return card_edge(), dim_colour()


def pill_fill() -> QColor:
    # biggest resolution pill. the others: outline only, card_edge().
    return _ground().lighter(210)
