"""Execute an ImportPlan: the one place that writes into library/.

Copy-and-hash in a single pass (the bytes are being read anyway), then write
asset.json, generate the thumbnail and index the result. The source in _inbox is
never touched - clearing it stays an explicit user action.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .analyse import ImportPlan, icon_source
from .hashing import _hasher, algo, file_hash
from .model import Asset, expand, to_token
from .naming import unique_name
from .thumbnail import make_thumb


def _copy_and_hash(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    h = _hasher(algo())
    with src.open("rb") as fin, dst.open("wb") as fout:
        while True:
            chunk = fin.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            fout.write(chunk)
    shutil.copystat(src, dst)
    return f"{algo()}:{h.hexdigest()}"


def same_volume(src: Path, dst_parent: Path) -> bool:
    """Can `src` be renamed into `dst_parent` rather than copied?

    The destination usually does not exist yet, so the nearest existing parent
    is the one asked.
    """
    probe = Path(dst_parent)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return os.stat(src).st_dev == os.stat(probe).st_dev
    except OSError:
        return False


def _place_and_hash(src: Path, dst: Path, move: bool = False) -> tuple:
    """Put one file in the package. Returns (digest, source_consumed).

    A move within one volume is a rename: instant, and it needs no second copy
    of a 12 GB texture set to exist while the import runs. Hashing then costs
    one read of the destination - still about half the I/O of a copy, which
    reads and writes every byte.

    Across volumes there is no rename, so the bytes are copied and hashed as
    usual and the source is left for the caller to remove LATER - never before
    the package is complete.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if move and same_volume(src, dst.parent):
        os.replace(src, dst)
        return file_hash(dst), True
    return _copy_and_hash(src, dst), False


