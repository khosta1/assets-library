---
name: doc-ritual
description: Decide which document a change has to update - decisions, gotchas, features, History, architecture invariants or the roadmap - and write it in the right register. Use after a change lands, when something was learned the hard way, when a design choice was made or rejected, when code is removed or switched off, or whenever it is unclear where a piece of knowledge belongs.
---

# Where this goes

A document with no defined moment of writing rots. These are the moments.

## The table

| What just happened | Where it goes | Command |
|---|---|---|
| a choice was made that someone could re-propose | `docs/decisions.md` | `/decide` |
| an idea was turned down | `docs/decisions.md`, *Rejected* | `/decide` |
| an hour was lost to a trap | `docs/gotchas.md` | `/gotcha` |
| code was deleted | `docs/History/` + `features.md` REMOVED | `/retire` |
| a feature was switched off | `docs/features.md` DORMANT, **switch named** | — |
| a feature shipped | `docs/features.md` LIVE | — |
| a subsystem boundary moved | `docs/architecture.md`, the joins | — |
| a property must now always hold | `docs/architecture.md` §invariants | `/invariants` |
| a rule flipped | `docs/decisions.md`, *Reversed* | `/decide` |
| a roadmap item landed, moved or was parked | `ROADMAP.md`, with the date | `/handoff` |
| a bug was observed | `ROADMAP.md`, *Open bugs* | `/handoff` |
| a paper, library or article was consulted | `docs/sources.md` | — |
| a path, version or disk fact changed | `docs/machine.md` | — |
| the session ended | `docs/journal.md` | `/handoff` |
| a preference of Felix's | Claude's memory, **never a project doc** | — |

## The register

- **Argue, do not paraphrase.** A doc that restates the code dies the day the
  code changes — and is trusted until someone notices.
- **Date anything that can change**: rules, states, reversals, measurements.
  When a rule flips, keep the old one in the sentence.
- **Say what is not built.** A design doc that reads as a description of
  existing code costs half a day.
- **One owner per fact.** Everything else links. If it is already written
  somewhere, link it instead of restating it — especially in `CLAUDE.md`, which
  is paid every session and goes stale first.
- **Use the words you would have searched for**, not the words you would use
  once you understood the problem.

## Before writing

Check it is not already there — `docs/gotchas.md`, `docs/decisions.md`,
`docs/History/`. A second entry on the same subject means the first one was not
finished, and now there are two answers.

## After writing

If the change touched code that a doc declares it `covers:`, that doc is now
either updated or stale. Run `/stale` and settle it while you still remember
what changed.
