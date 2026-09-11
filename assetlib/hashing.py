"""Content hashing for duplicate detection and integrity checks.

Not a security problem, so speed wins: xxh3 when available, blake2b (stdlib,
still fast) otherwise.

Every digest carries its algorithm as a prefix, and verification recomputes with
the algorithm the digest was WRITTEN with. Without that, a library imported on a
machine with xxhash and checked on one without it (or the reverse) reports every
single file as corrupted - which is exactly what happens when the library is
carried between machines on an external disk.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 1 << 20  # 1 MiB

try:  # pragma: no cover - depends on the environment
    import xxhash  # type: ignore

    HAVE_XXHASH = True
except ImportError:
    xxhash = None
    HAVE_XXHASH = False

DEFAULT = "xxh3" if HAVE_XXHASH else "b2"


class UnavailableAlgorithm(RuntimeError):
    """The digest was written with an algorithm this install cannot compute."""


def algo() -> str:
    return DEFAULT


def _hasher(name: str):
    if name == "xxh3":
        if not HAVE_XXHASH:
            raise UnavailableAlgorithm(
                "digest needs xxh3 but the xxhash package is not installed "
                "(pip install xxhash)"
            )
        return xxhash.xxh3_64()
    if name == "b2":
        return hashlib.blake2b(digest_size=16)
    raise UnavailableAlgorithm(f"unknown hash algorithm {name!r}")


def file_hash(path: Path, name: str | None = None) -> str:
    """Digest a file, prefixed with the algorithm used."""
    name = name or DEFAULT
    h = _hasher(name)
    with Path(path).open("rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return f"{name}:{h.hexdigest()}"


def split(digest: str) -> tuple:
    """'xxh3:abcd' -> ('xxh3', 'abcd'). Bare digests are assumed legacy b2."""
    if ":" in digest:
        name, _, value = digest.partition(":")
        return name, value
    return "b2", digest


def matches(path: Path, expected: str) -> bool:
    """Re-check a file against a stored digest, using ITS algorithm.

    Raises UnavailableAlgorithm if this install cannot compute it - callers
    should report that as "unverifiable", never as "corrupted".
    """
    name, _ = split(expected)
    return file_hash(path, name) == expected


def quick_key(path: Path) -> tuple:
    """(size, digest) - size alone rules out most pairs before hashing."""
    p = Path(path)
    return (p.stat().st_size, file_hash(p))
