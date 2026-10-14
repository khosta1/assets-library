---
description: Record a decision, its reasoning, and what it rejects
argument-hint: "<the decision, in your own words>"
allowed-tools: Read, Edit
---

Record this in `docs/decisions.md`, now, while the alternative is still fresh
enough to state fairly:

$ARGUMENTS

## Where it goes

- **Locked, with the reasoning** — the normal case. One row: the decision, and
  the *why* that makes it re-checkable if constraints change.
- **The central decision** — only if it is the one that shapes everything else
  in the project. Most projects have one; none have three.
- **Rejected — do not reopen** — if the substance is that an approach was
  turned down.
- **Reversed** — if this replaces an existing rule. Keep the old rule in the
  sentence: a rule with a history is obeyed, a rule without one is argued with.

## How to write it

- **The why is the reason it is recorded at all.** "We chose Python 3.11" is
  worth nothing; "3.11 is the only version shared by Houdini 20.5, 21.0 and
  22.0, so the core stays importable by `hou`" can be re-judged when Houdini
  ships 23.
- **Prefer the constraint over the preference.** A decision justified by taste
  gets overturned by the next person with different taste.
- **State a rejected idea well** — as its advocate would state it. A strawman
  will not match the strong version an agent proposes next week, so it will not
  be recognised as already-settled, which is the entire purpose of the table.
- **Date it.**

If the decision contradicts something already in the file, do not just add the
new row: move the old one to *Reversed* and say what made it wrong.
