---
description: Rebuild the context packs, and check they are still cut right
argument-hint: "[pack name, or nothing for all]"
allowed-tools: Bash(python tools/pack.py:*), Read, Edit
---

Rebuild: run `python tools/pack.py $ARGUMENTS` and report the token counts it
prints.

Then look at the numbers rather than just passing them on:

- **A pack over ~80k is two topics wearing a trenchcoat.** Propose the split,
  named by topic, not by folder.
- **A pack under ~5k is probably not a pack** — it is a couple of files you
  could have read directly.
- **A pack that failed** usually means `packs.json` lists a path that has moved.
  Fix the patterns, do not delete the pack.

## The rule a pack must satisfy

**Self-sufficient**: the topic's code, the headers of the neighbours it depends
on, and the docs that explain *why* it is like that. A pack that forces you to
open a second pack is cut wrong, and cutting it wrong costs a whole extra load
in the session that needed it.

`brief` is mandatory and is attached first, always.

If a pack listed in `packs.json` has never been used by any session, say so —
it is noise, and `packs.json` is meant to be edited, not curated.

Remember `context/` is gitignored on purpose: regenerate after a big move, and
never commit a pack. A stale pack is a confident description of code that no
longer exists.
