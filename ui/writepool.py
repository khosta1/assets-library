"""The thread that writes to the library.

Imports, edits and deletes must NEVER share the global thread pool with
thumbnail decoding. The global pool has one thread per core, and opening the
Contents window queues a decode job per file in the package - twenty 8K TIFFs
will happily occupy every thread for a minute. A write job queued behind them
does not start, so the progress dialog sits there forever and the signal that
would close it never fires.

So writes get their own pool, and it is deliberately single-threaded: two
things mutating `library/` at once is not a situation worth supporting.
"""

from __future__ import annotations

from PySide6.QtCore import QThreadPool

_POOL: QThreadPool | None = None


def pool() -> QThreadPool:
    global _POOL
    if _POOL is None:
        _POOL = QThreadPool()
        _POOL.setMaxThreadCount(1)
        _POOL.setObjectName("assetlib-write")
    return _POOL


def start(runnable) -> None:
    pool().start(runnable)
