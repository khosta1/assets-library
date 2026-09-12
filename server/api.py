"""Read-only HTTP catalogue for the asset library, served from the Rocky box.

The remote half of the library. A client browses the whole catalogue and pulls
only the assets it actually needs, over ZeroTier, without mounting anything.

**Read-only on purpose.** Assets enter the library from the PC over SMB on the
LAN, through the app that already knows how to import - so this process needs
no Pillow, no OpenEXR and no xxhash, and it cannot damage 1.7 TB that has no
off-site copy yet. The reasoning, and the alternatives it rejects, are in the
server panel's `docs/decisions.md` (2026-09-12).

Three tiers of traffic, and separating them is the entire design:

    catalogue    tens of KB, once per session, cached and diffed by ETag
    thumbnails   ~40 KB, lazily per visible tile, immutable once fetched
    files        50 MB - 1 GB, only on an explicit import, resumable

Search never comes here: the client syncs the catalogue into its own SQLite and
queries that, so typing in the search box costs nothing and still works while
the box is asleep.
"""

from __future__ import annotations

import dataclasses
import gzip
import hmac
import json
import os
import sqlite3
from pathlib import Path

from flask import Flask, Response, abort, g, jsonify, request, send_file

from assetlib import index
from assetlib.model import Asset

from .paths import load_config, read_stamp

# derived/ is regenerable by definition - `library.json` says so in the
# derived_is_disposable invariant - so it is never listed and never served.
# Shipping it would roughly double a transfer to send files the client rebuilds
# locally in seconds.
SKIP_TOP = {"derived"}

CFG = load_config()

TOKEN = os.environ.get("ASSETLIB_TOKEN", "")
if not TOKEN:
    # Fail closed. The panel next door deliberately has no login because the
    # worst a stranger on the mesh can do there is restart a game server; here
    # the worst is reading fifteen years of work, and the friends are on that
    # same mesh. Starting unauthenticated "just this once" is how that becomes
    # permanent.
    raise SystemExit(
        "ASSETLIB_TOKEN is empty - refusing to serve the library "
        "unauthenticated. Set it in /etc/assetlib/api.env."
    )

app = Flask(__name__)


# ----------------------------------------------------------------------- auth


@app.before_request
def _require_token():
    header = request.headers.get("Authorization", "")
    sent = header[7:] if header.startswith("Bearer ") else ""
    # compare_digest, not ==. String equality returns on the first wrong byte,
    # which hands the token's length and prefix to anyone who can time a few
    # thousand requests. One import to avoid, unpleasant to retrofit.
    if not hmac.compare_digest(sent, TOKEN):
        abort(401)


# -------------------------------------------------------------------- catalog


def db() -> sqlite3.Connection:
    """The catalogue, one connection per request.

    Per request because a sqlite3 connection belongs to the thread that opened
    it, and the server is threaded - which it must be, or one 1 GB download
    blocks every catalogue call queued behind it.
    """
    if "db" not in g:
        g.db = index.connect(CFG)
    return g.db


@app.teardown_appcontext
def _close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _asset_dir(uuid: str) -> Path:
    """uuid -> package directory, resolved THROUGH the index.

    The only translation from an id to a path in the whole service. Every route
    goes through it, which is what keeps user-supplied text out of every path
    this process builds.
    """
    row = db().execute(
        "SELECT path, origin FROM assets WHERE uuid = ?", (uuid,)
    ).fetchone()
    if row is None:
        abort(404)

    # cfg.asset_path(), not `CFG.library / row["path"]`. On this box every row
    # is origin='local' and the two are identical today - but the index grew a
    # second root, and the same relative path resolves under both, so the naive
    # join produces a real directory rather than an error. Correct by
    # construction beats correct by coincidence.
    #
    # dict(row), not row: asset_path() calls .get(), and a sqlite3.Row has no
    # .get() - it would raise AttributeError, not fall back.
    base = CFG.asset_path(dict(row))
    if base is None:
        # origin names a root that is not on this disk. Impossible here, since
        # the server never catalogues a remote library, but it is a real return
        # value and swallowing it would turn a wrong answer into a wrong file.
        abort(404)

    path = base.resolve()
    if not path.is_dir():
        # Indexed but no longer on disk. 410 rather than 404 so the client can
        # tell "your catalogue is stale, re-sync" from "no such asset" - the
        # catalogue is a cache and the disk is the truth.
        abort(410)
    return path


def _servable(rel: str) -> bool:
    """Is this relative path one the library is willing to hand out?

    A structural rule, so it can answer without a directory walk - which is
    what lets the download path check a file in constant time (see `file`).

    Dotfiles are refused at every level, not only the top. `Asset.write` writes
    atomically through a `.asset-XXXX.tmp` beside the real file, so a client
    listing a package mid-write would otherwise be offered a half-written
    temporary that vanishes before it can fetch it.
    """
    parts = rel.split("/")
    if parts[0] in SKIP_TOP:
        return False
    return not any(part.startswith(".") for part in parts)


