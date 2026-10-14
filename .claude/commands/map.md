---
description: Regenerate the code map, and report what moved
argument-hint: "[source dirs, if the default is wrong]"
allowed-tools: Bash(python tools/codemap.py:*), Bash(scc:*), Read
---

Run `python tools/codemap.py $ARGUMENTS` and report the summary line: files,
lines, types.

Then say what is worth saying about the shape rather than repeating the
numbers:

- **The heaviest files**, and whether the weight sits where the design says it
  should. A file that has quietly become the biggest in the tree is usually
  three subsystems that never got separated.
- **A type with no home** — something defined in a file whose name has nothing
  to do with it.
- **Whether `CLAUDE.md`'s code table still matches.** That table is the map an
  agent reads before opening anything; when it drifts, every session starts
  with a wrong turn. Line counts in it come from `scc` or from this run —
  never typed by hand.

`docs/codemap.html` is gitignored: regenerate, never commit. A map of code that
has moved is worse than no map, because it is believed.
