# Porting a vendor folder into the library

How a bulk import is actually run here, written after the first real one
(**2026-09-13**, VaultCache/FabLibrary, 36 assets). It is a procedure, not a
description: an agent should be able to follow it without re-deriving anything,
and Felix should be able to check it without reading code.

The premise, from `ROADMAP.md`, has not changed and must not be argued with:

> B1 is bounded by attention, not throughput. 300 assets × three declared
> fields is 900 decisions, and no engine removes those, because the central
> decision says a human declares them.

So the tool does not decide. It sequences, and it shows.

---

## The tool

`port.py` at the repo root. It is a command line, which was removed on purpose
in 2026-08-21 and came back **for this job only** — the reasoning and the scope
limit are in `docs/decisions.md` § Reversed. Five subcommands, and they must
not become six.

```
port.py plan <declarations.json>     (re)build the plan. Writes nothing to library/.
port.py status                       what is done, what is left
port.py next                         show the next asset. WRITES NOTHING.
port.py apply <folder> --apply       import that one asset
port.py set <folder> --category C    amend a declaration, then replan
port.py set <folder> --skip --why …  do not import this one
```

Without `--apply`, `apply` is a dry run. That is deliberate: the dangerous verb
is the one that needs the extra word.

### Two files, and the difference matters

| file | what it is | who writes it |
|---|---|---|
| `port-declarations.json` | `{root, assets:{folder:{type, category}}}` | **a person** |
| `context/port-plan.json` | what `analyse()` says each one becomes | derived, regenerated freely |
| `.assetlib/port-state.json` | what has already been imported | the tool |

`set` edits the **declarations** and replans. It must never edit the plan
directly: the plan is regenerated on every `plan` run, so an amendment made
there survives until the next one and then vanishes — and the asset imports
with the value you thought you had changed. That is the worst failure a
migration can have, because it is silent and it looks like it worked.

State is separate from the plan because the plan is intent and what has already
been imported is a fact about this disk.

`apply` **re-runs `analyse()`** rather than replaying the plan. The plan is a
report from a read-only pass and the source can move underneath it; only the
declaration is replayed, because it is the only part a person authored.

---

## The procedure

**1. Survey before declaring anything.** Count files and extensions, list the
folder shapes, and look at one asset in full. Ten minutes here saves an hour
later — every trap in the list below was visible at this stage.

**2. Flatten the source if it nests.** `batch_add` and `port.py` both take one
asset per top-level folder. FabLibrary had a stray `fbx/` folder holding 21
more assets alongside 27 siblings; left alone it would have become **one asset
containing 21**.

**3. Write the declarations.** Type and category for every folder, from the
closed vocabulary. Propose them, then **have Felix confirm before importing** —
this is the part the tool is forbidden to decide.

**4. `port.py plan`** and read the totals. Source bytes vs kept bytes, how many
skipped and why.

**5. Step.** `next`, show it, get a word back, `apply … --apply`, repeat.
Stepping is slow and it is the point: the first real run found **four
systematic bugs in eleven assets**, every one of them by looking at output
rather than at code.

**6. When Felix says he is confident, loop the rest.** Not before he says it.

**7. `verify`, then read the warnings by CLASS**, not one by one. Group them:
27 warnings after the first run turned out to be 25 of one cause and 2 of
another, and neither was the importer's fault.

**8. Push to the box.** `library/` on `H:` is a cache; the master is
`/srv/data2/assets/library`. Robocopy over SMB, then re-index there. See the
journal entry for 2026-09-13 for the exact command — **and run it from
PowerShell, never the Bash tool** (gotcha 17).

---

## What to look at in each `next`

The checklist that caught everything. Read the output in this order:

- **`reject > 0`** — always ask why. Sometimes correct (a genuinely duplicated
  source), sometimes a whole dimension being dropped.
- **the mesh names** — a stray `_large`, `_small`, `_high` means a token in the
  asset's own name was read as a variant.
- **`geo` count against what the vendor ships** — 1 mesh where the folder holds
  40 files is the signature of a variant or LOD dimension collapsing.
- **the slot list** — a map you know the asset has and cannot see in the list
  has lost a contest to something.
- **`extra` count** — high means files the library could not interpret. Fine,
  but look at what they are.
- **warnings** — every one is a real event, not noise.

---

## Traps, all found on real data

1. **Letter variants.** `variant_patterns` had `var\d+`. Fab ships
   `VarA..VarK`, so every variant read as `None`, they collided on
   `(ext, lod, variant)`, and ~90 meshes were rejected as "second .fbx file".
   Fixed by `var[a-z]`; the pattern is anchored `(?:^|_)(...)(?=_|$)` so it
   matches a four-character token and nothing longer.

2. **A variant word inside the asset's own name.** "Large Fallen Tree" has one
   mesh and no small one, but `large` is a variant pattern, so the mesh came out
   `..._large.fbx` with a variant dimension that does not exist. Six of 37.
   `split_variant()` now takes the asset name and skips any token already in it.

3. **Billboard textures winning real slots.** `_Billboard_BaseColor.jpg` matches
   the BaseColor keyword as well as the real file does, and `_settle_competing`
   broke the tie on stem length — the longer one won. Now `secondary_maps` in
   `texture_slots.json`, checked **before** slot matching, routing to `extra/`.

4. **`gloss` and `roughness` both writing `_roughness.jpg`.** Right for a vendor
   shipping one, a hard conflict for one shipping both — `conflicts()` would
   have blocked every commit. Now `superseded_by` on the gloss slot, applied per
   LOD level.

5. **A glTF is a bundle, not a file.** `.gltf` is in `geometry_ext`, so it binds
   as a representation while its `.bin` buffer and its textures land in
   `extra/` — bound and unloadable. No rule was invented from one example; the
   folder was deleted. **If a second one appears, that is the moment to make a
   rule.**

6. **`derived/` is not where Houdini writes.** Karma auto-converts textures to
   `.rat` on first render and writes them **beside the texture in `tex/`**.
   `verify` reports them as orphans, correctly. This is `A2`'s gap, not the
   importer's — do not "fix" it in the import path.

---

## What an agent must not do here

- **Declare a type or category on Felix's behalf.** Propose, then wait.
- **Grow `port.py`.** Five subcommands. A flag on an existing command is
  acceptable (`set --skip` was added that way); a sixth verb is not. If it ever
  grows a way to *decide* something, delete it.
- **Put logic in `port.py`.** `analyse()` and `commit()` do the work. The old
  CLI was removed because it stopped being a thin caller.
- **Batch before being told to.** Offer it, name the trade, and wait.
- **Report "done" without `verify`.** And read the warnings by class.
