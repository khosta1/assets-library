"""Bring every asset.json on disk up to the current schema.

Reading never needs this. `model.migrate()` upgrades an old file in memory on
every read, so a v1 package written a year ago still loads perfectly. This
module is about the FILES, not about compatibility: its job is to stop the
library becoming a permanent mix of schema versions.

The cost is paid once. `.assetlib/state.json` records the version last known to
be fully applied on disk; when it matches the code, startup reads one small file
and does nothing at all. Only a code upgrade triggers the O(n) walk.

That marker is an optimisation, never a guarantee - an older build writing into
a library already marked current would make it lie - so the same pass is also
reachable from Rebuild index and from Library > Migrate metadata, and `verify`
reports version skew. Three paths to one idempotent operation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .model import ASSET_FILE, SCHEMA_VERSION, Asset, iter_assets, on_disk_version

STATE_FILE = "state.json"


def state_path(cfg) -> Path:
    return cfg.state / STATE_FILE


def read_state(cfg) -> dict:
    try:
        with state_path(cfg).open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                # noqa: BLE001
        return {}


def write_state(cfg, assets: int) -> bool:
    """Record that the library is fully migrated. False if it cannot be written."""
    try:
        cfg.state.mkdir(parents=True, exist_ok=True)
        with state_path(cfg).open("w", encoding="utf-8") as fh:
            json.dump({
                "schema_version": SCHEMA_VERSION,
                "assets": assets,
                "migrated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, fh, indent=2)
            fh.write("\n")
        return True
    except OSError:
        return False                                 # read-only medium: not fatal


def pending(cfg) -> bool:
    """Might the files on disk be behind the code?

    The whole point of the marker: this is the question asked on every launch,
    and answering it must not cost a walk of the library.
    """
    return int(read_state(cfg).get("schema_version", 0)) < SCHEMA_VERSION


def run(cfg, progress=None) -> dict:
    """Rewrite every stale asset.json. Idempotent.

    Returns {upgraded, current, failed}. `failed` holds (path, reason) pairs and
    is never empty-swallowed: a package this build cannot read is the one thing
    the user has to be told about, because it means the library was written by a
    NEWER build than this one.
    """
    upgraded, current, failed = 0, 0, []
    directories = list(iter_assets(cfg.library))

    for index, asset_dir in enumerate(directories, 1):
        if progress:
            progress(asset_dir.name, index, len(directories))

        version = on_disk_version(asset_dir)
        if version is None:
            failed.append((asset_dir, f"unreadable {ASSET_FILE}"))
            continue
        if version > SCHEMA_VERSION:
            failed.append((asset_dir,
                           f"schema v{version}, this build understands v{SCHEMA_VERSION}"))
            continue
        if version == SCHEMA_VERSION:
            current += 1
            continue

        try:
            # read() migrates in memory; write() is atomic, so an interrupted
            # pass can never leave a truncated asset.json behind.
            Asset.read(asset_dir).write(asset_dir)
            upgraded += 1
        except Exception as exc:                     # noqa: BLE001
            failed.append((asset_dir, str(exc)))

    # Only claim the library is current when nothing was left behind, otherwise
    # the next launch would skip the pass and the skew would go unnoticed.
    if not failed:
        write_state(cfg, upgraded + current)

    return {"upgraded": upgraded, "current": current, "failed": failed}


def run_if_pending(cfg, progress=None):
    """The startup path: O(1) when the marker says there is nothing to do."""
    if not pending(cfg):
        return None
    return run(cfg, progress)


def describe(result) -> str:
    """One line for a status bar. Empty when there is nothing worth saying."""
    if not result:
        return ""
    bits = []
    if result["upgraded"]:
        bits.append(f"upgraded {result['upgraded']} asset(s) to schema v{SCHEMA_VERSION}")
    if result["failed"]:
        bits.append(f"{len(result['failed'])} could NOT be read")
    return " - ".join(bits)
