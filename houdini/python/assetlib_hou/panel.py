"""The library as a Houdini Python Panel.

Same window as the standalone app - `ui.app.MainWindow` - running in Houdini's
process instead of its own. That is possible because Houdini 22 ships PySide6,
the binding `ui/` already uses, and because the seam test confirmed Pillow,
numpy and OpenEXR are present too, so HDR and EXR previews still decode.

What it buys is one click instead of two. In this process `import hou` succeeds,
so `ui.import_houdini.in_houdini()` returns True and right-click -> Import to
Houdini calls the builder directly. No request file, no second button.

Two things this must NOT do:

  * put `runtime/` on sys.path. It holds a second PySide6, and two Qt libraries
    in one process crash the host rather than raising. The package file is
    careful about this and the seam test checks it.
  * call `ui.theme.apply()`. That forces the colour scheme on the whole
    QApplication, which in here is HOUDINI's - the standalone app owns its
    process and may do as it likes, a guest does not restyle the host. Building
    MainWindow directly skips it, which is why this does not call `ui.app.main`.

Writing still belongs to the standalone app: Houdini's interpreter has no
xxhash, so an Add or an Edit from in here would fall back to blake2b and write a
second digest algorithm into an xxh3 library. See `docs/decisions.md`.
"""

from __future__ import annotations

_WINDOW = None


def create():
    """Build the panel's widget. Called by assets_library.pypanel."""
    global _WINDOW

    from assetlib.config import find_config
    from ui.app import MainWindow

    cfg = find_config()
    cfg.ensure_roots()
    cfg.ensure_tree()

    # Kept on the module so the panel survives being torn down and rebuilt -
    # Houdini does that on layout changes, and a fresh MainWindow each time
    # would reopen the sqlite connection and re-run the startup migration check
    # for no reason.
    _WINDOW = MainWindow(cfg)
    return _WINDOW


def window():
    """The live panel window, or None. For debugging from the Python shell."""
    return _WINDOW
