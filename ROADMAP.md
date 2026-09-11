# Roadmap — Assets Library

## Everything asked for — the whole list

**Consuming the library**
- `A1` Houdini adapter — nearly trivial now the layout is normalised and LODs
  are recorded per level; a detail switch can be built without parsing names
- `A2` USD + `.tx` / `.rat` generation into `derived/`
- `A3` Maya, Blender, Unreal adapters

**Filling the library**
- `B1` bulk migration of `H:/3D/Maya/assets` — scan → review → apply → verify,
  with an append-only journal so it survives the hours it will take, preferring
  same-drive renames over copies
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

Everything built so far is the first half of that sentence. `A1` is the second.

---

## Build order

*Updated 2026-09-11.*

### Phase 1 — Import, edit, browse — *done 2026-08-21*

Hand-declared import with per-row override, LODs end to end, editing,
deleting, the contents viewer, HDR/EXR thumbnails, the bounded preview cache,
FTS search, verify (including deep), the bundled runtime, portability tested
from a different path.

### Phase 2 — `A1` Houdini adapter — *next, days*

The payoff of the whole design, and the first thing that consumes the library
rather than filling it. Until something reads the normalised layout, "zero
heuristics downstream" is a claim, not a result.

### Phase 3 — `A2` derived formats — *~1 week*

`.tx` / `.rat` / `.usda` into `derived/`, regenerable and never backed up.
Blocked on nothing; more useful once `A1` exists to consume it.

### Phase 4 — `B1` bulk migration — *the long one, hours of runtime*

Scan → review → apply → verify, resumable through an append-only journal.
Prefer same-drive renames over copies. `B3` dedup matters here, because `J:/3d`
looks like a FreeFileSync mirror of `H:/3D` and much of the data exists twice.

### What this order deliberately does not do

It does not add more importers before something reads what has been imported.
Eight assets are enough to prove the adapter; 4 000 are not more proof, they
are more risk.

---

## Open bugs

- (none recorded)

---

## Still unverified

Marked `VERIFY` in `types.json` — two minutes in each app's save dialog settles
them:

- Gaea: `.tor` (2.x) vs `.terrain` (1.x)
- ZBrush brush files: `.zbp` is a guess
- Marvelous Designer: `.zpac`
