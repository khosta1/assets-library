"""Generating the regenerable: `.rat` and `.tx` into `derived/`.

`derived/` has existed in every package since the first commit and has been
empty in all of them. This is what fills it.

**Why it is worth doing at all.** Karma reads a `.jpg` by converting it first —
and it writes the result *beside the source*, in `tex/`, because nothing told it
otherwise. On 2026-09-13 that was 60 files and 1.85 GB of `.rat` scattered
through packages, every one of them an orphan `verify` reports and none of them
in the place the design named for exactly this. Hand Karma a `.rat` and there is
nothing left for it to convert: the strays stop being generated rather than
being cleaned up afterwards.

**On demand, not at import.** Measured with Houdini 20.5's `iconvert`:

    2K jpg    1.6 MB  ->    9.0 MB  .rat   1.0 s
    8K jpg   43.2 MB  ->  150.2 MB  .rat   4.6 s

Baking all 111 assets would be ~900 conversions, roughly +100 GB on a library
of 43.75 GB, most of it for assets nobody renders this year. So it happens when
an asset is actually built, and a batch action exists for pre-baking a shelf
before a job.

**No `hou` import.** The converters are executables that ship with Houdini and
are called as subprocesses, which is what lets this module live in `assetlib`
alongside everything else the rule covers.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from .model import expand

# fmt -> (executable, argv builder). `.rat` is Houdini's own; `.tx` is the OIIO
# build Houdini ships, which is what Arnold and RenderMan read.
CONVERTERS = {
    ".rat": ("iconvert", lambda src, dst: [str(src), str(dst)]),
    ".tx": ("hoiiotool", lambda src, dst: [str(src), "--tile", "64", "64",
                                           "-otex", str(dst)]),
}

DEFAULT_FORMAT = ".rat"

# Searched in order; the FIRST existing one wins, and newest-first because that
# is the Houdini being run. Overridable per format with ASSETLIB_ICONVERT /
# ASSETLIB_HOIIOTOOL, which is also how a non-standard install is handled
# without this list growing.
SEARCH_ROOTS = (
    r"C:\Program Files\Side Effects Software",
    r"D:\Program Files\Side Effects Software",
    "/opt",
    "/usr/local",
)

_CACHE: dict = {}


class NoConverter(RuntimeError):
    """No Houdini binary found for this format. Not an error worth crashing on.

    Generating a bake is an optimisation: without it Houdini reads the source
    texture and everything still renders. So every caller treats this as "skip",
    never as "fail".
    """


def _hou_dirs() -> list:
    """Houdini installs, newest first, by the version in the folder name."""
    found = []
    for root in SEARCH_ROOTS:
        base = Path(root)
        if not base.is_dir():
            continue
        try:
            for child in base.iterdir():
                if child.is_dir() and re.search(r"(?i)h(oudini|fs)[ .-]?\d", child.name):
                    found.append(child)
        except OSError:
            continue

    def version(path: Path) -> tuple:
        nums = re.findall(r"\d+", path.name)
        return tuple(int(n) for n in nums) or (0,)

    return sorted(found, key=version, reverse=True)


def converter(fmt: str = DEFAULT_FORMAT) -> Path:
    """The executable that makes `fmt`. Raises NoConverter when there is none."""
    if fmt in _CACHE:
        return _CACHE[fmt]
    if fmt not in CONVERTERS:
        raise NoConverter(f"no converter is defined for {fmt}")

    name = CONVERTERS[fmt][0]
    override = os.environ.get(f"ASSETLIB_{name.upper()}")
    exe = f"{name}.exe" if sys.platform == "win32" else name

    candidates = [Path(override)] if override else []
    candidates += [d / "bin" / exe for d in _hou_dirs()]
    for path in candidates:
        if path.is_file():
            _CACHE[fmt] = path
            return path
    raise NoConverter(
        f"{exe} not found - it ships with Houdini. Set ASSETLIB_{name.upper()} "
        "to its full path if Houdini is installed somewhere unusual.")


def available(fmt: str = DEFAULT_FORMAT) -> bool:
    try:
        converter(fmt)
        return True
    except NoConverter:
        return False


# --------------------------------------------------------------------- paths


def derived_rel(tex_rel: str, fmt: str = DEFAULT_FORMAT) -> str:
    """'tex/x_basecolor.jpg' -> 'derived/x_basecolor.rat'.

    The stem is kept whole, so the slot, the LOD, the resolution and the UDIM
    token all survive - `x_basecolor.<UDIM>.jpg` becomes
    `x_basecolor.<UDIM>.rat`, which is still the spelling Houdini resolves.

    Only the extension changes, unlike Karma's own `x.jpg.rat`. Ours are named
    by what they are, not by what they were, and the doubled extension is how
    you tell a stray apart from one of these at a glance.
    """
    p = Path(tex_rel)
    return f"derived/{p.stem}{fmt}"


def is_current(src: Path, dst: Path) -> bool:
    """A bake is current when it exists and is not older than its source.

    mtime rather than a hash: these are regenerable by definition, so the cost
    of being wrong is one needless conversion, while hashing a 150 MB file to
    avoid a 4 s conversion is the more expensive mistake.
    """
    try:
        return dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime
    except OSError:
        return False


# ---------------------------------------------------------------- converting


def convert(src: Path, dst: Path, fmt: str = DEFAULT_FORMAT,
            timeout: int = 600) -> None:
    """Run one conversion. Raises on failure; the caller decides what that means."""
    exe = converter(fmt)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")

    # CREATE_NO_WINDOW: iconvert is a console program, and a black window
    # flashing up once per texture - hundreds of times in a batch - is exactly
    # what the launcher was rewritten to stop (gotcha 18's neighbour).
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    argv = [str(exe)] + CONVERTERS[fmt][1](src, tmp)
    proc = subprocess.run(argv, capture_output=True, text=True,
                          timeout=timeout, creationflags=flags, check=False)

    if proc.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(f"{exe.name} failed on {src.name}: "
                           + (detail[-1] if detail else f"exit {proc.returncode}"))

    # Written to .part and renamed, so an interrupted conversion never leaves a
    # truncated bake that `is_current` would then believe.
    tmp.replace(dst)


def ensure(asset_dir: Path, tex_rel: str, fmt: str = DEFAULT_FORMAT,
           generate: bool = True) -> str | None:
    """The package-relative bake for one texture, making it if needed.

    Returns None rather than raising when there is no converter or the source
    is missing: the caller falls back to the original texture and everything
    still renders, just slower. A missing optimisation is not a failure.

    A `<UDIM>` binding is refused here and belongs to `ensure_udim`, which needs
    the asset to know which tiles exist. Refusing is deliberate: converting the
    literal token path would produce a file called `x_basecolor.<UDIM>.rat` that
    nothing can ever resolve.
    """
    rel_out = derived_rel(tex_rel, fmt)
    src = asset_dir / tex_rel
    dst = asset_dir / rel_out

    if "<UDIM>" in tex_rel:
        return None

    if not src.is_file():
        return None
    if is_current(src, dst):
        return rel_out
    if not generate:
        return None
    try:
        convert(src, dst, fmt)
    except (NoConverter, RuntimeError, subprocess.TimeoutExpired):
        return None
    return rel_out


def ensure_udim(asset, asset_dir: Path, tex_rel: str,
                fmt: str = DEFAULT_FORMAT, generate: bool = True) -> str | None:
    """Same, for a `<UDIM>` binding: every tile, answered with the token path.

    All or nothing. A half-converted set is worse than none - Houdini would
    resolve the token, find some tiles missing and render holes, which looks
    like a broken asset rather than a missing optimisation.
    """
    rel_out = derived_rel(tex_rel, fmt)
    tiles = [t for t in expand(asset, tex_rel)]
    if not tiles:
        return None
    for tile_rel in tiles:
        src = asset_dir / tile_rel
        dst = asset_dir / derived_rel(tile_rel, fmt)
        if not src.is_file():
            return None
        if is_current(src, dst):
            continue
        if not generate:
            return None
        try:
            convert(src, dst, fmt)
        except (NoConverter, RuntimeError, subprocess.TimeoutExpired):
            return None
    return rel_out


def bake_asset(asset, asset_dir: Path, fmt: str = DEFAULT_FORMAT,
               on_file=None, should_stop=None) -> dict:
    """Every bound texture of one asset. For the batch action, not for a build.

    Walks `textures` AND `resolutions`, because a shelf pre-baked before a job
    should cover whichever size the artist picks in the options dialog, not only
    the biggest.
    """
    wanted: list = []
    for rel in (asset.textures or {}).values():
        if rel and rel not in wanted:
            wanted.append(rel)
    for sizes in (asset.resolutions or {}).values():
        for rel in (sizes or {}).values():
            if rel and rel not in wanted:
                wanted.append(rel)

    made, skipped, failed = 0, 0, []
    for i, rel in enumerate(wanted):
        if should_stop is not None and should_stop():
            break
        if on_file is not None:
            on_file(i + 1, len(wanted), rel)
        dst_rel = derived_rel(rel, fmt)
        src = asset_dir / rel
        if "<UDIM>" in rel:
            out = ensure_udim(asset, asset_dir, rel, fmt)
        else:
            if is_current(src, asset_dir / dst_rel):
                skipped += 1
                continue
            out = ensure(asset_dir, rel, fmt)
        if out is None:
            failed.append(rel)
        else:
            made += 1
    return {"made": made, "skipped": skipped, "failed": failed,
            "of": len(wanted)}
