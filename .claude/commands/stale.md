---
description: Find docs the code has moved out from under, and judge each one
allowed-tools: Bash(python tools/stale.py:*), Bash(git log:*), Bash(git diff:*), Read, Edit
---

Run `python tools/stale.py --all`.

Drift is a **signal, not a verdict**. For each doc it reports, read the commits
that touched its subject since the doc was last changed, and classify it:

- **Still true** — the doc argues about design, and the commits were
  implementation. Nothing to do. This is the normal case for a well-written
  doc, and it is the point of writing them that way.
- **Now wrong** — it describes something that no longer works like that. Fix
  the sentences that are wrong; do not rewrite the file to look busy.
- **Now incomplete** — the design grew a part the doc never mentions. Add it.
- **Obsolete** — its subject is gone. It belongs in `docs/History/`, with a
  line at the top saying what replaced it and when. Archived is not the same as
  wrong; say which it is.

For any doc reported as declaring **no coverage**, propose the `covers:` line
it should have. One line, git pathspecs, at the top:

```
<!-- covers: src/WaterSim.*, src/SimHost.* -->
```

A doc with no coverage line is invisible to this check forever, which is the
one failure this tooling exists to prevent.

Report as a short list: doc, verdict, and what you changed. Do not edit a doc
you have not read the commits for.
