"""P0 - prove the seam, before anything is ported.

One question: does `import assetlib` work inside Houdini, on every version that
matters, without disturbing the host?

Everything in the adapter plan rests on that. `assetlib` imports no Qt and no
`hou` (invariant 2), which is supposed to mean Houdini's own Python can import
it directly - no bundled runtime, no second Qt in the process. Supposed to. This
is the thirty lines that settle it, and it is worth running before porting a
thousand.

The dangerous outcome is not an ImportError - that is loud and obvious. It is
`runtime/` ending up on sys.path, because that directory holds a second PySide6
and two Qt libraries in one process is how you crash Houdini rather than how you
get an error message. So that is checked explicitly and reported as a failure
even though nothing has gone wrong yet.
"""

from __future__ import annotations

import sys
from pathlib import Path


def report() -> list:
    """(ok, label, detail) for each thing that has to be true."""
    out = []

    # 3.11 is the FLOOR, not the version. The pin in decisions.md exists so
    # `assetlib` stays importable by the OLDEST Houdini that matters - it says
    # "avoid 3.12+ syntax", which is a rule about what we write, not about what
    # we run on. Houdini 22.0.368 runs 3.13.10 and imports the core fine.
    # The first version of this check asserted == (3, 11) and failed a seam
    # that was working.
    out.append((sys.version_info[:2] >= (3, 11), "python >= 3.11",
                "%d.%d.%d" % sys.version_info[:3]))

    try:
        import hou
        out.append((True, "hou", hou.applicationVersionString()))
    except Exception as exc:                         # noqa: BLE001
        out.append((False, "hou", str(exc)))

    # The whole point. If this raises, the adapter design is wrong.
    try:
        import assetlib
        out.append((True, "import assetlib", str(Path(assetlib.__file__).parent)))
    except Exception as exc:                         # noqa: BLE001
        out.append((False, "import assetlib", str(exc)))
        return out

    try:
        from assetlib.config import find_config
        cfg = find_config()
        out.append((True, "library", str(cfg.library)))
        out.append((cfg.library.is_dir(), "library exists", str(cfg.library.is_dir())))
    except Exception as exc:                         # noqa: BLE001
        out.append((False, "find_config", str(exc)))
        return out

    try:
        from assetlib.model import SCHEMA_VERSION, iter_assets
        count = sum(1 for _ in iter_assets(cfg.library))
        out.append((True, "assets", "%d, schema v%d" % (count, SCHEMA_VERSION)))
    except Exception as exc:                         # noqa: BLE001
        out.append((False, "read the library", str(exc)))

    # The crash risk, checked rather than hoped for.
    runtime = (cfg.base / "runtime").resolve()
    polluted = [p for p in sys.path if p and Path(p).resolve() == runtime
                or (p and runtime in Path(p).resolve().parents)]
    out.append((not polluted, "runtime/ OFF sys.path",
                "clean" if not polluted else "POLLUTED: %s" % polluted))

    # Which Qt the host actually has, so the options dialog knows what to import.
    # assetlib must not have pulled one in; a binding here is Houdini's own.
    qt = [m for m in ("PySide2", "PySide6") if m in sys.modules]
    out.append((True, "host Qt", ", ".join(qt) or "none loaded yet"))

    # Does the WINDOW have what it needs in this interpreter?
    #
    # Not a pass/fail - it decides a design question. Houdini 22 ships PySide6,
    # the same binding ui/ uses, so a Python Panel is possible rather than a
    # subprocess. What stops it is the rest: thumbnail.py imports Pillow, numpy
    # and OpenEXR defensively precisely so the CORE stays importable here, but
    # the browser without them shows no HDR or EXR previews at all, which is
    # most of this library.
    #
    # All four present -> a panel is worth building. Any missing -> the
    # subprocess on the bundled runtime stays the right answer, and that is a
    # finding, not a failure.
    have = []
    for name in ("PySide6", "PIL", "numpy", "OpenEXR", "xxhash"):
        try:
            __import__(name)
            have.append(name)
        except Exception:                            # noqa: BLE001
            have.append("-" + name)
    out.append((True, "panel deps", " ".join(have)))

    return out


def run() -> bool:
    lines = report()
    width = max(len(label) for _, label, _ in lines)
    print("-" * 60)
    print("assetlib seam test (P0)")
    print("-" * 60)
    for ok, label, detail in lines:
        print("  %s  %-*s  %s" % ("ok  " if ok else "FAIL", width, label, detail))
    passed = all(ok for ok, _, _ in lines)
    print("-" * 60)
    print("SEAM OK - the adapter can be built on this" if passed
          else "SEAM BROKEN - fix this before porting anything")
    print("-" * 60)
    return passed
