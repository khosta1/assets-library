# Roadmap — Assets Library

## Everything asked for — the whole list

**Consuming the library**
- `A1` Houdini adapter — **done 2026-09-12**, `houdini/`
- `A2` USD + `.tx` / `.rat` generation into `derived/` — **`.rat` done
  2026-09-13** (`fb379c6`), `.tx` and `.usda` not started
- `A3` Maya, Blender, Unreal adapters
- `A4` USD variant sets built from the library's variant bindings, not from a
  cooked probe — see Phase 3b

**Filling the library**
- `B1` bulk migration — **batch importer built 2026-09-12**, nothing imported
  through it yet. Scope measured and much smaller than assumed; see Phase 4
- `B2` zip auto-extraction on import
- `B3` dedup in the UI — `index.find_by_hash()` is a stub; the hashes are
  already in every `asset.json`

**Housekeeping**
- `C1` verify the three unverified type signatures (see below)
- `C2` git — **done 2026-09-11**

---

## What this is

A prescriptive 3D asset library: it owns its hierarchy, normalises every
filename at import, and stores each asset as a self-contained package that can
be copied to a USB stick and still work.

> **The target slice: drop a vendor zip in, and open the asset in Houdini from
> a node that never had to guess what any file was.**

Both halves now exist. What is missing is the middle: the library holds 58
assets and the sources hold a few hundred. `B1` is the gap.

---

## Build order

*Updated 2026-09-12.*

### Phase 1 — Import, edit, browse — *done 2026-08-21*

Hand-declared import with per-row override, LODs end to end, editing,
deleting, the contents viewer, HDR/EXR thumbnails, the bounded preview cache,
FTS search, verify (including deep), the bundled runtime, portability tested
from a different path.

### Phase 2 — `A1` Houdini adapter — **done 2026-09-12**

The payoff of the whole design, and the first thing that consumes the library
rather than filling it. Until something reads the normalised layout, "zero
heuristics downstream" is a claim, not a result. It now reads it.

`houdini/` — one package file to install. Seam test, browser launcher, Python
Panel, and `build.py`: 1 058 lines of Karma/MaterialX/Solaris node building
ported from the old shelf tool, with roughly a thousand lines of filename
guessing left behind because `asset.json` already answers it. Right-click an
asset → *Import to Houdini*. Confirmed building nodes.

Still open on it: no geometry format ranking (see *Open bugs*), `derived/`
empty until `A2`'s uncommitted `derived.py` is finished and proven in Houdini,
and only Karma is wired —
Arnold and Redshift would need a second mapping table, which is config.

### Phase 2b — `C1` the cloud library — **done 2026-09-13**

The box at `/srv/data2/assets/library/` becomes the single master and this
folder becomes a client. Server half is `server/`, owned by the server-panel
session and deployed to `/opt/assetlib`; contract in
`server/client-contract.md`.

Seeded 2026-09-13: **75 packages, 1 039 files, 38.296 GB** over SMB, verified
at both ends.

Three tiers, kept apart because collapsing them is how it becomes slow:
catalogue (`remote.py`, `catalog.py`, `index.search_union`), thumbnails
(`_RemoteThumbJob`, `netpool.py`), files (`materialise.py`,
`ui/import_remote.py`). A download lands in `_cache/` and **keeps its uuid** —
that is the single-master decision, and `materialise.py` never imports
`commit.py` because `Asset.new()` would mint a new one.

**Proven end to end on 2026-09-13**, from a fresh copy on `J:` with an empty
`library/`: all 75 arrived as cloud tiles, and an asset downloaded, verified and
flipped from blue to local. Felix: "everything is working as intended."

Also landed alongside it: first-run panel, *Create a new library…*, Desktop
shortcut and icon, and `pythonw` launching with no console at all.

### Phase 3 — `A2` derived formats — **`.rat` done 2026-09-13** (`fb379c6`)

`.tx` / `.rat` / `.usda` into `derived/`, regenerable and never backed up.

