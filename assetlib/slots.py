"""Texture slot matching.

Order is significant: the first slot whose keyword appears in the filename wins,
which is why `diffuse` sits last in the config as the catch-all. This is the only
place in the codebase that guesses anything about a texture - after import the
filenames are normalised and nothing downstream ever guesses again.
"""

from __future__ import annotations

import re
from pathlib import Path

PREVIEW = "__preview__"


class SlotMatcher:
    def __init__(self, cfg):
        s = cfg.slots_cfg
        self.slots = s["slots"]
        self.by_key = {sl["key"]: sl for sl in self.slots}
        self.output_names = s["output_names"]
        self.format_priority = s["format_priority"]
        self.preview_stems = [p.lower() for p in s["preview_stems"]]
        self.preview_rules = s.get("preview_rules", {})
        m = s.get("matching", {})
        self.udim_patterns = [re.compile(p) for p in m.get("udim_patterns", [])]
        low, high = m.get("udim_range", [1001, 1999])
        self.udim_range = (int(low), int(high))
        self.min_slots = int(m.get("min_slots_for_texture_set", 2))

    # ---------------------------------------------------------------- matching

    def _tile(self, found):
        """The UDIM number a match represents, or None if it is not a tile.

        Two groups means the u/v form: Mari writes `_u1_v1` 1-based, so the tile
        is 1001 + (u-1) + (v-1)*10. The old code read group(1) only, which threw
        v away and put every row of the grid on tile u.
        """
        groups = [g for g in found.groups() if g is not None]
        if not groups:
            return None
        if len(groups) >= 2:
            tile = 1001 + (int(groups[0]) - 1) + (int(groups[1]) - 1) * 10
        else:
            tile = int(groups[0])
        low, high = self.udim_range
        return tile if low <= tile <= high else None

    def _clean_stem(self, filename: str) -> tuple[str, str | None]:
        """Strip the UDIM tile off a name, returning (stem, tile).

        The stem is probed with its delimiter restored - `name.1001.exr` becomes
        `name.1001.` - because the dominant Mari convention puts the tile last.
        Once Path.stem removes the extension the name ENDS at `.1001`, so a
        pattern anchored on a trailing dot never fired: every tile of a set
        landed on the same slot and all but one were rejected as duplicates.
        """
        stem = Path(filename).stem.lower()
        probe = stem + "."
        for pattern in self.udim_patterns:
            found = pattern.search(probe)
            if not found:
                continue
            tile = self._tile(found)
            if tile is None:
                continue                     # a 4-digit number that is not a tile
            cleaned = probe[:found.start()] + "_" + probe[found.end():]
            cleaned = re.sub(r"[_.]+", "_", cleaned).strip("_.")
            return cleaned, f"{tile:04d}"
        return stem, None

    def match(self, filename: str, asset_base: str | None = None):
        """Return (slot_key | PREVIEW | None, udim, variant)."""
        stem, udim = self._clean_stem(filename)

        if stem in self.preview_stems or any(p in stem for p in self.preview_stems):
            return PREVIEW, udim, None

        # A bare stem equal to the asset name, with no slot suffix, is the vendor
        # preview render. ambientCG ships exactly this: Concrete014.png.
        if (
            self.preview_rules.get("bare_stem_is_preview")
            and asset_base
            and stem == asset_base.lower()
        ):
            return PREVIEW, udim, None

        for slot in self.slots:
            if any(kw in stem for kw in slot["keywords"]):
                return slot["key"], udim, self._variant(slot, stem)
        return None, udim, None

    @staticmethod
    def _variant(slot: dict, stem: str) -> str | None:
        variants = slot.get("variants")
        if not variants:
            return None
        for name, keys in variants.items():
            if any(k in stem for k in keys):
                return name
        return None

    # ------------------------------------------------------------------ policy

    def is_color_slot(self, key: str) -> bool:
        slot = self.by_key.get(key)
        return bool(slot and slot.get("colorspace") == "srgb_texture")

    def format_rank(self, key: str, ext: str) -> int:
        """Higher is better. Unlisted formats rank below every listed one."""
        table = (
            self.format_priority["color_slots"]
            if self.is_color_slot(key)
            else self.format_priority["data_slots"]
        )
        ext = ext.lower()
        return table.index(ext) if ext in table else -1

    def keep_variant(self, key: str) -> str | None:
        """Which variant of a slot the library stores (normals: opengl only)."""
        return self.by_key.get(key, {}).get("keep")

    def output_filename(self, asset: str, key: str, ext: str, udim: str | None = None,
                        lod: int | None = None) -> str:
        """<asset>[_lodN]_<slot>[.udim].<ext>

        The LOD token sits before the slot so a directory listing groups a
        level's maps together, which is how you actually read them. An asset
        without LODs gets no token at all.
        """
        suffix = self.output_names.get(key, key)
        tile = f".{udim}" if udim else ""
        level = f"_lod{lod}" if lod else ""
        return f"{asset}{level}_{suffix}{tile}{ext.lower()}"
