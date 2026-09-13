"""The HTTP client for a remote library, and the hosts it knows about.

The other half of `server/api.py`, which is read-only by decision: assets enter
the library over SMB on the LAN, through this app, and nothing here can write
to a server.

**stdlib only, and no Qt.** `requests` is not in the bundled runtime and adding
it would mean vendoring a dependency tree for four HTTP calls; Qt's
`QNetworkAccessManager` would do it well but `assetlib` imports no Qt, which is
the rule that lets Houdini's own interpreter import this package. So:
`urllib.request`, and the small amount of work urllib does not do for us.

Three tiers of traffic, kept apart on purpose (see `server/client-contract.md`):

    catalogue    tens of KB, once per session, diffed by ETag
    thumbnails   ~40 KB, lazily per visible tile, immutable once fetched
    files        50 MB - 1 GB, only on an explicit import, resumable

Search never comes here. The catalogue is synced into a local SQLite and
queried there, so typing costs nothing and browsing still works while the box
is asleep - which matters, because Wake-on-LAN does not reach it from outside
the LAN.
"""

from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HOSTS_FILE = "hosts.json"

# Enough for a catalogue on a healthy link, short enough that a sleeping box
# does not freeze the window. File transfers pass their own, much larger.
TIMEOUT = 15

# A relayed ZeroTier link runs at 1-2 MB/s, so a 1 GB asset is ~17 minutes. The
# timeout is per read, not per transfer - it is "the link has gone quiet", not
# "this is taking a while".
FILE_TIMEOUT = 120

CHUNK = 1 << 20                     # 1 MiB, same as hashing.CHUNK


