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
    origin      TEXT NOT NULL DEFAULT 'local',
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
    return connect_at(cfg.db_path())


def connect_at(db_path: Path) -> sqlite3.Connection:
    """Open (and migrate) one database at an explicit path.

    Split out of connect() so a synced remote catalogue can reuse this schema
    exactly rather than growing its own copy that drifts. Same tables, same
    FTS5, same column repairs - the only difference between the local index and
    a remote catalogue is where the rows came from.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
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
    if "origin" not in have:
        # 'local' as the default, unlike has_geo above: a row written before
        # this column existed was written by a build that had exactly one root,
        # so local is not a guess - it is the only thing it could have been.
        conn.execute("ALTER TABLE assets ADD COLUMN origin TEXT NOT NULL "
                     "DEFAULT 'local'")
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


def upsert(conn: sqlite3.Connection, asset: Asset, asset_dir: Path,
           library_root: Path, origin: str = "local", size: int | None = None) -> None:
    """Index one package. `origin` says which root `library_root` is.

    `size` is an escape hatch for a caller that already knows the number: a
    materialised download has the byte count from the server's manifest, and
    re-deriving it with _dir_size() would rglob a package that was just written
    file by file. Left None, the walk happens as before.
    """
    rel = str(asset_dir.relative_to(library_root)).replace("\\", "/")
    tags = " ".join(asset.tags)
    conn.execute(
        "INSERT INTO assets (uuid,name,type,category,path,origin,size,resolution,"
        "resolutions,has_geo,tags,created) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(uuid) DO UPDATE SET name=excluded.name, type=excluded.type, "
        "category=excluded.category, path=excluded.path, origin=excluded.origin, "
        "size=excluded.size, resolution=excluded.resolution, "
        "resolutions=excluded.resolutions, has_geo=excluded.has_geo, "
        "tags=excluded.tags",
        (asset.uuid, asset.name, asset.type, asset.category, rel, origin,
         _dir_size(asset_dir) if size is None else size,
         asset.fields.get("resolution"),
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
    # Cache first, library second, and the order is the point: uuid is the
    # primary key, so if the same asset is both downloaded and held locally the
    # LAST write wins. Local should win - it is the copy that can be edited,
    # while _cache/ is disposable and can be fetched again.
    for root, origin in ((cfg.cache_root, "cache"), (cfg.library, "local")):
        for asset_dir in iter_assets(root):
            try:
                asset = Asset.read(asset_dir)
            except Exception as exc:                 # noqa: BLE001
                failed.append((asset_dir, str(exc)))
                continue
            upsert(conn, asset, asset_dir, root, origin)
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


# ------------------------------------------------------------ local ∪ remote


def search_union(local_conn, remotes, text: str = "", limit: int = 5000) -> list:
    """Search the local index and every synced catalogue as one library.

    `remotes` is [(host_name, conn)]. Two databases and two queries rather than
    an ATTACH and one: FTS5 cannot rank across attached databases, so the join
    would have to be done in Python regardless, and ATTACH would only add a way
    for a corrupt remote catalogue to take the local index down with it.

    **A uuid seen locally wins.** That is not a tie-break, it is the single
    master decision arriving here: a downloaded asset keeps the uuid it has on
    the server, so the same asset legitimately appears in both answers and the
    copy on this disk is the one to point at. It is also what makes "already
    downloaded" answerable without touching the filesystem.
    """
    rows = search(local_conn, text, limit)
    seen = {r["uuid"] for r in rows}

    # Which local uuids the server also has. Computed HERE because this is the
    # only place both answers exist at once - by the time the grid has a row,
    # the remote side has been deduplicated away and a local asset that is on
    # the server looks exactly like one that is not.
    #
    # `mirrored` is left None, not False, when no catalogue is configured: "the
    # server does not have this" and "there is no server" are different facts,
    # and painting every tile as un-backed-up on a machine that never had a
    # server would be a warning about nothing.
    mirrored = None
    if remotes:
        mirrored = set()
        for _, conn in remotes:
            mirrored |= {r["uuid"] for r in conn.execute("SELECT uuid FROM assets")}

    for row in rows:
        row["mirrored"] = None if mirrored is None else (row["uuid"] in mirrored)

    for name, conn in remotes:
        for row in search(conn, text, limit):
            if row["uuid"] in seen:
                continue
            row["origin"] = f"remote:{name}"
            row["mirrored"] = True          # it IS the server's copy
            seen.add(row["uuid"])
            rows.append(row)

    _, _, free = parse_query(text or "")
    if free:
        # Leave the order alone. Each source came back in its own FTS5 rank
        # order and those ranks are not comparable - they are computed against
        # different corpora - so re-sorting by relevance would be inventing a
        # number. Local first is at least a rule someone can predict.
        return rows[:limit]
    rows.sort(key=lambda r: (r["type"], r["category"], r["name"]))
    return rows[:limit]


def counts_union(local_conn, remotes) -> dict:
    """Sidebar counts across local and remote, deduplicated by uuid.

    Counted from uuids rather than by summing per-database COUNT(*), because a
    downloaded asset exists in both and summing would show it twice - the
    sidebar would disagree with the grid, and the sidebar is what people trust.
    """
    seen, out = set(), {}
    sources = [local_conn] + [conn for _, conn in remotes]
    for conn in sources:
        for row in conn.execute("SELECT uuid, type, category FROM assets"):
            if row["uuid"] in seen:
                continue
            seen.add(row["uuid"])
            key = (row["type"], row["category"])
            out[key] = out.get(key, 0) + 1
            out[(row["type"], None)] = out.get((row["type"], None), 0) + 1
    return out


def find_by_hash(conn: sqlite3.Connection, digest: str):
    return None  # hashes live in asset.json; wired up when dedup lands in the UI
