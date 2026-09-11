"""SQLite + FTS5 search index.

A cache, never the truth: delete index.db and Rebuild index (F5) reproduces
it from the asset.json files on disk. Search must never touch the
filesystem - the UI queries this and nothing else.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .model import Asset, iter_assets

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    uuid        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    category    TEXT NOT NULL,
    path        TEXT NOT NULL,
    size        INTEGER DEFAULT 0,
    resolution  INTEGER,
    resolutions TEXT DEFAULT '',
    has_geo     INTEGER,
    tags        TEXT DEFAULT '',
    created     TEXT
);
CREATE INDEX IF NOT EXISTS idx_type_cat ON assets(type, category);
CREATE VIRTUAL TABLE IF NOT EXISTS assets_fts USING fts5(
    uuid UNINDEXED, name, tags, category, type, tokenize='unicode61'
);
"""

FILTER_RE = re.compile(r"(-?)(type|cat|category|tag|res|src):(\S+)", re.I)


def connect(cfg) -> sqlite3.Connection:
    cfg.state.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    # CREATE TABLE IF NOT EXISTS never alters a table that already exists, so a
    # database written before `resolutions` simply lacks the column and every
    # query mentioning it fails. The index is a cache and F5 rebuilds it, but a
    # missing column would break the window before anyone could press F5.
    have = {row[1] for row in conn.execute("PRAGMA table_info(assets)")}
    if "resolutions" not in have:
        conn.execute("ALTER TABLE assets ADD COLUMN resolutions TEXT DEFAULT ''")
    if "has_geo" not in have:
        # Deliberately NULL, not 0. NULL means "this row predates the column and
        # nobody has looked", which a caller can tell apart from 0, "looked, and
        # there is no geometry". Defaulting to 0 would make every asset claim it
        # has no mesh until someone happened to press F5.
        conn.execute("ALTER TABLE assets ADD COLUMN has_geo INTEGER")
    return conn


def _res_blob(asset) -> str:
    """' 16k 8k 4k 2k ' - every size the asset holds, padded for exact LIKE.

    A list in a column is normally the wrong shape, and a resolutions table
    would be the right one. It is not worth it here: the whole database is a
    cache rebuilt from asset.json by F5, nothing joins on a resolution, and the
    only question ever asked of it is whether one label is present.
    """
    labels = asset.fields.get("resolutions") or []
    if not labels and asset.fields.get("resolution"):
        from .model import res_label
        labels = [res_label(asset.fields["resolution"])]
    return (" " + " ".join(str(x) for x in labels) + " ") if labels else ""


def _has_geometry(asset) -> int:
    """1 when the package holds a mesh, 0 when it does not.

    Answered here, at index time, because the browser must not read asset.json
    to decide whether to show a menu entry - the window never walks the
    filesystem during interaction, and a right-click is interaction.

    Type is not the answer. A hand-declared texture asset can hold an .obj since
    geometry routes on the extension, and a `model` whose mesh was skipped holds
    none. The bindings are what is true.
    """
    for entry in asset.representations or []:
        if (entry.get("file") or "").startswith("geo/"):
            return 1
    for level in (asset.lods or {}).values():
        if (level or {}).get("geo"):
            return 1
        for entry in (level or {}).get("representations") or []:
            if (entry.get("file") or "").startswith("geo/"):
                return 1
    return 0


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def upsert(conn: sqlite3.Connection, asset: Asset, asset_dir: Path, library_root: Path) -> None:
    rel = str(asset_dir.relative_to(library_root)).replace("\\", "/")
    tags = " ".join(asset.tags)
    conn.execute(
        "INSERT INTO assets (uuid,name,type,category,path,size,resolution,resolutions,"
        "has_geo,tags,created) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(uuid) DO UPDATE SET name=excluded.name, type=excluded.type, "
        "category=excluded.category, path=excluded.path, size=excluded.size, "
        "resolution=excluded.resolution, resolutions=excluded.resolutions, "
        "has_geo=excluded.has_geo, tags=excluded.tags",
        (asset.uuid, asset.name, asset.type, asset.category, rel,
         _dir_size(asset_dir), asset.fields.get("resolution"),
         _res_blob(asset), _has_geometry(asset), tags, asset.created),
    )
    conn.execute("DELETE FROM assets_fts WHERE uuid = ?", (asset.uuid,))
    conn.execute(
        "INSERT INTO assets_fts (uuid,name,tags,category,type) VALUES (?,?,?,?,?)",
        (asset.uuid, asset.name.replace("_", " "), tags, asset.category, asset.type),
    )
    conn.commit()


