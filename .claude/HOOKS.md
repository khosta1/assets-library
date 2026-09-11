# The three hooks

`settings.json` is strict JSON and cannot carry comments, so the reasoning
lives here. This file is the owner of it; do not restate it elsewhere.

The hooks are deliberately **inline commands**, not a helper script. Each one
is a single readable line you can run in a terminal to see exactly what it
does, and there is no fifth tool to keep in sync.

---

## SessionStart — five hundred tokens that replace ten minutes

Runs on `startup` and `resume`. Five commands, each answering one question a
new session would otherwise ask you:

| command | answers |
|---|---|
| `git log --oneline -5` | what happened last |
| `git status --short` | what is in flight right now |
| first 40 lines of `docs/journal.md` | what was decided, what is half-done, what is next |
| the `## Open bugs` block of `ROADMAP.md` | what is known-broken, so it is not "discovered" again |
| `python tools/stale.py` | which docs can no longer be trusted |

Everything is guarded with `Test-Path`, so a project missing `journal.md` or
`ROADMAP.md` prints nothing rather than an error. `stale.py` exits 1 on drift;
that is a report, not a failure.

If this ever gets slow or noisy, cut a line rather than the whole hook. The
orientation is worth more than any single item in it.

---

## PreCompact — the only defence against a lost morning

Compaction keeps conclusions and loses **state**: what is half-done, which of
three approaches was abandoned, what the next step was.

A hook cannot run a slash command — it can only put text in front of the model
before the window is summarised. So it prints the instruction, and
`CLAUDE.md`'s *How to work here* backs it up as a standing rule. Between the
two, `/handoff` gets run while the reasoning still exists.

**This one is worth checking manually the first few times.** If a compaction
ever happens without a journal entry landing, the fix is to run `/handoff`
yourself at the first sign of a long session, not to make the hook cleverer.

---

## Stop — catching drift at the only moment it is cheap

When the session ends: if the working tree has changes under `src/` and none
under `docs/`, say so, and name where the missing note would go.

It is a prompt, not a gate. Plenty of sessions legitimately change code and no
document — a typo fix, a rename, a build tweak. The message costs a line and
the omission it catches costs an afternoon three weeks later.

`^.. src/` matches the status short-format's two status columns, so a file
merely *named* `src` somewhere in a path does not trigger it.

---

## Changing them

- **Windows-first.** The PowerShell calls assume `powershell.exe`; on another
  platform replace them with the obvious `sh` equivalent, keeping one command
  per question.
- **Add a hook only when it answers a question you keep asking.** Every hook
  runs forever and is paid on every session, exactly like `CLAUDE.md`.
- **Never make a hook write to a file the agent also writes to.** The hook
  runs outside the conversation; a concurrent edit is invisible to both.
