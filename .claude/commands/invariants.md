---
description: Check the current change against the architecture invariants
allowed-tools: Read, Bash(git diff:*), Bash(git status:*), Grep, Glob
---

Before this change is called finished, check it against the invariants.

The diff under review: !`git diff --stat`

## How to do it

1. Read the **invariants** section at the end of `docs/architecture.md`. All of
   it — the list is short precisely so it can be read in full every time.
2. Read the actual diff, not the summary.
3. Go down the list **one entry at a time** and say, for each:
   - **not touched** — the change cannot affect it, in one clause; or
   - **holds** — the change touches it and it still holds, with the reason; or
   - **at risk** — what specifically could break it, and where.

No entry may be skipped. An invariant that is "obviously fine" is exactly the
one that was obviously fine the last time it broke — every entry on that list
is there because breaking it once cost a day.

## Then

- If anything is **at risk**, say so plainly and stop. Do not present the
  change as finished and mention the risk afterwards.
- If the change *introduces* a property that must now always hold, propose it
  as a new invariant, with the failure that motivates it.
- If an invariant turns out to be wrong rather than violated, that is a
  decision, not a fix: `/decide` it, and move the old one to *Reversed*.

Report as a list, one line per invariant. Brevity here is the point — this
check has to be cheap enough to run every time, or it will not be run at all.
