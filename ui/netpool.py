"""The threads that talk to a server.

A third pool, for the same reason `writepool` is a second one. The global pool
has one thread per core and is where thumbnails are decoded; a network fetch
parked on it is a core-thread doing nothing for as long as the other machine
takes to answer - and a sleeping box does not refuse a connection, it simply
never answers, so "as long as it takes" is the full TCP timeout. Scrolling a
remote catalogue with the box asleep would occupy every decode thread and the
LOCAL library would stop painting.

Three threads, not one: the contract puts two or three concurrent transfers as
the useful amount over a relayed link, and more only splits the same pipe. It
is the same number for thumbnails and for files, so it is decided once, here.
"""

from __future__ import annotations

from PySide6.QtCore import QThreadPool

MAX_THREADS = 3

# How long a close is willing to wait for jobs already in flight. Past this the
# window is gone and the user believes the app has quit, so continuing to wait
# is continuing to lie.
SHUTDOWN_WAIT_MS = 1500

_POOL: QThreadPool | None = None
_STOPPING = False


def pool() -> QThreadPool:
    global _POOL
    if _POOL is None:
        _POOL = QThreadPool()
        _POOL.setMaxThreadCount(MAX_THREADS)
        _POOL.setObjectName("assetlib-net")
    return _POOL


def stopping() -> bool:
    """True once the window is closing. Long jobs must poll this and give up.

    A socket blocked in read() cannot be interrupted from outside, so the only
    thing that can stop one promptly is the job itself, between chunks.
    """
    return _STOPPING


def start(runnable) -> None:
    if _STOPPING:
        return
    pool().start(runnable)


def shutdown(wait_ms: int = SHUTDOWN_WAIT_MS) -> bool:
    """Stop taking work, drop what is queued, wait briefly for what is running.

    Returns True when the pool actually drained.

    This exists because of a real failure, not a theoretical one: Qt waits for
    running pool jobs before the process can exit, so ONE thumbnail fetch
    blocked on a sleeping server - fifteen seconds, or a hundred and twenty for
    a file - kept `pythonw.exe` alive after the window had gone. With no
    console there was nothing to see, and the folder could not be deleted
    because a process nobody could find was holding it open.
    """
    global _STOPPING
    _STOPPING = True
    if _POOL is None:
        return True
    _POOL.clear()                   # queued but not yet started: drop them
    return _POOL.waitForDone(wait_ms)
