"""Name normalisation.

The library owns its names. Source names are input, never authority.
Resolution and format tokens are stripped so that a 4K and an 8K version of the
same asset resolve to the SAME name and merge as variants rather than becoming
two unrelated assets.
"""

from __future__ import annotations

import re
from pathlib import Path

_PAREN_DUP = re.compile(r"\(\s*\d+\s*\)")
_SEPARATORS = re.compile(r"[\s\-.]+")
_ILLEGAL = re.compile(r"[^a-z0-9_]")
_REPEATS = re.compile(r"_+")


def normalise(name: str, cfg) -> str:
    """'Concrete014_8K-PNG' -> 'concrete014'."""
    strip = {t.lower() for t in cfg.naming.get("strip_tokens", [])}
    max_len = int(cfg.naming.get("max_length", 64))

    n = name.lower()
    n = _PAREN_DUP.sub("", n)
    n = _SEPARATORS.sub("_", n)
    parts = [p for p in n.split("_") if p and p not in strip]
    n = "_".join(parts)
    n = _ILLEGAL.sub("", n)
    n = _REPEATS.sub("_", n).strip("_")
    return n[:max_len] or "unnamed"


def split_lod(stem: str, cfg) -> tuple:
    """'mushroom_001_LOD2_albedo' -> ('mushroom_001_albedo', 2).

    LOD is a second dimension, not part of the name: four levels of detail are
    one asset. The token is stripped wherever it sits so every file of the set
    resolves to the same asset name, and re-inserted at a known place on the way
    out. Returns (stem, None) when there is no LOD.
    """
    pattern = cfg.naming.get("lod", {}).get("pattern")
    if not pattern:
        return stem, None
    found = re.search(pattern, stem, re.I)
    if not found:
        return stem, None
    cleaned = f"{stem[:found.start()]}_{stem[found.end():]}"
    cleaned = _REPEATS.sub("_", cleaned).strip("_")
    return cleaned, int(found.group(1))


def split_variant(stem: str, cfg) -> tuple:
    """'dactylisglomerata_hznoe_big' -> ('dactylisglomerata_hznoe', 'big').

    A variant is a SECOND version of the same asset that has to be KEPT, which
    is the opposite of the texture `variants` in texture_slots.json - those name
    a thing the library deliberately stores only one of. Megascans ships a Big
    and a Small mesh of one plant, sharing one texture set; before this the
    second lost the (ext, lod) contest and never imported at all.

    Stripped from the stem for the same reason LOD is: two variants are one
    asset, so both must resolve to one name. Returns (stem, None) when nothing
    matches.

    The result is a PRE-FILL, never a decision. The Var column in the Add window
    is what settles it, because a token that looks like a variant but is part of
    the real name is the mistake a person catches at a glance and a pattern
    never will.
    """
    patterns = cfg.naming.get("variant_patterns") or []
    for pattern in patterns:
        found = re.search(rf"(?:^|_)({pattern})(?=_|$)", stem, re.I)
        if not found:
            continue
        cleaned = f"{stem[:found.start()]}_{stem[found.end():]}"
        cleaned = _REPEATS.sub("_", cleaned).strip("_")
        return cleaned, found.group(1).lower()
    return stem, None


def unique_name(base: str, parent: Path) -> str:
    """Append _02, _03 ... until the name is free inside `parent`."""
    if not (parent / base).exists():
        return base
    for i in range(2, 100):
        candidate = f"{base}_{i:02d}"
        if not (parent / candidate).exists():
            return candidate
    raise RuntimeError(f"too many name collisions for {base!r} in {parent}")


def guess_category(source_name: str, type_id: str, cfg) -> str | None:
    """Best-effort category from the source name, restricted to the closed list.

    Returns None rather than guessing wildly - the user picks at confirm time.
    """
    cats = cfg.categories_for(type_id)
    haystack = normalise(source_name, cfg)
    # longest category name first, so 'concrete' beats a hypothetical 'con'
    for cat in sorted(cats, key=len, reverse=True):
        if cat == "misc":
            continue
        if cat in haystack or cat.rstrip("s") in haystack:
            return cat
    return None
