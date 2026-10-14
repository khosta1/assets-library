"""Fetch one Poly Haven category into _inbox/, ready for port.py.

    runtime\\python.exe fetch_polyhaven.py textures ground-terrain

A FETCHER, not a front-end (decisions.md, Reversed, 2026-10-14): it writes only
into _inbox/, imports nothing from assetlib, and declares no type or category.
The moment it does any of those it falls under the 2026-08-21 rule. Procedure,
what is taken and why: docs/polyhaven.md.

Serial, one file at a time, md5-checked, resumable: a rerun skips every file
already on disk with the right size and md5. Poly Haven's terms ask for a
User-Agent naming the software (2.4) and forbid degrading the API (2.6).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = "https://api.polyhaven.com"
UA = "AssetsLibrary/1.0 (personal asset library, CC0 port)"

RES = ("1k", "4k", "8k")                 # Felix, 2026-10-14
FORMATS = ("jpg", "png", "exr")          # first one present wins
# nor_dx: library keeps OpenGL only, would be rejected. arm: unpacked maps
# exist and win anyway. blend/gltf/mtlx: sidecars naming files the import
# renames. rough_ao: rough x ao baked into one image, shipped beside both. It
# matches roughness first and wins the tie on stem length, pushing the real
# roughness into extra/ - dropped here rather than a slot rule made from one
# vendor (porting.md, trap 8).
SKIP_MAPS = {"blend", "gltf", "mtlx", "nor_dx", "arm", "rough_ao"}
PAUSE_S = 1.0                            # between assets: courtesy, one stream already
ATTEMPTS = 3


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def request(url: str):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120)


def get_json(url: str):
    with request(url) as r:
        return json.load(r)


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dst: Path, size: int | None = None, md5: str | None = None) -> int:
    """Bytes downloaded; 0 when the file was already there and good."""
    if dst.is_file() and (size is None or dst.stat().st_size == size) \
            and (md5 is None or md5_of(dst) == md5):
        return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    last = None
    for attempt in range(ATTEMPTS):
        try:
            h, n = hashlib.md5(), 0
            with request(url) as r, tmp.open("wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
            if md5 and h.hexdigest() != md5:
                raise ValueError(f"md5 mismatch on {dst.name}")
            # .part + rename: a cut download never looks complete to a rerun
            # or to port.py.
            tmp.replace(dst)
            return n
        except Exception as exc:        # noqa: BLE001
            last = exc
            time.sleep(5 * (attempt + 1))
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"{dst.name}: {last}")


def roots() -> dict:
    """config/library.json roots, read as plain JSON: importing assetlib's
    Config for two paths would make the fetcher a front-end."""
    cfg = json.loads((ROOT / "config" / "library.json").read_text(encoding="utf-8"))
    return {k: ROOT / v for k, v in cfg["roots"].items() if not k.startswith("_")}


def library_names() -> set:
    """Package folder names already in the library, read straight off disk."""
    lib = roots()["library"]
    names = set()
    for t in (p for p in lib.iterdir() if p.is_dir()):
        for c in (p for p in t.iterdir() if p.is_dir()):
            names.update(p.name for p in c.iterdir() if p.is_dir())
    return names


def thumb_url(url: str) -> str:
    """Same CDN image at 512 px, as png: drop format=webp, keep the version hash."""
    parts = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(parts.query))
    q.pop("format", None)
    q["width"] = q["height"] = "512"
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("type", choices=["textures"],
                    help="textures only: HDRIs and models need their own rules first (docs/polyhaven.md)")
    ap.add_argument("category", help="Poly Haven slugPath, e.g. ground-terrain or ground-terrain/sand")
    args = ap.parse_args()

    tag = args.category.replace("/", "-")
    inbox = roots()["inbox"] / "polyhaven"
    dest = inbox / tag
    meta_path = inbox / f"{tag}.meta.json"

    assets = get_json(f"{API}/assets?type={args.type}&category={urllib.parse.quote(args.category)}")
    if not assets:
        log(f"no {args.type} in {args.category!r} - check the slugPath against /taxonomy/{args.type}")
        return 1
    have = library_names()
    # Beside the root, not in it: port.py plan reads every folder in the root
    # as an asset.
    meta = {slug: {**info, "in_library": slug in have} for slug, info in assets.items()}
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"{len(assets)} {args.type} in {args.category}; "
        f"{sum(m['in_library'] for m in meta.values())} already in library")

    todo = [s for s in sorted(assets) if s not in have]
    total, failed = 0, []
    for i, slug in enumerate(todo, 1):
        got, files = 0, 0
        try:
            tree = get_json(f"{API}/files/{slug}")
            for name, by_res in tree.items():
                if name in SKIP_MAPS or not isinstance(by_res, dict):
                    continue
                for res in RES:
                    fmts = by_res.get(res) or {}
                    fmt = next((f for f in FORMATS if f in fmts), None)
                    if fmt is None:
                        continue
                    o = fmts[fmt]
                    target = dest / slug / Path(urllib.parse.urlsplit(o["url"]).path).name
                    got += fetch(o["url"], target, o.get("size"), o.get("md5"))
                    files += 1
            # 512 png first; the listed webp only if the CDN refuses the resize.
            turl = assets[slug].get("thumbnail_url")
            if turl:
                try:
                    got += fetch(thumb_url(turl), dest / slug / f"{slug}_thumb.png")
                except RuntimeError:
                    got += fetch(turl, dest / slug / f"{slug}_thumb.webp")
        except Exception as exc:        # noqa: BLE001
            failed.append(f"{slug}: {exc}")
            log(f"[{i}/{len(todo)}] {slug}  FAILED  {exc}")
            continue
        total += got
        log(f"[{i}/{len(todo)}] {slug}  {files} maps  +{got / 1e6:.0f} MB  (total {total / 1e9:.1f} GB)")
        if got:
            time.sleep(PAUSE_S)

    log(f"done: {len(todo) - len(failed)}/{len(todo)} assets, {total / 1e9:.1f} GB downloaded")
    for f in failed:
        log(f"  FAILED {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
