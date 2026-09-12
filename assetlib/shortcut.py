"""Putting a shortcut on the Desktop, with the app's icon on it.

Windows only, and a no-op everywhere else.

Done through a generated `.vbs` run by `wscript.exe` rather than from Python
directly, for two reasons that both matter:

* `.lnk` is an undocumented-in-practice binary format, and the only supported
  way to write one is `WScript.Shell.CreateShortcut`. Hand-rolling the bytes
  works until a Windows update decides it does not.
* `wscript.exe` is a GUI-subsystem binary, so it cannot own a console. The
  obvious alternatives - `powershell`, `cscript` - are console programs, and
  spawning one would put back exactly the black window that `Asset Library.vbs`
  was rewritten to remove.

The Desktop path is resolved by the script, not guessed here:
`SpecialFolders("Desktop")` is authoritative and gets OneDrive-redirected
Desktops right, which `~/Desktop` does not.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

NAME = "Asset Library"
LAUNCHER = "Asset Library.vbs"
ICON = Path("ui") / "resources" / "asset_library.ico"
MARKER = "shortcut_offered"

_TEMPLATE = '''Option Explicit
Dim shell, fso, link, out
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
out = fso.BuildPath(shell.SpecialFolders("Desktop"), "{name}.lnk")
Set link = shell.CreateShortcut(out)
link.TargetPath = "{target}"
link.WorkingDirectory = "{workdir}"
link.IconLocation = "{icon}"
link.Description = "Browse and import your 3D asset library"
link.Save
Dim report
Set report = fso.CreateTextFile("{report}", True)
report.WriteLine out
report.Close
'''


def available() -> bool:
    return sys.platform == "win32"


def _escape(text: str) -> str:
    """VBScript doubles a quote to escape it, and treats backslash literally.

    So a Windows path needs nothing done to it, and the only real hazard is a
    quote in a folder name - rare, but a folder called `My "Work"` would end
    the string early and the script would fail to parse rather than do anything
    visible.
    """
    return str(text).replace('"', '""')


def icon_path(base: Path) -> Path:
    return Path(base) / ICON


def marker_path(cfg) -> Path:
    return cfg.state / MARKER


def offered(cfg) -> bool:
    """Whether this copy has already been asked about a shortcut."""
    return marker_path(cfg).exists()


def mark_offered(cfg) -> None:
    try:
        marker_path(cfg).parent.mkdir(parents=True, exist_ok=True)
        marker_path(cfg).write_text("asked once\n", encoding="utf-8")
    except OSError:
        pass


def create(base: Path, name: str = NAME) -> Path:
    """Write the Desktop shortcut. Returns where it landed.

    Raises on failure rather than returning None: the caller asked for this
    explicitly, by ticking a box or choosing a menu entry, and a shortcut that
    silently did not appear is worse than a message saying why.
    """
    if not available():
        raise RuntimeError("Desktop shortcuts are a Windows thing.")

    base = Path(base).resolve()
    target = base / LAUNCHER
    if not target.is_file():
        raise FileNotFoundError(f"{LAUNCHER} is not in {base}")

    icon = icon_path(base)
    # Fall back to the launcher's own icon rather than failing: a shortcut with
    # a dull icon still works, and a missing .ico is not a reason to refuse.
    icon_ref = str(icon) if icon.is_file() else str(target)

    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "where.txt"
        script = Path(tmp) / "mkshortcut.vbs"
        script.write_text(_TEMPLATE.format(
            name=_escape(name), target=_escape(target),
            workdir=_escape(base), icon=_escape(icon_ref),
            report=_escape(report)), encoding="utf-8")

        # CREATE_NO_WINDOW as well as wscript being GUI-subsystem. Belt and
        # braces, because this is the one place left that starts a process and
        # the whole point of the change was that no window ever appears.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            ["wscript.exe", "//nologo", str(script)],
            capture_output=True, text=True, timeout=30,
            creationflags=flags, check=False)

        if report.is_file():
            where = report.read_text(encoding="utf-8").strip()
            if where:
                return Path(where)

    detail = (proc.stderr or proc.stdout or "").strip()
    raise RuntimeError(detail or
                       f"wscript returned {proc.returncode} and wrote nothing")


def desktop_guess() -> Path | None:
    """Where the shortcut PROBABLY is, for an 'already there?' check.

    A guess, and named one. The authoritative answer comes from the script
    above; this is only good enough to avoid offering a shortcut that is
    already sitting on the Desktop, and it is allowed to be wrong on a
    redirected profile - the cost of being wrong is one redundant offer.
    """
    if not available():
        return None
    home = os.environ.get("USERPROFILE") or str(Path.home())
    for candidate in (Path(home) / "Desktop", Path(home) / "OneDrive" / "Desktop"):
        if candidate.is_dir():
            return candidate
    return None


def already_there(name: str = NAME) -> bool:
    desktop = desktop_guess()
    return bool(desktop and (desktop / f"{name}.lnk").exists())
