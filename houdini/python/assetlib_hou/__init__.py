"""Houdini side of the Assets Library.

Imports `hou`. Never imported by `assetlib` - the arrow runs one way, the same
rule that keeps `ui/` out of the core. An adapter depends on the library; the
library knows about no DCC.

No Qt at module level, in any file here. The options dialog will import
Houdini's own PySide2/6 when it is opened, never the PySide6 sitting in
`runtime/` - two Qt libraries in one process crash the host rather than raising.
"""

__all__ = ["seam", "launch"]
