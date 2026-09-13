"""Running a tool out of the library.

The only way a tool is used. Inside Houdini the library window IS a Python
Panel, which is already the process the tool wants to run in - so launching
imports the module and calls it there: no package file, no restart, nothing
written outside `library/`.

A package-file installer existed for one day and was removed once this worked;
the argument and the one thing it could do that this cannot - putting a tool's
HDAs on HOUDINI_OTLSCAN_PATH, which is read at startup - are in
`docs/History/houdini-package-install-removed.md`.

**This is the one place the app runs package content, and only ever because a
person asked it to.** Invariant 15 says nothing under `library/` is executed by
the app *of its own accord*, and that still holds: no import path, no sync, no
download and no background job reaches this module. A Launch is a person
choosing a named asset from a menu, and the command is shown before it runs.
That distinction is load-bearing now that script assets can arrive by download
from the box.

Two routes, and which one is available is a fact about the host:

    inside Houdini   import the module and call it, in this process
    standalone app   run it as a subprocess with the bundled runtime

A Houdini tool has no third option: it imports `hou`, which exists only inside
Houdini. Offering to launch one from the standalone window would produce an
ImportError dressed as a broken asset, so it is not offered, and nothing is
offered in its place. Install used to be that second route - it worked from the
standalone window because writing a package file needs no `hou` - and it is the
one capability that went with it.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import apps


class LaunchError(RuntimeError):
    """The tool could not be started. Says which entry and why."""


def entries(asset) -> list:
    """What this asset offers to launch. Empty for anything that is not a tool."""
    return list(asset.fields.get("shelf") or [])


def interpreter(asset) -> str:
    """The interpreter this tool asked for, or "" for the bundled runtime."""
    return str(asset.fields.get("python") or "").strip()


def in_host(asset, host: bool) -> bool:
    """Whether this launch should run in THIS process.

    The host process, unless the tool asked for an interpreter - which is a
    tool saying "not the one you are". A tkinter tool is the plain case twice
    over: the bundled runtime has no tcl/tk at all, and running a tkinter
    mainloop inside Houdini would sit on the thread Houdini needs.
    """
    return bool(host) and not interpreter(asset)


def _python(asset, override: Path | None = None) -> Path:
    """Which interpreter to start, and a legible error when it is not there.

    A BARE NAME is looked up on PATH rather than kept as a path, because an
    asset syncs to a shared master: an absolute path that is right on this
    machine is wrong on every other one. `"python"` travels; a path out of
    AppData does not.
    """
    if override:
        return Path(override)
    name = interpreter(asset)
    if not name:
        return Path(sys.executable)
    if "/" in name or "\\" in name:
        path = Path(name)
        if path.is_file():
            return path
        raise LaunchError(f"this tool asks for the interpreter {name} and it "
                          "is not there - install it, or change \"python\" in "
                          "the asset to a name on PATH")
    found = shutil.which(name)
    if not found:
        raise LaunchError(f"this tool asks for {name!r} and there is no {name} "
                          "on PATH - the bundled runtime cannot run it, which "
                          "is why the tool named one")
    return Path(found)


def search_paths(asset, asset_dir: Path) -> list:
    """Folders the tool needs on sys.path, package root first.

    Package root first, then whatever the manifest declared, then each entry's
    own folder - the suite's modules sit one level down and import each other by
    bare name, which is what a tool's own sys.path lines were compensating for.
    """
    asset_dir = Path(asset_dir)
    out = [asset_dir]
    for rel in asset.fields.get("pythonpath") or []:
        folder = asset_dir / rel
        if folder.is_dir() and folder not in out:
            out.append(folder)
    for item in entries(asset):
        entry = (item.get("entry") or "").strip()
        if entry:
            folder = (asset_dir / entry).parent
            if folder.is_dir() and folder not in out:
                out.append(folder)
    return out


def describe(asset, asset_dir: Path, item: dict, host: bool = True) -> str:
    """Exactly what will run, for showing BEFORE it runs.

    Not decoration. This module executes code out of a package that may have
    been downloaded, so the person pressing the button is entitled to read the
    module and the call first - and a tool whose entry looks wrong is caught
    here rather than by whatever it does.
    """
    entry = (item.get("entry") or "").strip()
    call = (item.get("callable") or "show").strip()
    module = Path(entry).stem
    path = Path(asset_dir) / entry

    # The two routes do genuinely different things, and the confirmation is
    # worthless if it describes the wrong one. In-process imports the module
    # and calls one function; a subprocess runs the whole FILE as __main__,
    # which for most of these tools is where the work actually is.
    if host:
        return f"{path}\n\nimport {module}\n{module}.{call}()"
    named = interpreter(asset) or Path(sys.executable).name
    return (f"{path}\n\nrun with {named}, as __main__\n"
            f"then {call}(), if the module defines one")


def _checked(asset, asset_dir: Path, item: dict) -> tuple:
    entry = (item.get("entry") or "").strip()
    if not entry:
        raise LaunchError("this entry names no file")
    path = Path(asset_dir) / entry
    if not path.is_file():
        raise LaunchError(f"{entry} is not in the package - re-import it with "
                          "the files the manifest describes")
    return path, Path(entry).stem, (item.get("callable") or "show").strip()


def in_process(asset, asset_dir: Path, item: dict):
    """Import the module and call it, here. For a host that is already the DCC.

    `reload` because a tool launched twice in one session should run the code on
    disk, not the copy imported an hour ago - which is what every shelf snippet
    in this project's source does, for the same reason.
    """
    path, module, call = _checked(asset, asset_dir, item)

    added = []
    for folder in search_paths(asset, asset_dir):
        text = str(folder)
        if text not in sys.path:
            # Appended, never inserted at 0. A tool's folder shadowing a stdlib
            # or host module would be a failure with no obvious cause, and this
            # process is Houdini's - it has thousands of modules already loaded
            # and is not ours to reorder.
            sys.path.append(text)
            added.append(text)

    try:
        mod = importlib.import_module(module)
        mod = importlib.reload(mod)
    except Exception as exc:                            # noqa: BLE001
        raise LaunchError(f"{module} could not be imported: {exc}") from exc

    fn = getattr(mod, call, None)
    if not callable(fn):
        raise LaunchError(f"{module} has no {call}() to call")
    return fn()


def as_subprocess(asset, asset_dir: Path, item: dict, python: Path | None = None):
    """Run the entry in its own interpreter. For a tool that needs no host.

    The bundled runtime, because it is the only interpreter this project can be
    sure of - the machine may have no system Python, which is the whole reason
    `runtime/` travels with the folder.
    """
    path, module, call = _checked(asset, asset_dir, item)

    python = Path(python) if python else Path(sys.executable)
    env = dict(os.environ)
    joined = os.pathsep.join(str(p) for p in search_paths(asset, asset_dir))
    env["PYTHONPATH"] = (joined + os.pathsep + env["PYTHONPATH"]
                         if env.get("PYTHONPATH") else joined)

    snippet = (f"import runpy, sys\n"
               f"m = runpy.run_path(r'{path}', run_name='__main__')\n"
               f"fn = m.get('{call}')\n"
               f"fn() if callable(fn) else None\n")

    # run_path with __main__, because most of these tools do their work under
    # `if __name__ == '__main__'` and define no callable at all - importing one
    # defines functions and opens nothing. Calling the entry afterwards when it
    # exists covers the other shape without having to know which this is.
    try:
        return subprocess.Popen(
            [str(python), "-c", snippet], cwd=str(path.parent), env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        raise LaunchError(f"could not start {python.name}: {exc}") from exc


def launchable(cfg, asset) -> bool:
    """Whether launching this asset could work from a NON-host process.

    False for a tool that targets a DCC: it imports `hou` or `maya.cmds`, which
    exist only inside them, so a subprocess would raise an ImportError that
    reads as a broken asset. Inside the host itself, `in_process` is the route
    and this does not apply.
    """
    if not entries(asset):
        return False
    targets = set(apps.apps_of(asset.tags))
    return not (targets - {apps.FALLBACK})
