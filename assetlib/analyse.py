"""Analyse a source folder and produce an ImportPlan.

Strictly read-only: nothing outside this module's return value is written. The
plan says exactly which files would be kept, which rejected and why, and how big
the asset becomes. Committing it is a separate, explicit step.

Types come from config. The *precedence* between them is code, because it
encodes real knowledge no extension list can: a folder holding an .fbx AND a
dozen PNGs is a model with textures, not a texture set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .model import UDIM_TOKEN, res_label, res_width, to_token
from .naming import guess_category, normalise, split_lod, split_variant
from .slots import PREVIEW, SlotMatcher

JUNK_EXTS = {".exe", ".msi", ".url", ".lnk", ".ini", ".db"}
# Formats that DESCRIBE an asset rather than being one. ambientCG ships a 2.5KB
# .usdc next to its textures; counting that as geometry would classify a texture
# set as a model. They never decide a type on their own.
SIDECAR_EXTS = {".mtlx", ".mtl", ".usd", ".usda", ".usdc", ".usdz"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".exr", ".hdr", ".bmp", ".webp"}


@dataclass
class FileAction:
    src: Path
    action: str           # keep | preview | bonus | reject
    dest: str | None = None   # path relative to the asset folder
    slot: str | None = None
    lod: int | None = None    # level of detail, None when the asset has none
    udim: str | None = None   # "1001" when this file is one tile of a set
    res: str | None = None    # "4k" when the slot holds more than one size
    variant: str | None = None  # "big"/"small" - a second version to KEEP
    reason: str = ""
    size: int = 0

    @property
    def kept(self) -> bool:
        return self.action in ("keep", "preview", "bonus")


@dataclass
class ImportPlan:
    source: Path
    name: str
    type_id: str
    category: str | None
    actions: list = field(default_factory=list)
    fields: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    # Which file the icon is rendered FROM. Deliberately not a binding: a
    # basecolor can be the icon and still be the basecolor. Only a file whose
    # sole purpose is the icon gets bound with action "preview".
    preview_src: Path | None = None

    @property
    def kept(self):
        return [a for a in self.actions if a.kept]

    @property
    def rejected(self):
        return [a for a in self.actions if a.action == "reject"]

    @property
    def size_in(self) -> int:
        return sum(a.size for a in self.actions)

    @property
    def size_out(self) -> int:
        return sum(a.size for a in self.kept)

    @property
    def ready(self) -> bool:
        return bool(self.category) and bool(self.kept)

    def rel(self, path: Path) -> str:
        """Path inside the package. Files picked by hand can live anywhere on
        disk, so a file outside `source` keeps its bare name - a destination is
        never allowed to be absolute."""
        try:
            return str(path.relative_to(self.source)).replace(chr(92), "/")
        except ValueError:
            return path.name


# --------------------------------------------------------------------- helpers


def _walk(root: Path) -> list:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(("__MACOSX", "."))]
        for fn in filenames:
            out.append(Path(dirpath) / fn)
    return out


def _image_size(path: Path):
    """Delegated so EXR and HDR measure correctly, not just what Pillow reads."""
    from .thumbnail import dimensions

    return dimensions(path)


def _measured_label(path: Path) -> str:
    """The resolution label for one texture file, read from the pixels.

    Not from the filename. Megascans writes `_16384ppm`, which is pixels per
    metre and says nothing certain about the image; ambientCG writes `8K` and
    Poly Haven `8k` for the same thing. slots.py has already stripped whichever
    token was there, so the only honest source left is the header.

    A file that cannot be measured gets an empty label, which groups every
    unmeasurable file of a slot together and lets the format contest settle it
    exactly as it did before resolutions existed.
    """
    size = _image_size(path)
    return res_label(max(size)) if size else ""


def mesh_extensions(cfg) -> set:
    """Extensions that make a file geometry.

    Sidecars are excluded: the 2.5 KB .usdc ambientCG ships next to its textures
    describes them, it is not a mesh. One definition, used by both the type
    detector and the name deriver - the library must not have two ideas about
    what counts as a 3D object.
    """
    out = set()
    for tid in ("model", "scan", "vegetation"):
        out |= {
            e.lower()
            for e in cfg.type_by_id[tid]["primary_ext"]
            if e.lower() not in IMAGE_EXTS
        }
    return out - SIDECAR_EXTS


def detect_type(files, cfg, matcher: SlotMatcher, asset_base: str) -> str:
    exts = {f.suffix.lower() for f in files}
    images = [f for f in files if f.suffix.lower() in IMAGE_EXTS]
    slot_hits = set()
    for f in images:
        key, _, _ = matcher.match(f.name, asset_base)
        if key and key != PREVIEW:
            slot_hits.add(key)

    has_mesh = bool(mesh_extensions(cfg) & exts)

    for t in cfg.types:
        tid = t["id"]
        if tid == "unknown":
            continue
        prim = {e.lower() for e in t.get("primary_ext", [])}
        if not prim & exts:
            continue

        # A texture set cannot contain geometry - that makes it a model.
        if t["ingest"] == "texture_set":
            if has_mesh or len(slot_hits) < matcher.min_slots:
                continue
        # HDRI needs a real .hdr, or a lone equirectangular EXR.
        if tid == "hdri" and ".hdr" not in exts:
            lone = [f for f in images if f.suffix.lower() == ".exr"]
            if len(lone) != 1 or slot_hits:
                continue
            size = _image_size(lone[0])
            if not size or abs(size[0] / max(size[1], 1) - 2.0) > 0.1:
                continue
        return tid

    return "unknown"


# -------------------------------------------------------------------- analysis


def analyse(source: Path, cfg, type_hint: str | None = None,
            category_hint: str | None = None, files=None,
            name_hint: str | None = None) -> ImportPlan:
    """Plan the import of ONE asset.

    `files` and `name_hint` exist for the scanner: a folder can hold a dozen
    assets side by side, and such a candidate cannot be described by its parent
    directory alone - walking it would swallow its siblings. When `files` is
    given, `source` is only the base that relative paths are resolved against.
    """
    source = Path(source).resolve()
    if not source.is_dir():
        raise NotADirectoryError(f"{source} is not a folder")

    files = _walk(source) if files is None else [Path(f) for f in files]
    if not files:
        raise ValueError(f"{source} contains no files")

    matcher = SlotMatcher(cfg)
    name = normalise(name_hint or source.name, cfg)
    type_id = type_hint or detect_type(files, cfg, matcher, name)
    if type_id not in cfg.type_by_id:
        raise ValueError(f"unknown type {type_id!r}")

    category = category_hint or guess_category(source.name, type_id, cfg)
    plan = ImportPlan(source=source, name=name, type_id=type_id, category=category)

    if category and not cfg.valid_category(type_id, category):
        plan.warnings.append(
            f"category {category!r} is not in the closed vocabulary for type "
            f"{type_id!r}: {', '.join(cfg.categories_for(type_id))}"
        )
        plan.category = None

    strategy = cfg.type_by_id[type_id]["ingest"]
    if strategy == "texture_set":
        _plan_texture_set(plan, files, cfg, matcher)
    else:
        _plan_generic(plan, files, cfg, matcher, strategy)

    if not plan.category:
        plan.warnings.append(
            "no category - pick one from: " + ", ".join(cfg.categories_for(type_id))
        )
    return plan


def _reject_junk(plan: ImportPlan, path: Path, size: int) -> bool:
    ext = path.suffix.lower()
    if ext in JUNK_EXTS:
        plan.actions.append(FileAction(path, "reject", reason="not an asset file", size=size))
        return True
    if ext in ARCHIVE_EXTS:
        plan.actions.append(
            FileAction(path, "reject", reason="archive - extract it into _inbox instead", size=size)
        )
        return True
    return False


# ------------------------------------------------------- destinations, by hand

BONUS_REASON = "kept verbatim, not interpreted"

# What a file may be bound to. Anything the library does not understand becomes
# a bonus file rather than being thrown away - the user decides, not the tool.
SKIP, BONUS, PREVIEW_TARGET, PRIMARY = "skip", "bonus", "preview", "primary"
# Geometry is its own target, on every type. PRIMARY used to carry this job
# and only for mesh types, so an .obj dropped into a texture asset could only
# be sent to the package root or to extra/ - never to geo/, where it belongs.
GEOMETRY = "geometry"


def derived_exts(tdef: dict, cfg) -> set:
    """What counts as a regenerable bake for this type: the global set plus its own.

    Global, like `geometry_ext`, because the two answer the same shape of
    question: a `.rat` is a mip-mapped bake wherever it is found, and which
    asset it happens to sit beside says nothing about that. Declared per type,
    only `texture` ever declared it - so a `.rat` beside an HDRI or a Megascans
    mesh went to `extra/`, which is the part of the package that is KEPT, while
    `derived/` is defined as deletable. Exactly backwards, and silent.

    Unioned rather than overridden so a type can still add a format nothing
    else bakes, without having to restate the common ones.
    """
    return cfg.derived_ext | {e.lower() for e in (tdef.get("derived_ext") or [])}


def bonus_action(plan: ImportPlan, path: Path, size: int, why: str = "",
                 udim: str | None = None) -> FileAction:
    reason = BONUS_REASON if not why else why + " - " + BONUS_REASON
    return FileAction(path, "bonus", dest=f"extra/{plan.rel(path)}", size=size,
                      reason=reason, udim=udim)


def set_key(action: FileAction):
    """What makes two files the same UDIM set, or None if this is a lone file.

    Same job, same destination once the tile is taken out. Used to show ten
    tiles as one row rather than ten - and to rebind them together, since
    changing a set one tile at a time is not an operation anyone wants.
    """
    if not action.udim or not action.dest:
        return None
    return (action.action, action.slot, action.lod,
            to_token(action.dest, action.udim))


def current_target(action: FileAction) -> str:
    """Which entry of targets_for() this action currently represents."""
    if action.action == "reject":
        return SKIP
    if action.action == "bonus":
        return BONUS
    if action.action == "preview":
        return PREVIEW_TARGET
    if action.slot:
        return action.slot
    return GEOMETRY if (action.dest or "").startswith("geo/") else PRIMARY


def targets_for(plan: ImportPlan, cfg) -> list:
    """(value, label) pairs offered for one file, in menu order."""
    tdef = cfg.type_by_id[plan.type_id]
    out = [(GEOMETRY, "geometry -> geo/")]
    # A mesh type's "main file" IS its geometry, so offering both would be two
    # names for one destination. Every other type keeps a main file that is not
    # a mesh - an .ies profile, an .hdr, a ZBrush .psd - and needs the entry.
    if tdef["ingest"] != "mesh_plus_textures":
        out.append((PRIMARY, "main file"))
    out += [
        (PREVIEW_TARGET, "preview image"),
        (BONUS, "bonus file -> extra/"),
        (SKIP, "skip - do not copy"),
    ]
    out += [(s["key"], "texture: " + s["key"]) for s in SlotMatcher(cfg).slots]
    return out


def rebind(plan: ImportPlan, action: FileAction, target: str, cfg) -> None:
    """Send one file somewhere else. The only place a destination is computed.

    Called when the user overrides a row. Slot names, folder layout and the
    format of an output filename stay owned by config, exactly as they are on
    the automatic path - a hand-placed file lands where an auto-placed one would.
    """
    matcher = SlotMatcher(cfg)
    action.reason = ""

    # Only a texture slot keeps a tile. Sending a file to extra/, to the icon or
    # to the main-file spot means the tile is no longer part of its identity, so
    # it must be cleared - otherwise bind() would record a UDIM set for a
    # destination whose name has no tile in it.
    action.udim = None

    # The size token survives only into another texture slot, and for the same
    # reason. It also has to survive INTO one: rebinding one of four sizes to a
    # different slot without it would compute the same destination as the other
    # three, and conflicts() would block the whole import over a rename the
    # user thought was local.
    res, action.res = action.res, None
    # Variant follows the same rule as the size token: it is part of a kept
    # file's identity and meaningless once the file is bonus, icon or skipped.
    variant, action.variant = action.variant, None

    if target == SKIP:
        action.action, action.dest, action.slot = "reject", None, None
        action.reason = "skipped by hand"
    elif target == BONUS:
        action.action, action.slot = "bonus", None
        action.dest = f"extra/{plan.rel(action.src)}"
        action.reason = BONUS_REASON
    elif target == PREVIEW_TARGET:
        action.action, action.slot, action.dest = "preview", None, "preview/thumb.jpg"
    elif target in (PRIMARY, GEOMETRY):
        tdef = cfg.type_by_id[plan.type_id]
        folder = "geo/" if (target == GEOMETRY
                            or tdef["ingest"] == "mesh_plus_textures") else ""
        level = f"_lod{action.lod}" if action.lod else ""
        which = f"_{variant}" if variant else ""
        action.action, action.slot, action.variant = "keep", None, variant
        action.dest = f"{folder}{plan.name}{which}{level}{action.src.suffix.lower()}"
    else:
        if target not in matcher.by_key:
            raise ValueError(f"unknown target {target!r}")
        _, udim, _ = matcher.match(action.src.name, plan.name)
        action.action, action.slot, action.udim = "keep", target, udim
        action.res = res
        action.dest = "tex/" + matcher.output_filename(
            plan.name, target, action.src.suffix.lower(), udim, action.lod, res
        )


def _record_lods(plan: ImportPlan) -> None:
    levels = sorted({a.lod for a in plan.kept if a.lod})
    if levels:
        plan.fields["lods"] = levels


def _record_resolutions(plan: ImportPlan) -> None:
    """Both resolution fields, for every planner.

    This lived inside the texture-set planner and nothing else called it, so a
    model or a scan - which is most of this library, and every Megascans plant -
    came out with no resolution metadata at all and answered no `res:` query.
    Anything true of every asset belongs beside _record_lods, not inside one
    branch.

    `resolution` is the single biggest width: the index wants one sortable
    scalar. `resolutions` is the set, and `res:4k` asks of it "is this one of
    them", never "is it the largest".
    """
    base = next((a for a in plan.kept if a.slot == "diffuse"), None)
    if base:
        size = _image_size(base.src)
        if size:
            plan.fields["resolution"] = max(size)

    sizes = {a.res for a in plan.kept if a.slot and a.res}
    if not sizes and plan.fields.get("resolution"):
        # One size, so no token was ever assigned - but the asset still has a
        # resolution and must still be findable by it.
        sizes = {res_label(plan.fields["resolution"])}
    if sizes:
        plan.fields["resolutions"] = sorted(sizes, key=res_width, reverse=True)


def set_variant(plan: ImportPlan, action: FileAction, variant, cfg) -> None:
    """Name this file's variant by hand, or clear it.

    Normalised through the same rules as everything else, so a typed 'Big ' and
    a detected 'big' cannot become two variants of one asset. Goes through
    rebind() rather than patching the destination, exactly like set_lod.
    """
    variant = normalise(str(variant), cfg) if variant else None
    action.variant = variant or None
    rebind(plan, action, current_target(action), cfg)


def set_lod(plan: ImportPlan, action: FileAction, lod, cfg) -> None:
    """Move a file to a different level of detail.

    The destination is recomputed through rebind() rather than patched, so a
    hand-set level produces exactly the filename an auto-detected one would.
    """
    action.lod = int(lod) if lod else None
    rebind(plan, action, current_target(action), cfg)


def icon_source(plan: ImportPlan):
    """The file preview/thumb.jpg should be rendered from, or None.

    An explicit choice wins over anything the planner found on its own, and it
    does NOT have to be a file bound to `preview` - picking the basecolor as the
    icon must leave the basecolor exactly where it was.
    """
    if plan.preview_src is not None:
        return plan.preview_src
    return next((a.src for a in plan.kept if a.action == "preview"), None)


def conflicts(plan: ImportPlan) -> list:
    """Destinations claimed by more than one file.

    Two files bound to the same slot would have one silently overwrite the
    other during commit - the exact bug the NormalDX/NormalGL collision was.
    """
    seen: dict = {}
    for a in plan.kept:
        if a.dest:
            seen.setdefault(a.dest, []).append(a.src.name)
    return [(dest, names) for dest, names in seen.items() if len(names) > 1]


# ------------------------------------------------------------- naming the set


def _shared_stem(paths) -> str:
    """The part of the name every one of these files agrees on.

    Takes stems, not paths - callers strip the LOD token first.

    A texture set names itself in its own prefix: the twelve ambientCG files all
    start with 'Concrete014_8K-PNG_' and differ only in the slot suffix. Taking
    the common prefix strips the slot without needing to know a single keyword,
    and normalise() then removes the 8K/PNG tokens - so the whole set is called
    'concrete014', which is what a 4K version of it will be called too.
    """
    if len(paths) == 1:
        return paths[0]
    prefix = os.path.commonprefix(paths).rstrip(" _-.")
    return prefix if len(prefix) >= 3 else paths[0]


MIN_DERIVED_NAME = 4


def _bare_stem(path: Path, cfg, matcher: SlotMatcher) -> str:
    """A filename with both extra dimensions removed: the UDIM tile and the LOD.

    Both are properties OF the asset, not part of its name, so they must come
    off before the files are asked what they have in common.
    """
    stem, _ = matcher._clean_stem(path.name)
    # Variant off as well as LOD: two variants are ONE asset, so both have to
    # resolve to one name. Without this an asset shipping only Big would be
    # called '..._big', and the day its Small arrived it would import as a
    # second, unrelated asset.
    return split_variant(split_lod(stem, cfg)[0], cfg)[0]


def _settle_name(candidate: str, files, cfg) -> str:
    """Fall back to the enclosing folder when the shared prefix says nothing.

    TexturingXYZ names its maps `XYZ_albedo_…` and `XYZ_dispCalibrated_…`, which
    agree on exactly 'XYZ' - so the set called itself 'xyz'. The folder they came
    from, 'TexturingXYZFemale', identifies the asset far better than three
    letters of vendor prefix.
    """
    if len(candidate) >= MIN_DERIVED_NAME:
        return candidate
    parents = {f.parent for f in files}
    if len(parents) == 1:
        folder = normalise(next(iter(parents)).name, cfg)
        if len(folder) >= MIN_DERIVED_NAME:
            return folder
    return candidate


def derive_name(files, cfg, type_id: str | None = None) -> str:
    """Name the asset after the file that best identifies it.

    Priority: a 3D object, then a texture, then anything else. A mesh names its
    asset far better than one of its twelve maps does, and a preview render
    names it not at all - so images only count when they match a real slot.
    """
    candidates = [f for f in files
                  if f.suffix.lower() not in JUNK_EXTS | ARCHIVE_EXTS]
    if not candidates:
        return ""

    matcher = SlotMatcher(cfg)

    # 1. a 3D object. LOD1 and LOD4 are one asset, so the token comes off
    # before the name is taken - otherwise four levels look like four assets.
    meshes = [f for f in candidates if f.suffix.lower() in mesh_extensions(cfg)]
    if meshes:
        stems = sorted(_bare_stem(f, cfg, matcher) for f in meshes)
        return _settle_name(normalise(_shared_stem(stems), cfg), candidates, cfg)

    # 2. a texture - previews and unmatched images do not name anything
    textures = []
    for f in candidates:
        if f.suffix.lower() not in IMAGE_EXTS:
            continue
        key, _, _ = matcher.match(f.name)
        if key and key != PREVIEW:
            textures.append(f)
    if textures:
        stems = [_bare_stem(f, cfg, matcher) for f in textures]
        return _settle_name(normalise(_shared_stem(stems), cfg), candidates, cfg)

    # 3. anything else, preferring what the declared type calls its main file
    if type_id and type_id in cfg.type_by_id:
        primary = {e.lower() for e in cfg.type_by_id[type_id].get("primary_ext", [])}
        for f in candidates:
            if f.suffix.lower() in primary:
                return _settle_name(
                    normalise(_bare_stem(f, cfg, matcher), cfg), candidates, cfg)
    return _settle_name(
        normalise(_bare_stem(candidates[0], cfg, matcher), cfg), candidates, cfg)


def _settle_competing(plan: ImportPlan, key: str, entries: list,
                      matcher: SlotMatcher) -> list:
    """When two DIFFERENT maps claim one slot, keep one and bank the rest.

    TexturingXYZ ships `dispCalibrated` and `dispMultiChannel` side by side and
    both match the `disp` keyword. Without this they fight for the same
    destination - and once UDIM is understood that is not one clash but one per
    tile, which blocks the import outright.

    Grouped by the name the files share once the tile is stripped, so the ten
    tiles of one map stay together. The loser is NOT discarded: it goes to
    extra/ verbatim, and a row in the table can rebind it to a real slot.
    """
    groups: dict = {}
    for entry in entries:
        stem, _ = matcher._clean_stem(entry[0].name)
        groups.setdefault(stem, []).append(entry)
    if len(groups) < 2:
        return entries

    def rank(item):
        stem, group = item
        # best format, then the most complete set, then alphabetical so the
        # same folder always resolves the same way.
        return (max(matcher.format_rank(key, e[4]) for e in group),
                len(group), [-ord(c) for c in stem])

    winner, *losers = sorted(groups.items(), key=rank, reverse=True)
    for stem, group in losers:
        for path, size, udim, _, _ in group:
            plan.actions.append(bonus_action(
                plan, path, size,
                f"a second '{key}' map in this set ({stem})", udim))
    plan.warnings.append(
        f"{key}: {len(groups)} different maps matched this slot - kept "
        f"'{winner[0]}', the rest went to extra/ (rebind a row to change that)")
    return winner[1]


def _emit_slot_actions(plan: ImportPlan, candidates: dict, matcher: SlotMatcher) -> set:
    """One file per slot, in the winning variant and format.

    Shared by the texture-set and mesh planners so a model's textures obey
    exactly the same rules as a standalone texture set - the library must not
    have two ideas about what a normal map is called.
    """
    for (key, lod), entries in candidates.items():
        wanted = matcher.keep_variant(key)
        if wanted:
            preferred = [e for e in entries if e[3] == wanted]
            if preferred:
                for path, size, _, variant, _ in entries:
                    if variant != wanted:
                        plan.actions.append(
                            FileAction(path, "reject", size=size,
                                       reason=f"{variant or 'unknown'} variant - library stores {wanted} only, "
                                              f"regenerated on demand")
                        )
                entries = preferred
            elif entries and entries[0][3]:
                plan.warnings.append(
                    f"{key}: only a {entries[0][3]} variant supplied; it will be converted to {wanted} at commit"
                )

        entries = _settle_competing(plan, key, entries, matcher)

        # One map, possibly at several sizes. Split by MEASURED width, never by
        # the filename token: Megascans writes ppm (pixels per metre), ambientCG
        # writes 8K, Poly Haven writes 8k, and none of them is a promise about
        # the pixels. slots.py has already stripped whatever the token was.
        by_res: dict = {}
        for entry in entries:
            by_res.setdefault(_measured_label(entry[0]), []).append(entry)

        # A single size gets no token at all, exactly like an asset with no
        # LODs gets no _lodN - so nothing already in the library renames.
        multi = len(by_res) > 1
        if multi:
            plan.warnings.append(
                f"{key}: {len(by_res)} resolutions kept ("
                + ", ".join(sorted(by_res, key=res_width, reverse=True)) + ")"
            )

        for res, group in sorted(by_res.items(), key=lambda kv: res_width(kv[0]), reverse=True):
            token = res if multi else None

            # UDIM tiles are all kept; a non-tiled slot keeps one winning format.
            tiled = [e for e in group if e[2]]
            if tiled:
                for path, size, udim, _, ext in tiled:
                    plan.actions.append(
                        FileAction(path, "keep", slot=key, lod=lod, size=size, udim=udim,
                                   res=token,
                                   dest="tex/" + matcher.output_filename(
                                       plan.name, key, ext, udim, lod, token))
                    )
                continue

            group.sort(key=lambda e: matcher.format_rank(key, e[4]), reverse=True)
            path, size, _, _, ext = group[0]
            plan.actions.append(
                FileAction(path, "keep", slot=key, lod=lod, size=size, res=token,
                           dest="tex/" + matcher.output_filename(
                               plan.name, key, ext, None, lod, token))
            )
            where = f" of lod{lod}" if lod else ""
            at = f" at {res}" if multi else ""
            for path, size, _, _, ext in group[1:]:
                plan.actions.append(
                    FileAction(path, "reject", size=size, lod=lod,
                               reason=f"duplicate of slot '{key}'{where}{at} "
                                      f"in a lower-priority format ({ext})")
                )

    # Packed maps are redundant once the unpacked ones are present - decided
    # per level, because LOD2 may ship an ORM while LOD1 ships them unpacked.
    by_lod: dict = {}
    for a in plan.kept:
        if a.slot:
            by_lod.setdefault(a.lod, set()).add(a.slot)
    for lod, slots in by_lod.items():
        if "orm" in slots and {"ao", "roughness"} <= slots:
            for a in plan.actions:
                if a.slot == "orm" and a.lod == lod and a.action == "keep":
                    a.action, a.dest = "reject", None
                    a.reason = "packed map redundant - unpacked ao + roughness already present"
            slots.discard("orm")
    return {s for slots in by_lod.values() for s in slots}


def _plan_texture_set(plan: ImportPlan, files, cfg, matcher: SlotMatcher) -> None:
    discard = {
        e.lower() for e in cfg.slots_cfg.get("discard_on_import", {}).get("extensions", [])
    }
    derived = derived_exts(cfg.type_by_id[plan.type_id], cfg)

    candidates: dict = {}
    previews: list = []
    seen_geo: dict = {}

    for path in files:
        size = path.stat().st_size
        if _reject_junk(plan, path, size):
            continue
        ext = path.suffix.lower()
        if ext in discard:
            plan.actions.append(
                FileAction(path, "reject", size=size,
                           reason="vendor-authored, references the original filenames - regenerated into derived/")
            )
            continue

        # Baked textures, same rule and same reason as the generic planner.
        # This branch was missing here entirely, so a .rat beside a texture set
        # fell through to `ext not in IMAGE_EXTS` and became a bonus file in
        # extra/ - even though `texture` is the ONE type that declared
        # derived_ext. The declaration was real and nothing read it.
        if ext in derived:
            plan.actions.append(
                FileAction(path, "keep", dest=f"derived/{path.name}", size=size,
                           reason="baked, regenerable - stored in derived/")
            )
            continue

        # A texture set is not supposed to contain geometry - that is what
        # makes something a model - but this planner also runs when the TYPE
        # was declared by hand, and a hand-declared texture asset holding an
        # .obj should still put it in geo/ rather than burying it in extra/.
        # Same routing rule as the generic planner, so the two cannot disagree
        # about what a mesh is.
        if ext in cfg.geometry_ext:
            stem_no_lod, lod = split_lod(path.stem, cfg)
            _, variant = split_variant(stem_no_lod, cfg)
            if (ext, lod, variant) in seen_geo:
                where = f" for lod{lod}" if lod else ""
                which = f" of variant {variant}" if variant else ""
                plan.actions.append(
                    FileAction(path, "reject", size=size, lod=lod, variant=variant,
                               reason=f"second {ext} file{where}{which} - "
                                      "one file per format per level")
                )
                continue
            seen_geo[(ext, lod, variant)] = path
            level = f"_lod{lod}" if lod else ""
            which = f"_{variant}" if variant else ""
            plan.actions.append(
                FileAction(path, "keep", dest=f"geo/{plan.name}{which}{level}{ext}",
                           size=size, lod=lod, variant=variant)
            )
            continue

        if ext not in IMAGE_EXTS:
            plan.actions.append(bonus_action(plan, path, size))
            continue

        key, udim, variant = matcher.match(path.name, plan.name)
        if key == PREVIEW:
            previews.append((path, size))
            continue
        if key is None:
            plan.actions.append(bonus_action(plan, path, size, "no slot matched"))
            continue
        _, lod = split_lod(path.stem, cfg)
        candidates.setdefault((key, lod), []).append((path, size, udim, variant, ext))

    kept_slots = _emit_slot_actions(plan, candidates, matcher)

    # --- preview -----------------------------------------------------------
    if previews:
        previews.sort(key=lambda p: p[1], reverse=True)
        path, size = previews[0]
        plan.actions.append(FileAction(path, "preview", dest="preview/thumb.jpg", size=size))
        for path, size in previews[1:]:
            plan.actions.append(FileAction(path, "reject", reason="extra preview image", size=size))
    else:
        plan.warnings.append("no preview image - thumb.jpg will be generated from basecolor")

    # --- metadata ----------------------------------------------------------
    _record_resolutions(plan)
    plan.fields["slots_present"] = sorted(s for s in kept_slots if s)
    plan.fields["udim"] = any("." in Path(a.dest).stem for a in plan.kept if a.dest and a.slot)
    _record_lods(plan)


def _plan_generic(plan: ImportPlan, files, cfg, matcher: SlotMatcher, strategy: str) -> None:
    """Meshes, single files and folder_blob.

    Geometry keeps its extension and is renamed to the asset name; textures
    found alongside are slotted exactly as in a texture set; anything we do not
    understand is preserved verbatim under extra/.
    """
    tdef = cfg.type_by_id[plan.type_id]
    primary = {e.lower() for e in tdef.get("primary_ext", [])}
    derived = derived_exts(tdef, cfg)
    seen_primary: dict = {}
    candidates: dict = {}
    previews: list = []

    for path in files:
        size = path.stat().st_size
        if _reject_junk(plan, path, size):
            continue
        ext = path.suffix.lower()
        stem_no_lod, lod = split_lod(path.stem, cfg)
        _, variant = split_variant(stem_no_lod, cfg)

        # Baked textures (.tex/.tx/.rat) are regenerable by definition - that
        # is what derived/ is for. Kept under their own names because nothing
        # downstream reads them by ours.
        if ext in derived:
            plan.actions.append(
                FileAction(path, "keep", dest=f"derived/{path.name}", size=size, lod=lod,
                           reason="baked, regenerable - stored in derived/")
            )
            continue

        # Geometry routes on the EXTENSION, never on the type's primary_ext.
        # Those answer different questions - what is a mesh, versus what makes
        # this type detectable - and merging them is what sent every .fbx in a
        # vegetation asset to extra/, since vegetation is declared by its
        # SpeedTree formats alone and knows nothing about .fbx.
        #
        # An image is otherwise a texture, never the asset itself - a .png
        # beside an .fbx is its basecolor. But for a single-file type the asset
        # IS the image: an HDRI is an equirect, a ZBrush alpha is a .psd.
        # Without that exception every HDRI fell through to extra/, so nothing
        # in asset.json pointed at it and it never got an icon.
        is_geo = ext in cfg.geometry_ext
        if (is_geo or ext in primary) and (ext not in IMAGE_EXTS
                                           or strategy == "single_file"):
            # Variant is part of the identity, so Big and Small no longer
            # fight over one key. Before this the second one lost and a whole
            # mesh set never imported.
            if (ext, lod, variant) in seen_primary:
                where = f" for lod{lod}" if lod else ""
                which = f" of variant {variant}" if variant else ""
                plan.actions.append(
                    FileAction(path, "reject", size=size, lod=lod, variant=variant,
                               reason=f"second {ext} file{where}{which} - "
                                      "one file per format per level")
                )
                continue
            seen_primary[(ext, lod, variant)] = path
            folder = "geo/" if (is_geo or strategy == "mesh_plus_textures") else ""
            level = f"_lod{lod}" if lod else ""
            which = f"_{variant}" if variant else ""
            plan.actions.append(
                FileAction(path, "keep", dest=f"{folder}{plan.name}{which}{level}{ext}",
                           size=size, lod=lod, variant=variant)
            )
            continue

        if ext in IMAGE_EXTS:
            key, udim, variant = matcher.match(path.name, plan.name)
            if key == PREVIEW:
                previews.append((path, size))
                continue
            if key:
                candidates.setdefault((key, lod), []).append((path, size, udim, variant, ext))
                continue

        plan.actions.append(bonus_action(plan, path, size))

    kept_slots = _emit_slot_actions(plan, candidates, matcher)

    if previews:
        previews.sort(key=lambda p: p[1], reverse=True)
        plan.actions.append(FileAction(previews[0][0], "preview", dest="preview/thumb.jpg",
                                       size=previews[0][1]))
        for path, size in previews[1:]:
            plan.actions.append(FileAction(path, "reject", reason="extra preview image", size=size))

    if strategy == "mesh_plus_textures" and not any(
            a.dest and a.dest.startswith("geo/") for a in plan.kept):
        plan.warnings.append("no geometry file found for a mesh asset")

    if kept_slots:
        plan.fields["slots_present"] = sorted(kept_slots)
    # `e, *_` because the key carries lod and variant too - it has grown twice
    # and a fixed-width unpack breaks silently at the next dimension.
    plan.fields["formats"] = sorted({e.lstrip(".") for e, *_ in seen_primary})
    _record_resolutions(plan)
    _record_lods(plan)
