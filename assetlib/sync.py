"""Pushing this library onto the server's library, over SMB.

The box is the master (`server/client-contract.md`) and the API is read-only by
decision - so the only way an asset gets onto it is a file copy over SMB on the
LAN. This module is that copy, done by uuid instead of by path.

**Not robocopy /MIR, and the difference is the whole module.** A mirror
compares paths, and a path is not an identity here: re-categorising an asset
changes `library/{type}/{category}/{asset}` while the asset stays the same
asset. A mirror sees a new path plus a missing old one and answers by
re-uploading gigabytes and then deleting the original. Diffing by uuid turns
that same edit into a rename on the share - no bytes on the wire - and turns
"missing on this disk" into a report instead of a deletion.

**Both sides are read from disk, not from an index.** `asset.json` is truth and
`index.db` is a cache; the server's catalogue is rebuilt daily, so a diff taken
against it would be a diff against yesterday. Deciding to overwrite or delete
38 GB on the strength of a stale row is not a trade worth making.

**Who may do this is decided by smbd, not by us.** The library share is
`read only = yes` with `write list = felix`: anyone else is refused at the
protocol, before a syscall reaches the disk, and no local setting changes that
answer. `probe()` asks the share what this account is and the UI reports it -
it reads the permission, it never grants one. The check unix would normally do
- a sticky bit, so others may create but not delete - is unavailable here
because the library sits on ntfs-3g, which has no per-file ownership to hang it
on. Samba's own check works precisely because it happens above the filesystem.

Nothing here deletes an asset. `discard()` exists and is separate, is one asset
at a time, and moves the package into `_trash/` rather than removing it: 1.7 TB
with no off-site copy does not get an irreversible button.

No Qt, no `hou`: this is core, and `ui/sync_server.py` is a window onto it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .model import ASSET_FILE, Asset, iter_assets

# Laid out on the share exactly as the box lays them out under
# /srv/data2/assets, so the host record's `share` is that directory and none of
# these have to be guessed from it.
LIBRARY_DIR = "library"
INBOX_DIR = "_inbox"
TRASH_DIR = "_trash"

# derived/ is regenerable - `library.json` says so in the derived_is_disposable
# invariant and `server/api.py` already refuses to serve it. Sending it would
# roughly double a transfer to ship files the other end rebuilds in seconds.
SKIP_TOP = {"derived"}

PROBE = ".assetlib_probe"
PARTIAL = ".partial-"

CHUNK = 1 << 20                     # 1 MiB, same as hashing.CHUNK

ADD = "add"
MOVE = "move"
UPDATE = "update"
MISSING = "missing"

# Ordered worst-consequence-last: the UI stacks the blocks in this order and
# MISSING has to be the one at the bottom, furthest from the button that acts.
VERDICTS = (ADD, UPDATE, MOVE, MISSING)

LABELS = {
    ADD: "New here, not on the server",
    UPDATE: "Changed since it was sent",
    MOVE: "Moved or renamed",
    MISSING: "On the server, not here",
}

REINDEX_UNIT = "assetlib-reindex"


class SyncError(RuntimeError):
    """The share could not be used at all. Per-asset failures are collected."""


# ------------------------------------------------------------------ the plan


@dataclass
class Item:
    """One asset, and what a push would do to it."""

    uuid: str
    name: str
    type: str
    category: str
    verdict: str
    local_rel: str = ""             # under library/, this disk
    remote_rel: str = ""            # under library/, the share
    bytes: int = 0                  # what this item costs to transfer
    files: list = field(default_factory=list)   # package-relative, to copy
    gone: list = field(default_factory=list)    # on the server, not here
    also_changed: bool = False      # a MOVE whose content changed as well

    @property
    def label(self) -> str:
        return f"{self.type}/{self.category}/{self.name}"


@dataclass
class Plan:
    share: Path
    local_root: Path
    admin: bool
    reason: str                     # why not, when admin is False
    items: list = field(default_factory=list)
    scanned: int = 0
    failed: list = field(default_factory=list)  # [(rel, message)]
    cancelled: bool = False

    def of(self, verdict: str) -> list:
        return [i for i in self.items if i.verdict == verdict]

    @property
    def sendable(self) -> list:
        """Everything a push would act on. MISSING is never in here."""
        return [i for i in self.items if i.verdict != MISSING]


# ----------------------------------------------------------------- the share


def library_root(share) -> Path:
    return Path(share) / LIBRARY_DIR


def probe(share) -> tuple:
    """(admin, reason). Ask the share whether this account may write to it.

    A write, not a permission read. Windows exposes SMB share rights through an
    API Python does not reach, and reading the per-file ACL would answer about
    the filesystem - which on ntfs-3g is one uid for everything and says
    nothing about what smbd will allow. Creating a file and removing it again
    is the only question whose answer is the one needed, and it costs one round
    trip.
    """
    root = library_root(share)
    if not root.is_dir():
        return False, f"{root} is not reachable - is the share mounted?"
    target = root / PROBE
    try:
        with target.open("wb") as fh:
            fh.write(b"assetlib")
        target.unlink()
    except PermissionError:
        return False, ("the library share is read-only for this account - "
                       "assets can be added through the drop box, but nothing "
                       "already on the server can be changed or removed")
    except OSError as exc:
        return False, str(exc)
    return True, ""


# ------------------------------------------------------------------- diffing


def _package_files(pkg: Path) -> list:
    """Every file in one package worth sending, package-relative, sorted.

    derived/ is skipped whole rather than per-file: it is a directory by
    contract, and descending into it to reject each file is work spent to
    arrive at the same answer.
    """
    out = []
    try:
        tops = sorted(pkg.iterdir())
    except OSError:
        return out
    for top in tops:
        if top.name in SKIP_TOP:
            continue
        if top.is_file():
            out.append(top.name)
            continue
        for path in sorted(top.rglob("*")):
            if path.is_file():
                out.append(path.relative_to(pkg).as_posix())
    return out


def _sizes(pkg: Path, rels) -> dict:
    out = {}
    for rel in rels:
        try:
            out[rel] = (pkg / rel).stat().st_size
        except OSError:
            out[rel] = 0
    return out


def _thumb_size(pkg: Path) -> int:
    """preview/thumb.jpg is RENDERED at import, not copied, so it has no hash.

    Without this the hashes-only comparison below calls two packages identical
    when the only thing that changed is the icon - which is exactly what
    re-rendering a preview produces. One stat per package buys not silently
    refusing to send the visible half of an edit.
    """
    try:
        return (pkg / "preview" / "thumb.jpg").stat().st_size
    except OSError:
        return 0


def _scan(root: Path, seen: list, on_progress=None, should_stop=None) -> tuple:
    """{uuid: (rel, Asset, dir)} for one library root, plus what would not read."""
    found, failed = {}, []
    root = Path(root)
    for pkg in iter_assets(root):
        if should_stop is not None and should_stop():
            break
        rel = pkg.relative_to(root).as_posix()
        try:
            asset = Asset.read(pkg)
        except Exception as exc:                        # noqa: BLE001
            # Collected, never raised: one package written by a build this copy
            # does not understand must not stop the other seventy-four from
            # being pushed.
            failed.append((rel, f"{type(exc).__name__}: {exc}"))
            continue
        if asset.uuid in found:
            # Two packages, one uuid. Almost always a folder duplicated by hand
            # in Explorer - and sending it would drop the copy on top of the
            # original on the one machine that is the master.
            failed.append((rel, f"duplicate uuid, also at {found[asset.uuid][0]}"))
            continue
        found[asset.uuid] = (rel, asset, pkg)
        seen[0] += 1
        if on_progress is not None:
            on_progress(seen[0], rel)
    return found, failed


def diff(cfg, share, on_progress=None, should_stop=None) -> Plan:
    """What a push would do. Reads both sides, writes nothing but the probe.

    Only `cfg.library` is considered. `_cache/` holds assets pulled DOWN from
    this same server, and pushing them back would be the client teaching the
    master what the master already said - or, the first time a hero-LOD subset
    was cached, teaching it a truncated version of its own asset.
    """
    admin, reason = probe(share)
    root = library_root(share)
    plan = Plan(share=Path(share), local_root=Path(cfg.library),
                admin=admin, reason=reason)

    seen = [0]
    local, failed = _scan(cfg.library, seen, on_progress, should_stop)
    remote, remote_failed = _scan(root, seen, on_progress, should_stop)
    plan.scanned = len(local)
    plan.failed = failed + remote_failed

    for uuid, (rel, asset, pkg) in local.items():
        if should_stop is not None and should_stop():
            plan.cancelled = True
            break
        common = dict(uuid=uuid, name=asset.name, type=asset.type,
                      category=asset.category, local_rel=rel)

        if uuid not in remote:
            files = _package_files(pkg)
            sizes = _sizes(pkg, files)
            plan.items.append(Item(verdict=ADD, files=files,
                                   bytes=sum(sizes.values()), **common))
            continue

        rrel, rasset, rpkg = remote[uuid]
        # The hashes dict is the cheap comparison, and it covers every file
        # that was copied in. Trusting it here avoids walking the remote
        # package over SMB for the seventy assets that did not change, which is
        # the difference between a scan of seconds and one of minutes.
        same = (asset.hashes == rasset.hashes
                and _thumb_size(pkg) == _thumb_size(rpkg))
        moved = rrel != rel
        if same and not moved:
            continue

        changed, gone, cost = [], [], 0
        if not same:
            files = _package_files(pkg)
            sizes = _sizes(pkg, files)
            rfiles = set(_package_files(rpkg))
            rsizes = _sizes(rpkg, rfiles)
            for name in files:
                if name not in rfiles or rsizes.get(name) != sizes[name]:
                    changed.append(name)
                    cost += sizes[name]
            gone = sorted(rfiles - set(files))
            # asset.json carries the hashes, so it travels whenever anything
            # else does - and _apply_one sends it last.
            if (changed or gone) and ASSET_FILE not in changed:
                changed.append(ASSET_FILE)

        plan.items.append(Item(
            verdict=MOVE if moved else UPDATE, remote_rel=rrel,
            files=changed, gone=gone, bytes=cost, also_changed=not same,
            **common))

    for uuid, (rrel, rasset, _pkg) in remote.items():
        if uuid in local:
            continue
        plan.items.append(Item(
            uuid=uuid, name=rasset.name, type=rasset.type,
            category=rasset.category, verdict=MISSING, remote_rel=rrel))

    plan.items.sort(key=lambda i: (VERDICTS.index(i.verdict), i.label))
    return plan


# ------------------------------------------------------------------ the copy


def _copy(src: Path, dst: Path, on_chunk=None, should_stop=None) -> bool:
    """One file, in chunks. False when it was abandoned half-written.

    Chunked rather than shutil.copyfile because a 1 GB .exr over SMB is a
    minute during which the window must still repaint and a cancel must still
    be heard. copyfile answers neither until it returns.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fin, dst.open("wb") as fout:
        while True:
            if should_stop is not None and should_stop():
                return False
            chunk = fin.read(CHUNK)
            if not chunk:
                break
            fout.write(chunk)
            if on_chunk is not None:
                on_chunk(len(chunk))
    try:
        shutil.copystat(src, dst)
    except OSError:
        # Samba on an ntfs-3g mount refuses some timestamp writes. The bytes
        # are what matter; a failed utime is not a failed transfer.
        pass
    return True


