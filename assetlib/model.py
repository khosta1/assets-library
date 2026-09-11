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

SCHEMA_VERSION = 3
ASSET_FILE = "asset.json"

# A UDIM set is ONE binding pointing at many files. asset.json stores the path
# with the tile replaced by this token - the spelling Houdini, Karma, Arnold and
# Mari all resolve natively - and the tiles that actually exist alongside it, so
# nothing has to glob the directory to find out.
UDIM_TOKEN = "<UDIM>"


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
    for entry in asset.representations or []:
        if entry.get("file"):
            out[entry["file"]] = entry.get("role") or "geometry"
    for level in sorted(asset.lods or {}, key=lambda k: int(k)):
        data = asset.lods[level] or {}
        if data.get("geo"):
            out[data["geo"]] = f"LOD{level} geometry"
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
