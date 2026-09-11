#!/usr/bin/env python3
"""Screenshot a window, so the agent can look at the app instead of asking.

Every project here has a window -- PySide6, SFML, ImGui, Unreal, a browser --
and a picture of it answers in one read what a paragraph of description gets
wrong. This is what makes "run it and show me" possible without a verification
loop: one launch, one capture, the human still watching the real thing.

    python tools/shot.py                       the foreground window
    python tools/shot.py "Blooming"            first window whose title matches
    python tools/shot.py --list                visible windows, to find the title
    python tools/shot.py "Asset" --full        the whole screen instead
    python tools/shot.py "Asset" -o look.png   explicit output path

Output: .claude/shots/<slug>-<HHMMSS>.png, gitignored. The path is printed --
give it to the agent to read.

Windows only, and deliberately dependency-free: window geometry through ctypes,
the bitmap through PowerShell's System.Drawing. Pillow would be one import and
one more thing that has to be installed on every machine this is copied to.
"""

import ctypes
import re
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / ".claude" / "shots"

if sys.platform != "win32":
    sys.exit("shot.py is Windows-only. On another platform, capture by hand "
             "and drop the file in .claude/shots/.")

user32 = ctypes.WinDLL("user32", use_last_error=True)


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def window_title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def visible_windows():
    """Top-level windows with a title, in z-order."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = window_title(hwnd)
        if title and title not in ("Program Manager", "Windows Input Experience"):
            found.append((hwnd, title))
        return True

    user32.EnumWindows(callback, 0)
    return found


def find_window(needle):
    needle_low = needle.lower()
    for hwnd, title in visible_windows():
        if needle_low in title.lower():
            return hwnd, title
    return None, None


def rect_of(hwnd):
    """Window bounds, preferring the DWM frame.

    GetWindowRect includes the invisible resize border Windows 10+ leaves
    around a window -- about 7 px of desktop on each side, which is exactly the
    kind of artefact that makes a screenshot look like a rendering bug.
    DwmGetWindowAttribute(9 = EXTENDED_FRAME_BOUNDS) gives the real edge.
    """
    rect = RECT()
    try:
        dwm = ctypes.WinDLL("dwmapi")
        if dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), ctypes.c_uint(9),
                                     ctypes.byref(rect),
                                     ctypes.sizeof(rect)) == 0:
            return rect
    except OSError:
        pass
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def capture(rect, out_path):
    """Copy a screen region to a PNG, through PowerShell + System.Drawing."""
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        sys.exit("window has no area -- is it minimised?")

    script = (
        "Add-Type -AssemblyName System.Drawing;"
        "$bmp = New-Object System.Drawing.Bitmap({w},{h});"
        "$g = [System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen({x},{y},0,0,$bmp.Size);"
        "$bmp.Save('{out}',[System.Drawing.Imaging.ImageFormat]::Png);"
        "$g.Dispose(); $bmp.Dispose()"
    ).format(w=width, h=height, x=rect.left, y=rect.top,
             out=str(out_path).replace("\\", "\\\\"))

    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit("capture failed:\n" + (proc.stderr or proc.stdout))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]

    if "--list" in flags:
        for _, title in visible_windows():
            print("  " + title)
        return

    out = None
    if "-o" in sys.argv:
        out = Path(sys.argv[sys.argv.index("-o") + 1])
        args = [a for a in args if a != str(out)]

    if "--full" in flags:
        rect = RECT(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
        label = "screen"
    elif args:
        needle = " ".join(args)
        hwnd, title = find_window(needle)
        if not hwnd:
            print("no visible window matching %r. Try --list." % needle)
            sys.exit(1)
        # Raise it first: CopyFromScreen copies the DESKTOP, so anything
        # overlapping the target ends up in the picture.
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.35)
        rect = rect_of(hwnd)
        label = title
    else:
        hwnd = user32.GetForegroundWindow()
        rect = rect_of(hwnd)
        label = window_title(hwnd) or "foreground"

    if out is None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-").lower()[:40] or "shot"
        out = OUT_DIR / ("%s-%s.png" % (slug, time.strftime("%H%M%S")))

    capture(rect, out.resolve())
    print("%s   (%dx%d)  %s" % (out, rect.right - rect.left,
                                rect.bottom - rect.top, label))


if __name__ == "__main__":
    main()
