"""Bounded per-file preview cache in .assetlib/thumbs/.

Distinct from `preview/thumb.jpg`, which belongs to the package and is
permanent. This one is for the asset viewer, which may want twenty previews of
one asset, and it is a cache in the full sense: derived, deletable, and capped.

Three rules keep it from growing without limit:

  * tiles are small - a grid tile is never bigger than 256px, so rendering at
    512 would be four times the bytes for pixels nobody sees;
  * cheap files are not cached at all - a 300 KB png re-decodes in milliseconds
    and an entry would buy nothing, while a 189 MB TIFF is exactly the case
    worth keeping;
  * a hard budget, swept least-recently-used at startup.

All three come from config/library.json, so the size of this thing is a number
in a JSON file rather than a decision buried in code.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QRunnable, QThreadPool

from assetlib.thumbnail import thumb_bytes

DEFAULT_PX = 256
DEFAULT_MIN_BYTES = 2 * 1024 * 1024
DEFAULT_BUDGET_MB = 500


def _setting(cfg, key: str, fallback):
    try:
        return int(cfg.cache.get(key, fallback))
    except (AttributeError, TypeError, ValueError):
        return fallback


def tile_px(cfg) -> int:
    return _setting(cfg, "thumbs_px", DEFAULT_PX)


def _key(rel: str, size: int, mtime: float) -> str:
    """Identity of one rendering. Size and mtime are in the key, so an edited
    file simply misses instead of serving a stale picture."""
    raw = f"{rel}|{size}|{int(mtime)}".encode("utf-8")
    return hashlib.blake2b(raw, digest_size=12).hexdigest()


def get(cfg, uuid: str, path: Path, rel: str):
    """JPEG bytes for one file inside a package, or None if undecodable."""
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return None

    px = tile_px(cfg)
    worth_caching = stat.st_size >= _setting(cfg, "thumbs_min_bytes", DEFAULT_MIN_BYTES)
    target = cfg.thumbs_dir() / uuid / f"{_key(rel, stat.st_size, stat.st_mtime)}.jpg"

    if worth_caching and target.is_file():
        try:
            data = target.read_bytes()
            target.touch()          # mtime is the recency mark the sweep reads
            return data
        except OSError:
            pass

    data = thumb_bytes(path, px)
    if data and worth_caching:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError:
            pass                    # a cache that cannot be written is not an error
    return data


def sweep(cfg) -> int:
    """Delete least-recently-used entries until the cache is under budget.

    Returns the bytes freed. Called at startup, where a moment of disk work is
    invisible and the alternative is a directory that only ever grows.
    """
    budget = _setting(cfg, "thumbs_budget_mb", DEFAULT_BUDGET_MB) * 1024 * 1024
    root = cfg.thumbs_dir()
    if budget <= 0 or not root.is_dir():
        return 0

    entries = []
    total = 0
    for path in root.rglob("*.jpg"):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, path))
        total += stat.st_size
    if total <= budget:
        return 0

    freed = 0
    for _, size, path in sorted(entries):        # oldest touch first
        try:
            path.unlink()
        except OSError:
            continue
        freed += size
        if total - freed <= budget:
            break

    for folder in root.iterdir():                # drop the emptied asset folders
        if folder.is_dir() and not any(folder.iterdir()):
            try:
                folder.rmdir()
            except OSError:
                pass
    return freed


class _SweepJob(QRunnable):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.setAutoDelete(True)

    def run(self):
        try:
            sweep(self.cfg)
        except Exception:                       # noqa: BLE001 - housekeeping only
            pass


def sweep_async(cfg) -> None:
    """Bound the cache without charging the user for it at startup.

    A full cache is tens of thousands of files to stat. That is a second of
    nothing on the launch path, for work with no deadline - so it happens on the
    pool once the window is already up.
    """
    QThreadPool.globalInstance().start(_SweepJob(cfg))


def forget(cfg, uuid: str) -> None:
    """Drop one asset's entries - after an edit, everything about it may differ."""
    folder = cfg.thumbs_dir() / uuid
    if not folder.is_dir():
        return
    for path in folder.glob("*.jpg"):
        try:
            path.unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass
