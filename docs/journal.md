# Journal

Newest first.

---

## 2026-09-11

**Done.** Ported the project onto the AI base workflow scaffold
(`H:/Code/AI_base_workflow`). `CONTEXT.md` — 19 KB, one file, everything in it —
was split by subject: §2–3 → `docs/decisions.md`, §8 → `docs/gotchas.md` (the
twelve entries keep their numbers), §4+§6 → `docs/machine.md`, §5 "Done" →
`docs/features.md`, §5 layout + §7 flow + the layering rule →
`docs/architecture.md` with twelve invariants and a seams section, §9–10 →
`ROADMAP.md`. `CLAUDE.md` is the router that points at all of it.
`docs/History/` gained `cli-removed.md` and `draft-superseded.md` (the old
`DRAFT.md`). Copied in `tools/`, `.claude/` (9 commands, 3 skills, 2 subagents,
3 hooks) and `packs.json` with five real packs. `git init`, first commit.

**Decided.** `CONTEXT.md` is deleted rather than kept alongside: two sources of
truth is none, and the split *is* the port. `DRAFT.md` is archived rather than
deleted — it records what the design looked like before any code existed, which
is how you see which parts survived contact with real vendor files. Git,
finally: the code existed in exactly one place, on a disk with no backup.

**Open.** Nothing is half-done in the code. What is unproven is the scaffold
itself: none of the six tools has run against a real tree, and no hook has
fired. This project is the shake-out — expect `stale.py` to want `covers:`
lines it does not have yet, and expect one PowerShell line in
`.claude/settings.json` to need a quote fixed.

**Next.** Run the tools once, in this order: `tools\budget.bat` (cheapest, no
side effects), `tools\codemap.bat` (exercises the Python `ast` backend),
`tools\stale.bat` (needs the git history that now exists), then
`tools\shot.bat "Asset"` against the running window. Fix what breaks, and
carry the fixes back to `H:/Code/AI_base_workflow/template/tools/`.
