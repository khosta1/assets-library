# Journal

Newest first.

---

## 2026-09-12 (later) — Houdini reads the library, and B1 gets measured

Same day as the entry below, which covers the import pipeline.

**Done.** Three more commits on `fix/scaffold-shakeout`, still unmerged.

- `8662660` — **P0, the seam.** `import assetlib` works inside Houdini
  22.0.368, reads the library, and drags neither `runtime/` nor a second Qt in
  with it. Invariant 2 paid against a real host rather than argued for.
  `houdini/` is one package file to install; everything else is read out of the
  repo.
- `70ca304` — **Import to Houdini**, right-click, gated on a new `has_geo`
  index column. The options dialog is in `ui/import_houdini.py`, deliberately
  **not** in Houdini.
- `9d14718` — **the builder.** 1 058 lines copied verbatim from
  `Assets_manager_var01.py:400-1457`; five sites rewired; ~1 000 lines of
  guessing left behind. Plus the **Python Panel**, which makes right-click →
  Import build in-process.
- `6e2dfff` — **batch import**, `ui/batch_add.py`. One row per subfolder,
  multi-select, spread edits. Button beside *Add asset*, or Ctrl+Shift+N.
- `strip_tokens` listed image formats only, so every Megascans folder imported
  as `..._fbx`. Mesh and remaining image formats added.
- Gotchas **13** and **14**; `architecture.md` invariants **13** and **14**.

**Decided.** **Houdini 22+ only**, stated by Felix — which deletes the PySide2
shim and makes the Python Panel possible. **The panel reads and builds, writing
stays standalone**, because Houdini's interpreter has no xxhash and importing
from there would write blake2b digests into an xxh3 library. Both in
`docs/decisions.md`. The builder was **copied, not retyped** — transcribing a
thousand lines by hand is how you lose a `setInput(1, …)` — and the ported code
still speaks the original's shapes so the seam is the only new code. Geometry
format ranking was left **deliberately arbitrary** rather than invented inside
a bug fix.

**Open.** The measurement is the thing worth keeping.

- **B1 is an order of magnitude smaller than `ROADMAP.md` says.** Measured:
  `Maya/assets` 1 438 files / **27.3 GB**; `VaultCache` 1 896 / 24.4 GB;
  `Insect/Texture` 111 files but **32.3 GB** (~300 MB each); `megascantest`
  552 / 2.4 GB; `3DHome/Scan` 43 / 0.6 GB. **~4 040 files, ~87 GB, and on the
  order of 150–400 assets — not 4 000.** The "4 000 assets, hours of runtime"
  framing counted FILES. `H:/3D` overall is 509.7 GB, but ~420 GB of that is
  scenes and caches, not assets. **`J:/3d` does not exist**, so the
  FreeFileSync-mirror argument for dedup (`B3`) is stale.
- Consequence not yet acted on: the scan → review → apply → verify **migration
  engine may not be worth building**. Its append-only journal solves an
  interruption problem that 87 GB of same-drive renames does not have. The
  batch importer was built instead, and is the bet that B1 is bounded by
  attention rather than throughput.
- **Nothing has been committed through the batch window.** The scan path is
  proven on all 17 Plants folders (0 rejected, 0 conflicts, 7.2 GB); the import
  path has never run.
- **The Houdini builder has created nodes** — Felix confirmed — but only for one
  asset, and only after two bugs were fixed: "all variants" built the first mesh
  only, and `build_karma_component` returned `None` so `len(nodes)` blew up
  after a successful build.
- Plants analyse as type **`scan`**, because `vegetation.primary_ext` is
  SpeedTree-only. The one asset already imported is `vegetation/grass`. **Pick
  one before importing the other sixteen** — mixed types across one vendor
  folder is annoying to unpick later. Note `vegetation` has no `plant`
  category; it has `tree shrub grass flower moss misc`.
- Three app bugs from the previous stretch are still open in `ROADMAP.md`, and
  `strip_before_match` in `texture_slots.json` is still dead config needing
  `/retire`.

