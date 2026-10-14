---
description: Remove code properly - the argument into History/, the line into features.md
argument-hint: "<what is being removed>"
allowed-tools: Read, Edit, Write, Bash(git log:*), Bash(git show:*), Grep, Glob
---

Retire this, in writing, **at the moment of removal** — never reconstructed
later, when the reasons have softened into "it wasn't great":

$ARGUMENTS

## 1. Write `docs/History/<subject>.md`

Lower case, one subject per file. Four sections:

**What it did** — enough that a future reader can judge whether the problem it
solved is the one they now have.

**Why it went** — the argument. Specific: what it cost, what replaced it, what
stopped being true. "It was complex" is not an argument.

**What the problem was, and whether it has gone away** — the critical half. A
feature removed because its problem disappeared stays removed. A feature
removed because something else now covers it comes straight back the day that
something else changes, and then this file is the spec. Say which case this is.

**The code** — quoted, if re-deriving it would be expensive. Pull it from git
rather than from memory.

## 2. Flip the line in `docs/features.md`

Move it to **REMOVED**, with the date, the commit, one line of why, and a
pointer to the History file. If it is being switched off rather than deleted,
it is **DORMANT** instead — and a DORMANT entry must name its switch, or it is
a rumour and the feature gets rebuilt by someone who could not tell it was
already there.

## 3. Check the rest

- `docs/architecture.md` — does a **RULE** or an invariant refer to it? Does a
  seam close, or open?
- `packs.json` — does a pack still list files that no longer exist?
- `ROADMAP.md` — is there an item that assumed this existed?

## Then, and only then, remove the code.

Do not commit. Report what was written and what the removal touched.
