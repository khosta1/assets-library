#!/usr/bin/env python3
"""Which docs are older than the code they describe.

The failure this whole scaffold exists to prevent is a document that is trusted
and no longer true. Nothing detects that by reading the prose -- but git knows
when the doc last changed and when its subject last changed, and the gap
between the two is the entire signal.

A doc opts in with one line near the top:

    <!-- covers: src/WaterSim.*, src/SimHost.* -->

Patterns are git pathspecs, relative to the project root.

    python tools/stale.py               every doc that declares coverage
    python tools/stale.py --all         also list docs that declare none
    python tools/stale.py --days 30     only report drift older than N days

Exit code 1 when something has drifted, so it can be used in a hook or a
scheduled report without parsing the output.
"""

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Where docs live. A doc outside these is not ignored on purpose -- it is
# simply not the kind of file this tool is about.
DOC_GLOBS = ["docs/**/*.md", "docs/**/*.txt", "*.md"]

COVERS_RE = re.compile(r"<!--\s*covers:\s*(.+?)\s*-->", re.IGNORECASE)
HEAD_LINES = 10          # how far into a file to look for the covers line


def git(*args):
    proc = subprocess.run(["git"] + list(args), cwd=str(ROOT),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def last_commit_time(pathspecs):
    """Unix time of the last commit touching any of these pathspecs."""
    out = git("log", "-1", "--format=%ct", "--", *pathspecs)
    return int(out) if out.isdigit() else 0


def commits_since(ts, pathspecs):
    """How many commits touched these pathspecs STRICTLY after ts.

    --since is inclusive, so passing the doc's own timestamp counts the commit
    that created the doc: on a fresh repo every doc committed alongside its
    subject reports drift against itself. +1 second is the whole fix -- git
    timestamps are second-resolution, so nothing else can fall in the gap.
    """
    out = git("rev-list", "--count", "--since=@%d" % (ts + 1), "HEAD", "--", *pathspecs)
    return int(out) if out.isdigit() else 0


def find_docs():
    seen = []
    for pattern in DOC_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.append(path)
    return seen


def covers_of(path):
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            head = "".join(next(fh, "") for _ in range(HEAD_LINES))
    except OSError:
        return []
    match = COVERS_RE.search(head)
    if not match:
        return []
    return [p.strip() for p in match.group(1).split(",") if p.strip()]


def main():
    if not (ROOT / ".git").exists():
        sys.exit("not a git repository -- stale.py has nothing to compare against")

    show_all = "--all" in sys.argv
    min_days = 0
    if "--days" in sys.argv:
        min_days = int(sys.argv[sys.argv.index("--days") + 1])

    drifted, undeclared, clean = [], [], []
    now = time.time()

    for doc in find_docs():
        rel = doc.relative_to(ROOT).as_posix()
        patterns = covers_of(doc)
        if not patterns:
            undeclared.append(rel)
            continue

        doc_ts = last_commit_time([rel])
        if doc_ts == 0:
            # Never committed: it is new, not stale.
            clean.append((rel, 0, 0))
            continue

        n = commits_since(doc_ts, patterns)
        days = int((now - doc_ts) / 86400)
        if n > 0 and days >= min_days:
            drifted.append((rel, n, days))
        else:
            clean.append((rel, n, days))

    if drifted:
        print("DRIFTED -- the code moved, the doc did not")
        width = max(len(d[0]) for d in drifted)
        for rel, n, days in sorted(drifted, key=lambda d: -d[1]):
            print("  %-*s  %3d commits to its subject since it was last touched "
                  "(%d days ago)" % (width, rel, n, days))
    else:
        print("No drift.")

    if show_all and undeclared:
        print("\nNo coverage declared (add a <!-- covers: ... --> line to include them):")
        for rel in undeclared:
            print("  " + rel)

    if drifted:
        print("\nDrift is not automatically a rewrite: read the commits first. "
              "A doc that argues about design survives changes a doc that "
              "describes code does not.")
        sys.exit(1)


if __name__ == "__main__":
    main()
