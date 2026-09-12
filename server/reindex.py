"""Rebuild the catalogue from the asset.json files, then stamp it.

Run by `assetlib-reindex.timer`, or by hand after an import:

    sudo systemctl start assetlib-reindex

Deliberately NOT an API route. A full walk of the library on ntfs-3g takes
minutes, so a `POST /reindex` reachable by anyone holding the token is a denial
of service with extra steps. As a unit it is also something the server panel
can trigger with the single verb it already has - `systemctl` - without a new
privilege, a new helper or a new sudoers line.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

from assetlib import index

from .paths import STAMP, load_config


def main() -> int:
    cfg = load_config()
    cfg.state.mkdir(parents=True, exist_ok=True)

    started = time.time()
    result = index.rebuild(cfg)
    elapsed = round(time.time() - started, 1)

    stamp = {
        "indexed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": elapsed,
        "count": result["indexed"],
        # The ETag the API serves the catalogue under. It comes from here
        # rather than from index.db's mtime because the database is opened WAL:
        # writes land in a -wal sidecar and the main file's mtime does not move
        # until a checkpoint, so an mtime ETag can lag a whole re-index.
        "etag": f'{int(started)}-{result["indexed"]}',
        "failed": [[str(path), err] for path, err in result["failed"]],
    }
    (cfg.state / STAMP).write_text(
        json.dumps(stamp, indent=2) + "\n", encoding="utf-8"
    )

    # Printed, never swallowed: index.rebuild reports failures for exactly this
    # reason, and journalctl is where they will actually be read.
    for path, err in result["failed"]:
        print(f"FAILED {path}: {err}", file=sys.stderr)
    print(f"indexed {result['indexed']} assets in {elapsed}s "
          f"({len(result['failed'])} failed)")

    # Exit 0 even with failures. One unreadable package should not leave the
    # timer permanently red in the panel - the count is in the stamp and in
    # /api/health, which is where staleness is meant to be read.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
