"""asset.json - the source of truth for a single asset.

Everything else (index.db, thumbnails, derived/) is reconstructible from these
files. Keep the schema readable: it is meant to be opened in a text editor.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 6
ASSET_FILE = "asset.json"

# A UDIM set is ONE binding pointing at many files. asset.json stores the path
# with the tile replaced by this token - the spelling Houdini, Karma, Arnold and
# Mari all resolve natively - and the tiles that actually exist alongside it, so
# nothing has to glob the directory to find out.
UDIM_TOKEN = "<UDIM>"


def res_label(width) -> str:
    """2048 -> '2k'. A width that is not a clean multiple keeps its pixels.

    The label is what the user types into the search box, so it has to be the
    word they would have used: 'res:4k', never 'res:4096'. Vendors disagree
    about the token in the filename - Megascans writes 16384ppm, which is
    pixels-per-metre and not a pixel count at all - so the label is derived
    from the measured width and nothing else.
    """
    width = int(width or 0)
    if width <= 0:
        return ""
    return f"{width // 1024}k" if width % 1024 == 0 else str(width)


def res_width(label: str) -> int:
    """'2k' -> 2048. The inverse of res_label, for sorting biggest-first."""
    label = (label or "").strip().lower()
    if label.endswith("k") and label[:-1].isdigit():
        return int(label[:-1]) * 1024
    return int(label) if label.isdigit() else 0


@dataclass
class Asset:
    uuid: str
    name: str
    type: str
    category: str
    schema_version: int = SCHEMA_VERSION
    tags: list = field(default_factory=list)
    textures: dict = field(default_factory=dict)     # slot -> relative path
    representations: list = field(default_factory=list)
    lods: dict = field(default_factory=dict)         # "2" -> {geo, textures{}}
    udim: dict = field(default_factory=dict)         # token path -> [1001, 1002…]
    resolutions: dict = field(default_factory=dict)  # slot -> {'4k': rel, '8k': rel}
    fields: dict = field(default_factory=dict)       # type-specific metadata
    hashes: dict = field(default_factory=dict)       # relative path -> hash
    origin: dict = field(default_factory=dict)
    created: str = ""

    @classmethod
    def new(cls, name: str, type_id: str, category: str) -> "Asset":
        return cls(
            uuid=_uuid.uuid4().hex,
            name=name,
            type=type_id,
            category=category,
            created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    # ------------------------------------------------------------------- io

    def write(self, asset_dir: Path) -> Path:
        """Write asset.json ATOMICALLY: temp file beside it, then os.replace.

        Opening the real file for writing truncates it first, so an interruption
        - a crash, an external disk pulled out - leaves a half-written file.
        Since disk is the truth here, that is a DESTROYED asset rather than a
        stale one, and a bulk schema migration across thousands of packages is
        precisely the moment it would happen. os.replace is atomic on NTFS and
        POSIX alike, so the file is always either wholly old or wholly new.

        The temp file must share the directory: os.replace is only atomic within
        one filesystem.
        """
        path = Path(asset_dir) / ASSET_FILE
        data = asdict(self)
        ordered = {"schema_version": data.pop("schema_version"), **data}

        handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".asset-",
                                        suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                json.dump(ordered, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp, path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
        return path

    @classmethod
    def read(cls, asset_dir: Path) -> "Asset":
        path = Path(asset_dir) / ASSET_FILE
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        data = migrate(data)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def on_disk_version(asset_dir: Path):
    """The schema version written in the FILE, or None if it cannot be read.

    Deliberately not Asset.read(): the migration pass has to decide whether to
    touch a package at all, and building an object for every one of thousands of
    already-current assets is work done to learn nothing.
    """
    try:
        with (Path(asset_dir) / ASSET_FILE).open(encoding="utf-8") as fh:
            return int(json.load(fh).get("schema_version", 1))
    except Exception:                                # noqa: BLE001
        return None


def migrate(data: dict) -> dict:
    """Bring an older asset.json up to the current schema.

    Written before it is needed on purpose - the first time the schema changes
    across a library of thousands of assets is the wrong time to invent this.
    """
    version = data.get("schema_version", 1)
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"asset.json is schema v{version}, this build understands v{SCHEMA_VERSION}"
        )
    if version < 2:
        # v2 adds `lods`. An asset written before LODs existed simply has none,
        # and its top-level textures/representations stay exactly as they were.
        data.setdefault("lods", {})
        version = 2
    if version < 3:
        # v3 adds `udim`. Purely additive: an asset with no tiled textures has
        # an empty map and every existing path stays exactly as it was.
        data.setdefault("udim", {})
        version = 3
    if version < 4:
        # v4 adds `resolutions`. Additive for the same reason the hero LOD is
        # mirrored into the top level: `textures[slot]` keeps pointing at the
        # BEST size, so every existing reader - the browser, verify, the icon
        # picker, a future Houdini adapter - works without knowing that a
        # second dimension appeared. An asset that only ever had one size has
        # an empty map and not a single path changes.
        data.setdefault("resolutions", {})
        fields = data.get("fields") or {}
        if fields.get("resolution") and not fields.get("resolutions"):
            fields["resolutions"] = [res_label(fields["resolution"])]
            data["fields"] = fields
        version = 4
    if version < 5:
        # v5 gives each LOD level a `representations` LIST, the same shape the
        # top level has always had. `lods[N]["geo"]` was a single string, so a
        # level shipping both .fbx and .obj bound one and silently overwrote
        # the other - both files on disk, one with nothing pointing at it, and
        # no conflict because the two destinations differed.
        #
        # `geo` stays, still naming the primary, so every existing reader is
        # untouched. An asset with one format per level gains a one-item list
        # and changes in no other way.
        for level in (data.get("lods") or {}).values():
            if not isinstance(level, dict):
                continue
            level.setdefault("representations", [])
            if level.get("geo") and not level["representations"]:
                level["representations"] = [{
                    "file": level["geo"],
                    "format": level["geo"].rsplit(".", 1)[-1] if "." in level["geo"] else "",
                    "role": "primary",
                }]
        version = 5
    if version < 6:
        # v6 puts `variant` on every representation entry. A variant is a
        # SECOND version of the asset that must be kept - Megascans ships a Big
        # and a Small mesh of one plant, sharing one texture set - as opposed to
        # the texture `variants` in texture_slots.json, which name a thing the
        # library deliberately stores only one of. Older entries have no
        # variant, which is exactly what None means.
        for entry in data.get("representations") or []:
            entry.setdefault("variant", None)
        for level in (data.get("lods") or {}).values():
            if isinstance(level, dict):
                for entry in level.get("representations") or []:
                    entry.setdefault("variant", None)
        version = 6
    data["schema_version"] = SCHEMA_VERSION
    return data


# ------------------------------------------------------------------- udim


def to_token(rel: str, tile) -> str:
    """'tex/x_basecolor.1001.exr' -> 'tex/x_basecolor.<UDIM>.exr'."""
    return rel.replace(f".{tile}.", f".{UDIM_TOKEN}.", 1)


def expand(asset: "Asset", rel: str) -> list:
    """Every real file a binding points at.

    A plain path yields itself, so callers never have to ask whether a binding
    is tiled - which is what keeps verify, the icon picker and the viewer from
    each growing their own UDIM special case.
    """
    if UDIM_TOKEN not in rel:
        return [rel]
    return [rel.replace(UDIM_TOKEN, f"{int(t):04d}")
            for t in (asset.udim or {}).get(rel, [])]


def tile_of(asset: "Asset", rel: str):
    """(token path, tile) if `rel` is one tile of a known set, else (None, None)."""
    for token, tiles in (asset.udim or {}).items():
        for t in tiles:
            if rel == token.replace(UDIM_TOKEN, f"{int(t):04d}"):
                return token, int(t)
    return None, None


def roles(asset: "Asset") -> dict:
    """Package-relative path -> what asset.json says that file IS.

    'tex/x_lod2_normal.tif' -> 'LOD2 normal'. The viewer labels every tile with
    this rather than with a filename, which turns the window into a check on
    whether an import bound things the way you meant.
    """
    out: dict = {}
    for slot, rel in (asset.textures or {}).items():
        out[rel] = slot
    # Every size, labelled with it. The best one is already named above by the
    # plain slot, and naming it again here would relabel 'diffuse' as
    # 'diffuse 16k' - true, but it is the one the rest of the app treats as THE
    # diffuse, so it keeps the unqualified name.
    for slot, sizes in (asset.resolutions or {}).items():
        for label, rel in (sizes or {}).items():
            out.setdefault(rel, f"{slot} {label}")
    for entry in asset.representations or []:
        if entry.get("file"):
            out[entry["file"]] = entry.get("role") or "geometry"
    for level in sorted(asset.lods or {}, key=lambda k: int(k)):
        data = asset.lods[level] or {}
        if data.get("geo"):
            out[data["geo"]] = f"LOD{level} geometry"
        # The primary is already named above, without its format. The others
        # are named with theirs, so a level holding .usd and .abc reads as one
        # geometry plus one exchange format rather than two unlabelled files.
        #
        # Assigned, not setdefault: the hero level is mirrored into the top
        # level, whose loop ran first and named these bare 'exchange'. Same
        # reason the LOD textures below overwrite - the level-qualified name is
        # the fuller one and should win.
        for entry in data.get("representations") or []:
            rel = entry.get("file")
            if rel and rel != data.get("geo"):
                which = f" {entry['variant']}" if entry.get("variant") else ""
                out[rel] = (f"LOD{level}{which} {entry.get('role') or 'geometry'} "
                            f"({entry.get('format') or '?'})")
        for slot, rel in (data.get("textures") or {}).items():
            # A hero LOD is mirrored into the top level, so name it once, fully.
            out[rel] = f"LOD{level} {slot}"
    return out


def role_of(asset: "Asset", rel: str, table: dict | None = None) -> str:
    table = roles(asset) if table is None else table
    if rel in table:
        return table[rel]
    # A tile is a real file on disk but the binding names the whole set, so it
    # is looked up through its token path rather than showing as unlabelled.
    token, tile = tile_of(asset, rel)
    if token and token in table:
        return f"{table[token]} tile {tile}"
    if rel == "preview/thumb.jpg":
        return "preview"
    head = rel.split("/", 1)[0]
    if head == "extra":
        return "bonus"
    if head == "derived":
        return "derived"
    if rel == ASSET_FILE:
        return "metadata"
    return ""


def iter_assets(library_root: Path):
    """Yield every asset directory under library/ (those holding an asset.json).

    Once a package is found we stop descending. folder_blob payloads land under
    extra/ verbatim and some vendors ship their own asset.json - RenderMan .rma
    bundles do - so a plain rglob would index that payload as a second, deeper
    asset and `verify` would report it as a depth violation.
    """
    root = Path(library_root)
    if not root.is_dir():
        return
    if (root / ASSET_FILE).is_file():
        yield root
        return
    for child in sorted(root.iterdir()):
        if child.is_dir():
            yield from iter_assets(child)
