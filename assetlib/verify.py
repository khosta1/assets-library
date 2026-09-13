"""Check the invariants declared in config/library.json.

A violation is a bug in the tool or a hand-edit of library/, not something to
shrug at - the whole design rests on the tree being exactly what it claims.
"""

from __future__ import annotations

from pathlib import Path

from .hashing import UnavailableAlgorithm, matches
from .model import (ASSET_FILE, SCHEMA_VERSION, UDIM_TOKEN, Asset, expand,
                    iter_assets, on_disk_version, roles)


# Files that are allowed to exist without anything in asset.json pointing at
# them. extra/ is bonus payload kept verbatim and deliberately uninterpreted,
# derived/ is regenerable and may be rebuilt at any time, preview/ is generated,
# and _editing/ is a staging folder an interrupted edit can leave behind.
UNBOUND_DIRS = ("extra/", "derived/", "preview/", "_editing/")


def _orphans(asset: Asset, asset_dir: Path, rel) -> list:
    """Files on disk that nothing in asset.json names.

    The complement of every other check here. They all ask "does this pointer
    resolve"; none asked "does this file have a pointer", which is why a LOD
    level overwriting its own geometry stayed invisible - the surviving pointer
    resolved perfectly and the lost file simply sat there.

    A warning, not an error: an orphan is a binding that was not made, which is
    a real defect, but nothing is broken or unreadable because of it and the
    file itself is intact.
    """
    # A folder_blob's pointer is the TREE, not a file each (invariant 14). Its
    # whole point is that the tool arrives unexamined, so naming all 51 files
    # of a suite in asset.json would be a manifest of something the library
    # deliberately does not interpret - and without this every one of them
    # reports as an orphan. `toolbar/` joins it for a different reason: the
    # removed installer GENERATED one inside the package from the declaration,
    # so an asset imported on the day it existed still carries a folder nothing
    # points at. Nothing writes one any more - this stays so those packages do
    # not start reporting warnings for a feature that is gone.
    unbound_tree = tuple(
        f"{d}/" for d in (asset.fields.get("tree"), "toolbar") if d
    )

    table = roles(asset)
    bound = set(table)
    for relpath in list(table):
        # A tiled binding names a set; the tiles are the real files.
        bound.update(expand(asset, relpath))
    bound.add(ASSET_FILE)

    out = []
    for path in sorted(asset_dir.rglob("*")):
        if not path.is_file():
            continue
        # Asset.write() writes a temp file beside asset.json and os.replace()s
        # it, so one of these exists for a few milliseconds per package during
        # a migration. Verifying while the window is doing that pass reported
        # every in-flight write as an orphan - which is how this was found, on
        # the first run, against a library being migrated in another process.
        if path.name.startswith(".asset-") and path.suffix == ".tmp":
            continue
        inside = path.relative_to(asset_dir).as_posix()
        if inside in bound or inside.startswith(UNBOUND_DIRS):
            continue
        if inside.startswith(unbound_tree):
            continue
        out.append(("warn", str(rel), f"nothing in asset.json points at {inside}"))
    return out


