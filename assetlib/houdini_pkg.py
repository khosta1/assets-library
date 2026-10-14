"""Installing the Houdini package: one json in each Houdini's user prefs.

The package is `houdini/packages/assets_library.json`. Its one machine-specific
line is `ASSETLIB`, the library's base path; everything else is read straight
out of this folder through it. Copied by hand, that line was written once and
then lied the first time the disk came back with another letter - the folder
is meant to travel, and Houdini would quietly load nothing.

So the file is not copied, it is RENDERED: the repo template with `ASSETLIB`
set to wherever this copy is right now. The template stays the single source
for how the package is laid out; this module only fills in the path.

Filesystem only - no Qt, no hou (architecture: assetlib imports neither). It
writes one named file in Houdini's user prefs and nothing else, and only when a
person asked, which is the same footing as shortcut.py and the Desktop.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE_FILE = "assets_library.json"
TEMPLATE = Path("houdini") / "packages" / PACKAGE_FILE
# 21.0 and up: decisions.md, Reversed, 2026-10-14. 20.5 is shown, not offered.
SUPPORTED_MIN = (21, 0)

HERE = "here"                   # ours, pointing at this copy
ELSEWHERE = "elsewhere"         # ours, pointing at another library
MISSING = "missing"
UNREADABLE = "unreadable"       # our filename, not json we can read

_VER = re.compile(r"(\d+)\.(\d+)")


@dataclass
class Install:
    version: str                # "21.0"
    prefs: Path                 # the houdiniX.Y user prefs folder
    supported: bool
    state: str
    points_at: str | None = None
    target_exists: bool = True

    @property
    def file(self) -> Path:
        return self.prefs / "packages" / PACKAGE_FILE


def _key(version: str) -> tuple:
    return tuple(int(x) for x in version.split("."))


# ------------------------------------------------------------------ locating


def _documents() -> Path:
    """Where Houdini puts houdiniX.Y on Windows: the user's Documents.

    Asked of the shell rather than built from ~: OneDrive redirects Documents
    and `~/Documents` is then a folder Houdini has never heard of.
    """
    if sys.platform != "win32":
        return Path.home()
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD),
                        ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

        u = uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")   # FOLDERID_Documents
        guid = GUID(u.time_low, u.time_mid, u.time_hi_version,
                    (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:]))
        out = ctypes.c_wchar_p()
        fn = ctypes.windll.shell32.SHGetKnownFolderPath
        fn.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                       ctypes.POINTER(ctypes.c_wchar_p)]
        if fn(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0:
            path = Path(out.value)
            ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(out, ctypes.c_void_p))
            return path
    except Exception:                                   # noqa: BLE001
        pass
    return Path.home() / "Documents"


def prefs_dir(version: str) -> Path:
    """houdiniX.Y for one version. HOUDINI_USER_PREF_DIR wins when set."""
    custom = os.environ.get("HOUDINI_USER_PREF_DIR")
    if custom:
        return Path(custom.replace("__HVER__", version))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / "houdini" / version
    return _documents() / f"houdini{version}"


def versions() -> list:
    """Every Houdini X.Y on this machine, installed or with prefs, oldest first.

    Both sources: an install not launched yet has no prefs folder, and prefs
    can outlive an uninstalled Houdini - the person may still want the package
    there for when it comes back.
    """
    found = set()
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Side Effects Software",
             Path("/opt")]
    for root in roots:
        try:
            for d in root.iterdir():
                m = re.fullmatch(r"(?:Houdini |hfs)(\d+)\.(\d+)(?:\.\d+)?", d.name)
                if m:
                    found.add(f"{m[1]}.{m[2]}")
        except OSError:
            continue
    try:
        for d in _documents().iterdir():
            m = re.fullmatch(r"houdini(\d+)\.(\d+)", d.name)
            if m and d.is_dir():
                found.add(f"{m[1]}.{m[2]}")
    except OSError:
        pass
    return sorted(found, key=_key)


# -------------------------------------------------------------------- state


def _same(a: str, b: Path) -> bool:
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return False


def _points_at(path: Path) -> str | None:
    """The ASSETLIB a package file sets, or None if it sets none."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data.get("env") or []:
        if isinstance(entry, dict) and "ASSETLIB" in entry:
            value = entry["ASSETLIB"]
            return value if isinstance(value, str) else (value or {}).get("value")
    return None


def status(base: Path) -> list:
    """One Install per Houdini version found."""
    out = []
    for version in versions():
        inst = Install(version, prefs_dir(version), _key(version) >= SUPPORTED_MIN, MISSING)
        if inst.file.is_file():
            try:
                where = _points_at(inst.file)
            except (OSError, ValueError):
                where = None
            if where is None:
                inst.state = UNREADABLE
            else:
                inst.points_at = where
                inst.state = HERE if _same(where, base) else ELSEWHERE
                inst.target_exists = Path(where).is_dir()
        out.append(inst)
    return out


def stranded(base: Path) -> list:
    """Supported installs pointing at a library that is not there any more.

    The case a moved disk produces: the package was right when written and the
    drive letter changed under it. Another copy that still exists is a choice,
    not a fault, so it is not reported.
    """
    return [i for i in status(base)
            if i.supported and i.state == ELSEWHERE and not i.target_exists]


# ------------------------------------------------------------------- writing


def render(base: Path) -> str:
    """The template's text with ASSETLIB set to `base`.

    Substituted in the text rather than re-dumped, so the installed file keeps
    the template's layout line for line and a diff against it shows only the
    path.
    """
    text = (base / TEMPLATE).read_text(encoding="utf-8")
    value = json.dumps(base.resolve().as_posix())
    new, hits = re.subn(r'("ASSETLIB"\s*:\s*)"[^"]*"', lambda m: m.group(1) + value, text)
    if hits != 1:
        raise RuntimeError(f"{TEMPLATE} must set ASSETLIB exactly once, found {hits}")
    json.loads(new)                                     # never write broken json
    return new


def install(base: Path, version: str) -> Path:
    """Write the package for one version. Returns the file written."""
    if _key(version) < SUPPORTED_MIN:
        raise ValueError(f"Houdini {version} is not supported "
                         f"(needs {'.'.join(map(str, SUPPORTED_MIN))} or later)")
    dst = prefs_dir(version) / "packages" / PACKAGE_FILE
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_text(render(base), encoding="utf-8", newline="\n")
    tmp.replace(dst)                # tmp + replace: never half a package
    return dst


def remove(version: str) -> bool:
    """Delete the package for one version - only if it is recognisably ours.

    The filename alone is not proof. A file by that name that does not set
    ASSETLIB was written by someone else, and deleting other people's files is
    the one thing an uninstall must never do.
    """
    path = prefs_dir(version) / "packages" / PACKAGE_FILE
    if not path.is_file():
        return False
    try:
        if _points_at(path) is None:
            raise ValueError
    except (OSError, ValueError):
        raise RuntimeError(f"{path} does not look like this library's package - left alone")
    path.unlink()
    return True
