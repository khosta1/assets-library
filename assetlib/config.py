"""Loads the four JSON configs that define the library.

Nothing about the library's shape is hardcoded in Python: types, categories,
slots and the tree layout all come from config/*.json.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILES = ("library", "types", "categories", "texture_slots")


def _strip_notes(obj):
    """Drop the "_note"/"_xxx" documentation keys so callers see only data."""
    if isinstance(obj, dict):
        return {k: _strip_notes(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_notes(v) for v in obj]
    return obj


class Config:
    def __init__(self, base: Path):
        self.base = Path(base).resolve()
        cfg_dir = self.base / "config"
        if not cfg_dir.is_dir():
            raise FileNotFoundError(f"no config/ directory in {self.base}")

        raw = {}
        for name in CONFIG_FILES:
            path = cfg_dir / f"{name}.json"
            if not path.is_file():
                raise FileNotFoundError(f"missing config file: {path}")
            with path.open(encoding="utf-8") as fh:
                raw[name] = _strip_notes(json.load(fh))

        self.library_cfg = raw["library"]
        self.types = raw["types"]["types"]
        self.type_by_id = {t["id"]: t for t in self.types}
        self.geometry_ext = {e.lower() for e in raw["types"].get("geometry_ext", [])}
        self.categories = raw["categories"]["categories"]
        self.category_rules = raw["categories"].get("rules", {})
        self.slots_cfg = raw["texture_slots"]

        roots = self.library_cfg["roots"]
        self.library = self.base / roots["library"]
        self.inbox = self.base / roots["inbox"]
        self.quarantine = self.base / roots["quarantine"]
        self.state = self.base / roots["state"]

        self.naming = self.library_cfg["naming"]
        self.package = self.library_cfg["package"]
        self.cache = self.library_cfg.get("cache", {})

    # ------------------------------------------------------------------ paths

    def asset_dir(self, type_id: str, category: str, asset: str) -> Path:
        """library/{type}/{category}/{asset}/ - the only shape allowed."""
        return self.library / type_id / category / asset

    def ensure_roots(self) -> None:
        for p in (self.library, self.inbox, self.quarantine, self.state):
            p.mkdir(parents=True, exist_ok=True)
        (self.state / "thumbs").mkdir(exist_ok=True)

    def ensure_tree(self) -> None:
        """Materialise the full declared taxonomy, empty.

        The hierarchy is prescriptive: it exists because the config says so,
        not because assets happen to be there.
        """
        for t in self.types:
            for cat in self.categories.get(t["id"], ["misc"]):
                (self.library / t["folder"] / cat).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- vocabulary

    def categories_for(self, type_id: str) -> list:
        return self.categories.get(type_id, ["misc"])

    def valid_category(self, type_id: str, category: str) -> bool:
        return category in self.categories_for(type_id)

    def db_path(self) -> Path:
        return self.state / "index.db"

    def thumbs_dir(self) -> Path:
        return self.state / "thumbs"


def find_config(start: Path | None = None) -> Config:
    """Walk up from `start` looking for a directory containing config/library.json."""
    here = Path(start or Path(__file__).parent).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "config" / "library.json").is_file():
            return Config(candidate)
    raise FileNotFoundError("could not locate an asset library (config/library.json)")
