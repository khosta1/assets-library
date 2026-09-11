#!/usr/bin/env python3
"""What each document costs, against the tier budgets.

The four-tier model (guides/context-budget.md) only means something if someone
measures it. This is the someone.

    python tools/budget.py            the report
    python tools/budget.py --strict   exit 1 if a budget is exceeded

Token counts are an ESTIMATE -- characters divided by a per-kind ratio, no
tokeniser, no dependency. It is accurate to about 10%, which is far more
precision than a budget decision needs: the question is never "is it 14.2k or
15.8k", it is "has tier 1 quietly become tier 3".

For an exact count of a generated pack, read the number repomix printed when
pack.py built it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Prose tokenises at roughly 4 chars/token; code, with its punctuation and
# short identifiers, closer to 3.2. Splitting the two keeps the estimate honest
# for packs, which are mostly code, and for docs, which are mostly not.
CHARS_PER_TOKEN_PROSE = 4.0
CHARS_PER_TOKEN_CODE = 3.2

# Tier 0 is paid on every session of the project's life. The cap is a line
# count because that is what you can see while editing.
CLAUDE_MD_MAX_LINES = 150

TIER1 = ["docs/architecture.md", "docs/decisions.md", "docs/gotchas.md"]
TIER1_MAX_TOKENS = 15_000
PACK_MAX_TOKENS = 80_000


def estimate(path, code=False):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, 0
    ratio = CHARS_PER_TOKEN_CODE if code else CHARS_PER_TOKEN_PROSE
    return int(len(text) / ratio), text.count("\n") + 1


def line(name, tokens, extra="", flag=""):
    print("  %-34s %8s tokens  %s%s" % (name, "{:,}".format(tokens), extra, flag))


def main():
    over = []

    print("TIER 0 -- paid every session")
    claude = ROOT / "CLAUDE.md"
    if claude.exists():
        tokens, lines = estimate(claude)
        flag = ""
        if lines > CLAUDE_MD_MAX_LINES:
            flag = "   <-- OVER: %d lines, cap is %d" % (lines, CLAUDE_MD_MAX_LINES)
            over.append("CLAUDE.md")
        line("CLAUDE.md", tokens, "%d lines" % lines, flag)
    else:
        print("  CLAUDE.md missing -- the router is the one file that is not optional")
        over.append("CLAUDE.md")

    print("\nTIER 1 -- read almost every session")
    total = 0
    for rel in TIER1:
        path = ROOT / rel
        if not path.exists():
            print("  %-34s   (absent)" % rel)
            continue
        tokens, lines = estimate(path)
        total += tokens
        line(rel, tokens, "%d lines" % lines)
    flag = ""
    if total > TIER1_MAX_TOKENS:
        flag = "   <-- OVER budget of %s" % "{:,}".format(TIER1_MAX_TOKENS)
        over.append("tier 1")
    line("TOTAL", total, "", flag)

    print("\nTIER 2 -- subsystem docs, loaded on demand")
    docs = sorted((ROOT / "docs").glob("*.md")) if (ROOT / "docs").exists() else []
    for path in docs:
        rel = path.relative_to(ROOT).as_posix()
        if rel in TIER1:
            continue
        tokens, lines = estimate(path)
        line(rel, tokens, "%d lines" % lines)

    print("\nTIER 3 -- generated packs")
    context = ROOT / "context"
    if not context.exists():
        print("  none built yet (tools/pack.py)")
    else:
        for path in sorted(context.glob("*.md")):
            tokens, _ = estimate(path, code=True)
            flag = ""
            if tokens > PACK_MAX_TOKENS:
                flag = "   <-- over %dk, probably two topics" % (PACK_MAX_TOKENS // 1000)
            line("context/" + path.name, tokens, "", flag)

    if over:
        print("\nOver budget: " + ", ".join(over))
        print("The fix for tier 0 is never compression -- it is moving an "
              "explanation into docs/ and leaving a pointer.")
        if "--strict" in sys.argv:
            sys.exit(1)


if __name__ == "__main__":
    main()
