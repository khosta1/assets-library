"""Send one asset to Houdini.

The decisions live HERE, not in Houdini. The adapter on the other side is a
function that takes an asset and a dict of options and makes nodes; it has no
menus, no dialogs and no opinions. That split is deliberate: the old shelf tool
carried its own browser, its own options popup and its own idea of what a normal
map was called, and keeping a second copy of all that agreeing with this one is
the drift this project exists to prevent.

Two ways out, one entry point:

  in a Houdini Python Panel -> call the builder directly, same process
  standalone                -> write .assetlib/request.json, the shelf reads it

Which one happens is a detail of who imported this module. The options are
identical either way, so nothing about the asset depends on how the window was
launched.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QHBoxLayout, QLabel, QPushButton, QRadioButton,
                               QVBoxLayout)

from assetlib import derived
from assetlib.model import Asset, res_width

REQUEST_FILE = "request.json"
BIGGEST = "__biggest__"
ALL_VARIANTS = "__all__"


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    # Palette role, not a literal: the window forces dark and a hardcoded grey
    # here would be the one thing in the dialog that ignores it.
    label.setForegroundRole(label.foregroundRole())
    label.setStyleSheet("font-weight:bold; padding-top:8px;")
    return label


class HoudiniImportDialog(QDialog):
    """What to build, and how. Everything here is a choice the builder obeys.

    Opacity, displacement and the geometry variant set are ported from the old
    shelf tool's own popup, unchanged in meaning. Resolution and variant are
    new, and they are only possible because the import recorded those dimensions
    instead of leaving them in the filenames.
    """

    def __init__(self, asset: Asset, cfg, parent=None, count: int = 1):
        super().__init__(parent)
        self.asset = asset
        self.count = count
        self.setWindowTitle(
            f"Import to Houdini  -  {asset.name}" if count == 1
            else f"Import {count} assets to Houdini")
        self.setMinimumWidth(430)
        self.setModal(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)

        head = QLabel(f"<b>{asset.name}</b>  -  {asset.type} / {asset.category}")
        lay.addWidget(head)

        if count > 1:
            # Said out loud, because it is not obvious and it is the one way
            # this window can do something the user did not intend. The options
            # below describe ONE asset - opacity is offered because that asset
            # has an opacity map, 4k is offered because that asset has 4k - and
            # every other selected asset gets the same answers whether or not
            # they mean anything to it. The builder degrades rather than fails
            # (a missing size falls back to the biggest, a missing variant to
            # the primary), so nothing breaks; it just may not be what was
            # pictured. See ROADMAP.md.
            warn = QLabel(
                f"These options are read from <b>{asset.name}</b> and applied to "
                f"all <b>{count}</b> selected assets.<br>"
                "Where an option does not apply, that asset falls back to its "
                "own default rather than failing.")
            warn.setWordWrap(True)
            warn.setStyleSheet("padding:6px 0;")
            lay.addWidget(warn)

        # --- opacity -------------------------------------------------------
        lay.addWidget(_heading("Opacity"))
        self.op_none = QRadioButton("None")
        self.op_stencil = QRadioButton("Karma stencil map   (faster, SpeedTree-style)")
        self.op_shader = QRadioButton("Opacity shading   (higher fidelity, slower)")
        group = QButtonGroup(self)
        for rb in (self.op_none, self.op_stencil, self.op_shader):
            group.addButton(rb)
            lay.addWidget(rb)
        self.op_stencil.setChecked(True)

        # Greying out only makes sense for ONE asset. Across a selection, the
        # asset the dialog was read from may be the only one without an opacity
        # map, and disabling the choice would deny it to the other nineteen.
        # The builder already ignores an opacity mode for an asset that has no
        # opacity map, so offering it costs nothing.
        if count == 1 and "opacity" not in (asset.textures or {}):
            # Say so rather than offering a choice that will do nothing. The old
            # tool let you pick stencil on an asset with no opacity map and then
            # silently built nothing, which reads as a broken import.
            for rb in (self.op_stencil, self.op_shader):
                rb.setEnabled(False)
            self.op_none.setChecked(True)
            note = QLabel("no opacity map in this asset")
            note.setEnabled(False)
            lay.addWidget(note)

        # --- displacement ---------------------------------------------------
        lay.addWidget(_heading("Displacement"))
        self.disp = QCheckBox("Add mtlxdisplacement node")
        self.disp.setEnabled(count > 1 or "disp" in (asset.textures or {}))
        if not self.disp.isEnabled():
            self.disp.setText("Add mtlxdisplacement node   (no disp map in this asset)")
        lay.addWidget(self.disp)

        # --- resolution -----------------------------------------------------
        sizes = list(asset.fields.get("resolutions") or [])
        if len(sizes) > 1:
            lay.addWidget(_heading("Resolution"))
            self.res = QComboBox()
            self.res.addItem(f"biggest  ({sizes[0]})", BIGGEST)
            for label in sorted(sizes, key=res_width, reverse=True):
                self.res.addItem(label, label)
            lay.addWidget(self.res)
        else:
            self.res = None

        # --- variant --------------------------------------------------------
        variants = sorted({e.get("variant") for e in (asset.representations or [])
                           if e.get("variant")})
        if variants:
            lay.addWidget(_heading("Variant"))
            self.variant = QComboBox()
            self.variant.addItem(f"all  ({', '.join(variants)})", ALL_VARIANTS)
            for name in variants:
                self.variant.addItem(name, name)
            lay.addWidget(self.variant)
        else:
            self.variant = None

        # --- geometry -------------------------------------------------------
        lay.addWidget(_heading("Geometry"))
        self.varset = QCheckBox("Build a USD geometry variant set   (one per prim 'name')")
        self.varset.setToolTip(
            "Reads distinct prim 'name' values INSIDE one geometry file.\n"
            "Unrelated to the Variant above, which is a second mesh file.")
        lay.addWidget(self.varset)

        self.localize = QCheckBox("Localize to $HIP   (copy asset + textures, use $HIP paths)")
        self.localize.setToolTip(
            "Off: the network points into the library, which is what makes an\n"
            "asset shared rather than copied. On: the scene becomes portable\n"
            "without the library, at the cost of a second copy on disk.")
        lay.addWidget(self.localize)

        self.bake = QCheckBox("Use .rat textures   (bake missing ones into derived/)")
        self.bake.setChecked(derived.available())
        self.bake.setEnabled(derived.available())
        self.bake.setToolTip(
            "Karma reads a .rat far faster than a .jpg - and if you do not give\n"
            "it one it makes its own, writing it into tex/ beside the source.\n"
            "That is where the stray .rat files in this library came from.\n\n"
            "First build of an asset pays the conversion (~1s per 2K map, ~5s\n"
            "per 8K); after that they are reused. A .rat is about 3x the size of\n"
            "its source and lives in derived/, which is deletable and is never\n"
            "sent to the server."
            + ("" if derived.available() else
               "\n\nDisabled: iconvert was not found. It ships with Houdini."))
        lay.addWidget(self.bake)

        # --- buttons --------------------------------------------------------
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        go = QPushButton("Import")
        go.setDefault(True)
        go.clicked.connect(self.accept)
        row.addWidget(go)
        lay.addLayout(row)

    # ------------------------------------------------------------------ result

    def options(self) -> dict:
        """Plain data. Crosses a process boundary as JSON, so nothing but."""
        opacity = ("shader" if self.op_shader.isChecked()
                   else "stencil" if self.op_stencil.isChecked() else "none")
        return {
            "opacity": opacity,
            "displacement": bool(self.disp.isChecked() and self.disp.isEnabled()),
            "variant_set": bool(self.varset.isChecked()),
            "localize": bool(self.localize.isChecked()),
            "res": self.res.currentData() if self.res else BIGGEST,
            "variant": self.variant.currentData() if self.variant else ALL_VARIANTS,
            # Two flags, not one: "derived" is whether to USE a bake that
            # exists, "bake" is whether to make a missing one. Off-and-off
            # is the old behaviour exactly, which is what makes this safe
            # to turn off when a conversion misbehaves.
            "derived": bool(self.bake.isChecked()),
            "bake": bool(self.bake.isChecked()),
        }


# ------------------------------------------------------------------- dispatch


def in_houdini() -> bool:
    """True when this window is running inside Houdini's own interpreter.

    `hou` is importable only there. Checked rather than configured, because the
    same window is meant to run both ways and being told which one it is would
    be a setting someone eventually gets wrong.
    """
    try:
        import hou  # noqa: F401
        return True
    except Exception:                                # noqa: BLE001
        return False


def send(asset: Asset, asset_dir: Path, cfg, opts: dict) -> str:
    """Build now, or leave a request. Returns what to put in the status bar."""
    if in_houdini():
        try:
            from assetlib_hou import build

            nodes = build.karma_component(asset, asset_dir, cfg, opts)
            # None means the build was DEFERRED: textures are being baked on a
            # pool thread and the nodes are made from Houdini's idle callback
            # when that finishes. Counting them here would report 0 and read as
            # a failed import, which is the opposite of what happened.
            if nodes is None:
                return (f"baking textures for {asset.name} - the nodes appear "
                        "when it finishes; Houdini stays usable")
            return f"built {len(nodes)} node(s) for {asset.name}"
        except ImportError:
            # The adapter is not ported yet. Fall through to the request file
            # rather than failing: the shelf button can still pick it up, and
            # the user gets the same outcome one click later.
            pass

    path = write_request(asset, asset_dir, cfg, opts)
    return f"request written for {asset.name} - use the Houdini shelf ({path.name})"


def write_request(asset: Asset, asset_dir: Path, cfg, opts: dict) -> Path:
    """The handoff: a file on disk, not a socket.

    Same rule as the rest of the project - disk is what both sides agree on, and
    a request that survives a Houdini restart is more useful than one that does
    not. Overwritten each time: this is "what to build next", not a queue.
    """
    root = cfg.root_containing(asset_dir) or cfg.library
    payload = {
        "uuid": asset.uuid,
        "name": asset.name,
        "type": asset.type,
        "category": asset.category,
        # Relative to a root, like every path in the index. An absolute path
        # here would break the moment the disk gets a different letter, which is
        # the whole thing the library is built to survive.
        "path": asset_dir.relative_to(root).as_posix(),
        # WHICH root, and this is not optional now that there are two. The same
        # relative path exists under library/ and _cache/, so a request without
        # it does not fail - it silently builds the wrong copy of the asset.
        "origin": "cache" if root == cfg.cache_root else "local",
        "options": opts,
    }
    cfg.state.mkdir(parents=True, exist_ok=True)
    path = cfg.state / REQUEST_FILE
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    return path