`assetlib/derived.py` + the `build.py` hook in `textures_for()`, so Karma is
handed a `.rat` instead of converting a `.jpg` into `tex/` itself — which is
where the 25 `verify` warnings came from. The *Use .rat textures* checkbox in
`import_houdini.py` and `ui/bake.py` (batch pre-bake, off the GUI thread) close
the loop. Verified from the library side: 6 maps in 1.0 s, re-runs skip, zero
new `verify` warnings.

**Still open on it:** never run inside Houdini, so whether Karma is happy with
these files is unproven. `.tx` has a converter wired (`hoiiotool`) and no
caller. `.usda` is untouched. `derived/` has no size budget — same shape as the
`_cache/` gap, and a `.rat` is ~3× its source.

### Phase 3b — `A4` variant sets from the bindings — *not started*

The library now knows about variants properly, and Houdini does not use that.

**Today:** `_distinct_variant_names()` cooks a throwaway `file`→`unpack`
network in `/obj` purely to read the `name` prim attribute *inside one
geometry file*, and a variant set is built from whatever strings come back.
Separately, a real multi-file variant — `thatching_grass` ships
`_vara.fbx` … `_vark.fbx` — is built as **eleven independent component
chains**, one `componentoutput` each, all sharing one material.

**Wanted:** one component with an eleven-entry USD variant set, built from
`asset.representations[].variant`.

The machinery already exists and is proven —
`_build_sop_karma_component_variants()` collects N `componentgeometry` nodes
into a `componentgeometryvariants` LOP. It only takes its N from a cooked probe
instead of from `asset.json`. What changes is the source of the list, not the
node graph.

Why it is worth doing:

- **No probe cook.** Building and destroying a SOP network to read an attribute
  is the last piece of filename/geometry guessing left in the adapter, and it
  is exactly what `A1` deleted a thousand lines of elsewhere.
- **The names are better.** `vara`…`vark` were recorded at import with a person
  confirming them (the Var column), and they survive in `asset.json`. A cooked
  `name` attribute is whatever the vendor happened to call a piece.
- **One material instead of eleven**, and one prim for a scatter to pick a
  variant from — which is what a variant set is *for*.

Note the two are not the same thing and both should survive: prim `name` pieces
are variants *inside* one file, bindings are variants *across* files. The Import
dialog already says so in its own tooltip. An asset can plausibly have both.

### Phase 4 — `B1` bulk migration — **started 2026-09-13, FabLibrary done**

First real run: **36 assets** from `VaultCache/FabLibrary`, library **75 → 111**
(43.75 GB). Driven by `port.py` one asset at a time; the procedure and the traps
are in `docs/porting.md`, which is what the next run should follow instead of
re-deriving them.

It found four systematic bugs in the importer that no amount of reading would
have — letter variants, billboard maps winning real slots, `gloss`/`roughness`
colliding on one destination, and a variant word inside the asset's own name.
That is the argument for stepping, and it is why `docs/porting.md` says to step
until the failure modes are known and only then loop.

**The 36 are only on `H:` and the box is the master** — they still need the SMB
push and a re-index, after which `/api/health` should read 111.

Left in this source: 8 usdz-only assets and one manifest-only, skipped rather
than solved. Left overall: `H:/3D/Maya/assets`, `H:/3D/Insect/Texture`, and the
rest of the measurement below.

### The measurement

**Measured 2026-09-12**, because the estimate was load-bearing and wrong:

| source | files | size |
|---|---|---|
| `H:/3D/Maya/assets` | 1 438 | 27.3 GB |
| `G:/…/VaultCache` | 1 896 | 24.4 GB |
| `H:/3D/Insect/Texture` | 111 | **32.3 GB** |
| `H:/3D/HOUDINI/megascantest` | 552 | 2.4 GB |
| `H:/3DHome/Scan/Textures` | 43 | 0.6 GB |
| **total** | **~4 040** | **~87 GB** |

On the order of **150–400 assets**, not 4 000 — that number was the FILE count.
`H:/3D` is 509.7 GB in total, but ~420 GB of it is scenes and caches rather
than assets. **`J:/3d` does not exist**, so the FreeFileSync-mirror argument for
`B3` dedup is stale; check the drive before acting on it.

