"""Bringing a remote asset down onto this disk, as the same asset.

The third tier. The catalogue is kilobytes and the thumbnails are tens of them;
this is where the gigabytes are, and it happens only when somebody explicitly
asks for one asset.

**It does not go through `commit.py`, and that is the whole design.** The import
path is built to create assets: `Asset.new()` mints a fresh uuid, because an
imported folder is a new thing entering the library. A download is not. It is
the *same asset*, already in the library, arriving at a second location - and
the moment it gets a second uuid the server stops being the single master and
nothing in the schema can tell a deliberate variant from an accidental copy.
So the package is written out exactly as the server sent it, uuid included.

The three rules that follow from that:

    the uuid is never regenerated
    asset.json is written verbatim, not rebuilt from what arrived
    the package lands under cfg.cache_root, in the same three levels
"""

from __future__ import annotations

import json
from pathlib import Path

from . import hashing, remote
from .model import ASSET_FILE

# Always fetched whatever subset was asked for. asset.json is the package's
# truth and a package without it is not an asset at all; the thumbnail is 40 KB
# and its absence would leave a grey tile on something you just downloaded.
ALWAYS = (ASSET_FILE, "preview/thumb.jpg")

FULL = "full"
HERO = "hero"


def _res_of(path: str) -> str:
    """'..._basecolor_8k.png' -> '8k'. '' when the name carries no resolution.

    The library's own naming puts the resolution in the filename as a suffix
    token, so this reads a convention the tool itself wrote - it is not
    guessing about a vendor's names, which is the thing `slots.py` exists to
    keep in one place.
    """
    stem = Path(path).stem.lower()
    tail = stem.rsplit("_", 1)[-1] if "_" in stem else ""
    return tail if tail and tail[-1] == "k" and tail[:-1].isdigit() else ""


def resolutions(files: list) -> list:
    """Every resolution present in a manifest, biggest first."""
    found = {_res_of(f["path"]) for f in files}
    found.discard("")
    return sorted(found, key=lambda r: int(r[:-1]), reverse=True)


def subset(asset: dict, files: list, mode: str = FULL,
           resolution: str = "") -> list:
    """The manifest entries a given import actually wants.

    FULL is every file. HERO is the hero LOD and one resolution, which on a
    Megascans asset is the difference between 40 MB and 1 GB - the single thing
    that decides whether working from a remote library is pleasant.

    Selection reads `asset.json`, not the file names, wherever it can: the
    manifest is paths and sizes, while `lods` and `textures` already say which
    level is the hero and which file is bound to which slot. Names are only
    consulted for the resolution, because that IS a naming convention and the
    library wrote it.
    """
    if mode != HERO:
        return list(files)

    keep = set(ALWAYS)

    # Geometry only. The hero LOD is mirrored into the top level by schema v4,
    # so "hero only" is "the root bindings, and none of the lods[] entries".
    #
    # `textures` is deliberately NOT consulted here, and that is the whole
    # subtlety: invariant 13 says textures[slot] names the BIGGEST resolution.
    # Binding it would pull the 8k file into every subset, so asking for 4k
    # fetched the 8k as well and the light copy came out larger than the one
    # above it. The slot bindings say which maps exist; the resolution says
    # which file of each, and those are different questions.
    for entry in (asset.get("representations") or []):
        if entry.get("file"):
            keep.add(entry["file"])
    if asset.get("geo"):
        keep.add(asset["geo"])

    chosen, textures = [], {}
    for entry in files:
        path = entry["path"]
        top = path.split("/", 1)[0]
        if path in keep or top == "preview":
            chosen.append(entry)
            continue
        # extra/ is kept-but-uninterpreted by definition, and it is exactly the
        # payload nobody asked for when they asked for a light copy.
        if top in ("extra", "geo"):
            continue
        if top == "tex":
            textures.setdefault(_slot_key(path), []).append(entry)

    # One file per slot, chosen by resolution. Grouped first so that a slot
    # which simply has no file at the requested size still contributes its
    # closest one instead of vanishing - a missing roughness map is a broken
    # material, and silently shipping one is worse than shipping a bigger file.
    for group in textures.values():
        chosen.append(_pick_resolution(group, resolution))
    return chosen


def _slot_key(path: str) -> str:
    """'tex/x_basecolor_8k.png' -> 'tex/x_basecolor.png'. The slot, not the size."""
    p = Path(path)
    res = _res_of(path)
    stem = p.stem[: -(len(res) + 1)] if res else p.stem
    return f"{p.parent.as_posix()}/{stem}{p.suffix}"