class RemoteError(RuntimeError):
    """Anything that stopped a request. Carries a status when there was one."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class PartialMismatch(RemoteError):
    """The `.part` on disk cannot be resumed and must be thrown away.

    Its own type because the caller's response is specific and automatic -
    delete and start the file again - and it is not a reason to stop the whole
    import or to tell the user anything.
    """


@dataclass
class Host:
    """One remote library. `name` is the local label and the database filename."""

    name: str
    url: str
    token: str = ""
    enabled: bool = True
    etag: str = ""                      # last catalogue seen, for If-None-Match
    # The other two ways to reach the same box, and they are deliberately not
    # derived from `url`: the API is answered over ZeroTier and the share over
    # the LAN, so they are different addresses for one machine. Both are
    # optional - a server that is only ever browsed needs neither.
    share: str = ""                     # \\host\data2\assets - holds library/
    ssh: str = ""                       # felix@192.168.1.13, to re-index
    fields: dict = field(default_factory=dict)

    def endpoint(self, *parts: str) -> str:
        """Build one API URL. Slashes inside a part are kept as slashes.

        safe="/" and not the default: /api/file/<uuid>/<path:relpath> takes a
        package-relative path, so `tex/rock_basecolor.png` must arrive as three
        path segments. Quoting the separator to %2F leaves it to the WSGI server
        whether it is decoded before routing, which is a coin-flip dependency on
        something that has nothing to do with this library. Escaping the rest
        still matters - a filename can hold a space or a '#'.
        """
        base = self.url.rstrip("/")
        tail = "/".join(urllib.parse.quote(str(p), safe="/") for p in parts)
        return f"{base}/api/{tail}"


# ------------------------------------------------------------------- storage


def hosts_path(cfg) -> Path:
    return cfg.remote_dir() / HOSTS_FILE


def load_hosts(cfg) -> list:
    """Configured hosts, or [] when none. Never raises on a missing file.

    Kept in `.assetlib/`, not in `config/`. The token is a credential and
    `config/` is committed - a secret in a tracked file is a secret published
    the next time anyone pushes, and no amount of intending to remove it later
    survives one distracted afternoon.
    """
    try:
        with hosts_path(cfg).open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return []
    out, taken = [], set()
    for entry in raw.get("hosts", []):
        known = {"name", "url", "token", "enabled", "etag", "share", "ssh"}
        name = entry.get("name", "remote")
        # The name is the catalogue's FILENAME, so two hosts sharing one is two
        # hosts sharing one database. They do not merge, they fight: each sync
        # wipes the other's rows while keeping its own ETag, so the next sync
        # gets a 304 and reports "unchanged" over a catalogue that was deleted.
        # Dropped rather than renamed, because a silently renamed host would
        # sync into a database nothing else knows about.
        if name in taken:
            continue
        taken.add(name)
        out.append(Host(
            name=name,
            url=entry.get("url", ""),
            token=entry.get("token", ""),
            enabled=bool(entry.get("enabled", True)),
            etag=entry.get("etag", ""),
            share=entry.get("share", ""),
            ssh=entry.get("ssh", ""),
            fields={k: v for k, v in entry.items() if k not in known},
        ))
    return out


def save_hosts(cfg, hosts: list) -> None:
    path = hosts_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"hosts": [
        {"name": h.name, "url": h.url, "token": h.token,
         "enabled": h.enabled, "etag": h.etag,
         "share": h.share, "ssh": h.ssh, **h.fields}
        for h in hosts
    ]}
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    tmp.replace(path)


# ------------------------------------------------------------------ requests


def _request(host: Host, url: str, headers: dict | None = None,
             timeout: int = TIMEOUT):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {host.token}")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    return urllib.request.urlopen(req, timeout=timeout)      # noqa: S310


def _body(response) -> bytes:
    """The response body, decompressed if the server chose to compress it.

    The check is on the RESPONSE header, never on the request: the server
    gzips only above 8 KB, so compression is conditional and decompressing
    unconditionally fails on exactly the small-catalogue case. urllib does not
    do this step at all - `requests` would, which is precisely why code ported
    from a `requests` example breaks here and nowhere else.
    """
    raw = response.read()
    if (response.headers.get("Content-Encoding") or "").lower() == "gzip":
        return gzip.decompress(raw)
    return raw


def _json(host: Host, url: str, headers: dict | None = None,
          timeout: int = TIMEOUT) -> dict:
    head = {"Accept-Encoding": "gzip"}
    head.update(headers or {})
    try:
        with _request(host, url, head, timeout) as resp:
            return json.loads(_body(resp).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RemoteError(_explain(exc), exc.code) from exc
    except urllib.error.URLError as exc:
        raise RemoteError(f"{host.name} is unreachable: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise RemoteError(f"{host.name}: {exc}") from exc


def _explain(exc: urllib.error.HTTPError) -> str:
    """Turn a status into something worth reading in a status bar.

    The API answers errors in JSON precisely so a program does not have to
    guess, but the three that matter get said in words, because "401" in a
    status bar teaches nobody that the token is wrong.
    """
    if exc.code == 401:
        return "rejected the token - check it in Remote libraries"
    if exc.code == 410:
        return "the catalogue is stale - refresh it and try again"
    if exc.code == 404:
        return "not found on the server"
    try:
        detail = json.loads(exc.read().decode("utf-8")).get("error")
    except Exception:                                   # noqa: BLE001
        detail = None
    return f"HTTP {exc.code}" + (f": {detail}" if detail else "")


# ------------------------------------------------------------------- the API


def health(host: Host) -> dict:
    """Is the catalogue worth trusting right now.

    `library_mounted` is the one to read carefully: /srv/data2 is fstab'd
    nofail, so an unmounted disk answers every request successfully and reports
    an empty library. "Up" and "usable" are not the same state.
    """
    return _json(host, host.endpoint("health"))


def catalog(host: Host) -> tuple:
    """(rows, etag) for a changed catalogue, or (None, etag) when unchanged.

    None is the 304 answer and is not an error: the stored rows are current and
    re-downloading them would be the only cost. urllib raises HTTPError on 304
    because it is not a 2xx - the status is the payload here, so it is caught
    rather than propagated.
    """
    headers = {"If-None-Match": host.etag} if host.etag else {}
    try:
        payload = _json(host, host.endpoint("catalog"), headers)
    except RemoteError as exc:
        if exc.status == 304:
            return None, host.etag
        raise
    return payload.get("assets") or [], payload.get("etag") or ""


def asset(host: Host, uuid: str) -> dict:
    """asset.json as written, the file manifest, and what an import would cost."""
    return _json(host, host.endpoint("asset", uuid))


def fetch_file(host: Host, uuid: str, relpath: str, dest: Path,
               offset: int = 0, on_chunk=None, should_stop=None,
               timeout: int = FILE_TIMEOUT) -> int:
    """Append one file to `dest`, starting at `offset`. Returns bytes written.

    Deliberately NOT routed through `_body()`. That function decompresses when
    the server says it compressed, which is right for JSON and wrong here twice
    over: an asset file is already compressed, and `_body()` reads the whole
    response into memory - a 1 GB .exr would be a gigabyte of RAM before a byte
    reached the disk.

    `offset` is the resume: it is the size of the `.part` already on disk, and
    the server answers `Range` with a 206. A 200 means it ignored the header
    and is sending from the start, so the partial file has to go - silently
    appending a whole file onto a partial one produces a corrupt file whose
    hash fails much later, with nothing pointing at the cause.
    """
    headers = {}
    if offset:
        headers["Range"] = f"bytes={offset}-"

    try:
        resp = _request(host, host.endpoint("file", uuid, relpath), headers, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and offset:
            # Asked for a range past the end: the .part is at least as long as
            # the file. It is not a resume point, it is rubbish.
            raise PartialMismatch(f"{relpath}: stale partial file") from exc
        raise RemoteError(_explain(exc), exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RemoteError(f"{host.name}: {exc}") from exc

    with resp:
        resuming = resp.status == 206
        if offset and not resuming:
            raise PartialMismatch(f"{relpath}: server ignored the resume request")

        mode = "ab" if resuming else "wb"
        written = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open(mode) as fh:
            while True:
                if should_stop is not None and should_stop():
                    return written
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
                if on_chunk is not None:
                    on_chunk(len(chunk))
    return written


def thumb(host: Host, uuid: str) -> bytes:
    """preview/thumb.jpg. Immutable for a given uuid, so it is fetched once."""
    url = host.endpoint("thumb", uuid)
    try:
        with _request(host, url) as resp:
            return _body(resp)
    except urllib.error.HTTPError as exc:
        raise RemoteError(_explain(exc), exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RemoteError(f"{host.name}: {exc}") from exc
