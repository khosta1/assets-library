"""Updating the app itself from the repository it is published to.

The library has two masters and they are not the same thing. The box at
`/srv/data2/assets/library/` is the master for ASSETS; GitHub is the master for
CODE. Never the reverse - the box has no git, and GitHub must never see 44 GB.
This module is the second half only.

**Not `git pull`.** The project's premise is no install, no pip, no system
Python, and "you must also have git" breaks exactly the case the portability
exists for: a copy carried to a machine that has nothing. `.git/` travels fine
at 3.4 MB and is inert without the binary. So this fetches the published
archive over HTTPS with `urllib` and `zipfile`, both stdlib, both in the
bundled runtime - the same choice and the same reasoning as `remote.py`.

**The archive IS the tracked tree**, and that is what makes this safe rather
than careful. GitHub's zip contains what git tracks and nothing else, so
`library/`, `_cache/`, `_inbox/`, `_quarantine/`, `.assetlib/` and `runtime/`
*cannot* appear in it - they are gitignored. The list of things an update must
never touch is therefore not a filter in this file that has to be kept in step
with `.gitignore`; it is a property of what is being downloaded. A filter would
drift. This cannot.

What it does NOT do, stated rather than discovered:

    deletions   a file removed upstream stays on disk. Extracting over a tree
                adds and replaces; it does not remove. Rare enough to be worth
                less than the risk of a delete pass with a bug in it.
    runtime/    ~320 MB, gitignored, and changes approximately never. A machine
                with no copy of it cannot be fixed by this module, which is why
                a first copy still goes by disk or by `deploy.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Overridable so a fork can point this at itself without editing code. The
# default is this project's own published home.
REPO = os.environ.get("ASSETLIB_UPDATE_REPO", "khosta1/assets-library")
BRANCH = os.environ.get("ASSETLIB_UPDATE_BRANCH", "main")

API = "https://api.github.com"
CODELOAD = "https://codeload.github.com"

# Its own file, NOT state.json. `upgrade.write_state()` rewrites that one
# wholesale with three keys, so anything else kept there survives exactly until
# the next schema migration and then vanishes with no error.
STATE_FILE = "update.json"

TIMEOUT = 15
DOWNLOAD_TIMEOUT = 120
CHUNK = 1 << 20

# api.github.com answers 403 to a request with no User-Agent. urllib does not
# set one, and the failure reads as "forbidden" rather than "say who you are".
HEADERS = {
    "User-Agent": "assetlib-updater",
    "Accept": "application/vnd.github+json",
}

# Config is DATA the person edits - 18 types, 114 categories, 20 slots - and it
# is also tracked, so it arrives in every archive. Overwriting it silently is
# the worst failure available here: the app still runs, and the next import
# quietly lands somewhere else.
CONFIG_DIR = "config"


class UpdateError(RuntimeError):
    """Anything that stopped an update, in words that name the next move."""


# ------------------------------------------------------------------- state


def state_path(cfg) -> Path:
    return cfg.state / STATE_FILE


def read_state(cfg) -> dict:
    try:
        with state_path(cfg).open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                # noqa: BLE001
        return {}


def write_state(cfg, sha: str, config_hashes: dict) -> bool:
    """Record what was installed. False if it cannot be written.

    Not fatal on a read-only medium: an update that applied and could not be
    recorded is an update that will be offered again, which is annoying and
    correct, where refusing to apply it would be neither.
    """
    try:
        cfg.state.mkdir(parents=True, exist_ok=True)
        with state_path(cfg).open("w", encoding="utf-8") as fh:
            json.dump({
                "sha": sha,
                "repo": REPO,
                "branch": BRANCH,
                "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "config": config_hashes,
            }, fh, indent=2)
            fh.write("\n")
        return True
    except OSError:
        return False


def installed(cfg) -> str:
    """The commit this copy was last updated to, or "" if it never was.

    The sha and NOT `assetlib.__version__`, which has read 0.1.0 for 53 commits
    and would have an updater reporting "up to date" across three weeks of
    work. A version string is a promise someone has to keep; a sha is a fact.
    """
    return str(read_state(cfg).get("sha") or "")


# -------------------------------------------------------------------- ask


def _json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:   # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(
                f"{REPO} has no branch {BRANCH} - or the repository is private, "
                "which this updater cannot read") from exc
        if exc.code == 403:
            raise UpdateError(
                "GitHub refused the request (rate limit, most likely) - "
                "try again in a few minutes") from exc
        raise UpdateError(f"GitHub answered {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"could not reach GitHub: {exc.reason}") from exc
    except ValueError as exc:
        raise UpdateError("GitHub's answer was not JSON") from exc


def latest(branch: str = "") -> dict:
    """{sha, short, date, message} for the head of the published branch."""
    branch = branch or BRANCH
    data = _json(f"{API}/repos/{REPO}/commits/{branch}")
    sha = str(data.get("sha") or "")
    if not sha:
        raise UpdateError("GitHub named no commit for that branch")
    commit = data.get("commit") or {}
    author = commit.get("author") or {}
    return {
        "sha": sha,
        "short": sha[:7],
        "date": str(author.get("date") or "")[:10],
        "message": str(commit.get("message") or "").splitlines()[0],
    }


def changes(since: str, until: str) -> list:
    """Commit subjects between two shas, oldest first. [] when it cannot say.

    Deliberately soft: the compare endpoint fails on a sha GitHub no longer has
    (a force-push, a copy older than the history), and not being able to list
    what changed is no reason to refuse to update. The caller shows what it got.
    """
    if not since or since == until:
        return []
    try:
        data = _json(f"{API}/repos/{REPO}/compare/{since}...{until}")
    except UpdateError:
        return []
    out = []
    for item in data.get("commits") or []:
        line = str((item.get("commit") or {}).get("message") or "")
        if line:
            out.append(line.splitlines()[0])
    return out


# ------------------------------------------------------------------- fetch


def download(sha: str, into: Path, progress=None) -> Path:
    """Fetch the archive for one commit. Returns the zip on disk.

    By SHA and not by branch name, so what is verified is what was offered: a
    push landing between the check and the download would otherwise install a
    commit nobody was shown.
    """
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    target = into / f"{sha[:12]}.zip"
    url = f"{CODELOAD}/{REPO}/zip/{sha}"

    req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
    try:
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:  # noqa: S310
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            # .part, then rename. A zip that stops half way must not be left
            # where the next run would find it and trust it.
            part = target.with_suffix(".part")
            with part.open("wb") as fh:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            part.replace(target)
    except urllib.error.URLError as exc:
        raise UpdateError(f"download failed: {exc.reason}") from exc
    except OSError as exc:
        raise UpdateError(f"could not write the download: {exc}") from exc

    if not zipfile.is_zipfile(target):
        # An HTML error page saved with a .zip name is the usual shape of this.
        target.unlink(missing_ok=True)
        raise UpdateError("what arrived is not a zip - the download was "
                          "intercepted or the commit is gone")
    return target


def extract(archive: Path, into: Path) -> Path:
    """Unpack, and return the single folder GitHub wraps everything in.

    Checked rather than assumed: every entry must sit under one root, and that
    root must contain `assetlib/__init__.py`. An archive that fails either test
    is not this project, and finding that out BEFORE anything is copied over a
    working install is the whole reason staging exists.
    """
    into = Path(into)
    if into.exists():
        shutil.rmtree(into, ignore_errors=True)
    into.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive) as zf:
        roots = set()
        for name in zf.namelist():
            head = name.split("/", 1)[0]
            if not head or name.startswith("/") or ".." in Path(name).parts:
                raise UpdateError(f"the archive contains an unsafe path: {name}")
            roots.add(head)
        if len(roots) != 1:
            raise UpdateError(f"expected one folder in the archive, found {len(roots)}")
        zf.extractall(into)

    root = into / roots.pop()
    if not (root / "assetlib" / "__init__.py").is_file():
        raise UpdateError("the archive has no assetlib/ - this is not the "
                          "Asset Library")
    return root


# ------------------------------------------------------------------- apply


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _config_verdict(cfg, base: Path, root: Path) -> dict:
    """For each config file: 'write', 'same' or 'keep'. Never a silent replace.

    `keep` means the local file differs from the one recorded at the last
    update - so someone edited it, and their 115th category is not ours to
    discard. The new version lands beside it as `.new` and is reported.

    With nothing recorded - a copy that has never been updated - every
    difference reads as an edit. That is the conservative direction: the cost of
    being wrong is a `.new` file nobody needed, against losing a config nobody
    can reconstruct.
    """
    known = (read_state(cfg).get("config") or {})
    out = {}
    src_dir = root / CONFIG_DIR
    if not src_dir.is_dir():
        return out
    for src in sorted(src_dir.glob("*.json")):
        here = base / CONFIG_DIR / src.name
        if not here.exists():
            out[src.name] = "write"
            continue
        if _digest(here) == _digest(src):
            out[src.name] = "same"
            continue
        out[src.name] = "write" if _digest(here) == known.get(src.name) else "keep"
    return out


def plan(cfg, base: Path, root: Path) -> dict:
    """What applying this would do, before it does any of it."""
    base, root = Path(base), Path(root)
    verdict = _config_verdict(cfg, base, root)
    files = [p for p in root.rglob("*") if p.is_file()]
    return {
        "files": len(files),
        "config_kept": sorted(n for n, v in verdict.items() if v == "keep"),
        "config_written": sorted(n for n, v in verdict.items() if v == "write"),
        "verdict": verdict,
    }


def apply(cfg, base: Path, root: Path) -> dict:
    """Copy the staged tree over the install. Returns what happened.

    No deletion pass and no backup of the whole tree: the install IS a git
    checkout of what is being written, so the thing a backup would protect is
    already published. What is not published - `library/`, `runtime/`,
    `.assetlib/` - cannot be reached from here, because it is not in the
    archive.
    """
    base, root = Path(base), Path(root)
    verdict = _config_verdict(cfg, base, root)
    written, kept = 0, []

    for src in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = src.relative_to(root)
        parts = rel.parts
        if parts[0] == CONFIG_DIR and len(parts) == 2:
            call = verdict.get(parts[1], "write")
            if call == "same":
                continue
            if call == "keep":
                dest = base / rel
                dest.with_suffix(dest.suffix + ".new").write_bytes(src.read_bytes())
                kept.append(parts[1])
                continue
        dest = base / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            written += 1
        except OSError as exc:
            raise UpdateError(f"could not write {rel}: {exc}") from exc

    hashes = {}
    for src in sorted((root / CONFIG_DIR).glob("*.json")) if (root / CONFIG_DIR).is_dir() else []:
        hashes[src.name] = _digest(src)

    return {"written": written, "config_kept": kept, "config_hashes": hashes}


def clean(into: Path) -> None:
    """Throw the staging area away. Never fatal - it is a temp folder."""
    shutil.rmtree(Path(into), ignore_errors=True)
