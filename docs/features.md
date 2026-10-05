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

Last brought in line: **2026-09-13**. **14 392 lines** - 12 537 in
`assetlib`+`ui`, 1 855 in `houdini/` - and the library holds **137** assets,
44 GB. What the box holds has not been counted since it held 111; the
difference is `B1` continuing. `verify` warnings are `smudgeslarge001` and the
one vendor `.rat` listed in `ROADMAP.md`. Everything counted here is
committed.

---

## LIVE

- **Script assets keep their tree** — `folder_blob` is implemented
  (2026-09-13). The source lands verbatim at `src/<relative path>`: nothing
  renamed, slotted, contested or dropped. Also fixes `terrain`, `garment`,
  `reference`, `setup` and `unknown`, which were all silently getting the
  texture-set treatment. The `Manager_tool` suite went from *4 kept, 15
  rejected* to *51 kept, 0 rejected*.
- **App tags decide what a tool can do** — `app:houdini`, `app:maya`,
  `app:standalone`. Tags and not the category, because a tool can target two
  applications. `config/apps.json` holds the per-app detection; the tags
  decide whether a tool can be launched outside its host - a Houdini tool
  cannot, because it imports `hou`.
- **`install.json`, written by the tool author** — entry points, `pythonpath`,
  `otls`, read at import as the prefill. Autodetect is the fallback and is
  weaker than it looks: scanning for `def show()` proposed **five** entries for
  a suite with one launcher, because these tools do their work at module level.
  Read as **data, never executed** (invariant 15).
- **Launch a tool from the library** — right-click, or double-click the tile.
  Inside Houdini the window is a Python Panel, so the tool is imported and run
  in **that** process: no install, no restart, nothing written outside
  `library/`. From the standalone window only a tool needing no host is
  offered. The module and the call are shown and confirmed first — this is the
  single exception to invariant 15. **Both routes confirmed 2026-09-13**:
  `point_clean_tool` as a subprocess from the standalone window — the first
  tool this library ever ran — and the in-process route inside Houdini, the
  tool imported and run in the Python Panel's own session with no install and
  no restart. That last sentence is the claim the whole `script` type was built
  on, and it is now observed rather than argued.
- **A tool can name the interpreter it needs** — `"python"` in `install.json`
  (2026-09-13). The bundled runtime ships PySide6 and numpy and no tcl/tk, so a
  tkinter tool cannot run in it at all. A bare name is resolved on PATH at
  launch rather than stored as a path, because the asset syncs to a shared
  master. Declaring it also routes the launch out of process, host or not.
- **A launch that dies is reported** — the child is created with no console, so
  a tool that failed its first import looked exactly like one that started.
  Output goes to a log, read back 1.5 s later from the event loop; a missing
  module plus the bundled interpreter adds what the runtime actually ships.

- **Updating the app from GitHub** — `assetlib/update.py` + `ui/update_app.py`,
  Library ▸ *Check for updates…* (2026-10-05). Fetches the published archive
  over HTTPS with `urllib` + `zipfile`, **not** `git pull`: requiring git would
  break the one case portability exists for, a copy carried to a machine that
  has nothing. The archive **is** the tracked tree, so `library/`, `_cache/`,
  `.assetlib/` and `runtime/` cannot be touched — that is a property of the
  download rather than a filter kept in step with `.gitignore`. A config file
  the person has edited is kept and the new one lands beside it as `.new`.
  Identity is the **commit sha** in `.assetlib/update.json`, because
  `__version__` has read `0.1.0` for 53 commits. *Never run.*
- **Remote catalogue** — `assetlib/remote.py` + `catalog.py`. Library ▸ *Remote
  libraries…* declares a server; **Shift+F5** syncs `/api/catalog` into
  `.assetlib/remote/<host>.db`, ETag-diffed. Search runs local ∪ remote
  (`index.search_union`), so it works with the box asleep.
- **Remote thumbnails** — fetched per visible tile onto `netpool` (3 threads),
  cached at `.assetlib/remote/thumbs/<uuid>.jpg`, 60 s per-host cooldown after
  a failure. A thumbnail 404 is per-asset and never cools the host.
- **Remote import** — `assetlib/materialise.py` + `ui/import_remote.py`.
  Manifest first, cost shown before anything starts, `.part` + `Range` resume,
  hash-verified, into `_cache/{type}/{category}/{asset}/` **keeping the uuid**.
  Full package or hero LOD + one resolution. Proven end to end 2026-09-13.
- **Push to a server** — `assetlib/sync.py` + `ui/sync_server.py`. Library ▸
  *Push this library to a server…*: reads `asset.json` on both sides over SMB
  and groups the answer by verdict — **add**, **changed**, **moved**, and
  **on the server, not here**. A move is carried out as a rename on the share,
  so a re-categorised 1 GB asset costs nothing. A package is copied into a
  `.partial-` sibling and renamed into place, so an interrupted transfer never
  leaves a half-written package on the master. Nothing in a push deletes an
  asset.
