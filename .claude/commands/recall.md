---
description: Search past sessions for a decision, a symptom, or an attempt
argument-hint: "<what you half-remember>"
allowed-tools: Bash(python tools/recall.py:*), Read, Edit
---

Search the transcripts: `python tools/recall.py $ARGUMENTS`

If this project's sessions turn up nothing, widen once with `--all` before
concluding it never happened — work often starts in a neighbouring project or
in a session that ran from a different directory.

## Read the hits carefully

A transcript is a record of what was **said**, not of what is **true**. An idea
discussed enthusiastically three weeks ago may never have been built, or may
have been built and reverted. Check the claim against the code or the git log
before repeating it as fact.

## Then promote it

This is the part that matters. A fact you had to dig a transcript for will be
dug for again, by you, in a month:

| what you found | where it belongs now |
|---|---|
| a trap that cost time | `docs/gotchas.md` |
| a choice and its reasoning | `docs/decisions.md` |
| an idea considered and turned down | `docs/decisions.md`, *Rejected* |
| something built and removed | `docs/History/` |
| something built and switched off | `docs/features.md`, DORMANT |

Report what you found, and what you wrote down. If the answer was already in a
doc and you simply did not look, say that too — it means the doc is in the
wrong place or badly titled, which is worth knowing.