def _convert_normal_dx_to_gl(path: Path) -> bool:
    """Invert the green channel in place. Exact and reversible."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return False
    try:
        with Image.open(path) as im:
            bands = im.convert("RGB").split()
            flipped = Image.merge("RGB", (bands[0], ImageChops.invert(bands[1]), bands[2]))
            flipped.save(path)
        return True
    except Exception:
        return False




def bind(asset: Asset, dest: str, slot=None, lod=None, udim=None) -> None:
    """Point asset.json at one file that now lives at `dest` inside the package.

    Shared by commit (creating) and edit (mutating) so there is exactly one
    description of what asset.json says about a file. Two implementations would
    drift, and the whole design rests on asset.json being the truth.

    A tile binds the WHOLE set: the ten files of a UDIM basecolor produce one
    pointer at `…_basecolor.<UDIM>.exr` plus the tile list, not ten pointers of
    which the last one silently wins.
    """
    if udim:
        dest = to_token(dest, udim)
        tiles = asset.udim.setdefault(dest, [])
        if int(udim) not in tiles:
            tiles.append(int(udim))
            tiles.sort()

    if lod:
        # LOD-tagged files are recorded per level, so an adapter can build a
        # detail switch without parsing filenames.
        level = asset.lods.setdefault(str(lod), {"geo": None, "textures": {}})
        if slot:
            level["textures"][slot] = dest
        elif dest.startswith("geo/"):
            level["geo"] = dest
        return

    if slot:
        asset.textures[slot] = dest
    elif dest.startswith("geo/") or "/" not in dest:
        # A file at the package root is the primary of a single-file type
        # (area.ies). Without this nothing in asset.json points at it and an
        # adapter would have to guess the filename - which is the one thing
        # the library exists to make unnecessary.
        asset.representations.append(
            {"file": dest, "format": Path(dest).suffix.lstrip("."),
             "role": "primary" if not asset.representations else "exchange"}
        )


def fallback_icon(asset: Asset, asset_dir: Path):
    """What to render the icon from when nothing was chosen explicitly.

    The basecolor for a texture set - and otherwise the asset's own primary
    file, because for a whole class of types the asset IS an image: an HDRI is
    an equirect, and types.json asks for exactly that to be tone-mapped. Looking
    only at the diffuse slot left every HDRI without an icon.

    Returns a path even when nothing can decode it (a .fbx, say); make_thumb
    reports that harmlessly rather than us second-guessing the decoder here.

    A tiled basecolor is resolved to its first tile: the binding names the set
    with a <UDIM> token, which is not a file, so stat-ing it directly would
    leave every UDIM asset without an icon.
    """
    base = asset.textures.get("diffuse")
    if base:
        for rel in expand(asset, base):
            if (asset_dir / rel).is_file():
                return asset_dir / rel
    for entry in asset.representations:
        candidate = asset_dir / entry.get("file", "")
        if candidate.is_file():
            return candidate
    return None


def _promote_hero_lod(asset: Asset) -> None:
    """Mirror the finest level into the top-level fields.

    Everything that reads an asset - the browser, a future Houdini adapter -
    should get the best version without knowing LODs exist. `lods` still holds
    every level including this one, so nothing is hidden and nothing is copied
    on disk; only the pointers are duplicated.
    """
    if not asset.lods:
        return
    hero = asset.lods[min(asset.lods, key=lambda k: int(k))]
    if not asset.textures:
        asset.textures.update(hero.get("textures") or {})
    if not asset.representations and hero.get("geo"):
        asset.representations.append(
            {"file": hero["geo"], "format": Path(hero["geo"]).suffix.lstrip("."),
             "role": "primary"}
        )


def commit(plan: ImportPlan, cfg, tags=None, dry_run: bool = False,
           move: bool = False) -> Path:
    """Build the package. With `move`, the source files are consumed.

    Moving is opt-in per import and never the default, because it breaks the
    promise the rest of the design makes - that a source sits untouched until
    you clear it yourself. What it buys is real: on one volume the files are
    renamed, so importing a 12 GB scan costs no transient second copy.
    """
    if not plan.category:
        raise ValueError("plan has no category - a category from the closed list is required")
    if not cfg.valid_category(plan.type_id, plan.category):
        raise ValueError(
            f"{plan.category!r} is not a valid category for {plan.type_id!r}: "
            + ", ".join(cfg.categories_for(plan.type_id))
        )
    if not plan.kept:
        raise ValueError("plan keeps no files")

    tdef = cfg.type_by_id[plan.type_id]
    parent = cfg.library / tdef["folder"] / plan.category
    name = unique_name(plan.name, parent)
    asset_dir = parent / name

    if dry_run:
        return asset_dir

    parent.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir()

    asset = Asset.new(name=name, type_id=plan.type_id, category=plan.category)
    asset.tags = sorted(set(tags or []))
    asset.fields = dict(plan.fields)
    asset.origin = {"source": str(plan.source), "source_name": plan.source.name}

    # Never consume something already inside the library: that would be moving
    # an asset's files out of another asset.
    if move and any(_inside(a.src, cfg.library) for a in plan.kept):
        raise ValueError("refusing to move files that are already in the library")

    preview_keep = icon_source(plan)
    consumed = []
    for action in plan.kept:
        if action.action == "preview":
            continue                      # the icon is rendered, not copied
        dst = asset_dir / action.dest
        # The icon is rendered from its source AFTER this loop, so a file that
        # is both a texture and the icon must not be moved out from under it.
        take = move and action.src != preview_keep
        asset.hashes[action.dest], gone = _place_and_hash(action.src, dst, take)
        if take and not gone:
            consumed.append(action.src)
        bind(asset, action.dest, action.slot, action.lod, action.udim)

    _promote_hero_lod(asset)

    # Normals: the library stores OpenGL only. If a source supplied DirectX and
    # nothing else, convert so every asset in the library is uniform.
    for warning in plan.warnings:
        if warning.startswith("normal:") and "converted" in warning:
            target = asset.textures.get("normal")
            # Every tile, not just the binding: a UDIM normal set has to be
            # flipped file by file or the levels disagree with each other.
            if target and all(_convert_normal_dx_to_gl(asset_dir / rel)
                              for rel in expand(asset, target)):
                asset.fields["normal_converted_from"] = "directx"

    asset.fields.setdefault("normal_convention", "opengl" if "normal" in asset.textures else None)

    thumb = asset_dir / "preview" / "thumb.jpg"
    preview_src = icon_source(plan) or fallback_icon(asset, asset_dir)
    if preview_src and Path(preview_src).exists():
        make_thumb(Path(preview_src), thumb)

    (asset_dir / "derived").mkdir(exist_ok=True)
    if move:
        asset.origin["moved"] = True
    asset.write(asset_dir)

    # LAST, and only now: the package is complete on disk, so a cross-volume
    # move can finally drop the originals it already copied and hashed. Any
    # failure before this point leaves every source file where it was.
    for path in consumed:
        try:
            path.unlink()
        except OSError:
            pass
    return asset_dir


def _inside(path: Path, root: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
