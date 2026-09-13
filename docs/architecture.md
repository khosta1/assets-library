<!-- covers: assetlib/**, ui/**, config/** -->

# Architecture

A map of the whole system: what the pieces are, which way the data flows, and
which rules everything obeys. Written to be read before touching anything.

Where a claim is a design rule rather than a description, it is marked
**RULE**. Where something is stated but not built, it says so.

Split out of `CONTEXT.md` on **2026-09-11**; the reasoning is unchanged, only
its home is new.

---

## 1. What this is

A catalog that **owns its own hierarchy**. Assets are imported into
`library/{type}/{category}/{asset}/`, where the tool creates every folder and
names every file. Source layout is read for information and then discarded.

The payoff is concentrated in one place: because every texture filename is
normalised to a slot name **at import**, every adapter downstream —
Houdini, Maya, Blender, Unreal — reads a fixed layout with zero heuristics. The
guessing happens once, in `slots.py`, and never again.

---

## 2. The layers, and the arrow between them

```
ui/           PySide6 windows       imports assetlib
houdini/      hou + Solaris         imports assetlib
assetlib/     pure core             imports neither Qt nor hou
config/       JSON                  data, read by assetlib
```

`houdini/assetlib_hou` joined on **2026-09-12** and points the same arrow from a
second direction. It was the first real test of the rule rather than an argument
for it: `import assetlib` inside Houdini 22.0.368 works, reads the library, and
pulls in neither Qt nor the bundled `runtime/`. Every adapter after it — Maya,
Blender, Unreal — arrives the same way and needs no change to the core.

**RULE.** `assetlib` imports no Qt and no `hou`. The arrow direction is the
whole discipline: `ui/` depends on `assetlib`, never the reverse. Breaking it
breaks headless use and breaks embedding in a DCC, and it breaks quietly — the
import only fails on the machine that does not have Qt.

The CLI used to enforce this by existing. It was deleted once the rule could be
stated directly (`docs/History/cli-removed.md`).

---

## 3. The joins

### Disk ↔ database

> **Disk is truth, database is a cache.**

`asset.json` inside each package is authoritative. `.assetlib/index.db`
(SQLite + FTS5) is derived, and F5 rebuilds it from the packages. The library
stays readable, portable and hand-editable without the tool — and a corrupted
index is an inconvenience, never a loss.

Consequence: anything that must survive is written into `asset.json` at commit
time. The index may be deleted at any moment without asking.

### Analyse ↔ commit

`analyse.py` is **read-only**: it turns source files into an `ImportPlan` and
touches nothing. `commit.py` is the only writer. Nothing is written before the
Add button is pressed, and `conflicts()` refuses a plan in which two files
claim one destination.

**RULE.** A planner may not write, and a writer may not guess. Every guess
belongs in `analyse`/`slots`, where the user can see it as a row and override
it from a dropdown.

### Edit ↔ the package on disk

**Editing is a re-analysis, not a patch.** `analyse()` is fed the package's own
files plus whatever is being added; the result is diffed against disk, giving
exactly four kinds of change — keep, rename, add, delete. The payload is staged
into `_editing/old/` and that folder is destroyed **last**, so a failure at any
earlier point leaves every original recoverable by hand.

`uuid` and `created` survive an edit, so the index row updates in place — which
is why the thumbnail cache needs explicit invalidation (gotcha 9).

### Schema ↔ disk

Reading never needs a migration: `model.migrate()` upgrades an old `asset.json`
in memory on every read, so a v1 package written a year ago still loads.
`upgrade.py` is about the **files** — its job is to stop the library becoming a
permanent mix of schema versions.

The cost is paid once: `.assetlib/state.json` records the version last known to
be fully applied on disk, and when it matches the code, startup reads one small
file and does nothing. Only a code upgrade triggers the O(n) walk.

**RULE.** That marker is an optimisation, never a guarantee — an older build
writing into a library already marked current would make it lie. So the same
pass is reachable from three places (startup, Rebuild index, Library ▸ Migrate
metadata) and `verify` reports version skew. Three paths, one idempotent
operation.

### UI ↔ threads

Thumbnail decoding runs on the shared pool; **writes do not**. Twenty 8K TIFFs
occupy every thread for a minute, and a write job queued behind them never
starts (gotcha 7). `ui/writepool.py` is deliberately single-threaded and
separate.

**RULE.** The window must never walk the filesystem during interaction. Search
queries FTS5; the grid is a `QAbstractListModel` with uniform item sizes;
decoding happens on a pool.

---

## 4. The package layout

Identical for every type; absent sections simply do not appear.

```
library/texture/concrete/concrete014/
├─ asset.json      truth
├─ tex/            <asset>[_lodN]_<slot>[_<res>][.udim].<ext>
├─ geo/            <asset>[_<variant>][_lodN].<ext>
├─ preview/        thumb.jpg (512px)
├─ derived/        .tx / .rat / .usda - regenerable, deletable, NOT backed up
└─ extra/          bonus files, kept verbatim, never interpreted
```

A **`folder_blob`** type - `script`, `terrain`, `garment`, `reference`, `setup`,
`unknown` - has one more, and it replaces the others rather than joining them:

```
library/script/houdini/manager_tool/
├─ asset.json
├─ src/            THE TREE, verbatim. Nothing renamed, slotted or contested.
└─ preview/
```

For a tool the tree is not decoration, it is the asset: relative imports,
`__init__.py`, `preset/*.json` and `HDAs/` all depend on their positions. `src/`
and not the package root, because the root's names are reserved and a tool
shipping its own `preview/` would collide with the package's (2026-09-13).

Three levels above it, always: `{type}` from `types.json` (18), `{category}`
from the closed vocabulary in `categories.json` (114). No deeper nesting, no
per-type exceptions.

**Token order is load-bearing** (2026-09-12). The UDIM tile must remain the
last dot-segment before the extension or `<UDIM>` stops being the spelling
Houdini, Karma, Arnold and Mari resolve natively — so the resolution token
sits before it, never after. A token appears **only when there is something
to tell apart**: one size, or one variant, means no token at all and a
filename identical to what the library has always written.

Four dimensions now identify a file — slot, LOD, resolution, variant — and
each is recorded in `asset.json` rather than parsed back out of the name. The
name is for a human reading a directory listing; the JSON is what anything
downstream reads.

---

## 5. The import flow

```
1 DECLARE   type, category, name, tags in the Add window
2 DROP      files into the main zone; anything to keep but not interpret
            goes in the Bonus zone -> extra/
3 REVIEW    the table shows every file, where it will go, what it is bound to,
            and its LOD. Any row can be overridden from a dropdown.
4 COMMIT    commit.py copies + renames, hashing in the same pass, writes
            asset.json, generates the icon, indexes.
```

The user declares what an asset **is**; the tool decides where its files go.
Type, category and name are typed in — never inferred and silently committed.
What is automated is the tedious half: which image is the basecolor, which
format of a slot wins, what everything must be renamed to. Every one of those
decisions appears as a row that can be overridden.

---

## 6. Where a guess is allowed to live

One place: `slots.py`, at import time.

`texture_slots.json` holds 20 slots, each with keywords, colorspace and an
output name. **Order in that file is significant** — first match wins, so
`diffuse` must stay last as the catch-all (gotcha 4).

Everything downstream reads `asset.json`'s texture→slot binding, never the
filenames and never the FBX, whose internal texture paths are routinely
absolute, stale or wrong.

---

## 7. The invariants, in one place

Everything above, as the list to check a change against. `verify.py` enforces
1, 5 and 7; the rest are enforced by review.

1. **`asset.json` is truth; the index is rebuildable.** Nothing may exist only
   in `index.db`.
2. **`assetlib` imports no Qt and no `hou`.**
3. **Nothing is written before commit.** `analyse` is read-only.
4. **Two files may never claim one destination.** `conflicts()` blocks the
   commit rather than letting one silently overwrite the other.
5. **Every package is self-contained**: relative paths only, textures travel
   with it, nothing outside it is resolved. The single absolute path anywhere
   is `origin.source`, which is provenance and is never resolved.
6. **Nothing is discarded.** What the library cannot interpret lands verbatim
   in `extra/`. What loses a format contest is reported, never deleted.
7. **Nothing is auto-deleted.** Deletion is an explicit, confirmed action with
   the file list shown first.
8. **A digest carries its algorithm**, and unverifiable is never reported as
   corrupted (gotcha 8).
9. **Names are `lower_snake`**, with resolution, format, LOD **and variant**
   tokens stripped — so a 4K version of an 8K asset resolves to the same
   name, and a Big shipped without its Small is not named `..._big`.
10. **Types are data.** Adding SpeedTree/Marvelous/GAEA support is editing
    `types.json`; only the precedence *between* types is code.
11. **`iter_assets()` stops descending at a package.** A package can contain
    another `asset.json` (gotcha 6).
12. **Normals are stored OpenGL-only.** DirectX is an exact green-channel
    inversion, regenerated on demand; a DX-only source is converted at import.
13. **A dimension is added additively.** `textures[slot]` names the biggest
    resolution, `lods[N].geo` names one geometry file, the hero LOD is
    mirrored into the top level — every reader gets the best version without
    knowing the dimension exists. Schema v4, v5 and v6 each added a field and
    changed no existing path.
14. **Every file in a package is pointed at by `asset.json`**, except under
    `extra/`, `derived/`, `preview/` and `_editing/`. `verify` checks both
    directions: that a pointer resolves, and that a file has one. A
    `folder_blob` is the one shape where the pointer is the TREE rather than a
    file each: `fields.tree` names `src/` and everything under it travels
    unexamined.
15. **The library never executes package content of its own accord.** A package
    is data. No import path, no sync, no download, no background job and no
    analysis reaches code inside `library/`. This mattered from the day a
    `script` type existed and became load-bearing when the cloud half landed:
    `materialise.py` downloads packages from the box, so a library that ran
    code an asset carried would make *downloading* an asset mean *running its
    code*. A tool declares what it needs in `install.json`, which is read as
    data; nothing acts on it until a person asks. A manifest field that cannot
    express something is a new field and ten lines, never an escape hatch that
    runs anything.

    **The single exception is `launch.py`, and it is what the words "of its own
    accord" are doing there** (amended 2026-09-13, at Felix's instruction). A
    person choosing *Launch* on a named asset is that person running their own
    tool — the same act as *Open folder* and double-clicking, one step shorter.
    It is bounded so that it stays that act and does not become the other one:

    - reached only from a context menu, never from code
    - the module and the call are **shown and confirmed before anything runs**
    - a DCC tool is not offered outside its DCC, because the ImportError would
      read as a broken asset rather than as the wrong host
    - a tool that raises is reported as the *tool* failing, not the library

---

## 7b. The adapter join

Added **2026-09-12**.

> **The library decides nothing about a DCC; a DCC guesses nothing about the
> library.**

`ui/import_houdini.py` owns every choice — opacity mode, displacement,
resolution, variant, localize — and `houdini/.../build.py` is a function that
takes an asset and a dict of those choices and makes nodes. No dialogs on the
Houdini side, no `hou` on the library side.

The builder was ported from a working shelf tool whose other half walked the
folder and re-derived what every filename meant, on every run. That half was
deleted rather than moved, which is the payoff stated in §1 finally collected:
1 058 lines of Karma/MaterialX/Solaris knowledge kept, ~1 000 lines of guessing
dropped because `asset.json` already holds the answers.

Two ways in, one entry point. Inside a Python Panel the window has `hou` and
calls the builder directly; standalone it writes `.assetlib/request.json` and a
shelf button reads it. Disk is what both sides agree on, the same rule the rest
of the project runs on.

**RULE.** The panel READS and BUILDS. Add, Edit and deep verify stay in the
standalone app, because Houdini's interpreter has no xxhash and importing from
there would write a second digest algorithm into the library.

---

## 7c. The master join

Added **2026-09-13**.

> **The box is the master; this folder is a client. What crosses between them
> is an asset identified by its uuid, never a path.**

Three separate crossings, and they do not share a transport because they do not
share a shape:

| direction | how | what moves |
|---|---|---|
| catalogue, box → here | HTTP `/api/catalog`, ETag-diffed | rows |
| files, box → here | HTTP `/api/file`, `Range`-resumable | into `_cache/` |
| **assets, here → box** | **SMB on the LAN, `assetlib/sync.py`** | into `library/` |

The upward crossing is the one added here. It is a file copy rather than an
API call because the API is read-only by decision, and it diffs by **uuid** on
both sides, read from `asset.json` rather than from either index — the local
one is a cache and the box's is rebuilt daily, so neither is a safe basis for
overwriting or removing anything (invariant 1, applied outward).

Four verdicts come out of that diff, and the fourth is the point:

```
add     uuid not on the master        copy the package
update  same uuid, contents differ    copy the changed files
move    same uuid, different path     RENAME on the share - no bytes
missing uuid on the master, not here  report it, and stop
```

**RULE.** A push adds, updates and moves. It never deletes. Removing an asset
from the master is a separate act, one asset at a time, and it is a rename into
`_trash/` (invariant 7).

**RULE.** Permission is read, never granted. `sync.probe()` writes one file to
the share to find out whether `smbd` allows it; Samba's `write list` is the
gate, and the app reports its answer rather than keeping a flag of its own. The
add-only path for everyone else is a second, writable share used as a drop box
— a share definition rather than a rule this app is trusted to keep.

---

## 8. Where the seams are

As of **2026-09-12**.

- **The Houdini adapter exists** (2026-09-12, §7b). The payoff of the owned
  hierarchy is no longer theoretical: a Karma/MaterialX network is built from
  bindings, and the thousand lines of filename guessing its predecessor needed
  were deleted rather than ported. Karma only — Arnold and Redshift want a
  second `mtlx_input` mapping, which is config. Maya, Blender and Unreal are
  `A3` and arrive the same way.
- **`derived/` is empty.** USD and `.tx`/`.rat` generation is designed, not
  built. Vendor `.mtlx`/`.usdc` are kept in `extra/` and never bound, because
  they reference the original filenames; ours are not yet generated in their
  place, so nothing an adapter reads is there at all.
- **Dedup is a stub.** `index.find_by_hash()` exists and returns nothing. The
  hashes are already in `asset.json`, and `J:/3d` appears to be a FreeFileSync
  mirror of `H:/3D`, so much of the source data exists twice.
- **The bulk migration has not run.** The library holds 58; the sources hold a
  few hundred. A batch importer exists (`ui/batch_add.py`) and nothing has been
  imported through it. Measured 2026-09-12: ~4 040 files and ~87 GB across five
  roots — an order of magnitude less than `ROADMAP.md` assumed, because the
  old figure counted files, not assets. **This is now the widest seam**: the
  adapter reaches only what has been imported, and that is the whole cost of
  owning the hierarchy.
- **Three type signatures are unverified**, marked `VERIFY` in `types.json`:
  Gaea `.tor` (2.x) vs `.terrain` (1.x), ZBrush `.zbp`, Marvelous `.zpac`.