def _ordered(files) -> list:
    """asset.json last, always.

    It is the truth of the package: a copy interrupted after it and before its
    files would leave a manifest describing things that are not there. Written
    last, an interrupted update leaves extra files and an honest manifest,
    which the next push simply finishes.
    """
    rest = [f for f in files if f != ASSET_FILE]
    return rest + ([ASSET_FILE] if ASSET_FILE in files else [])


def _send_package(src: Path, dst: Path, files, on_chunk=None,
                  should_stop=None) -> bool:
    """A whole package, atomically: into a .partial sibling, then one rename.

    Copying straight into the final directory leaves a half-written package on
    the master the moment a transfer is interrupted - and a half-written
    package is indistinguishable from a whole one to everything downstream,
    the box's re-index included. 38 GB over SMB will be interrupted. The rename
    is the commit.

    An occupied destination is refused, not overwritten. `diff` only calls this
    for a uuid the server does not have, so a directory already sitting there
    is either a different asset or the wreckage of a run that predates the
    staging rename - and "nothing is auto-deleted" (invariant 7) applies with
    more force on the master than anywhere else. The only thing removed here is
    our own staging directory.
    """
    if dst.exists():
        raise OSError(f"{dst.name} already exists on the server - "
                      "not the same asset, so it is left alone")
    staging = dst.parent / f"{PARTIAL}{dst.name}"
    if staging.exists():
        # Our own leftovers from an interrupted run, and nothing else can be
        # here: resuming into it would mean trusting files nobody checked, so
        # re-sending is cheaper than the doubt.
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        for rel in _ordered(files):
            if not _copy(src / rel, staging / rel, on_chunk, should_stop):
                shutil.rmtree(staging, ignore_errors=True)
                return False
        os.replace(staging, dst)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return True


