"""Where the library, the catalogue and the stamp live on the server.

Shared by the API and the re-indexer so the two can never disagree about which
tree they are looking at.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from assetlib.config import Config, find_config

# Written by reindex.py, read by the API. The catalogue's ETag comes from here
# and NOT from index.db's mtime: the database is opened WAL, so writes land in
# a -wal sidecar and the main file's mtime does not move until a checkpoint.
# An ETag that lags a re-index is a client that never sees the new assets.
STAMP = "catalog.stamp"


def load_config() -> Config:
    """The library config, with the server's paths applied over it.

    Overridden here rather than in `config/library.json` because the box's copy
    of that file would then differ from the repo's - and a config that must
    differ between two machines is exactly the drift the server panel forbids
    `deploy.bat` from causing with its own `config.json`. An override set in the
    unit file is visible in `systemctl cat` and cannot be clobbered by a copy.
    """
    cfg = find_config(Path(os.environ.get("ASSETLIB_BASE", "/opt/assetlib")))

    if os.environ.get("ASSETLIB_LIBRARY"):
        cfg.library = Path(os.environ["ASSETLIB_LIBRARY"])
    if os.environ.get("ASSETLIB_STATE"):
        # SSD, never /srv/data2. SQLite opens WAL, WAL needs a shared-memory
        # mapping, ntfs-3g is FUSE and does not provide one. Filebrowser's
        # BoltDB already paid for this lesson - server panel gotcha 12.
        cfg.state = Path(os.environ["ASSETLIB_STATE"])

    return cfg


def read_stamp(cfg: Config) -> dict:
    """What the last re-index reported, or {} if it has never run."""
    try:
        with (cfg.state / STAMP).open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}
