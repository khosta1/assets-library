<!-- covers: assetlib/**, ui/** -->

# Feature inventory

Four states:

```
LIVE       running now
DORMANT    built and working, currently switched off - the switch is named
VESTIGIAL  kept but unread - a value computed that nothing consumes
REMOVED    deleted, listed so it does not get reinvented
```

`ROADMAP.md` is what is being BUILT. This file is what EXISTS.

Last brought in line: **2026-09-12**. ~5 200 lines; the library holds 57
assets and verifies clean apart from three orphan warnings (see `ROADMAP.md`).

---

## LIVE

- **Hand-declared import, with full per-row override** — the Add window
  (Ctrl+N): drop zones, plan table, every decision overridable from a dropdown.
  Nothing is written before the Add button.
- **LODs end to end** — stripped from vendor names, recorded per level,
  re-emitted as `_lodN`; hero LOD promoted by `commit._promote_hero_lod()`.
- **Multiple resolutions per slot** — schema v4. Every size kept, labelled
  from the measured pixel width (`16k`), re-emitted as `_<res>` before the
  UDIM tile; biggest promoted into `textures[slot]` by
  `commit._promote_best_resolution()`. `res:4k` asks *has this size*.
- **Import to Houdini** — right-click an asset. Options dialog lives in the
  library (`ui/import_houdini.py`), never in Houdini: opacity mode,
  displacement, resolution, variant, USD variant set, localize to `$HIP`.
  Inside a Python Panel it calls the builder directly; standalone it writes
  `.assetlib/request.json` for the `Build last request` shelf button.
  **The builder itself is not ported yet** — the request is written and
  readable, and the shelf says so plainly.
- **Houdini Python Panel** — the same `MainWindow` inside Houdini's process,
  so right-click → Import builds directly instead of leaving a request.
  Never touches `runtime/` or the host's palette.
- **Karma / MaterialX / Solaris builder** — `houdini/python/assetlib_hou/
  build.py`, 1 183 lines ported from the old shelf tool. Component chain,
  MTLX subnet, opacity stencil, VDB foliage proxy, USD variant sets.
  Reads `asset.json`; guesses nothing.
- **Houdini seam** — `houdini/`, one package file to install. Passes on
  22.0.368 / Python 3.13.10 / PySide6.
- **Geometry variants** — schema v6. A second version of one asset (Big/Small,
  Var01) is kept rather than losing the format contest, keyed
  `(ext, lod, variant)` and named `<asset>_<variant>[_lodN].<ext>`. Pre-filled
  from `variant_patterns`, overridable per row in the **Var** column. `role`
  distinguishes `variant` from `exchange`.
- **Geometry recognised on every type** — `geometry_ext` in `types.json` routes
  19 mesh formats to `geo/` regardless of the declared type, and `geometry`
  is a binding target in its own right rather than a second name for
  "main file". Fixes vegetation assets losing every mesh to `extra/`.
- **Editing** (Ctrl+E) — re-analysis and diff, staged through `_editing/old/`,
  which is destroyed last.
- **Deleting** (Shift+Del) — explicit, confirmed, file list shown first.
- **Contents viewer** (Ctrl+I) — every file labelled by its ROLE.
- **HDR/EXR thumbnails** — decoded, exposure from a high percentile,
  subsampled while reading.
- **Bounded preview cache** — `ui/thumbcache.py`, invalidated on edit.
- **Forced dark theme** — `ui/theme.py`, one `setColorScheme(Dark)` in `main()`
  before the first widget. Every colour is palette-derived; no literal left in
  a widget. Not a preference and not OS-following — see `docs/decisions.md`.
- **Sidebar collapsed by default** — types start closed; what you open survives
  the rebuild that follows every add, edit, delete and F5.
- **FTS search** — free text prefix-matched, filters `type: cat: tag: res:
  src:`, each negatable with `-`.
- **Verify, and verify deep** — Library ▸ Verify. Deep recomputes digests,
  algorithm-aware.
- **Index rebuild** — F5, from the packages themselves.
- **Bundled runtime** — `runtime\python.exe`, ~330 MB, Python 3.11.9 with
  PySide6 6.11.2, Pillow 12.3.0, numpy 2.4.6, OpenEXR 3.4.14, xxhash 4.0.1. No
  install, no pip, no system Python.
- **Portability** — tested by running the full toolchain from a completely
  different path. Config roots are relative, `find_config()` walks up from
  `assetlib/`, index paths are relative to `library/`.

---

## DORMANT

Nothing. Every switch in this project is a user-facing option, not a hidden
one.

---

## VESTIGIAL

- **`index.find_by_hash()`** — present, returns nothing, called by nothing. It
  is the stub for dedup, and the hashes it would need are already in every
  `asset.json`. Kept because the signature is right; see `ROADMAP.md`.

---

## REMOVED — do not reinvent

- **The command line** — `assetlib/cli.py` and `requirements.txt`, deleted
  2026-08-21. Its real job was forcing the core to stay UI-free, and that is
  now an import rule instead. Every command it had exists in the window.
  Detail and the old command → menu mapping: `docs/History/cli-removed.md`.
- **Vendor `.mtlx` / `.usdc` sidecars** — discarded at import, by design. They
  reference the original filenames, which the import renames. Ours will be
  generated into `derived/` instead. See `docs/decisions.md`.