def _free_name(parent: Path, name: str) -> Path:
    """`parent/name`, numbered if taken. Nothing is ever written over."""
    dest = parent / name
    n = 2
    while dest.exists():
        dest = parent / f"{name}_{n:02d}"
        n += 1
    return dest


def _prune(path: Path, stop: Path) -> None:
    """Remove the folder an asset just left, if nothing else is in it.

    Upwards until something is found or `stop` is reached. The tree is
    prescriptive - `ensure_tree` recreates every declared category on demand -
    so an empty one left behind is litter, not structure.
    """
    path, stop = Path(path), Path(stop).resolve()
    while path.resolve() != stop:
        try:
            next(path.iterdir())
            return
        except StopIteration:
            pass
        except OSError:
            return
        parent = path.parent
        try:
            path.rmdir()
        except OSError:
            return
        path = parent


def _trash(share, uuid: str, name: str) -> Path:
    """Where anything leaving the library goes. uuid first, so it is findable."""
    return Path(share) / TRASH_DIR / f"{uuid[:8]}_{name}"


def _retire_files(root: Path, item: Item) -> None:
    """Files the package no longer has, moved out of it rather than deleted.

    A rename inside the same share, so it costs nothing and is reversible by
    hand. An `os.remove` here would be the one irreversible act in a module
    written specifically not to have one.
    """
    if not item.gone:
        return
    pkg = root / item.local_rel
    base = _trash(root.parent, item.uuid, item.name)
    # Its own folder per update, so a file retired today cannot land on a file
    # of the same name retired last week - which would be a delete, arrived at
    # through the mechanism that exists to avoid one.
    dest = _free_name(base.parent, base.name)
    for rel in item.gone:
        src = pkg / rel
        if not src.exists():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, target)