def remove(conn: sqlite3.Connection, uuid: str) -> None:
    """Drop an asset from the index. The package on disk is somebody else's job."""
    conn.execute("DELETE FROM assets WHERE uuid = ?", (uuid,))
    conn.execute("DELETE FROM assets_fts WHERE uuid = ?", (uuid,))
    conn.commit()


def rebuild(cfg) -> dict:
    """Rebuild the index from the asset.json files. Returns what happened.

    An asset that cannot be read is REPORTED, never silently skipped. The old
    behaviour - catch everything, continue - meant a library written by a newer
    build showed up as simply empty, with nothing anywhere saying why.
    """
    conn = connect(cfg)
    conn.execute("DELETE FROM assets")
    conn.execute("DELETE FROM assets_fts")
    count, failed = 0, []
    for asset_dir in iter_assets(cfg.library):
        try:
            asset = Asset.read(asset_dir)
        except Exception as exc:                     # noqa: BLE001
            failed.append((asset_dir, str(exc)))
            continue
        upsert(conn, asset, asset_dir, cfg.library)
        count += 1
    conn.commit()
    conn.close()
    return {"indexed": count, "failed": failed}


# ---------------------------------------------------------------------- query


def parse_query(text: str) -> tuple:
    """Split 'type:texture -src:megascans rough concrete' into filters + free text."""
    include, exclude = [], []
    for neg, key, value in FILTER_RE.findall(text):
        key = {"category": "cat"}.get(key.lower(), key.lower())
        (exclude if neg else include).append((key, value.lower()))
    free = FILTER_RE.sub("", text).strip()
    return include, exclude, free


def search(conn: sqlite3.Connection, text: str = "", limit: int = 5000) -> list:
    include, exclude, free = parse_query(text or "")
    where, params = [], []

    for key, value in include:
        if key == "type":
            where.append("a.type = ?"); params.append(value)
        elif key == "cat":
            where.append("a.category = ?"); params.append(value)
        elif key == "res":
            # "has this resolution", not "is this resolution": an asset holding
            # 2k/4k/8k/16k answers res:4k as readily as res:16k. The blob is
            # space-delimited on both sides so '4k' cannot match '4096' or
            # '14k'.
            where.append("a.resolutions LIKE ?"); params.append(f"% {value.strip().lower()} %")
        else:  # tag / src -> tag namespace
            token = value if key == "tag" else f"{key}:{value}"
            where.append("a.tags LIKE ?"); params.append(f"%{token}%")

    for key, value in exclude:
        token = value if key == "tag" else f"{key}:{value}"
        if key == "type":
            where.append("a.type <> ?"); params.append(value)
        elif key == "cat":
            where.append("a.category <> ?"); params.append(value)
        else:
            where.append("a.tags NOT LIKE ?"); params.append(f"%{token}%")

    if free:
        # prefix-match each word so typing feels instant
        match = " ".join(f'"{w}"*' for w in free.split() if w)
        sql = ("SELECT a.* FROM assets_fts f JOIN assets a ON a.uuid = f.uuid "
               "WHERE assets_fts MATCH ?")
        params = [match] + params
        if where:
            sql += " AND " + " AND ".join(where)
        sql += " ORDER BY rank LIMIT ?"
    else:
        sql = "SELECT a.* FROM assets a"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY a.type, a.category, a.name LIMIT ?"

    params.append(limit)
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    except sqlite3.OperationalError:
        return []


def counts(conn: sqlite3.Connection) -> dict:
    """{(type, category): n} plus {(type, None): n} totals, for the sidebar."""
    out = {}
    for row in conn.execute("SELECT type, category, COUNT(*) n FROM assets GROUP BY type, category"):
        out[(row["type"], row["category"])] = row["n"]
        out[(row["type"], None)] = out.get((row["type"], None), 0) + row["n"]
    return out


def find_by_hash(conn: sqlite3.Connection, digest: str):
    return None  # hashes live in asset.json; wired up when dedup lands in the UI
