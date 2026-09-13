"""Syncing a remote catalogue into a local database, and reading it back.

The join between `remote.py` (which knows HTTP) and `index.py` (which knows
SQLite). Neither of those should know about the other: the HTTP client is
usable without a database, and the index has no business making network calls -
F5 rebuilds it from disk, and a rebuild that could hang on a sleeping server
would be a rebuild nobody dares press.

The catalogue is a *mirror*, not an index. It is never built by walking
anything; it is whatever the server last said, stored so the window can be
browsed and searched with the server switched off.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import index, remote

# Columns the server sends. Listed rather than SELECT *'d so that a server
# running ahead of this client adds a column without breaking the insert - the
# extra field is ignored instead of shifting every value one place left.
ROW_FIELDS = ("uuid", "name", "type", "category", "path", "size", "resolution",
              "resolutions", "has_geo", "tags", "created")


def open_catalog(cfg, host: remote.Host):
    """The synced catalogue for one host. Empty and valid if never synced."""
    return index.connect_at(cfg.remote_db_path(host.name))


def sync(cfg, host: remote.Host, hosts: list | None = None) -> dict:
    """Fetch the catalogue and replace the stored one. Returns what happened.

    Replace, not merge. The server sends the whole catalogue every time behind
    an ETag - there is no `since=` and deliberately so - and a replace is the
    only thing that removes an asset deleted on the server. A merge would keep
    ghosts forever, and a ghost is worse than a stale count because it offers
    an import that cannot succeed.
    """
    rows, etag = remote.catalog(host)

    # Stamped on every SUCCESSFUL answer, including a 304. The question the UI
    # has to answer is "how old is what I am showing you", and an unchanged
    # catalogue that was confirmed unchanged a minute ago is current - not
    # stale since whenever it last changed.
    host.fields["synced_at"] = datetime.now(timezone.utc).isoformat()

    if rows is None:
        # 304. The stored catalogue is current, which is the whole point of
        # sending If-None-Match, and touching the database would be work done
        # to arrive back where we started.
        conn = open_catalog(cfg, host)
        try:
            count = conn.execute("SELECT COUNT(*) n FROM assets").fetchone()["n"]
        finally:
            conn.close()
        # Persisted here too, and this is the path it matters on: 304 is the
        # COMMON answer, so a stamp written only when the catalogue changed
        # would make a healthy daily sync look like it had not run since the
        # last import.
        if hosts is not None:
            remote.save_hosts(cfg, hosts)
        return {"host": host.name, "changed": False, "count": count,
                "etag": etag}

    conn = open_catalog(cfg, host)
    try:
        conn.execute("DELETE FROM assets")
        conn.execute("DELETE FROM assets_fts")
        origin = f"remote:{host.name}"
        for row in rows:
            values = [row.get(field) for field in ROW_FIELDS]
            conn.execute(
                "INSERT INTO assets (uuid,name,type,category,path,size,"
                "resolution,resolutions,has_geo,tags,created,origin) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (*values, origin),
            )
            conn.execute(
                "INSERT INTO assets_fts (uuid,name,tags,category,type) "
                "VALUES (?,?,?,?,?)",
                (row.get("uuid"), (row.get("name") or "").replace("_", " "),
                 row.get("tags") or "", row.get("category"), row.get("type")),
            )
        conn.commit()
    finally:
        conn.close()

    # Only now. An ETag stored before the rows are committed would make the
    # next sync answer 304 against a catalogue that was never written, and the
    # window would show an empty remote library until someone thought to delete
    # the database by hand.
    host.etag = etag
    if hosts is not None:
        remote.save_hosts(cfg, hosts)

    return {"host": host.name, "changed": True, "count": len(rows),
            "etag": etag}


def synced_age(host: remote.Host) -> float | None:
    """Seconds since this host's catalogue was last confirmed, or None if never.

    What the window needs in order to say how much to trust a red outline: the
    "not on the server" state is only as true as the last successful sync, and
    a catalogue from before an import is what made 43 tiles look un-pushed when
    seven were.
    """
    stamp = host.fields.get("synced_at")
    if not stamp:
        return None
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds()


def describe_age(seconds: float | None) -> str:
    """'4 minutes ago' / 'never'. Plain words, for a status bar."""
    if seconds is None:
        return "never synced"
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} day(s) ago"


def open_all(cfg, hosts: list) -> list:
    """[(host_name, conn)] for every enabled host, ready for search_union.

    Opened whether or not the server is reachable: the catalogue is on this
    disk, so browsing and searching do not depend on the box being awake. Only
    importing does.
    """
    out = []
    for host in hosts:
        if not host.enabled:
            continue
        try:
            out.append((host.name, open_catalog(cfg, host)))
        except Exception:                               # noqa: BLE001
            # A catalogue that will not open must not stop the window from
            # showing the local library. Re-syncing rewrites it.
            continue
    return out