def _apply_one(item: Item, root: Path, local_root: Path, on_chunk,
               should_stop) -> bool:
    """One item onto the share. False means it was cancelled part-way."""
    src = local_root / item.local_rel
    dst = root / item.local_rel

    if item.verdict == ADD:
        return _send_package(src, dst, item.files, on_chunk, should_stop)

    if item.verdict == MOVE:
        old = root / item.remote_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            # Something is already at the destination and it is not this asset
            # - diff proved that, since this uuid was found at remote_rel. Two
            # assets with one path is the master's problem to resolve, not
            # something to settle by overwriting.
            raise OSError(f"{item.local_rel} is already taken on the server")
        os.replace(old, dst)
        _prune(old.parent, root)
        if not item.also_changed:
            return True

    # UPDATE, and the tail of a MOVE that also changed. Into the live package
    # rather than a staging copy: an update touches a handful of files out of a
    # gigabyte, and re-sending the whole package to gain atomicity would cost
    # more than the interruption it guards against. _ordered() is what keeps an
    # interrupted update honest.
    for rel in _ordered(item.files):
        if not _copy(src / rel, dst / rel, on_chunk, should_stop):
            return False
    _retire_files(root, item)
    return True


def push(plan: Plan, items, on_progress=None, should_stop=None) -> dict:
    """Carry out ADD / UPDATE / MOVE. Never removes an asset.

    `items` is the subset that was actually ticked, so the plan can be shown
    whole and applied in parts.
    """
    if not plan.admin:
        raise SyncError(plan.reason or "this account may not write to the share")

    root = library_root(plan.share)
    total = sum(i.bytes for i in items)
    done, current = [0], [""]
    sent, failed, cancelled = [], [], False

    def chunk(n: int) -> None:
        done[0] += n
        if on_progress is not None:
            on_progress(done[0], total, current[0])

    for item in items:
        if should_stop is not None and should_stop():
            cancelled = True
            break
        current[0] = item.label
        if on_progress is not None:
            on_progress(done[0], total, item.label)
        try:
            ok = _apply_one(item, root, plan.local_root, chunk, should_stop)
        except OSError as exc:
            failed.append((item.label, str(exc)))
            continue
        if not ok:
            cancelled = True
            break
        sent.append(item)

    return {"sent": sent, "failed": failed, "cancelled": cancelled,
            "bytes": done[0]}


# -------------------------------------------------------------- the drop box


