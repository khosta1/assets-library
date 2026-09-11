<!-- ARCHIVED. Moved here 2026-09-11. -->

# Design draft — archived

The original design document, written 2026-08-20, **before any code existed**.
Superseded by `CLAUDE.md` + `docs/` on 2026-09-11 (it had already been largely
superseded by `CONTEXT.md` on 2026-08-21, which this doc set replaced in turn).

**Archived, not wrong.** Everything still true in it is now stated in
`docs/architecture.md`, `docs/decisions.md` or `ROADMAP.md`. It is kept for one
reason: it records what the design looked like when it was still a plan, which
is the only way to see which parts survived contact with the files — the
prescriptive hierarchy and the three-level tree did; the import pipeline it
imagined was reshaped by what vendors actually ship (see `docs/gotchas.md`).

Where this file and the current docs disagree, **the current docs win.**

---

# Assets Library — design draft

Status: **draft**, updated 2026-08-20. No code yet. Nothing outside
`H:/Code/Assets_library` has been touched.

## Direction

The library is **prescriptive, not adaptive**. It starts empty, it owns its own
hierarchy, and the tool is the only thing that writes into it. Source folder layout is
information to be *read and discarded* at import — never mirrored.

There is no in-place browsing of `H:/3D/Maya/assets`. That folder is a **source** to import
from, not a library to display.

## Core rule

**Disk is truth, database is a cache.** Metadata lives in `asset.json` inside each asset
folder. `index.db` (SQLite + FTS5) is derived and rebuildable at any time. The library stays
readable and portable without the tool.

## The tree — exactly three levels, always

```
H:/Code/Assets_library/
├─ .assetlib/            tool state (index.db, thumbs/, journal)
├─ _inbox/               THE ONLY WAY IN. drop folders or zips here
├─ _quarantine/          imports that failed validation. nothing is ever lost
└─ library/              tool-owned. never hand-edited
    └─ {type}/{category}/{asset}/
```

`{type}` from `types.json` (17 types), `{category}` from the closed vocabulary in
`categories.json`. No deeper nesting, no per-type exceptions.

## Every asset package looks identical

```
library/texture/concrete/concrete014/
├─ asset.json      metadata, source of truth
├─ tex/            <asset>_<slot>.<ext>   normalised names
├─ geo/            <asset>.<ext>
├─ preview/        thumb.jpg (512px)
├─ derived/        .tx / .rat / .usda — regenerable, deletable
└─ extra/          folder_blob payloads we keep but don't interpret
```

Sections that don't apply are absent, never renamed or restructured.

## Why the owned hierarchy pays off

Import normalises filenames to slot names. ambientCG's `_Color.png` and Poly Haven's
`_diff_8k.jpg` both become `<asset>_basecolor.png`. **The guessing happens once, at import.**
Every adapter, importer and shader builder afterwards reads a fixed layout with zero
heuristics. That is the entire argument for not adapting to source folders.

## Config files

| file | decides |
|---|---|
| `config/library.json` | the canonical tree, package layout, naming rules, import flow, invariants |
| `config/types.json` | 17 types, extensions, ingest + preview strategy, metadata fields |
| `config/categories.json` | the one category level per type + tag namespaces |
| `config/texture_slots.json` | 20 slots, keywords, colorspace, MaterialX input, output names |

Types are **data, not code**. Five ingest strategies only; `folder_blob` is the guaranteed
fallback so nothing is ever un-ingestable.

Naming is **lower_snake** deliberately: Windows is case-insensitive, Linux is not, and this
library will eventually be read from the Rocky box. Resolution/format tokens are stripped
from names and live in metadata, so `Concrete014_8K-PNG` and a future 4K version resolve to
the same asset instead of two.

## Import flow — reversible until commit

```
1 DROP      folder or zip into _inbox/
2 ANALYSE   unpack, detect type/slots/resolution/duplicates. writes nothing to library/
3 PROPOSE   name, type, category, slot mapping, files kept vs rejected, size before/after
4 CONFIRM   user fixes and approves. category MUST come from the closed list
5 COMMIT    create the folder, copy+rename, write asset.json, preview, index
6 CLEANUP   source stays in _inbox until explicitly cleared. never auto-deleted
```

Duplicates by `xxh3`. Redundant archives sitting next to their extracted folder are
**reported, never auto-deleted**.

## Verified against the debug assets

`config/` dry-run on `H:/Code/Assets_library/Concrete/`:

- naming: 4/4 examples normalise correctly
- slots: 13/13 texture files matched (`_diff_` gap and the bare-stem preview rule were both
  found by this dry run and fixed)
- `concrete_floor_worn_001` → 683 MB becomes ~326 MB: the 346 MB duplicate `nor_gl` PNG
  loses to the 127 MB EXR, and `_arm_` is redundant since unpacked AO/rough already exist

## Build status

> **This document records the original design. For how the tool actually works
> now — GUI-first, bundled runtime, no command line — read `CONTEXT.md`.**

1. ✅ analyse + commit, verified on both debug assets
2. ✅ `asset.json` schema + migration hook + verify (incl. deep re-hash)
3. ✅ SQLite/FTS5 index + search with the filter syntax
4. ✅ PySide6 browser — sidebar / grid / search / Open folder
5. ✅ Import UI — declare the asset, drop the files, override any row
6. ✅ Editing, deleting, the package viewer, LODs, HDR/EXR thumbnails
7. ⬜ Houdini adapter, USD generation into `derived/`, other DCCs
8. ⬜ Bulk migration of `H:/3D/Maya/assets`

The CLI that drove steps 1–3 has since been **deleted**: it existed to force the
core to stay UI-free, and that discipline is now held by the import rule
(`assetlib` may not import Qt) instead.

### Running it

Double-click **`Asset Library.vbs`**. Nothing needs installing — a Python 3.11
runtime is bundled in `runtime/`. `run_ui.bat` is the console version.

## Decisions locked

- Python 3.11 — the only version shared by Houdini 20.5 / 21.0 / 22.0
- PySide6 — same widgets standalone, as a Houdini panel, or docked in Maya
- `assetlib` core imports no `hou`, no Qt. Adapters and UI depend on core, never the reverse
- format-agnostic packages; USD is an optional generated artefact in `derived/`
- library data at `H:/Code/Assets_library/library/`, gitignored

## Open questions

1. **Normal maps**: keep GL only and regenerate DX on demand (a green-channel flip, exact),
   or store both? Keeping GL only saves ~150 MB per ambientCG asset.
2. **Verify three extension guesses**: Gaea (`.tor` vs `.terrain`), ZBrush brushes (`.zbp`?),
   Marvelous (`.zpac`).
3. **Type list** — 17 types now (IES added after finding `H:/3D/Maya/assets/IES`). Anything
   still missing?
4. `H:/Code/Assets_library/Concrete/` — the debug data. Move it into `_inbox/` when the
   importer is ready.
