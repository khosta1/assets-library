"""Putting a script asset where an application will find it.

Every other asset type is finished when it is in the tree. A tool is finished
when the application it was written for can load it, and that is a different
kind of done - it means writing something outside `library/`, into a place the
user owns.

**Houdini, via a package file.** One JSON in
`$HOUDINI_USER_PREF_DIR/packages/`, whose `path` points at the asset package.
Houdini then contributes that package's `toolbar/`, `python_panels/` and
`otls/` by itself. That is how this project installs ITSELF
(`houdini/packages/assets_library.json`) and how the eleven third-party
packages already on this machine do it - FLOPs, Megascans, RenderMan, Octane.

Why it beats the alternative, which is what the tools do today: nothing of the
user's is edited. No shelf of theirs is appended to, no `userSetup.py` line is
inserted. Install writes one file, uninstall deletes one file, and a half-done
install is a file that either exists or does not.

**The launcher is generated, never stored.** `Main_ui.txt` in the source hard-
codes `H:\3D\Maya\Scripts\Manager_tool\suite\Main_ui`, which is wrong the moment
the library owns a copy - and wrong in the worst way, because `sys.path.insert`
at position 0 means Houdini would silently keep running the ORIGINAL while you
edit the copy. So the asset records what the tool IS (entry, callable, label,
icon) and the shelf XML is emitted here with the path the library actually has.

No Qt and no `hou`: this writes JSON and XML into a directory, so it works from
the standalone app with Houdini closed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from xml.sax.saxutils import escape

PACKAGES = "packages"
TOOLBAR = "toolbar"

# What a generated shelf tool runs. Deliberately NOT the source's pattern of
# inserting an absolute path: the package file has already put this asset on
# PYTHONPATH, so the import just works, and no path is baked into the XML that
# could go stale or shadow the copy the user meant to run.
SNIPPET = """import importlib
import {module}
importlib.reload({module})
{module}.{call}()
"""


class InstallError(RuntimeError):
    """Something outside the library refused. Always says which path."""


# --------------------------------------------------------------------- paths


def pref_dirs(cfg, app: str = "houdini") -> list:
    """The application preference folders that exist on this machine.

    Returned in config order, which is newest-first for Houdini, so the default
    offered is the version most likely to be in use. Several are normally
    installed and an asset goes into ONE of them: a `.py` is version-agnostic
    but an `.hda` is not, and an H22 asset silently failing to load in H20.5 is
    worse than not offering it.
    """
    spec = cfg.apps.get(app) or {}
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    roots = [home / "Documents", home]
    out = []
    for name in spec.get("pref_dirs", []):
        for root in roots:
            candidate = root / name
            if candidate.is_dir():
                out.append(candidate)
                break
    return out


def package_path(pref_dir: Path, asset_name: str) -> Path:
    return Path(pref_dir) / PACKAGES / f"{asset_name}.json"


def installed_in(cfg, asset_name: str, app: str = "houdini") -> list:
    """Every pref dir that currently holds a package for this asset."""
    return [d for d in pref_dirs(cfg, app)
            if package_path(d, asset_name).is_file()]


# ----------------------------------------------------------------- emitting


def shelf_xml(asset_name: str, shelf: list) -> str:
    """One `<shelfDocument>` holding every declared entry of this asset.

    Zero, one or many: a tool pack of five unrelated utilities gets five tools
    in one shelf, and a library with no UI gets no shelf file at all. The list
    comes from `asset.json` - scanning is how the Add window OFFERS entries,
    never how they are decided.
    """
    tools = []
    for item in shelf:
        entry = (item.get("entry") or "").strip()
        call = (item.get("callable") or "show").strip()
        if not entry:
            continue
        module = Path(entry).stem
        label = item.get("label") or module.replace("_", " ").title()
        icon = item.get("icon") or "MISC_python"
        script = SNIPPET.format(module=module, call=call)
        tools.append(
            f'  <tool name="{escape(module)}" label="{escape(label)}" '
            f'icon="{escape(icon)}">\n'
            f'    <script scriptType="python"><![CDATA[\n{script}]]></script>\n'
            f'  </tool>'
        )
    if not tools:
        return ""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            "<shelfDocument>\n" + "\n".join(tools) + "\n</shelfDocument>\n")


def package_json(asset_dir: Path, shelf: list) -> dict:
    """The package Houdini reads. Absolute, because it is written per machine.

    Every directory the tool might import from goes on PYTHONPATH, not just the
    package root: the suite's modules sit one level down in their own folders
    and import each other by bare name, which is what the source's
    `sys.path.insert` lines were compensating for. Doing it here is what lets
    those lines be deleted rather than rewritten.
    """
    root = str(asset_dir).replace("\\", "/")
    env = [{"PYTHONPATH": {"value": root, "method": "append"}}]
    for item in shelf:
        entry = (item.get("entry") or "").strip()
        if not entry or "/" not in entry:
            continue
        folder = f"{root}/{Path(entry).parent.as_posix()}"
        pair = {"PYTHONPATH": {"value": folder, "method": "append"}}
        if pair not in env:
            env.append(pair)
    return {"enable": True, "env": env, "path": root}


# ---------------------------------------------------------------- installing


def install(cfg, asset, asset_dir: Path, pref_dir: Path,
            app: str = "houdini") -> dict:
    """Write the package, and the shelf inside the asset. Returns what it did.

    The shelf file is written INTO the asset package rather than into the user's
    toolbar folder, which is the whole point: it travels with the asset, it is
    regenerated whenever the declaration changes, and uninstalling touches
    nothing but the one package file.
    """
    if app != "houdini":
        raise InstallError(f"no installer is written for {app!r} yet")

    asset_dir = Path(asset_dir)
    shelf = list(asset.fields.get("shelf") or [])

    written = []
    xml = shelf_xml(asset.name, shelf)
    shelf_file = asset_dir / TOOLBAR / f"{asset.name}.shelf"
    if xml:
        try:
            shelf_file.parent.mkdir(parents=True, exist_ok=True)
            shelf_file.write_text(xml, encoding="utf-8")
            written.append(shelf_file)
        except OSError as exc:
            raise InstallError(f"cannot write {shelf_file}: {exc}") from exc
    elif shelf_file.is_file():
        # The declaration lost its last entry. Leaving the old shelf behind
        # would keep offering a button for something that is no longer claimed.
        shelf_file.unlink()

    target = package_path(pref_dir, asset.name)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(package_json(asset_dir, shelf), indent=4) + "\n",
            encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"cannot write {target}: {exc}") from exc

    return {"package": target, "shelf": shelf_file if xml else None,
            "tools": len(shelf), "restart": True}


def uninstall(cfg, asset_name: str, pref_dir: Path) -> bool:
    """Delete the package file. The asset itself is untouched.

    Returns True when something was removed. Only the package goes: the shelf
    lives inside the asset package and is part of it, and deleting the asset is
    a different, confirmed action that belongs to `edit.delete_asset`.
    """
    target = package_path(pref_dir, asset_name)
    if not target.is_file():
        return False
    try:
        target.unlink()
    except OSError as exc:
        raise InstallError(f"cannot remove {target}: {exc}") from exc
    return True
