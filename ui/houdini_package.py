"""Library ▸ Houdini package… - install, update or remove it per Houdini.

One row per Houdini found. The state is said in words, because the case worth
seeing is the one a moved disk makes: "points at E:/… (gone)" is the whole
diagnosis of a Houdini that silently stopped loading the library.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QGridLayout, QLabel, QVBoxLayout)

from assetlib import houdini_pkg as hp


def describe(inst: hp.Install) -> str:
    if not inst.supported:
        return "not supported (21.0 or later)"
    if inst.state == hp.HERE:
        return "installed for this library"
    if inst.state == hp.ELSEWHERE:
        gone = "" if inst.target_exists else "  (gone)"
        return f"points at another library: {inst.points_at}{gone}"
    if inst.state == hp.UNREADABLE:
        return f"{hp.PACKAGE_FILE} present but unreadable"
    return "not installed"


class HoudiniPackageDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.changed = False
        self.setWindowTitle("Houdini package")
        self.setMinimumWidth(560)

        lay = QVBoxLayout(self)
        intro = QLabel(
            "One file per Houdini, in its user prefs <code>packages/</code> folder. "
            "It points Houdini at <b>this</b> library, so the shelf, the panel and "
            f"Import to Houdini load from<br>{cfg.base.resolve().as_posix()}")
        intro.setWordWrap(True)
        intro.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(intro)

        self.grid = QGridLayout()
        self.grid.setColumnStretch(1, 1)
        lay.addLayout(self.grid)

        self.result = QLabel("")
        self.result.setWordWrap(True)
        lay.addWidget(self.result)

        buttons = QDialogButtonBox()
        self.install_btn = buttons.addButton("Install / update", QDialogButtonBox.ActionRole)
        self.remove_btn = buttons.addButton("Remove", QDialogButtonBox.ActionRole)
        buttons.addButton(QDialogButtonBox.Close)
        self.install_btn.clicked.connect(self._install)
        self.remove_btn.clicked.connect(self._remove)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.boxes: dict = {}
        self._fill()

    def _fill(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.boxes.clear()

        found = hp.status(self.cfg.base)
        if not found:
            self.grid.addWidget(QLabel("No Houdini found in Program Files or Documents."), 0, 0)
        for row, inst in enumerate(found):
            box = QCheckBox(f"Houdini {inst.version}")
            box.setEnabled(inst.supported)
            # Ticked where there is something to do; an install already
            # pointing here is left unticked so Remove cannot take it by habit.
            box.setChecked(inst.supported and inst.state != hp.HERE)
            box.setToolTip(str(inst.file))
            state = QLabel(describe(inst))
            state.setEnabled(inst.supported)
            state.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.grid.addWidget(box, row, 0)
            self.grid.addWidget(state, row, 1)
            if inst.supported:
                self.boxes[inst.version] = box
        has_any = bool(self.boxes)
        self.install_btn.setEnabled(has_any)
        self.remove_btn.setEnabled(has_any)

    def _picked(self) -> list:
        return [v for v, box in self.boxes.items() if box.isChecked()]

    def _install(self) -> None:
        done, failed = [], []
        for version in self._picked():
            try:
                hp.install(self.cfg.base, version)
                done.append(version)
            except Exception as exc:                    # noqa: BLE001
                failed.append(f"{version}: {exc}")
        self._report("Installed for", done, failed)

    def _remove(self) -> None:
        done, failed = [], []
        for version in self._picked():
            try:
                if hp.remove(version):
                    done.append(version)
            except Exception as exc:                    # noqa: BLE001
                failed.append(f"{version}: {exc}")
        self._report("Removed from", done, failed)

    def _report(self, verb: str, done: list, failed: list) -> None:
        self.changed = self.changed or bool(done)
        lines = []
        if done:
            # Said every time: Houdini reads packages at startup only, and an
            # install that "did nothing" is otherwise exactly what it looks like.
            lines.append(f"{verb} Houdini {', '.join(done)}. Restart Houdini to load it.")
        if failed:
            lines.append("Failed: " + "; ".join(failed))
        if not lines:
            lines.append("Nothing selected - tick a Houdini first.")
        self.result.setText("\n".join(lines))
        self._fill()
