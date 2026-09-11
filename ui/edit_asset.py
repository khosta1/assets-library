"""Edit an asset that is already in the library.

The same window as Add, because it is the same question: what is this asset,
and which files make it up. The only differences are that the fields arrive
filled in from `asset.json`, the package's own files are already in the table,
and pressing Apply mutates the package instead of creating one.

Everything else - the binding dropdown, the LOD column, the preview zone, the
clash detection - is inherited rather than reimplemented, so the two windows
cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from assetlib import edit as edit_mod
from assetlib import index as idx
from assetlib.model import Asset

from . import writepool
from .add_asset import AddAssetDialog


class _EditSignals(QObject):
    step = Signal(str, int, int)
    done = Signal(str)
    failed = Signal(str)


class EditWorker(QRunnable):
    """Renames are instant but an added 8K map is not, so this stays off the
    GUI thread like every other write."""

    def __init__(self, eplan, cfg):
        super().__init__()
        self.eplan, self.cfg = eplan, cfg
        self.signals = _EditSignals()
        self.setAutoDelete(True)

    def run(self):
        def report(message, done, total):
            self.signals.step.emit(message, done, total)

        try:
            asset_dir = edit_mod.apply(self.eplan, self.cfg, progress=report)
        except Exception as exc:                       # noqa: BLE001
            self.signals.failed.emit(str(exc))
            return
        try:
            self.signals.step.emit("updating the index", 0, 0)
            conn = idx.connect(self.cfg)
            idx.upsert(conn, Asset.read(asset_dir), asset_dir, self.cfg.library)
            conn.close()
        except Exception as exc:                       # noqa: BLE001
            self.signals.failed.emit(f"edited, but not re-indexed: {exc}")
            return
        self.signals.done.emit(str(asset_dir))


class EditAssetDialog(AddAssetDialog):
    def __init__(self, cfg, asset_dir, parent=None):
        self.asset_dir = Path(asset_dir).resolve()
        self.asset = Asset.read(self.asset_dir)
        super().__init__(cfg, parent)

        self.setWindowTitle(f"Edit  {self.asset.name}")
        self.add_btn.setText("Apply")
        self.again_btn.hide()
        # Editing has no move path yet: added files are copied in.
        self.move_box.hide()
        self.drop.set_count(0, "drop files here to add them")
        self._load()

    # --------------------------------------------------------------- loading

    def _load(self) -> None:
        """Fill the window from asset.json and the package contents."""
        pos = self.type_box.findData(self.asset.type)
        if pos >= 0:
            self.type_box.setCurrentIndex(pos)       # repopulates the categories
        pos = self.cat_box.findData(self.asset.category)
        if pos >= 0:
            self.cat_box.setCurrentIndex(pos)

        self.name_edit.setText(self.asset.name)
        self._name_touched = True                    # an existing name is not a guess
        self.tags_edit.setText(" ".join(self.asset.tags))

        thumb = self.asset_dir / "preview" / "thumb.jpg"
        self._files = [f for f in edit_mod.package_files(self.asset_dir) if f != thumb]
        if thumb.is_file():
            self._preview = thumb
            self.icon_zone.show_image(thumb)
        self._replan()

    def _plan_source(self, files: list) -> Path:
        """Relative destinations are resolved against the package itself, so a
        file already in extra/ plans back to extra/ instead of being flattened."""
        return self.asset_dir

    # ---------------------------------------------------------------- status

    def _refresh_status(self) -> None:
        super()._refresh_status()
        if self.plan is None:
            return
        try:
            eplan = edit_mod.build(self.asset_dir, self.asset, self.plan, self.cfg,
                                   self._tags())
        except Exception:                              # noqa: BLE001
            return
        self.status.setText(self.status.text() + "\n" + eplan.summary())

    def _tags(self) -> list:
        return sorted({t for t in self.tags_edit.text().split() if t})

    # ---------------------------------------------------------------- commit

    def _commit(self, keep_going: bool) -> None:
        if self.plan is None or not self.plan.ready:
            return
        try:
            eplan = edit_mod.build(self.asset_dir, self.asset, self.plan, self.cfg,
                                   self._tags())
        except Exception as exc:                       # noqa: BLE001
            QMessageBox.critical(self, "Cannot plan this edit", str(exc))
            return

        if not eplan.touched:
            self.status.setText("nothing to apply")
            return

        removed = eplan.of(edit_mod.DELETE)
        if removed:
            listing = "\n".join(f"  {c.old_rel}  ({_size(c.size)})" for c in removed[:15])
            if len(removed) > 15:
                listing += f"\n  … and {len(removed) - 15} more"
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Delete files?")
            box.setText(f"{len(removed)} file(s) will be deleted for good.")
            box.setInformativeText("This cannot be undone.")
            box.setDetailedText(listing)
            box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
            box.setDefaultButton(QMessageBox.Cancel)
            if box.exec() != QMessageBox.Yes:
                return

        self._progress = QProgressDialog("Preparing…", "", 0, 0, self)
        self._progress.setWindowTitle(f"Editing {self.asset.name}")
        self._progress.setCancelButton(None)
        self._progress.setMinimumWidth(460)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.show()

        # Kept on self: a runnable that only the local scope references can be
        # collected out from under the signals it still has to emit.
        self._worker = EditWorker(eplan, self.cfg)
        self._worker.signals.step.connect(self._commit_step)
        self._worker.signals.done.connect(lambda p: self._commit_done(p, False))
        self._worker.signals.failed.connect(self._commit_failed)
        writepool.start(self._worker)

    def _commit_step(self, message: str, done: int, total: int) -> None:
        if not self._progress:
            return
        self._progress.setLabelText(message)
        if total:
            self._progress.setRange(0, total)
            self._progress.setValue(done)
        else:
            self._progress.setRange(0, 0)


def _size(n: int) -> str:
    from .gridmodel import _human

    return _human(n)
