#!/usr/bin/env python3
"""Search past Claude Code sessions.

Every session is stored as JSONL under ~/.claude/projects/<slug>/. The answer
to "did we already try this, and what happened" is usually sitting in a
transcript from three weeks ago -- and grepping it costs nothing next to
reasoning it out again.

    python tools/recall.py erosion            this project's sessions
    python tools/recall.py "chunk boundary" --days 60
    python tools/recall.py normal --all       every project on this machine
    python tools/recall.py --sessions         list sessions, newest first

Matching is case-insensitive substring by default; a query containing regex
metacharacters is treated as a regex (use --literal to force plain text).

WHEN IT FINDS THE ANSWER, PROMOTE IT. A fact you had to dig a transcript for
will be dug for again: it belongs in gotchas.md, decisions.md or History/.
This tool is an archaeology kit, not a memory.
"""

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = Path.home() / ".claude" / "projects"

CONTEXT_CHARS = 220      # around each hit
MAX_HITS = 40


def slug_for(path):
    """Claude Code's directory name for a project path.

    C:\\Users\\felix  ->  C--Users-felix
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def session_files(all_projects):
    if not PROJECTS.exists():
        sys.exit("no transcripts at %s" % PROJECTS)

    if all_projects:
        dirs = [d for d in PROJECTS.iterdir() if d.is_dir()]
    else:
        d = PROJECTS / slug_for(ROOT)
        if not d.exists():
            sys.exit("no transcripts for this project (%s).\n"
                     "Looked for: %s\nUse --all to search every project." % (ROOT, d))
        dirs = [d]

    files = []
    for d in dirs:
        files.extend(d.glob("*.jsonl"))
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def text_of(entry):
    """Pull readable text out of one transcript line, whatever its shape.

    The format has changed before and will again; anything unrecognised is
    skipped rather than crashed on. (Same rule as every reader in this repo:
    skip unknown tags, default absent ones.)
    """
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            # The command or the file path is often the thing being searched for.
            parts.append(json.dumps(block.get("input", ""))[:400])
    return "\n".join(parts)


def iter_messages(path):
    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if entry.get("type") not in ("user", "assistant"):
                continue
            yield entry


def when(entry, path):
    ts = entry.get("timestamp")
    if isinstance(ts, str) and len(ts) >= 10:
        return ts[:10]
    return time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    all_projects = "--all" in flags

    days = 0
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
        args = [a for a in args if a != str(days)]
    cutoff = time.time() - days * 86400 if days else 0

    files = session_files(all_projects)
    if cutoff:
        files = [f for f in files if f.stat().st_mtime >= cutoff]

    if "--sessions" in flags:
        for f in files:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))
            size = f.stat().st_size // 1024
            print("  %s  %6d kb  %s" % (stamp, size, f.name[:8]))
        print("\n%d sessions." % len(files))
        return

    if not args:
        sys.exit(__doc__.strip().splitlines()[0] + "\n\nusage: recall.py <query> [--all] [--days N]")

    query = " ".join(args)
    literal = "--literal" in flags or not re.search(r"[\\^$.|?*+()\[\]{}]", query)
    pattern = re.compile(re.escape(query) if literal else query, re.IGNORECASE)

    hits = 0
    for path in files:
        session_printed = False
        for entry in iter_messages(path):
            text = text_of(entry)
            if not text:
                continue
            match = pattern.search(text)
            if not match:
                continue

            if not session_printed:
                print("\n=== %s  session %s" % (when(entry, path), path.name[:8]))
                session_printed = True

            start = max(0, match.start() - CONTEXT_CHARS // 2)
            end = min(len(text), match.end() + CONTEXT_CHARS // 2)
            snippet = " ".join(text[start:end].split())
            role = entry.get("message", {}).get("role", "?")
            print("  [%s] ...%s..." % (role, snippet))

            hits += 1
            if hits >= MAX_HITS:
                print("\n(%d hits shown, stopping -- narrow the query)" % hits)
                return

    if hits == 0:
        print("Nothing found for %r in %d session(s)." % (query, len(files)))
    else:
        print("\n%d hits. If one of them answered a real question, write it into "
              "gotchas.md or decisions.md -- do not leave it in the transcript." % hits)


if __name__ == "__main__":
    main()