def verify(cfg, deep: bool = False) -> list:
    """Return a list of (severity, path, message). Empty list means clean.

    Severity is error, warn or info. Schema skew is INFO: an old asset.json is
    read correctly by the migration chain, so it costs nothing - it is reported
    only so the state of the library is never a surprise.
    """
    problems = []
    behind: dict = {}
    if not cfg.library.exists():
        return [("error", str(cfg.library), "library/ does not exist - it is created at startup, so this is the "
                 "wrong library base")]

    asset_dirs = set()

    for asset_dir in iter_assets(cfg.library):
        asset_dirs.add(asset_dir)
        rel = asset_dir.relative_to(cfg.library)
        parts = rel.parts

        if len(parts) != 3:
            problems.append(("error", str(rel),
                             f"depth {len(parts)}, expected exactly 3 ({{type}}/{{category}}/{{asset}})"))
            continue
        type_folder, category, folder_name = parts

        version = on_disk_version(asset_dir)
        if version is not None and version < SCHEMA_VERSION:
            behind[version] = behind.get(version, 0) + 1

        try:
            asset = Asset.read(asset_dir)
        except Exception as exc:
            problems.append(("error", str(rel), f"unreadable {ASSET_FILE}: {exc}"))
            continue

        tdef = cfg.type_by_id.get(asset.type)
        if tdef is None:
            problems.append(("error", str(rel), f"type {asset.type!r} is not in types.json"))
        elif tdef["folder"] != type_folder:
            problems.append(("error", str(rel),
                             f"sits in {type_folder}/ but declares type {asset.type!r}"))

        if not cfg.valid_category(asset.type, asset.category):
            problems.append(("error", str(rel),
                             f"category {asset.category!r} is outside the closed vocabulary"))
        elif asset.category != category:
            problems.append(("error", str(rel),
                             f"sits in {category}/ but declares category {asset.category!r}"))

        if asset.name != folder_name:
            problems.append(("warn", str(rel),
                             f"asset.json name {asset.name!r} != folder name {folder_name!r}"))

        pointers = [(f"slot {slot}", relpath) for slot, relpath in asset.textures.items()]
        for slot, sizes in (asset.resolutions or {}).items():
            for label, relpath in (sizes or {}).items():
                pointers.append((f"slot {slot} {label}", relpath))
        for level, entry in (asset.lods or {}).items():
            if entry.get("geo"):
                pointers.append((f"lod{level} geo", entry["geo"]))
            for rep in entry.get("representations") or []:
                if rep.get("file"):
                    pointers.append((f"lod{level} {rep.get('role') or 'geo'}", rep["file"]))
            for slot, relpath in (entry.get("textures") or {}).items():
                pointers.append((f"lod{level} slot {slot}", relpath))

        for label, relpath in pointers:
            if Path(relpath).is_absolute() or ".." in Path(relpath).parts:
                problems.append(("error", str(rel), f"{label} escapes the package: {relpath}"))
                continue

            # A tiled binding names a SET. <UDIM> is not a file, so it is
            # expanded through the recorded tile list and every tile checked -
            # stat-ing the token itself would fail every UDIM asset.
            tiles = expand(asset, relpath)
            if UDIM_TOKEN in relpath and not tiles:
                problems.append(("error", str(rel),
                                 f"{label} is a UDIM set with no tiles recorded: {relpath}"))
                continue
            missing = [t for t in tiles if not (asset_dir / t).exists()]
            if missing:
                shown = ", ".join(missing[:3]) + (f" (+{len(missing) - 3} more)"
                                                  if len(missing) > 3 else "")
                problems.append(("error", str(rel),
                                 f"{label} points at missing file(s): {shown}"))

        problems.extend(_orphans(asset, asset_dir, rel))

        # A tool's DECLARED paths, which the orphan check cannot see: it walks
        # files and asks whether something points at them, and this is the
        # opposite direction - a pointer with nothing under it. An asset whose
        # shelf entry is missing imports cleanly and fails at the first
        # launch, a long way from the cause.
        from .apps import unresolved

        for miss in unresolved(asset, asset_dir):
            problems.append(("error", str(rel), f"declares a path that is not "
                                                f"in the package - {miss}"))

        if deep:
            for relpath, expected in asset.hashes.items():
                target = asset_dir / relpath
                if not target.exists():
                    problems.append(("error", str(rel), f"hashed file missing: {relpath}"))
                    continue
                try:
                    ok = matches(target, expected)
                except UnavailableAlgorithm as exc:
                    # Unverifiable is not the same as corrupted - say so.
                    problems.append(("warn", str(rel), f"cannot check {relpath}: {exc}"))
                    continue
                if not ok:
                    problems.append(("error", str(rel), f"content changed since import: {relpath}"))

    # Files sitting in library/ outside any asset package = someone wrote here by hand.
    # tex/, preview/ and derived/ live INSIDE a package and are not drift.
    for path in cfg.library.rglob("*"):
        if not path.is_dir() or path in asset_dirs:
            continue
        if any(d == path or d in path.parents for d in asset_dirs):
            continue
        if any(f.is_file() for f in path.iterdir()):
            problems.append(("warn", str(path.relative_to(cfg.library)),
                             "contains files but no asset.json - hand-edited?"))

    # One line, not one per asset: a stale schema is a property of the library.
    if behind:
        spread = ", ".join(f"{n} on v{v}" for v, n in sorted(behind.items()))
        problems.append(("info", "library",
                         f"{sum(behind.values())} asset(s) on an older schema "
                         f"({spread}); current is v{SCHEMA_VERSION} - "
                         "run Library > Migrate metadata"))

    return problems