def drop(plan: Plan, items, on_progress=None, should_stop=None) -> dict:
    """Add-only: copy new packages into `_inbox/` on the share.

    This is the path for an account that is NOT on Samba's write list. The
    drop box is a separate share that is writable, and it is not the library:
    whoever promotes a package out of it into `library/` is the one deciding
    the library changed. So a contributor can add and can never delete, and
    that is a share definition rather than a rule this app is trusted to keep.

    ADD only, by the same logic. Updating or moving something already on the
    master is an edit to the master, and an edit is not an addition.
    """
    inbox = Path(plan.share) / INBOX_DIR
    new = [i for i in items if i.verdict == ADD]
    total = sum(i.bytes for i in new)
    done, current = [0], [""]
    sent, failed, cancelled = [], [], False

    def chunk(n: int) -> None:
        done[0] += n
        if on_progress is not None:
            on_progress(done[0], total, current[0])

    for item in new:
        if should_stop is not None and should_stop():
            cancelled = True
            break
        current[0] = item.label
        if on_progress is not None:
            on_progress(done[0], total, item.label)
        # Named by uuid, not by category: the drop box is a queue, not a
        # library, and two people dropping "rock_01" on the same afternoon must
        # not land on each other. Numbered if the same asset was dropped
        # before, because whoever is promoting the queue has not necessarily
        # looked at the earlier one yet.
        dst = _free_name(inbox, f"{item.uuid[:8]}_{item.name}")
        try:
            ok = _send_package(plan.local_root / item.local_rel, dst,
                               item.files, chunk, should_stop)
        except OSError as exc:
            failed.append((item.label, str(exc)))
            continue
        if not ok:
            cancelled = True
            break
        sent.append(item)

    return {"sent": sent, "failed": failed, "cancelled": cancelled,
            "bytes": done[0]}


# --------------------------------------------------------------- removal


def discard(plan: Plan, item: Item) -> Path:
    """Take one asset out of the server's library. Admin only, one at a time.

    A rename into `_trash/`, never a delete. The library is the only copy of
    1.7 TB and a sync is exactly the moment a mistaken deletion looks
    reasonable, so the act is recoverable by definition and the sweeping of
    `_trash/` is a decision someone takes later, on purpose, on the box.
    """
    if not plan.admin:
        raise SyncError(plan.reason or "this account may not write to the share")
    root = library_root(plan.share)
    src = root / item.remote_rel
    if not src.is_dir():
        raise SyncError(f"{item.remote_rel} is no longer on the server")
    # Numbered when the same asset has been removed before - restored by hand
    # and removed again, most likely. Two packages merged into one folder is
    # not something anyone can unpick afterwards.
    dest = _trash(plan.share, item.uuid, item.name)
    dest = _free_name(dest.parent, dest.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dest)
    _prune(src.parent, root)
    return dest


# -------------------------------------------------------------- re-indexing


def reindex_command(ssh: str) -> list:
    """The command, as a list, so the UI can show exactly what it will run."""
    return ["ssh", "-o", "BatchMode=yes", ssh,
            f"sudo -n systemctl start --no-block {REINDEX_UNIT}"]


def reindex(ssh: str, timeout: int = 25) -> tuple:
    """Ask the box to rebuild its catalogue. (ok, message).

    `--no-block` because the unit is Type=oneshot and a full walk of the
    library over ntfs-3g takes minutes: without it, ssh sits there until the
    re-index finishes and the window looks hung. The answer to "is it done" is
    `indexed_at` in /api/health, which is where staleness is meant to be read.

    `BatchMode` and `sudo -n` both refuse to prompt. Starting a system unit
    needs root, and whether that is a NOPASSWD exception here is a fact about
    the box - so the failure has to be a fast, legible one rather than a
    password prompt nobody can answer from a Qt dialog.
    """
    if not ssh:
        return False, "no SSH account is set for this server"
    try:
        done = subprocess.run(reindex_command(ssh), capture_output=True,
                              text=True, timeout=timeout,
                              creationflags=getattr(subprocess,
                                                    "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        return False, "ssh is not on PATH - install the OpenSSH client"
    except subprocess.TimeoutExpired:
        return False, f"the box did not answer within {timeout}s"
    if done.returncode == 0:
        return True, "re-index started - Shift+F5 once it has run"
    detail = (done.stderr or done.stdout or "").strip().splitlines()
    return False, detail[-1] if detail else f"ssh exited {done.returncode}"