def _pick_resolution(group: list, wanted: str):
    """The one file of a slot to fetch: the wanted size, or the nearest under it."""
    exact = [e for e in group if _res_of(e["path"]) == wanted]
    if exact:
        return exact[0]
    sized = [(int(_res_of(e["path"])[:-1]), e) for e in group if _res_of(e["path"])]
    if not sized:
        return group[0]             # no resolution token: it is the only one
    sized.sort()
    limit = int(wanted[:-1]) if wanted[:-1].isdigit() else 0
    under = [e for px, e in sized if px <= limit]
    return under[-1] if under else sized[0][1]


def total_bytes(files: list) -> int:
    return sum(int(f.get("size") or 0) for f in files)


def target_dir(cfg, asset: dict) -> Path:
    """cache_root/{type}/{category}/{name} - the same three levels as library/.

    Same shape on purpose: `houdini/build.py` walks a package without being
    told which root it came from, so a downloaded asset builds in Karma with
    nothing anywhere knowing it was downloaded.
    """
    return cfg.cache_root / asset["type"] / asset["category"] / asset["name"]


def _verify(path: Path, expected: str | None) -> str:
    """'' when good, otherwise why not. Unverifiable is NOT corrupt (gotcha 8)."""
    if not expected:
        return ""
    try:
        return "" if hashing.matches(path, expected) else "hash mismatch"
    except hashing.UnavailableAlgorithm:
        return ""


def materialise(cfg, host, uuid: str, mode: str = FULL, resolution: str = "",
                on_progress=None, should_stop=None) -> dict:
    """Download one asset into cfg.cache_root and return what happened.

    `on_progress(done_bytes, total_bytes, name)` is called as chunks land.
    `should_stop()` is polled; stopping leaves the `.part` files in place so the
    next attempt resumes rather than starting over.
    """
    payload = remote.asset(host, uuid)
    asset = payload["asset"]
    files = subset(asset, payload["files"], mode, resolution)
    total = total_bytes(files)

    dest = target_dir(cfg, asset)
    dest.mkdir(parents=True, exist_ok=True)

    # Counted in bytes, not files, and updated per CHUNK. A package is a few
    # 200 MB textures and a handful of tiny ones, so a per-file bar sits still
    # for minutes and then jumps - which reads as a hang.
    state = {"done": 0}
    failed = []

    def report(name: str) -> None:
        if on_progress is not None:
            on_progress(state["done"], total, name)

    for entry in files:
        if should_stop is not None and should_stop():
            return {"cancelled": True, "dir": dest, "bytes": state["done"],
                    "of": total, "failed": failed}

        rel = entry["path"]
        size = int(entry.get("size") or 0)
        final = dest / rel
        part = final.with_name(final.name + ".part")

        # Already here and intact: an interrupted import resumes at the file
        # level before it resumes at the byte level.
        if final.is_file() and not _verify(final, entry.get("hash")):
            state["done"] += size
            report(rel)
            continue

        def chunk(n: int, _rel=rel) -> None:
            state["done"] += n
            report(_rel)

        offset = part.stat().st_size if part.is_file() else 0
        try:
            state["done"] += offset          # already on disk from last time
            remote.fetch_file(host, uuid, rel, part, offset,
                              on_chunk=chunk, should_stop=should_stop)
        except remote.PartialMismatch:
            # The partial cannot be continued. Start it again from zero - once,
            # not in a loop, because a second failure is a real problem and
            # retrying forever would hide it.
            state["done"] -= offset
            part.unlink(missing_ok=True)
            remote.fetch_file(host, uuid, rel, part, 0,
                              on_chunk=chunk, should_stop=should_stop)

        if should_stop is not None and should_stop():
            return {"cancelled": True, "dir": dest, "bytes": state["done"],
                    "of": total, "failed": failed}

        problem = _verify(part, entry.get("hash"))
        if problem:
            # Deleted, not kept. A file that failed its hash is not a resume
            # point - continuing from it would append onto known-bad bytes.
            part.unlink(missing_ok=True)
            state["done"] -= size
            failed.append(f"{rel}: {problem}")
            continue

        final.parent.mkdir(parents=True, exist_ok=True)
        part.replace(final)
        report(rel)

    # Written last and verbatim. Not rebuilt from what arrived, and not passed
    # through Asset.new() - the uuid in here is the one the server has, and
    # keeping it is what makes this the same asset rather than a copy of it.
    with (dest / ASSET_FILE).open("w", encoding="utf-8") as fh:
        json.dump(asset, fh, indent=2)
        fh.write("\n")

    return {"cancelled": False, "dir": dest, "bytes": state["done"],
            "of": total, "failed": failed, "uuid": asset["uuid"],
            "asset": asset}