- **Admin read off the share, never granted** — `sync.probe()` writes and
  removes one file in `library/` on the share. Write access means the Send
  button pushes; refusal means it copies into `_inbox/` on the server instead,
  which is the add-only path for anyone not on Samba's `write list`
  (gotcha 19).
- **Removing one asset from a server** — admin only, one at a time, the name
  typed to confirm, and it is a rename into `_trash/` on the share rather than
  a delete. Files an update leaves behind go the same way.
- **Re-index over SSH** — `sync.reindex()` runs
  `sudo -n systemctl start --no-block assetlib-reindex` with `BatchMode=yes`,
  so the box rebuilds its catalogue after a push and a missing NOPASSWD rule
  fails in a legible second instead of waiting on a password prompt nobody can
  answer.
- **Cloud tiles** — blue ground and outline for assets that are on a server and
  not on this disk, and a `☁ Cloud` toggle that hides them. `cache` is not
  marked: it is here.
- **First-run setup panel** — `ui/first_run.py`. A copy with no assets and no
  usable server shows it once: where assets live, server address + token,
  Desktop shortcut. Skip is remembered.
- **Create a new library…** — `assetlib/deploy.py` + `ui/new_library.py`.
  Copies the app and its runtime (~293 MB) to another disk, no assets, no
  index, no token; carries every way of REACHING the server — address, SMB
  share, SSH account — so the new copy can browse and push with only the token
  typed in. `first_run` shows the address and keeps the other two silently
  (2026-09-13).
- **Desktop shortcut with the app icon** — `assetlib/shortcut.py`, written via
  `wscript.exe` so no console appears; `ui/resources/asset_library.ico`.
- **No console on launch** — `Asset Library.vbs` starts `pythonw.exe` directly;
  `app._install_logging()` redirects stdout/stderr to `launch.log` and installs
  an excepthook, because `pythonw` has no stdout at all.

- **Hand-declared import, with full per-row override** — the Add window
  (Ctrl+N): drop zones, plan table, every decision overridable from a dropdown.
  Nothing is written before the Add button.
- **LODs end to end** — stripped from vendor names, recorded per level,
  re-emitted as `_lodN`; hero LOD promoted by `commit._promote_hero_lod()`.
- **Multiple resolutions per slot** — schema v4. Every size kept, labelled
  from the measured pixel width (`16k`), re-emitted as `_<res>` before the
  UDIM tile; biggest promoted into `textures[slot]` by
  `commit._promote_best_resolution()`. `res:4k` asks *has this size*.
- **Grid tiles sized to their content** — `gridmodel.TileDelegate` and
  `tile_sizes()`: 16:9 tile, image bottom-aligned, name in a fixed two-line
  block with middle elision. One aspect for the whole view, because
  `setUniformItemSizes(True)` needs it (gotcha 12).
- **Multi-select import to Houdini** — select a shelf of assets, one
  options dialog, all built. Options are read from the FIRST asset; the
  dialog says so. Non-mesh assets are skipped.
- **Batch import** — `ui/batch_add.py`, button beside *Add asset* or
  Ctrl+Shift+N. One row per subfolder, shift-select, and a change to Type,
  Category or the checkbox spreads across the selection. Name never
  spreads. `analyse()` per asset, `commit()` still the only writer.
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
- **Script / tool type** (2026-09-13) — 18th root type, `folder_blob` +
  `sidecar`, `.py .shelf .vfl .h .json .xml`, seven categories named after the
  app that runs it. Declared LAST of the real types: `.json` and `.xml` are the
  most generic extensions in the registry and anything earlier would claim
  every Megascans folder off its sidecar. Blob, not single-file, because a tool
  is a package and flattening it breaks its imports. Config only — no code
  changed.
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

- **Installing a tool into Houdini as a package** — built and removed
  2026-09-13, the same day. One JSON into `$HOUDINI_USER_PREF_DIR/packages/`
  plus a generated shelf inside the asset. Removed because *Launch* does the
  same job better from inside a Python Panel, with no restart and nothing
  written outside `library/`. **The one thing it could do that Launch cannot is
  put a tool's HDAs on `HOUDINI_OTLSCAN_PATH`**, which is read at startup — so
  the day someone declares `otls`, this is the thing to reconsider. Argument,
  emitted shapes and what survived:
  `docs/History/houdini-package-install-removed.md`.

- **The command line** — `assetlib/cli.py` and `requirements.txt`, deleted
  2026-08-21. Its real job was forcing the core to stay UI-free, and that is
  now an import rule instead. Every command it had exists in the window.
  Detail and the old command → menu mapping: `docs/History/cli-removed.md`.
- **Vendor `.mtlx` / `.usd` / `.usdc` / `.mtl` sidecars** — **kept verbatim in
  `extra/`, never bound** (changed 2026-09-13; they used to be deleted). They
  reference the original filenames, which the import renames, so resolving one
  would hand an adapter missing textures — but unusable is not worthless, and
  deletion is the one outcome that cannot be undone. Nothing in `asset.json`
  points at them, so no adapter can load one by accident. Ours are still
  generated into `derived/`. `vendor_sidecars` in `texture_slots.json`; the
  reasoning is in `docs/decisions.md` § Reversed.
