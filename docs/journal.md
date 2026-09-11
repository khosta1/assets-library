# Journal

Newest first.

---

## 2026-09-11 — scaffold shake-out

**Done.** Ran four of the six tools against this tree for the first time.
`budget.bat`: tier 0+1 = 6 837 tokens. `codemap.bat`: 27 files, 6 212 lines,
34 types, 55 kb — the Python `ast` backend parsed everything without a failure.
`stale.bat`: reported drift on `architecture.md` and `features.md`, both false.
`pack.bat`: all five packs built through `npx` repomix on the first run —
brief 8 288, docs 14 257, ingest 25 555, storage 15 556, ui 37 102 tokens; none
near the 80 k "two topics wearing a trenchcoat" warning; contents spot-checked
against `packs.json` and correct.

Four bugs found and fixed, each in **both** this tree and
`H:/Code/AI_base_workflow/template/` — all four were template defects, present
in the baseline, not porting mistakes:

- `tools/stale.py` — `git rev-list --since` is inclusive, so a doc committed in
  the same commit as its subject counted that commit as its own drift. Fixed
  with `ts + 1`; `stale.bat` now says "No drift". Tools bumped to **v2** in
  `tools/_version.txt` in both trees.
- Stop hook — tested `^.. src/`, a directory this project does not have. Inert
  since the day it was copied in. Now a negative test: anything not `docs/`,
  `ROADMAP.md` or `CLAUDE.md` counts as code.
- Stop hook — pointed at `BOOTSTRAP.md`, which does not exist here; now points
  at `.claude/skills/doc-ritual/SKILL.md`, which owns that table.
- SessionStart `stale.py` — exits 1 on drift, and the harness drops a failing
  hook's stdout, so the drift report vanished exactly when it had something to
  say. Wrapped as `powershell -Command "python tools/stale.py; exit 0"`.

`.claude/HOOKS.md` rewritten in both trees to own the reasoning for the two
hook changes, dated, with the old rule kept in the sentence.

**Decided.** The Stop hook's test is **negative** — it names the docs and
treats everything else as code — because the positive form encodes a layout the
template cannot know, and a hook that never fires looks exactly like a hook
with nothing to report. Fixes went to the baseline in the same breath as the
project, because all four would otherwise be re-found by every project ported
onto the scaffold. The `covers:` gap was *not* closed unilaterally: which docs
should be watched is a judgement about each doc, not a bulk edit.

**Open.** Nothing half-done in the code — the app was not touched this session,
and `assetlib/` and `ui/` are byte-identical to `46e5c06`. Four files are
modified and **uncommitted**: `.claude/HOOKS.md`, `.claude/settings.json`,
`tools/_version.txt`, `tools/stale.py`. The template's matching four are
modified too and that tree is not under git at all, so those edits exist in
exactly one place.

Two tools are still unrun: `shot.bat` (needs the window open) and `recall.bat`
(needs sessions to search, and this is only the second). Neither has ever been
exercised.

Two scaffold problems are known and **not** fixed. Only 2 of 9 docs declare
`<!-- covers: -->` — `architecture.md` and `features.md` — so `stale.py`
silently skips `decisions.md`, `gotchas.md`, `machine.md`, `sources.md`,
`journal.md`, `CLAUDE.md` and `ROADMAP.md`; and the undeclared list only prints
under `--all` (`stale.py:119`), which is why the gap is invisible by default.
Separately, every `.bat` ends in `pause`, so each non-interactive run ends on a
dead "Appuyez sur une touche" line — harmless, stdin hits EOF and falls
through.

**Next.** Commit the four fixed files — the fixes are verified and the tree has
been dirty since this morning.

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
