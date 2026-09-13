"""Which applications a script asset targets, and how it reaches them.

A script is the first asset type the library does not merely STORE. A rock is
finished when it is in the tree; a tool is finished when the application it was
written for can find it. Every application finds things differently, so the
differences live in `config/apps.json` and this module reads them.

**Tags, not category.** An asset declares its targets as `app:houdini`,
`app:maya`, `app:standalone`. The category is one folder and stays the primary
app; the tags are many, because a Python library used from both Houdini and Maya
is one asset with two of them, and the tags are what decide which buttons
appear.

**Detection is a pre-fill and never a decision** - the same rule as
`variant_patterns` and `guess_category`. What is found here is shown as editable
chips in the Add window and the person keeps, adds or removes them. A pattern
that looks right and is wrong is exactly the mistake someone catches at a glance
and a rule never will.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PREFIX = "app:"
FALLBACK = "standalone"

# Read for import lines only. A 200 KB module is not worth scanning to the end
# to learn something its first page always says, and `import hou` under a
# function is still in the first page of the file that needs it.
HEAD_BYTES = 8192

TEXT_EXTS = {".py", ".txt", ".mel", ".json", ".shelf", ".xml", ".vfl"}


def tag(app: str) -> str:
    return f"{PREFIX}{app}"


def app_of(tag_value: str) -> str | None:
    """'app:houdini' -> 'houdini'. None for any other tag."""
    return tag_value[len(PREFIX):] if tag_value.startswith(PREFIX) else None


def apps_of(tags) -> list:
    """Every application an asset declares, in config order."""
    found = {app_of(t) for t in (tags or [])}
    found.discard(None)
    return [a for a in found if a]


def unresolved(asset, asset_dir: Path) -> list:
    """Declared paths that are not in the package. Empty when the asset is sound.

    A manifest is written by hand against a source tree, and what gets imported
    is a choice made later in the Add window - so the two can disagree, and
    nothing noticed. It was found the hard way: an asset holding only its
    manifest and no code imported cleanly, and the failure surfaced three steps
    later as "src/Main_ui/manager_ui.py is not in the package".

    The opposite direction from `verify`'s orphan check, which walks files and
    asks whether a pointer exists; this walks pointers and asks whether a file
    does. Neither finds the other's defect.

    Written for the Houdini installer, which was removed the same day
    (`docs/History/houdini-package-install-removed.md`). It moved here rather
    than going with it: the check is about a manifest being honest, which is
    this module's subject, and that is worth checking whether or not anything
    ever acts on the manifest.
    """
    asset_dir = Path(asset_dir)
    out = []
    for item in asset.fields.get("shelf") or []:
        entry = (item.get("entry") or "").strip()
        if entry and not (asset_dir / entry).is_file():
            out.append(f"shelf entry: {entry}")
    for rel in asset.fields.get("otls") or []:
        if rel and not (asset_dir / rel).is_dir():
            out.append(f"otls: {rel}")
    for rel in asset.fields.get("pythonpath") or []:
        if rel and not (asset_dir / rel).is_dir():
            out.append(f"pythonpath: {rel}")
    return out


# ------------------------------------------------------------------- detect


def _imports_in(path: Path, modules) -> bool:
    """True when the head of this file imports one of `modules`.

    Matched as an import STATEMENT, not as a substring. 'hou' appears inside
    'house', 'hound' and every third variable name in a file about housing, and
    a substring test would tag half the library for Houdini.
    """
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:HEAD_BYTES]
    except OSError:
        return False
    for module in modules:
        root = re.escape(module.split(".")[0])
        rest = re.escape(module)
        if re.search(rf"^\s*(?:import\s+{rest}|from\s+{rest}\b|"
                     rf"import\s+{root}\b.*\b{rest}\b)", head, re.M):
            return True
    return False


def detect(files, cfg, base: Path | None = None) -> list:
    """Tags proposed for these source files, most specific first.

    Three signals, any one of which is enough, because vendors ship tools in all
    three shapes: an extension only that application uses, an import of its
    Python module, or a folder name it looks for by convention.

    `base` matters and is not optional in practice. Folder names are matched
    against the path INSIDE the asset, never the absolute one: Manager_tool
    lives at H:/3D/Maya/Scripts/..., so matching the full path tagged it
    app:maya because Maya's convention list contains "scripts". Every tool in
    that tree would have been tagged for Maya, on the strength of where Felix
    happens to keep his scripts.

    Always returns at least `app:standalone` - every tool runs somewhere, and an
    asset with no app tag would show no buttons and no explanation for why.
    """
    files = [Path(f) for f in files]
    exts = {f.suffix.lower() for f in files}

    def inside(f: Path) -> Path:
        if base is None:
            return Path(f.name)
        try:
            return f.relative_to(base)
        except ValueError:
            return Path(f.name)

    rel_paths = [inside(f) for f in files]
    parts = {p.lower() for r in rel_paths for p in r.parts[:-1]}
    rels = {"/".join(r.parts[:-1]).lower() for r in rel_paths}

    hits = []
    for app, spec in cfg.apps.items():
        if app == FALLBACK:
            continue
        det = spec.get("detect") or {}
        if exts & {e.lower() for e in det.get("extensions", [])}:
            hits.append(app)
            continue
        folders = {d.lower() for d in det.get("folders", [])}
        if folders & parts or folders & rels:
            hits.append(app)
            continue
        modules = det.get("imports") or []
        if modules and any(f.suffix.lower() in TEXT_EXTS and _imports_in(f, modules)
                           for f in files):
            hits.append(app)

    return [tag(a) for a in hits] or [tag(FALLBACK)]


MANIFEST = "install.json"


def read_manifest(files, base: Path | None = None) -> dict | None:
    """The tool author's own declaration, if the source ships one.

    Better than anything guessed, and that is the whole reason it exists: the
    person who wrote the tool knows which module is meant to be launched, and a
    regex looking for `def show()` does not. Scanning the Manager_tool suite
    proposed FIVE entries when exactly one is meant to be called.

    **Read as data and never executed.** A script asset can arrive by download
    now - the box is the master and `materialise.py` pulls packages from it -
    so a library that ran code an asset carried would turn "download an asset"
    into "run its code". Nothing under library/ is ever executed by this app.
    The manifest says what the tool needs; the library decides what to do about
    it.

    Shallowest wins. A vendor tree can contain several `install.json` files -
    one per sub-tool, or one in a bundled dependency - and the one describing
    THIS asset is the one nearest its root.
    """
    found = None
    depth = None
    for path in (Path(f) for f in files):
        if path.name.lower() != MANIFEST:
            continue
        try:
            rel = path.relative_to(base) if base else Path(path.name)
        except ValueError:
            rel = Path(path.name)
        if depth is None or len(rel.parts) < depth:
            found, depth = path, len(rel.parts)
    if found is None:
        return None
    try:
        with found.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        # A malformed manifest is reported by the caller as a warning and the
        # import continues on autodetect. A tool is not un-importable because
        # its metadata has a trailing comma.
        return None
    if not isinstance(data, dict):
        return None
    data["_manifest"] = found
    data["_root"] = found.parent
    return data


def from_manifest(data: dict, base: Path) -> dict:
    """Manifest -> the fields `asset.json` stores, with paths made asset-relative.

    The manifest writes paths relative to ITSELF, because that is what the tool
    author can see; the library stores them relative to the package, which is
    what `launch.py` needs. That translation happens once, here, so neither
    side has to think about the other's layout.
    """
    root = data.get("_root") or base
    try:
        prefix = Path(root).relative_to(base).as_posix()
    except (ValueError, TypeError):
        prefix = ""
    prefix = f"{prefix}/" if prefix and prefix != "." else ""

    def under(value: str) -> str:
        return f"{prefix}{str(value).strip().replace(chr(92), '/').strip('/')}"

    shelf = []
    for item in data.get("shelf") or []:
        if not isinstance(item, dict) or not item.get("entry"):
            continue
        shelf.append({
            "entry": under(item["entry"]),
            "callable": (item.get("callable") or "show").strip(),
            "label": item.get("label") or Path(item["entry"]).stem,
            "icon": item.get("icon") or "MISC_python",
        })

    out = {"shelf": shelf,
           "otls": [under(p) for p in (data.get("otls") or [])],
           "pythonpath": [under(p) for p in (data.get("pythonpath") or [])]}
    app = (data.get("app") or "").strip().lower()
    if app:
        out["tags"] = [tag(app)]
    return out


def entries(files, base: Path) -> list:
    """Shelf entries PROPOSED for this asset: [{entry, callable, label}].

    Zero, one or many - a tool pack of five unrelated utilities gets five
    buttons and a library with no UI gets none. Proposed only: the Add window
    shows them as rows to keep, edit or delete, and `asset.json` is what
    `launch.py` reads afterwards. Scanning is how the rows are offered, never how
    they are decided.

    A module is a candidate when it defines a zero-argument `show()`, `launch()`
    or `main()` at top level - the three names this kind of tool uses for "open
    my window", and all three are what Main_ui.txt calls.
    """
    out = []
    for path in sorted(Path(f) for f in files):
        if path.suffix.lower() != ".py":
            continue
        try:
            head = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = re.search(r"^def\s+(show|launch|main)\s*\(\s*\)", head, re.M)
        if not found:
            continue
        try:
            rel = path.relative_to(base).as_posix()
        except ValueError:
            rel = path.name
        out.append({
            "entry": rel,
            "callable": found.group(1),
            "label": path.stem.replace("_", " ").title(),
        })
    return out