Consequence: the scan → review → apply → verify engine with an append-only
journal was specified to survive *hours of runtime*. At 87 GB, with same-drive
renames, it solves a problem the measurement removed. **B1 is bounded by
attention, not throughput** — 300 assets × three declared fields is 900
decisions, and no engine removes those, because the central decision says a
human declares them.

So the tool built instead is a **batch importer** (`ui/batch_add.py`,
2026-09-12): one row per subfolder, multi-select, spread edits, `analyse()` per
asset and `commit()` still the only writer. What is batched is the confirming,
not the deciding.

Order: `VaultCache` first — uniformly named, already the source every new
dimension was built against, and every asset in it exercises resolutions,
variants and LODs.

### What this order deliberately does not do

It does not add more importers before something reads what has been imported.
That held until 2026-09-12, when `A1` landed; filling the library is now the
thing in front rather than the thing being deferred.

---

## Open bugs

**Open from 2026-09-13** (the cloud work; the rest of that session's list was
closed by the J: run):

**The push tool has read the share and never written to it.** `assetlib/sync.py`
+ `ui/sync_server.py`. `probe()` and `diff()` ran against `Y:\assets` on
2026-09-13: admin `True`, 1.6 s, 222 packages, **111 local and 111 remote, no
verdicts, no skips** — both sides already agree, because Felix robocopied the 36
across at 01:53. So `push`, `drop`, `discard`, move-as-rename, the `.partial-`
rename and `reindex` are **unexercised on real data**. Before the first real
push:

- **The Samba stanzas are not applied.** The whole admin gate is
  `read only = yes` + `write list = felix` on the library share, plus a second
  writable share as the drop box — and that is on the box, which is the server
  panel's side of the fence. Until it is applied, every LAN account has write
  access and `sync.probe()` will report admin for all of them.
- **Whether `sudo -n systemctl start assetlib-reindex` works over SSH is
  unknown.** The box has three NOPASSWD exceptions and nobody checked whether
  this unit is one. If it is not, the Re-index button fails in a second and
  shows the command to run by hand — which is the intended fallback, not a bug,
  but it should be confirmed rather than assumed.
- **`_trash/` on the server has no sweep and no budget.** Same shape as the
  `_cache/` problem below, on a disk that matters more. Nothing empties it; it
  is meant to be emptied on purpose, by a person, and nothing yet reminds
  anyone that it exists.
- **The drop box has no promotion step.** A contributor can copy a package into
  `_inbox/` on the server; moving it into `library/` is a manual act with no
  tool behind it and no verification of what arrived.
- **The `.rat` work is wired end to end and none of it is committed.**
  `assetlib/derived.py`, the `build.py` hook, the *Use .rat textures* checkbox
  in `import_houdini.py`, and `ui/bake.py` for the batch pre-bake. Not known to
  have been run inside Houdini, so the 25 `.rat` strays in `tex/` are addressed
  in code and not yet observed to stop appearing.
- **The scan reads one `asset.json` per package over SMB, both sides.**
  Measured 2026-09-13: 1.6 s for 222 packages. It is linear, and at a few
  thousand it will not be.
  `/api/catalog` is the obvious pre-filter and was deliberately not used — a
  catalogue rebuilt daily is a stale answer to "what is on the server", and
  deciding to overwrite on a stale row is the failure this was built to avoid.

- **`_cache/` has no size budget.** Raised and deliberately deferred. Unbounded
  growth on a portable drive, which is exactly where it will be used. The
  thumbnail cache already has the pattern to copy — `thumbs_budget_mb` plus an
  LRU sweep in `ui/thumbcache.py`.
- **Remote thumbnails are never re-fetched** (contract: uuid is the cache key).
  An asset re-imported on the box shows its old tile until
  `.assetlib/remote/thumbs/` is cleared by hand.
- **Hero-LOD subsetting has only been exercised on constructed manifests.** The
  fallback path — a slot with no file at the requested resolution takes the
  nearest smaller — has not met a real Megascans package.

**App, found 2026-09-12 by the new orphan check in `verify`:**