def _manifest(asset: Asset, asset_dir: Path) -> list:
    """Every file the client may fetch, with its size and its hash if known.

    Built by walking the package, not by reading `asset.hashes`: the hash map
    covers the files that came in through an import, and the client needs the
    package as it actually stands - `asset.json` and `preview/thumb.jpg`
    included. The walk is one directory of a few dozen entries, which is cheap
    even through FUSE; what is not cheap is walking the whole library, and
    nothing on a request path here does that.
    """
    files = []
    for path in sorted(asset_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(asset_dir).as_posix()
        if not _servable(rel):
            continue
        files.append({
            "path": rel,
            "size": path.stat().st_size,
            "hash": asset.hashes.get(rel),
        })
    return files


# --------------------------------------------------------------------- routes


@app.get("/api/health")
def health():
    """Enough to answer "is the catalogue worth trusting right now"."""
    row = db().execute("SELECT COUNT(*) AS n FROM assets").fetchone()
    stamp = read_stamp(CFG)

    # /srv/data2 is fstab'd nofail and the unit only orders itself after the
    # mount, so an unmounted disk is a real state - and health is precisely the
    # route that must answer during it rather than 500 and say nothing.
    try:
        stat = os.statvfs(CFG.library)
        free = stat.f_bavail * stat.f_frsize
        mounted = True
    except OSError:
        free, mounted = None, False

    return jsonify({
        "assets": row["n"],
        "indexed_at": stamp.get("indexed_at"),
        "index_seconds": stamp.get("seconds"),
        "index_failed": len(stamp.get("failed") or []),
        "library": str(CFG.library),
        "library_mounted": mounted,
        "free_bytes": free,
    })


@app.get("/api/catalog")
def catalog():
    """The whole catalogue, every time, behind an ETag.

    No `since=` and no incremental sync, deliberately. A few hundred rows is
    ~100 KB before gzip and the client re-reads it faster than a delta could be
    negotiated. It also keeps this service out of `assetlib/index.py`, which
    has no `updated` column and does not need one to serve this.
    """
    stamp = read_stamp(CFG)
    tag = stamp.get("etag")
    if tag and request.if_none_match.contains(tag):
        # The ETag goes on the 304 too. A response that omits it is legal but
        # leaves a cache with nothing to re-validate against next time.
        resp = Response(status=304)
        resp.set_etag(tag)
        return resp

    # Columns listed by name, and `origin` is deliberately NOT among them.
    # Every row here reads origin='local', but local is the CLIENT's word for
    # "on my disk" - shipping it would tell a client its remote assets are
    # already local, which is the one lie that would make it skip downloading
    # them. Never widen this to SELECT *.
    rows = [dict(r) for r in db().execute(
        "SELECT uuid, name, type, category, path, size, resolution, "
        "resolutions, has_geo, tags, created FROM assets "
        "ORDER BY type, category, name"
    )]
    payload = json.dumps(
        {"etag": tag, "count": len(rows), "assets": rows}
    ).encode("utf-8")

    # Compressed here, by hand, because nothing else will: there is no reverse
    # proxy in front of this and Flask does not compress. The catalogue is
    # highly repetitive JSON and gzips to roughly a fifth, which is the
    # difference between a snappy start and a visible wait on a relayed
    # ZeroTier link. Only above 8 KB - below that the round-trip dominates.
    headers = {"Content-Type": "application/json"}
    if len(payload) > 8192 and "gzip" in request.headers.get("Accept-Encoding", ""):
        payload = gzip.compress(payload, 6)
        headers["Content-Encoding"] = "gzip"
        headers["Vary"] = "Accept-Encoding"

    resp = Response(payload, headers=headers)
    if tag:
        resp.set_etag(tag)
    return resp


@app.get("/api/asset/<uuid>")
def asset(uuid):
    """asset.json as written, plus what importing it would cost."""
    asset_dir = _asset_dir(uuid)
    record = Asset.read(asset_dir)
    files = _manifest(record, asset_dir)
    return jsonify({
        "asset": dataclasses.asdict(record),
        "files": files,
        "bytes": sum(f["size"] for f in files),
    })


@app.get("/api/thumb/<uuid>")
def thumb(uuid):
    """preview/thumb.jpg - part of the package, so it is served as it is."""
    path = _asset_dir(uuid) / "preview" / "thumb.jpg"
    if not path.is_file():
        abort(404)
    # A thumbnail changes only when the asset is re-imported, and the client
    # keys its cache on the uuid, so a week of max-age costs nothing and saves
    # a round-trip per tile on every cold grid.
    return send_file(path, mimetype="image/jpeg", conditional=True, max_age=604800)


@app.get("/api/file/<uuid>/<path:relpath>")
def file(uuid, relpath):
    """One file out of one package, resumable.

    `relpath` is never joined onto a directory and trusted. Two checks, both
    cheap: the structural rule in `_servable`, and containment of the RESOLVED
    path inside the package. Resolving first is what makes it symlink-safe -
    `..` and a symlink pointing out of the package both land outside asset_dir
    and are refused - and derived/ is refused by name.

    It deliberately does NOT check membership of the full manifest, which is
    the obvious way to write this and is quadratic: the manifest is an rglob of
    the package, so importing a 200-file asset would rglob it 200 times, which
    on ntfs-3g through FUSE is tens of thousands of stat calls to learn what
    containment already answers in one.
    """
    asset_dir = _asset_dir(uuid)
    if not _servable(relpath):
        abort(404)

    path = (asset_dir / relpath).resolve()
    if not path.is_file() or asset_dir not in path.parents:
        abort(404)

    # conditional=True is Flask's default and is what gives Range and 304
    # through werkzeug - the whole resume story for a 1 GB asset on a relayed
    # ZeroTier link, at no cost in code.
    return send_file(path, conditional=True)


# --------------------------------------------------------------------- errors


@app.errorhandler(401)
@app.errorhandler(404)
@app.errorhandler(410)
def _as_json(exc):
    # The only consumer is a program. An HTML error page would make it guess.
    return jsonify({"error": exc.name, "status": exc.code}), exc.code
