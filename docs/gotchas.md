# Gotchas — found the hard way, do not re-learn

Split out of `CONTEXT.md` §8 on **2026-09-11**. Numbering is preserved: entries
are referred to by number, so nothing is ever renumbered.

---

**1. A sidecar format decided the type** — 2026-08-20

ambientCG ships a 2.5 KB `.usdc` next to its textures. Counting it as geometry
classified a texture set as a `material`, which ran the generic planner, which
had no variant filtering — so NormalDX and NormalGL both landed on
`tex/concrete014_normal.png` and one silently overwrote the other.

**Cause:** a file's mere *presence* was taken as evidence of what the asset is.

**Fix:** `SIDECAR_EXTS`; one shared slot-resolution function for both planners;
and `conflicts()` now refuses to commit a plan where two files claim one
destination at all.

**Rule:** a small file that merely accompanies an asset never determines what
that asset is.

---

**2. `_diff_` was missing from the diffuse keywords** — 2026-08-20

Poly Haven basecolors fell through unmatched.

**Rule:** test slot keywords against real vendor data, not against the naming
scheme you would have chosen.

---

**3. A bare stem is a preview** — 2026-08-20

`Concrete014.png` beside `Concrete014_8K-PNG_Color.png` is ambientCG's preview
render. It matches no slot keyword, and it must not: it is a picture *of* the
asset, not a channel of it.

---

**4. Slot order in `texture_slots.json` is significant** — 2026-08-20

First match wins, so `diffuse` MUST stay last as the catch-all, or
`subsurface_color` and `specular_color` get mis-slotted as diffuse.

**Rule:** when a matcher is first-match-wins, its config file is code, and
reordering it is a behaviour change.

---

**5. `verify` must skip subfolders inside a package** — 2026-08-20

`tex/` and `preview/` are not drift. Drift is files in `library/` *outside* any
package.

---

**6. A package can contain another `asset.json`** — 2026-08-21

RenderMan `.rma` bundles ship one, and `folder_blob` payloads land in `extra/`
verbatim. A plain `rglob` indexed the payload as a second, deeper asset, and
`verify` called it a depth violation. Real case:
`library/ies/spot/*/extra/asset.json`.

**Fix:** `iter_assets()` stops descending once it finds a package.

**Rule:** anything kept verbatim may contain the tool's own file formats. Treat
`extra/` as opaque, always.

---

**7. Writes must not share the thread pool with thumbnail decoding** — 2026-08-21

Opening Contents queues a decode per file. Twenty 8K TIFFs occupy every thread
for a minute, a write job queued behind them never starts, and the progress
dialog hangs forever.

**Fix:** `ui/writepool.py`, deliberately single-threaded and separate.

**Rule:** a job the user is *waiting on* never shares a queue with work that is
merely nice to have.

---

**8. Verification must recompute with the algorithm the digest was written
with** — 2026-08-21

Found by testing the external-disk scenario: assets imported while `xxhash` was
absent carry `b2:` digests. Verifying after installing xxhash recomputed
`xxh3:` and reported **every file as corrupted**.

**Fix:** `hashing.matches()` parses the prefix and raises `UnavailableAlgorithm`
when it cannot compute — reported as **"cannot check"** (a warning), never
"corrupted".

**Rule:** *unverifiable is not the same as corrupted*, and a stored digest must
carry its algorithm.

---

**9. A thumbnail cache keyed by uuid needs explicit invalidation** — 2026-08-21

A uuid deliberately survives an edit, so without `invalidate()`/`forget()` an
edited asset shows its old icon forever.

**Rule:** every identifier chosen because it is *stable* creates a cache that
must be invalidated by hand.

---

**10. An edit can be handed a file already at its destination** — 2026-08-21

For example a file dragged out of `derived/`. Copying it would open the same
file for reading and writing at once and destroy it.

**Fix:** `edit.apply()` checks for this before copying.

---

**11. Float images cannot be clamped to 8 bits** — 2026-08-21

A linear 32-bit equirect needs exposure and gamma, and the exposure must come
from a **high percentile** — otherwise one bright sun disc drags the whole sky
to black. An 8K HDR would also be 400 MB as float32, so the decoder subsamples
while reading.

---

**12. Qt performance is not optional** — 2026-08-21

`QListView` + `QAbstractListModel` (never `QListWidget`),
`setUniformItemSizes(True)`, decoding on a pool, and search that queries FTS5
only.

**Rule:** the window must never walk the filesystem during interaction.