**Next.** Import the 17 Plants through the batch window — it is the only part
of the chain that has never run, and it fills the library the adapter is
waiting on.

---

## 2026-09-12 — four dimensions the planner did not have

**Done.** Five commits on `fix/scaffold-shakeout`, unmerged.

- `66cc48c` — four template bugs, fixed in this tree **and** in
  `H:/Code/AI_base_workflow/template/`. `stale.py` counted a doc's own creating
  commit as drift (`--since` is inclusive); the Stop hook tested `^.. src/`, a
  directory this project does not have, so it was inert from the day it was
  copied in; that hook pointed at `BOOTSTRAP.md`, which lives in the baseline
  and never ships; SessionStart's `stale.py` exits 1 on drift and the harness
  drops a failing hook's stdout, so the report vanished exactly when it had
  something to say.
- `34e4ce2` — `codemap.py` weight chart, tools **v3**. "Per-file line weight"
  had been satisfied by the accordion's sort order and a grey count in a
  collapsed summary, which nobody read as an answer.
- `f05a95c` — forced dark (`ui/theme.py`, **confirmed working in the window**),
  sidebar collapsed by default with expansion surviving the rebuild, and the
  caveman comment convention.
- `31f4b7b` — the import pipeline, schema **v4 → v5 → v6**:
  resolutions kept per slot (`res_patterns`, size measured from pixels);
  `lods[N].representations` as a list, fixing a silent overwrite;
  `geometry_ext` routing on the extension whatever the type; geometry variants
  keyed `(ext, lod, variant)`.
- `verify` gained an **orphan check** — every other check asks whether a
  pointer resolves, none asked whether a file has one.
- Baseline `H:/Code/AI_base_workflow` is now a git repo (`c2be6fc`, `df8569e`,
  `6efdd8c`). It had no history at all.
- Gotchas **13** and **14** written. `docs/decisions.md` gained four rows,
  `docs/features.md` four entries.

**Decided.** Every new dimension is **additive** — `textures[slot]` still names
the biggest size, `lods[N].geo` still names one file — because that is what
`_promote_hero_lod` already does and it means no existing reader, and no future
adapter, has to know a dimension appeared. Resolution is **measured, never read
from the filename**: Megascans writes `16384ppm`, which is pixels-per-metre and
is 4096px on a quarter-metre plant. Variants are **pre-filled, never decided**
by the pattern. `primary_ext`, `geometry_ext` and `mesh_extensions()` are three
lists because they answer three questions; the reasoning for all of it is in
`docs/decisions.md`.

**Open.** Nothing half-built, but one large gap in what has been *seen*.

- **No import has ever been committed to disk under this code.** Everything was
  verified with read-only `analyse()` plus in-memory `bind()`/promote. The
  commit path has never written a multi-resolution or multi-variant package,
  never renamed one on edit, and `_editing/old/` has not been exercised since
  the schema moved.
- **The Res and Var columns have not been looked at.** The window was running
  on pre-`f05a95c` code all evening; only the dark theme was confirmed.
- Three orphans stand in the library, reported by the new check and left alone:
  a `.rat` beside an HDRI, and two `_lod1/_lod2.jpg` files in
  `texture/decal/smudgeslarge001…` whose asset has `lods={1,2}` and **zero**
  texture bindings — that last one is a real binding bug in the texture-set
  planner, diagnosed but not fixed.
- `_promote_lod_geo` picks **first-bound**, which is arbitrary. There is no
  geometry `format_priority` anywhere; `primary_ext` order is never read. Left
  arbitrary on purpose rather than burying the decision in a bug fix.
- `matching.strip_before_match` in `texture_slots.json` is dead config —
  declared, never read, and overlapping what `res_patterns` now does. Needs
  `/retire`, not a silent delete.
- The library holds **57** assets, not the 8 `features.md` claimed all evening.

**Next.** Restart the app and import one Megascans plant end to end — the
commit path is the only part of this that has never run.

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
