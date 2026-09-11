"""Change an asset that is already in the library.

`commit.py` CREATES packages. This module MUTATES them, and it is the only
other thing allowed to write inside `library/`.

The trick that keeps it small: an edit is just a re-analysis. Feed `analyse()`
the package's own files plus whatever you are adding, with the type, category
and name you want, and it produces the layout the asset SHOULD have. Comparing
that against what is on disk gives four kinds of change - keep, rename, add,
delete - and nothing else. The library's naming is deterministic, so a file that
is not being touched round-trips to exactly where it already is.

`uuid` and `created` never change. The asset keeps its identity, so the index
row updates in place instead of leaving an orphan behind.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .analyse import ImportPlan, icon_source
from .commit import _copy_and_hash, _promote_hero_lod, bind, fallback_icon
from .hashing import file_hash
from .model import ASSET_FILE, Asset
from .naming import unique_name
from .thumbnail import make_thumb

KEEP, RENAME, ADD, DELETE = "keep", "rename", "add", "delete"

# Regenerable output. An edit does not own these: derived/ is left alone
# entirely - that is what "deletable, never backed up" means - and preview/ is
# rewritten from scratch at the end of every apply.
GENERATED = ("derived", "preview")
STAGING = "_editing"


@dataclass
class Change:
    kind: str
    src: Path                       # absolute; inside the package unless ADD
    dest: str | None = None         # relative destination, None for DELETE
    old_rel: str | None = None      # relative source, None for ADD
    size: int = 0

    def describe(self) -> str:
        if self.kind == ADD:
            return f"add     {self.src.name}  ->  {self.dest}"
        if self.kind == RENAME:
            return f"rename  {self.old_rel}  ->  {self.dest}"
        if self.kind == DELETE:
            return f"DELETE  {self.old_rel}"
        return f"keep    {self.dest}"


@dataclass
class EditPlan:
    asset_dir: Path
    target_dir: Path
    asset: Asset
    plan: ImportPlan
    tags: list = field(default_factory=list)
    changes: list = field(default_factory=list)

    def of(self, kind: str) -> list:
        return [c for c in self.changes if c.kind == kind]

    @property
    def moved(self) -> bool:
        return self.asset_dir != self.target_dir

    @property
    def thumb(self) -> Path:
        return self.asset_dir / "preview" / "thumb.jpg"

    @property
    def icon_changed(self) -> bool:
        """Would the icon be rendered from something other than what is there?

        Choosing a new preview changes no file in the package - the icon is
        rendered, not copied - so nothing else in this class notices it. Without
        this, picking an icon and pressing Apply answered "nothing to apply".
        A missing thumbnail counts too: an asset imported while a decoder was
        unavailable otherwise has no way back to a complete package.
        """
        if not self.thumb.is_file():
            return True
        source = icon_source(self.plan)
        return source is not None and Path(source).resolve() != self.thumb.resolve()

    @property
    def touched(self) -> bool:
        return (self.moved
                or bool(self.of(ADD) or self.of(RENAME) or self.of(DELETE))
                or sorted(self.tags) != sorted(self.asset.tags)
                or self.icon_changed)

    def summary(self) -> str:
        bits = []
        if self.moved:
            bits.append(f"move to {self.target_dir.name}")
        for kind, word in ((ADD, "added"), (RENAME, "renamed"), (DELETE, "DELETED")):
            n = len(self.of(kind))
            if n:
                bits.append(f"{n} {word}")
        if sorted(self.tags) != sorted(self.asset.tags):
            bits.append("tags changed")
        if self.icon_changed:
            bits.append("new icon" if self.thumb.is_file() else "icon to generate")
        return " · ".join(bits) or "no changes"


# ------------------------------------------------------------------ inspect


def package_files(asset_dir: Path, payload_only: bool = True) -> list:
    """Files inside the package.

    `payload_only` - the default - returns the asset's own content: what an edit
    is allowed to move, rename or delete. It leaves out asset.json, which is
    metadata, and both GENERATED folders. derived/ is regenerable by definition,
    and preview/thumb.jpg is rewritten by every apply - counting the thumbnail
    as payload made *changing an asset's icon* look like a file deletion, and
    Apply then demanded confirmation to "delete for good" a file it was about to
    rewrite one step later.

    Pass payload_only=False to list everything actually on disk, which is what
    the contents viewer wants.
    """
    asset_dir = Path(asset_dir)
    out = []
    for path in sorted(asset_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(asset_dir)
        if rel.parts[0] == STAGING or rel.name == ASSET_FILE:
            continue
        if payload_only and rel.parts[0] in GENERATED:
            continue
        out.append(path)
    return out


def build(asset_dir: Path, asset: Asset, plan: ImportPlan, cfg, tags=None) -> EditPlan:
    """Diff what the asset should be against what it is."""
    asset_dir = Path(asset_dir).resolve()
    current = {}
    for path in package_files(asset_dir):
        current[str(path.relative_to(asset_dir)).replace(chr(92), "/")] = path

    changes, claimed = [], set()
    for action in plan.kept:
        if not action.dest:
            continue
        try:
            old_rel = str(action.src.resolve().relative_to(asset_dir)).replace(chr(92), "/")
        except ValueError:
            old_rel = None

        if old_rel is None or old_rel not in current:
            changes.append(Change(ADD, action.src, action.dest, size=action.size))
            continue
        claimed.add(old_rel)
        changes.append(Change(KEEP if old_rel == action.dest else RENAME,
                              action.src, action.dest, old_rel, action.size))

    for rel, path in current.items():
        if rel not in claimed:
            changes.append(Change(DELETE, path, None, rel, path.stat().st_size))

    tdef = cfg.type_by_id[plan.type_id]
    parent = cfg.library / tdef["folder"] / plan.category
    if parent == asset_dir.parent and plan.name == asset_dir.name:
        target = asset_dir                       # staying put
    else:
        target = parent / unique_name(plan.name, parent)

    return EditPlan(asset_dir=asset_dir, target_dir=target, asset=asset, plan=plan,
                    tags=sorted(set(tags or [])), changes=changes)


# -------------------------------------------------------------------- apply


def _validate(eplan: EditPlan, cfg) -> None:
    plan = eplan.plan
    if not plan.category:
        raise ValueError("no category - one from the closed list is required")
    if not cfg.valid_category(plan.type_id, plan.category):
        raise ValueError(
            f"{plan.category!r} is not a valid category for {plan.type_id!r}")
    if not plan.kept:
        raise ValueError("the edit would leave the asset with no files")
    for change in eplan.of(ADD):
        if not change.src.is_file():
            raise FileNotFoundError(f"missing source file: {change.src}")
    if eplan.moved and eplan.target_dir.exists():
        raise FileExistsError(f"{eplan.target_dir} already exists")
    if (eplan.asset_dir / STAGING).exists():
        raise FileExistsError(
            f"{STAGING}/ left over from an interrupted edit - inspect it by hand first")


def apply(eplan: EditPlan, cfg, progress=None) -> Path:
    """Carry out the edit. Returns the asset's directory afterwards.

    Order matters more than anything else here. Everything is validated first,
    the package's payload is moved aside into a staging folder rather than
    renamed in place - two files swapping names is otherwise unsolvable - and
    the staging folder is destroyed LAST. A failure at any earlier point leaves
    every original file sitting in `_editing/old/`, recoverable by hand.

    `progress(message, done, total)` is called at each step. Copying an added
    8K map takes real seconds, so the caller gets to say which one.
    """
    total = len(eplan.plan.kept) + len(eplan.of(DELETE)) + 4
    state = {"done": 0}

    def say(message: str) -> None:
        state["done"] += 1
        if progress:
            progress(message, state["done"], total)

    say("checking the plan")
    _validate(eplan, cfg)

    asset_dir = eplan.asset_dir
    plan = eplan.plan
    staging = asset_dir / STAGING
    old = staging / "old"
    old.mkdir(parents=True)

    # --- A. move the whole payload out of the way -------------------------
    staged = sum(1 for c in eplan.changes if c.old_rel)
    say(f"moving {staged} existing file(s) aside")
    for change in eplan.changes:
        if change.old_rel:
            destination = old / change.old_rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(change.src), str(destination))

    asset = eplan.asset
    # Snapshot before the pointers are cleared: moving a file does not change
    # its bytes, so its digest survives the rename and gigabytes go unread.
    old_hashes = dict(asset.hashes)
    asset.name = plan.name
    asset.type = plan.type_id
    asset.category = plan.category
    asset.tags = list(eplan.tags)
    asset.fields = dict(plan.fields)
    # Rebuilt from scratch: a stale pointer to a file that no longer exists is
    # exactly the drift verify would flag.
    asset.textures, asset.representations = {}, []
    asset.lods, asset.hashes, asset.udim = {}, {}, {}

    by_old = {c.old_rel: c for c in eplan.changes if c.old_rel}
    # Where each source file ended up. The icon may be rendered from a file that
    # is ALSO a texture, in which case by the time we need it, it sits under its
    # new name - neither its original path nor the staging copy exists any more.
    placed: dict = {}

    # --- B. put every surviving file at its new name ----------------------
    for action in plan.kept:
        if not action.dest:
            continue
        if action.action == "preview":
            continue                      # the icon is rendered, not copied
        say(f"{Path(action.dest).name}")

        change = None
        try:
            rel = str(action.src.resolve().relative_to(asset_dir)).replace(chr(92), "/")
            change = by_old.get(rel)
        except ValueError:
            pass

        target = asset_dir / action.dest
        target.parent.mkdir(parents=True, exist_ok=True)
        if change is not None:
            shutil.move(str(old / change.old_rel), str(target))
            asset.hashes[action.dest] = old_hashes.get(change.old_rel) or file_hash(target)
        elif action.src.resolve() == target.resolve():
            # A file already sitting exactly where it belongs, e.g. something
            # dragged out of derived/. Copying it would open the same file for
            # reading and writing at once and destroy it.
            asset.hashes[action.dest] = file_hash(target)
        else:
            asset.hashes[action.dest] = _copy_and_hash(action.src, target)
        placed[action.src.resolve()] = target
        bind(asset, action.dest, action.slot, action.lod, action.udim)

    _promote_hero_lod(asset)
    asset.fields.setdefault(
        "normal_convention", "opengl" if "normal" in asset.textures else None)

    # --- C. the icon -------------------------------------------------------
    say("generating the preview")
    thumb = asset_dir / "preview" / "thumb.jpg"
    preview_src = icon_source(plan)
    if preview_src is not None:
        source = placed.get(Path(preview_src).resolve())
        if source is None:
            source = Path(preview_src)
            try:                                 # it may have been staged in A
                rel = str(source.resolve().relative_to(asset_dir)).replace(chr(92), "/")
            except ValueError:
                rel = None
            if rel and (old / rel).is_file():
                source = old / rel
        # Re-encoding the thumbnail from itself would only lose quality; the
        # icon is already what was asked for.
        if source.resolve() != thumb.resolve():
            make_thumb(source, thumb)
    elif not thumb.exists():
        source = fallback_icon(asset, asset_dir)
        if source:
            make_thumb(source, thumb)

    # --- D. metadata, then the folder itself ------------------------------
    say("writing asset.json")
    asset.write(asset_dir)
    final = asset_dir
    if eplan.moved:
        say(f"moving package to {eplan.target_dir.parent.name}/{eplan.target_dir.name}")
        eplan.target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(asset_dir), str(eplan.target_dir))
        final = eplan.target_dir
        staging = final / STAGING

    # --- E. only now is anything destroyed --------------------------------
    gone = len(eplan.of(DELETE))
    say(f"deleting {gone} removed file(s)" if gone else "cleaning up")
    shutil.rmtree(staging, ignore_errors=True)
    _prune_empty(final)
    return final


def delete_asset(asset_dir: Path, cfg) -> dict:
    """Remove an entire package from the library. Irreversible.

    Four guards stand between a click and `rmtree`, because the cost of getting
    this wrong is somebody's texture library. The path must sit INSIDE
    `library/`, at exactly the three levels the tree allows, and it must carry
    an asset.json - a folder that is not a package is never something this
    deletes. Returns what was removed, so the caller can say so.
    """
    asset_dir = Path(asset_dir).resolve()
    library = Path(cfg.library).resolve()

    if not asset_dir.is_dir():
        raise NotADirectoryError(f"{asset_dir} is not a folder")
    if asset_dir == library or not asset_dir.is_relative_to(library):
        raise ValueError(f"{asset_dir} is not inside the library")
    depth = len(asset_dir.relative_to(library).parts)
    if depth != 3:
        raise ValueError(
            f"{asset_dir} is {depth} levels deep, an asset package is exactly 3")
    if not (asset_dir / ASSET_FILE).is_file():
        raise ValueError(f"{asset_dir} holds no {ASSET_FILE} - it is not a package")

    asset = Asset.read(asset_dir)
    files = [p for p in asset_dir.rglob("*") if p.is_file()]
    summary = {
        "uuid": asset.uuid,
        "name": asset.name,
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "path": str(asset_dir),
    }
    shutil.rmtree(asset_dir)
    return summary


def _prune_empty(asset_dir: Path) -> None:
    """Drop tex/ or geo/ if the edit emptied them. Absent sections are the
    package convention; empty ones are litter."""
    for child in sorted(asset_dir.iterdir(), reverse=True):
        if child.is_dir() and not any(child.iterdir()):
            child.rmdir()
