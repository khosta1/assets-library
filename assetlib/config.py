"""Loads the four JSON configs that define the library.

Nothing about the library's shape is hardcoded in Python: types, categories,
slots and the tree layout all come from config/*.json.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILES = ("library", "types", "categories", "texture_slots")

# Where an asset physically is. Carried on every index row and every Houdini
# request, because "library/{type}/{category}/{asset}" stopped being enough the
# moment a second root existed: the same relative path is valid under both.
ORIGIN_LOCAL = "local"
ORIGIN_CACHE = "cache"
REMOTE_PREFIX = "remote:"          # remote:<host> - catalogued, not on this disk


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
        self.derived_ext = {e.lower() for e in raw["types"].get("derived_ext", [])}
        self.categories = raw["categories"]["categories"]
        self.category_rules = raw["categories"].get("rules", {})
        self.slots_cfg = raw["texture_slots"]

        roots = self.library_cfg["roots"]
        self.library = self.base / roots["library"]
        # cache_root, not cache: `self.cache` is already the thumbnail cache
        # SETTINGS dict below, and two things called cache in one object is how
        # a caller ends up joining a path onto a dict.
        self.cache_root = self.base / roots.get("cache", "_cache")
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

    def root_for(self, origin: str | None) -> Path | None:
        """Origin -> the root it lives under, or None when it is not on this disk.

        None is a real answer, not a failure: a remote asset is catalogued and
        browsable without a single byte of it being here, which is the whole
        point of syncing the catalogue separately from the files. Callers must
        handle it rather than assuming every row has a path.
        """
        if not origin or origin == ORIGIN_LOCAL:
            return self.library
        if origin == ORIGIN_CACHE:
            return self.cache_root
        return None

    def asset_path(self, row) -> Path | None:
        """Index row -> package directory. The ONE place that join is made.

        Every caller used to write `cfg.library / row["path"]`, which was true
        while there was one root and silently wrong the moment there were two -
        the same relative path resolves under both, so the mistake produces a
        real directory rather than an error.

        Takes a dict OR a raw `sqlite3.Row`, which is why the lookup is spelt
        this way instead of `row.get("origin")`: a Row has no `.get()` and
        raises AttributeError rather than falling back to `__getitem__`. Callers
        coming from index.search() hold dicts, but anything holding the result
        of a fetchone() does not, and a function advertised as the one place
        every path is built must not be picky about which of the two it gets.
        """
        keys = row.keys()
        origin = row["origin"] if "origin" in keys else None
        return None if (root := self.root_for(origin)) is None else root / row["path"]

    def root_containing(self, path: Path) -> Path | None:
        """Which root a package sits under. For code holding a path, not a row."""
        path = Path(path).resolve()
        for root in (self.library, self.cache_root):
            try:
                path.relative_to(root.resolve())
            except ValueError:
                continue
            return root
        return None

    def ensure_roots(self) -> None:
        for p in (self.library, self.cache_root, self.inbox, self.quarantine,
                  self.state):
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

    # ---------------------------------------------------------------- remote

    def remote_dir(self) -> Path:
        """Everything to do with a remote library: hosts, catalogues, thumbs.

        Under .assetlib/ and not beside _cache/, because all of it is genuinely
        disposable - a deleted catalogue re-syncs in one request. _cache/ holds
        the downloaded FILES, which do not.
        """
        return self.state / "remote"

    def remote_db_path(self, host_name: str) -> Path:
        """One catalogue per host, in a SECOND database.

        Not a table in index.db and not a flag on a shared row. The local index
        is rebuilt from disk by F5 and a remote catalogue cannot be - mixing
        them would mean F5 either wipes the remote rows or has to know how to
        talk HTTP, and both are worse than two files.
        """
        return self.remote_dir() / f"{host_name}.db"

    def remote_thumbs_dir(self) -> Path:
        return self.remote_dir() / "thumbs"


def find_config(start: Path | None = None) -> Config:
    """Walk up from `start` looking for a directory containing config/library.json."""
    here = Path(start or Path(__file__).parent).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "config" / "library.json").is_file():
            return Config(candidate)
    raise FileNotFoundError("could not locate an asset library (config/library.json)")
