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


def tile_colour() -> QColor:
    """Placeholder tile, drawn until the real thumbnail arrives.

    Lightened Base, not QPalette.Mid. Mid resolves to #282828 under the forced
    dark scheme, which is DARKER than Base (#2d2d2d) - the tile would be a hole
    in the grid rather than a shape in it. The literal this replaced was
    #3a3a3e, deliberately a step lighter than its ground, and lighter(130)
    lands in the same place while still tracking the palette.
    """
    return QApplication.palette().color(QPalette.Base).lighter(130)


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


def dim_colour() -> QColor:
    # de-emphasised text: empty categories, rejected rows. PlaceholderText is
    # Qt's own role for this and stays legible on either ground - a literal
    # Qt.gray is a fixed mid-grey and goes muddy the moment the ground darkens.
    return QApplication.palette().color(QPalette.PlaceholderText)
