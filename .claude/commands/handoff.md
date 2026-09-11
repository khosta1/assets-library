---
description: Write the session into docs/journal.md and update ROADMAP.md
argument-hint: "[optional: anything to emphasise in the entry]"
allowed-tools: Bash(git status:*), Bash(git log:*), Bash(git diff:*), Read, Edit, Write
---

Close the session in writing. This is the only thing standing between a
compaction and a lost day of reasoning.

Current state, for reference:

- branch and changes: !`git status --short`
- commits this session: !`git log --oneline -8`

## What to write

Append a new entry at the TOP of the "Newest first" list in `docs/journal.md`,
dated today, with exactly these four fields:

**Done.** What landed. One line each, naming the file or the commit. Not a
narrative — a reader three weeks from now wants the list, not the story.

**Decided.** Choices taken, each with its reason in the same sentence. If a
choice will still matter in a month, put it in `docs/decisions.md` and link it
from here instead of repeating it. If an idea was rejected, record it in the
*Rejected — do not reopen* table, stated as its advocate would state it.

**Open.** What is half-done, and in exactly what state — mid-refactor, built
but not wired up, working but slow, three approaches tried and two abandoned.
**This is the field that compaction destroys and that costs a morning to
rebuild.** Be specific enough that tomorrow's session can resume without
re-deriving anything.

**Next.** The one thing to do first next session. One, not five.

## Then

1. **`ROADMAP.md`** — mark any item that landed with its date (never delete
   it), move anything that got reordered or parked, and add any bug observed
   today to *Open bugs*, in the words you would use watching it happen.
2. **`docs/gotchas.md`** — if an hour was lost to something today and it is not
   already written down, write it now. At the end of the week it will be
   remembered as "something with the paths".
3. **`docs/features.md`** — if a feature shipped, was switched off, or was
   deleted, move its line to the right state. A DORMANT entry must name its
   switch.

## Rules

- Do **not** commit. Writing the journal and committing are separate decisions.
- Do not invent completeness. If something was abandoned half-way, the entry
  says so — a journal that only records successes is a journal nobody trusts
  when it matters.
- Keep it short. Anything still true in a month gets promoted to a real doc;
  the journal is what was true that day.

$ARGUMENTS