- ~~**A texture set with LOD-tagged textures binds none of them.**~~ **Fixed
  2026-09-13**, and it was not `_emit_slot_actions`. `commit.bind()`'s LOD
  branch handled `slot` and `geo/` and returned; the non-LOD branch below has
  always had a third case, `"/" not in dest`, the package root. A file sent to
  *main file* gets `slot=None` and, on a type that is not
  `mesh_plus_textures`, no folder either — so a root-level file carrying
  `_lodN` matched neither condition and bound nothing, while `_record_lods`
  recorded the level anyway. One missing condition. `_promote_lod_geo` needed
  guarding in the same change, or the newly-bound `.jpg` would have become the
  level's `geo` and offered itself to Houdini as a mesh.
  **Still on disk:** `texture/decal/smudgeslarge001_overlay_var1_6k` is the one
  damaged package (all 75 scanned) and needs re-importing.
- ~~**`.rat`/`.tx` beside a mesh or an HDRI land in `extra/`, not
  `derived/`.**~~ **Fixed 2026-09-13**, and wider than reported: `texture` was
  the only type declaring `derived_ext`, and `_plan_texture_set` never read it
  — so even a texture set's `.rat` went to `extra/`. `derived_ext` is now
  **global in `types.json`**, beside `geometry_ext` and for the same reason: a
  `.rat` is a bake wherever it is found, and which asset it sits beside says
  nothing about that. `analyse.derived_exts()` unions the global with any a
  type adds. `.tex` (RenderMan) and `.b2r` (Redshift) added.
  **Still on disk:** `hdri/outdoor/tcom_vestrahorn_hdri_sphere_tone/` holds
  `tcom_vestrahorn_hdri_sphere_tone.jpg.rat` at the package root.
  **Not decided:** whether a *vendor* bake should be trusted at all — it was
  baked against the vendor's filenames, which is the argument that got vendor
  `.mtlx`/`.usdc` discarded. Ours are regenerated; theirs are kept for now.
- **No format ranking for geometry.** `primary_ext` is a membership list whose
  order is never read, so which of `.abc/.fbx/.obj/.usd` becomes `primary` is
  whichever the filesystem yields first. `_promote_lod_geo` is deliberately
  first-bound until this is decided. Probably `.usd` first for `model`.

- **One options dialog decides for a whole selection.** Multi-select in the
  grid and *Import to Houdini* reads the options from the **first** asset and
  applies them to all of them. Harmless when the selection is uniform - the
  point of the feature - and wrong in a mixed one: a resolution or variant the
  others do not have, an opacity mode meaningless to half of them. It degrades
  rather than fails (a missing size falls back to the biggest, a missing variant
  to the primary) and the dialog says out loud where the options came from, but
  it can still build something other than what was pictured. **Marked, not
  solved** (2026-09-12). The real fix is per-asset resolution of the options at
  build time, or refusing a selection that spans types.

**Scaffold, found 2026-09-11, still open:**

- **Seven of nine docs are watched by nothing.** Only `architecture.md` and
  `features.md` carry a `<!-- covers: -->` line, so `stale.py` skips the rest
  without saying so — and the "no coverage declared" list only prints under
  `--all` (`tools/stale.py:119`). At minimum `gotchas.md` should cover
  `assetlib/analyse.py, assetlib/slots.py` and `CLAUDE.md` should cover
  `assetlib/**, ui/**`. Printing the undeclared list by default is the other
  half: a doc nothing watches is the exact failure the tool exists to catch.
- **Every `tools\*.bat` ends in `pause`.** Correct for a double-click, dead
  line for every scripted run. `if "%CI%"=="" pause`, or a `--no-pause` flag.

Four scaffold bugs found the same day were fixed in both trees — see
`docs/journal.md`, 2026-09-11.

---

## Still unverified

Marked `VERIFY` in `types.json` — two minutes in each app's save dialog settles
them:

- Gaea: `.tor` (2.x) vs `.terrain` (1.x)
- ZBrush brush files: `.zbp` is a guess
- Marvelous Designer: `.zpac`
