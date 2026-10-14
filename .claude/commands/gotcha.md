---
description: Record a trap that cost an hour, so it costs an hour only once
argument-hint: "<what bit you>"
allowed-tools: Read, Edit
---

Add this to `docs/gotchas.md` as a new numbered entry, dated today:

$ARGUMENTS

## The shape, in this order

**Title** — the symptom, not the cause. The cause is not what you will be
searching for at 2am; the symptom is.

**What was observed** — concretely, in the words that were in your head at the
time. "Reloading a chunk appears full of water" beats "chunk boundary
desynchronisation". A gotcha is found by grep, and grep only matches what you
would have typed.

**Cause** — what was actually happening, one or two sentences.

**Fix** — what changed, and where. Name the file and the function.

**Rule** — the general form, if there is one. This is the line that prevents
the *next* instance rather than this one: "unverifiable is not the same as
corrupted", "a small file that merely accompanies an asset never determines
what that asset is". Omit the line entirely when the gotcha is genuinely
one-off — an invented rule is worse than none.

## Rules

- **Never renumber.** Entries are referred to by number.
- **Append at the end**, keeping the numbering ascending.
- If it turns out to be a design decision rather than a trap, it belongs in
  `docs/decisions.md`. If it turns out to be a removed feature, `docs/History/`.
  Put it in one place only.
