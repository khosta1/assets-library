# Journal

Newest first.

---

## 2026-09-13 (last) — a tool becomes an asset, and an installer lives one day

Fifth entry today, and the whole of it is the `script` type: 18 commits from
`812dc0e` to `23d8a50`, the last of which deletes a feature written eight
commits earlier.

**Done.**

- **`script`/`tool`, the 18th root type** (`812dc0e`) — config only, seven
  categories named after the app that runs it. Declared **last** of the real
  types, because `.json` and `.xml` are the most generic extensions in the
  registry and anything earlier would claim every Megascans folder off its
  sidecar.
- **`folder_blob` implemented** (`eaf5c5f`) — the source tree lands verbatim at
  `src/<relative path>`: nothing renamed, slotted, contested or dropped. It was
  declared in config on the previous commit and did not exist in `analyse.py`,
  so every declared blob type was silently getting the texture-set treatment.
  The `Manager_tool` suite went from *4 kept, 15 rejected* to *51 kept, 0
  rejected*. `terrain`, `garment`, `reference`, `setup` and `unknown` were
  fixed by the same function.
- **App tags** (`bcee2f3`, `config/apps.json`) — `app:houdini`, `app:maya`,
  `app:standalone`, detected from extensions, imported module names and folder
  names. Tags and not the category, because a Python library used from both
  Houdini and Maya is one asset with two targets and one folder.
- **`install.json`, read as the prefill** (`c85dafb`) — the tool author's own
  manifest wins over autodetect, because they know which module is meant to be
  launched. Later gained an `icon` field (`328f96b`), so a tool can put its own
  window icon on its tile.
- **Launch** (`bb3d434`, `7566d6c`) — right-click, or double-click the tile.
  Inside Houdini the library window *is* a Python Panel, so the module is
  imported and called in that process: no install, no restart, nothing written
  outside `library/`. The module and the call are shown before anything runs.
- **The installer, built and retired the same day** (`1b12927`, `23d8a50`) —
  see below.
- **Five importer bugs**, all found by trying to import one real suite:
  `extra/` doubling on every edit (`74c3290`); a dropped folder taking one
  level instead of its tree (`c8dbe88`); plan paths taken from
  `files[0].parent` instead of the common ancestor, which flattened the tree
  and produced an asset containing only `install.json` (`f35b340`); a
  declaration that names a file the package does not contain, now refused
  up-front (`3deb4f0`); and `otls` inferred from finding `.hda` files, now
  never inferred (`1a50024`).
- **Transparent icons composite onto the tile ground** (`93ee536`) — Pillow's
  `convert("RGB")` *drops* alpha rather than compositing it, so an icon drawn
  on white-under-alpha arrived with white corners on a dark tile.

**Decided.**

- **The library never executes package content of its own accord** — invariant
  15, written the day a `script` type existed (`66757cb`). It became
  load-bearing immediately: `materialise.py` downloads packages from the box,
  so a library that ran code an asset carried would make *downloading* an asset
  mean *running its code*. `launch.py` is the **single exception**, and the
  words "of its own accord" are what carry it: a person choosing Launch on a
  named asset is that person running their own tool.
- **`otls` is never inferred.** Declaring a folder of HDAs puts them on
  Houdini's path *and* ships them onto a shared master for other people to
  load. Whether a bundled `.hda` may be redistributed is its owner's decision,
  not something an importer settles by noticing a file extension.
- **Autodetect is weaker than it looks.** Scanning for a zero-argument `show()`
  proposed **five** entry points for a suite with exactly one launcher, because
  these tools do their work at module level. The manifest says one. Autodetect
  stays as the fallback for a tool that ships no manifest, and it proposes,
  never decides.
- **Installing into Houdini is not how a tool is used here** — Felix: *"since
  the houdini script and tools can be directly launched from the library get
  rid of the installation part"*. Built at `1b12927`, removed at `23d8a50`,
  eight commits and a few hours apart. Launch does the same job from inside a
  Python Panel with no restart and nothing written outside `library/`. **The
  one thing the installer could do that Launch cannot is put a tool's HDAs on
  `HOUDINI_OTLSCAN_PATH`, which is read once at startup** — so the day someone
  declares `otls`, that is the thing to reconsider, and it is the only
  capability that distinguishes the two routes. Argument, both emitted file
  shapes and what survived:
  `docs/History/houdini-package-install-removed.md`.
- `apps.unresolved()` moved to `apps.py` rather than going with the installer:
  a manifest being honest is worth checking whether or not anything ever acts
  on it. `otls` is still read into `asset.json` and consumed by nothing — the
  honest state, and agreed with the `Manager_tool` session, because a field
  that vanishes with its consumer is a field someone has to rediscover.

**Open.** Nothing is half-written, and **nothing on either side has been run
inside Houdini** — both halves are *emitted, parsed, unclicked*. The next real
information comes from Felix opening the panel, not from more code.

- **`refresh_from_source()` was never built** — step 7 of the script plan, the
  copy-with-update half. A tool imported today is a snapshot; re-pulling from
  the author's working folder has no button.
- **The `Manager_tool` suite has still never imported successfully.** Every
  attempt so far produced a broken asset, and each one found a different bug in
  the list above. The bugs are fixed; the import has not been re-run.
- **Three `reference/` assets were imported while `folder_blob` was declared
  and unimplemented**, so they got the texture-set treatment and need
  re-importing.
- Carried forward from earlier today: `.tx` has a converter and no caller,
  `.usda` is untouched, `derived/` and `_cache/` have no size budget,
  `smudgeslarge001` needs re-importing, the Samba stanzas are not applied on
  the box, and `sync.py` has still never *written* to a share.

**Wrong turn worth keeping.** I reported four `sys.path.insert` lines in the
suite as a hard blocker — "worse than a crash". They were inside module
docstrings. The peer session challenged it, and it was wrong: I had grepped for
the pattern and reported line numbers without reading what surrounded them. A
grep hit is a location, not a fact.

**Next.** Import `Manager_tool/suite` end to end with the five fixes in place —
it is the only thing that has exercised any of this — then Felix in Houdini:
open the panel, double-click the tile.

---

## 2026-09-13 — derived/ stops being empty, and a progress bar that lied

Fourth entry today. `A2`, the re-index that closed the previous entry's *Next*,
and a context-pack set that had quietly stopped describing the project.

**Done.**

- **`A2`, the `.rat` half** — `assetlib/derived.py` (`fb379c6`). `iconvert` and
  `hoiiotool` found by scanning Houdini installs newest-first, called as
  subprocesses, so **no `hou` import** and the module lives in `assetlib` like
  everything else. `derived_rel()` changes only the extension, so slot, LOD,
  resolution and `<UDIM>` survive into the bake. UDIM is all-or-nothing —
  half a set renders holes.
- **The hook is one line** in `build.textures_for()`, the only place a texture
  becomes a path. Two flags: `derived` = use a bake, `bake` = make a missing
  one; off-and-off is exactly last week's behaviour. One checkbox in
  `import_houdini.py`, because the decisions live in the library.
- **`ui/bake.py`** + Library menu — pre-bake a shelf, off the GUI thread,
  selection only.
- **The freeze, and the fix** (`4234b2d` then `1d8c01e`). See *Decided*.
- **`A4` recorded** (`0499293`) — USD variant sets from the bindings instead of
  a cooked prim-`name` probe. Phase 3b.
- **The box re-indexed**: `111 assets in 1.1s (0 failed)`, `/api/health` now
  `assets=111 mounted=True`. Master and cache agree. Passwordless sudo for
  `felix` turned out to be configured, so it ran over SSH with no password.
- **`packs.json` rewritten.** `remote` and `houdini` added, `ui` cut from a
  `ui/**` glob to a named list. Uncovered code **4 739 lines → 87**.
- **Codemap**: 55 files, 15 232 lines, 76 types.

**Decided.** Baking is **on demand, not at import**: measured 1.0 s per 2K map
and 4.6 s per 8K, so all 111 would be ~900 conversions and roughly **+100 GB**
on a 43.75 GB library, most of it for assets nobody renders. And the reason for
any of it is not speed — Karma converts a `.jpg` itself and writes the result
into `tex/`, which is where the 60 strays came from. Give it a `.rat` and there
is nothing left to convert.

The freeze is the entry worth reading twice. Baking behind a progress bar that
called `QApplication.processEvents()` produced **an animated bar on a frozen
Houdini** — `processEvents` pumps *Qt widget* events, so our own dialog
repainted, while Houdini's viewport and cook run on *Houdini's* loop, which
cannot run while a Python script is on the main thread. Pumping Qt does not hand
control back; **only returning does**. So the build is now deferred:
`hou.ui.addEventLoopCallback` (found in the shipped `hou.py`, not assumed)
builds the nodes once the worker finishes. The contract change is real and is
stated rather than hidden — a build that had to bake returns `None`, and
`send()` says "baking… the nodes appear when it finishes" instead of counting
zero.

Rejected: binding the `.jpg` immediately, baking in the background and
re-pointing the nodes. Never stalls, and changes paths under a scene that is
already open — a surprise traded for a wait.

**Open.**

- **The deferred path has been confirmed working by Felix**, but only on the
  route he used. Which of the two entry points — Python Panel or shelf button —
  is not recorded, and they hold the main thread differently.
- **`.tx` has a converter wired (`hoiiotool`) and no caller.** `.usda`
  untouched. `A2` is a third done.
- **`derived/` has no size budget.** A `.rat` is ~3× its source, and the
  `_cache/` gap is the same shape. Neither is bounded.
- **The 60 pre-existing strays in `tex/` are still there** (1.85 GB on the box,
  25 `verify` warnings). Now worth cleaning, because with `A2` they stop coming
  back — before it, deleting them was pointless.
- **`smudgeslarge001` still needs its re-import** — the last two non-`.rat`
  warnings.
- **`packs.json` is committed but the packs are not** — `context/` is
  gitignored on purpose. `ui` at 66k is the heaviest left and could split again
  (Add/Edit are their own topic); the cut is not obvious enough to make yet.

**Next.** Clean the 60 strays, now that `A2` stops them returning — locally and
on the box, then re-index. It is the one item whose cost only goes up while the
library grows.

---

## 2026-09-13 (later) — the push, and who is allowed to make it

Third entry today. The one below is `B1`; this is the way back up to the box,
and the gate on it.

**Done.**

- **`assetlib/sync.py`** (new, 640 lines) — pushes this library onto the
  master over SMB, diffing by **uuid** on both sides. Four verdicts: `add`,
  `update`, `move`, `missing`. A move is `os.replace` on the share, so a
  re-categorised 1 GB asset costs nothing. A package is copied into a
  `.partial-` sibling and renamed into place. No Qt, no `hou`.
- **`ui/sync_server.py`** (new, 380 lines) — *Library ▸ Push this library to a
  server…*: the plan grouped by verdict, `missing` last and uncheckable,
  progress and cancel, scan and copy both off the GUI thread.
- **`probe()` reads the permission and never grants one** — writes and removes
  one file in `library/` on the share. Write access → the Send button pushes;
  refusal → it copies into `_inbox/` instead, which is the add-only path.
- **Removal is separate** — one asset, admin only, the name typed to confirm,
  and it is a rename into `_trash/`. Files an update leaves behind go the same
  way. Nothing in this module deletes.
- **`sync.reindex()`** — `ssh -o BatchMode=yes … sudo -n systemctl start
  --no-block assetlib-reindex`, so a missing NOPASSWD rule fails in a legible
  second instead of waiting on a prompt nobody can answer.
- **`Host` gains `share` and `ssh`**, stored beside the token in
  `.assetlib/remote/hosts.json`; two more columns in *Remote libraries*.
- **A new library inherits all three** — `deploy.suggest_host()` carries
  address, share and SSH account, never the token; `first_run` keeps the two it
  does not show. A fresh copy is asked for one thing and can then browse **and**
  push.
- **Docs** — `decisions.md` § *Pushing onto the master* + four rejected rows,
  gotcha **19**, `architecture.md` § **7c the master join**, `features.md`,
  `ROADMAP.md`.
- **Measured against the real share** (`Y:\assets`, read-only): admin `True`,
  **1.6 s**, 222 packages read, **111 local and 111 remote, no verdicts and no
  skips**. Both sides already agree — which closes the previous entry's *Next*.
  It was closed by Felix's own robocopy at 01:53 (`push.log`, 4.3 GB copied, no
  `/MIR`, no `/PURGE`), not by this tool.
- **Not mine, uncommitted, earlier the same day:** `assetlib/derived.py` (281
  lines) and the `build.py` hook that hands Karma a `.rat` instead of a `.jpg`
  — the answer to the 25 `verify` warnings in the entry below. State in *Open*.

**Decided.** A push **diffs by uuid, not by path**, because a path is not an
identity here — a mirror turns a re-categorisation into a re-upload plus a
delete (`decisions.md` § *Pushing onto the master*; `robocopy /MIR` is in the
rejected table). **Admin is an SMB account, not a setting**: an app-side
password or a `config/` flag is a lie that looks like a lock when anyone
holding the disk can edit JSON, so the gate is Samba's `write list` and the app
only reads which side of it this account is on. The unix alternative is in
gotcha **19** — a sticky bit on an ntfs-3g mount succeeds and grants nothing.
**No upload route on the API**: Felix, asked directly — LAN/SMB is enough, and
read-only is what keeps a leaked token from damaging 1.7 TB. `first_run` shows
the address but **not** the share and SSH fields, carrying them silently,
because that panel asks the one thing it cannot know and two already-correct
boxes would make it read as a form.

**Open.**

- **`sync.py` has never written to a share.** Only `probe()` and `diff()` have
  run against `Y:\assets`. `push`, `drop`, `discard`, the move-as-rename, the
  `.partial-` rename and `reindex` are **unexercised on real data** — they
  compile, they import, and that is all that is known. A shakeout script
  against a throwaway share in the scratchpad was written and **Felix stopped
  it before it ran** ("ok everything working"); the scratchpad is disposable, so
  nothing of it survives. Do not rebuild it unless asked.
- **The Samba stanzas are not applied on the box.** The entire admin gate is
  `read only = yes` + `write list = felix` on the library share plus a second
  writable share as the drop box, and until that is in `smb.conf` **every LAN
  account probes as admin** — the app currently tells the truth about a gate
  that does not exist. That is server-panel territory.
- **Whether `sudo -n systemctl start assetlib-reindex` works over SSH is
  unknown.** The box has three NOPASSWD exceptions; nobody checked whether this
  unit is one. If not, the button fails in a second and prints the command,
  which is the intended fallback and not a bug.
- **The `.rat` work is complete and uncommitted.** Four files, none of them
  tracked: `assetlib/derived.py`, the `build.py` hook in `textures_for()`, the
  *Use .rat textures* checkbox in `import_houdini.py` (two flags — `derived` is
  whether to USE a bake, `bake` whether to MAKE a missing one), and `ui/bake.py`
  + `app.py:454` for the batch pre-bake. Felix wired the last two while this
  entry was being written, which is why an earlier draft of it called them
  missing. **Not known to have been run inside Houdini.** `.usda` untouched.
- **`_trash/` on the server has no sweep and no budget** — same shape as the
  `_cache/` problem, on the disk that matters more.
- **The drop box has no promotion step** — a contributor can copy into
  `_inbox/`; moving it into `library/` is manual, with nothing verifying what
  arrived.
- **The scan is linear**: one `asset.json` per package, both sides. 1.6 s at
  222. `/api/catalog` is the obvious pre-filter and was deliberately refused —
  a catalogue rebuilt daily is a stale answer to "what is on the server".
- **`push.log` is untracked at the repo root** — Felix's robocopy log, 124 KB.
  Delete it or gitignore it; it is not ours.

**Next.** Apply the two Samba stanzas on the box and confirm `probe()` reports
**not** admin from a second account. Everything written today about who may
delete is true only once that is in `smb.conf`.

---

## 2026-09-13 (later) — B1 starts, and stepping earns its keep

Second entry today. The one below is the cloud library; this is the bulk
migration that followed it.

**Done.**

- **36 assets imported** from `VaultCache/FabLibrary`. Library **75 → 111**,
  43.75 GB. `scan` 27, `vegetation` 30 (was 19), and every one of the 36 has
  its meshes, its slots and a preview.
- **`port.py`** — a plan-driven CLI, `bad71a5`. Reverses the 2026-08-21 CLI
  removal for this job only; scope and reasoning in `decisions.md` § Reversed.
  Five subcommands; `set --skip` was added as a flag rather than a sixth.
- **`docs/porting.md`** — the procedure, so the next bulk import does not
  re-derive any of this.
- **Four systematic bugs found and fixed**, all by stepping, none by reading
  code: letter variants `VarA..VarK` (`cb68b3c`, ~90 meshes were being
  rejected), billboard maps winning real slots (same), `gloss`+`roughness`
  colliding on one destination (same — would have blocked every commit), and a
  variant word inside the asset's own name (`a6553c1`, six assets).
- Earlier the same day and feeding this: `.rat` routed to `derived/`, vendor
  sidecars kept in `extra/`, the LOD-binding fix in `bind()`.

**Decided.** Stepping over batching, on Felix's choice — one asset, one word,
36 times. It cost an evening and found four bugs that would each have been
multiplied by 36. He switched to a single pass at asset 12, after the fixes had
landed, which is the right shape: step until the failure modes are known, then
loop. The glTF bundle got **no rule** — one example is not a pattern, the folder
was deleted, and `docs/porting.md` says to make a rule if a second appears.
`Granite_Rock-68ea246b` skipped by hand, 699 MB of raw 8K; the skip lives in the
declarations, not the plan, so a replan cannot resurrect it.

**Open.**

- **The 36 are only on `H:`.** The box is the master. They need the same SMB
  push and re-index the original 75 got, and `/api/health` should then read
  **111**. Not done.
- **25 `verify` warnings are `.rat` files in `tex/`, written by Houdini**, not
  by the importer — Karma auto-converts on first render and writes beside the
  texture. `derived/` exists for exactly this and nothing tells Houdini so.
  That is `A2`'s gap and it now has a reproducible symptom.
- **2 warnings are the old `smudgeslarge001`**, still needing a re-import.
- **8 usdz-only assets and `European_Black_Alder` were skipped**, not solved. A
  `.usdz` hides its textures inside the zip; importing one gives geometry with
  no bindings.
- **`Tundra_Grass` shipped its payload twice** (loose + `_extracted`,
  byte-identical). The planner deduped correctly — 45 kept, 45 rejected — but
  it dedupes on `(ext, lod, variant)`, not on content, so it does not *know*
  they were identical.

**Next.** Push the 36 to the box and re-index, so master and cache agree again
before anything else is imported. Everything after that is `B1` continuing:
`H:/3D/Maya/assets`, `H:/3D/Insect/Texture`, the rest.

---

## 2026-09-13 — the library leaves this machine

The box becomes the master and this folder becomes a client. Built against
`server/client-contract.md`, written by the server-panel session; `server/` is
theirs and was not touched.

**Done.**

- **The seed ran.** `library/` → `\\192.168.1.13\data2\assets\library` over SMB:
  **75 packages, 1 039 files, 38.296 GB at 112 MB/s**, 0 failed, 0 mismatched,
  `derived/` excluded. The box reports 75 and `library_mounted: true`.
- **Origin plumbing.** `config/library.json` gains `roots.cache`;
  `config.py` gains `cache_root`, `root_for()`, `asset_path()`,
  `root_containing()`. Ten call sites that said `cfg.library / row["path"]` now
  go through one function. `index.py` gains an `origin` column, `upsert(origin=,
  size=)`, and a `rebuild()` that walks both roots.
- **Houdini seam carries the origin** — `import_houdini.write_request()` writes
  it, `launch.py` resolves through `root_for()`, `build.py` localises via
  `root_containing()`, `seam.py` reports the cache root.
- **Catalogue tier.** `assetlib/remote.py` (stdlib `urllib`, no Qt),
  `assetlib/catalog.py`, `index.search_union()` / `counts_union()`,
  `ui/remote_libraries.py`. Shift+F5 syncs; ETag 304 honoured.
- **Thumbnail tier.** `_RemoteThumbJob` + `ui/netpool.py`, cached at
  `.assetlib/remote/thumbs/<uuid>.jpg`, per-host cooldown.
- **File tier.** `assetlib/materialise.py` + `ui/import_remote.py`: manifest,
  `.part` + `Range` resume, hash verify, into `_cache/` **keeping the uuid**.
- **Cloud tiles** — blue ground + outline (`theme.cloud_fill/cloud_edge`),
  `CLOUD_ROLE`, and a `☁ Cloud` toggle that hides them.
- **First-run panel** (`ui/first_run.py`), **Create a new library…**
  (`assetlib/deploy.py` + `ui/new_library.py`), **Desktop shortcut + icon**
  (`assetlib/shortcut.py`, `ui/resources/asset_library.ico`).
- **No console, ever** — `Asset Library.vbs` runs `pythonw.exe` directly;
  `cmd.exe` is out of the chain. `app._install_logging()` redirects to
  `launch.log` and installs an excepthook.
- Gotchas **17** and **18**.

**Decided.** `_cache/` is a **sibling** of `library/`, not inside `.assetlib/`
— that folder means "delete it, pay a rebuild", this one means "pay a
re-download of gigabytes". `library/` is **kept** and empties itself, so origin
stays 3-way rather than 2-way. Verify **skips** `_cache/` — it is a copy the box
already verified and every file is hash-checked at download. `cache` is
deliberately **not** blue: a downloaded asset is here and costs nothing, and
marking it would warn about the one case with nothing to warn about. Downloads
are **one at a time**, because seeing the cost before paying it does not survive
being applied to twelve assets. No `/api/ping` — the client never probes before
a token exists, and weakening the server's fail-closed rule for it would buy
nothing. **No frozen `.exe`**: it would break the Houdini seam, which needs an
importable `assetlib/` on disk — recorded in `decisions.md`.

**Proven.** Same day, after the entry above was written: the J: lock was
cleared, the copy remade from *Create a new library…*, and the whole chain run
from an empty `library/` — first-run panel, token, Shift+F5, all 75 arriving as
cloud tiles, and an asset downloaded, hash-verified and flipped from blue to
local. Felix: "everything is working as intended." So `Range`, the hash check,
the uuid-preserving write and the origin plumbing are all exercised, not merely
compiled. The three items this entry originally listed as unobserved are closed.

**Open.**

- **`_cache/` has no size budget.** Asked and deferred: "no cache budget needed
  for now". On a portable drive it grows until the disk is full. `thumbcache.py`
  already has the pattern — a budget in `library.json` and an LRU sweep.
- **Remote thumbnails are never re-fetched.** Per the contract, uuid is the
  cache key. An asset re-imported on the box keeps its old tile until
  `.assetlib/remote/thumbs/` is cleared by hand.
- **Hero-LOD subsetting has only met constructed manifests.** The interesting
  path — a slot with no file at the requested resolution falling back to the
  nearest smaller — has not seen a real Megascans package.
- **`run_ui.bat` was deleted** this session (not by the agent). `CLAUDE.md` and
  the `.vbs` comment have been corrected to a literal `runtime\python.exe -m
  ui.app`.

**Next.** `B1` bulk migration — Felix's call, taken at the end of this session.
`VaultCache` first, per the order already in `ROADMAP.md`: uniformly named, and
every asset in it exercises resolutions, variants and LODs. Two known bugs will
bite during it — LOD-tagged textures binding nothing, and `.rat`/`.tx` landing
in `extra/` instead of `derived/` — both in *Open bugs*.

---

## 2026-09-12 (last) — the first batch lands, and the grid has to hold it

Third entry today. The two below cover the import pipeline and the Houdini
adapter; this is only what changed after them.

**Done.**

- **The Plants batch ran.** Library went **58 → 75**. `vegetation/grass` holds
  **18**, `scan/plant` 1. 19 assets now carry geometry. First real use of
  `ui/batch_add.py`, and the first time the library was filled by anything but
  one-at-a-time.
- **The Python Panel works in Houdini 22** — confirmed by screenshot, browsing
  and building from inside the host.
- `39476b0` — **multi-select import**: grid is `ExtendedSelection`, right-click
  gives *Import N to Houdini*, one dialog, every selected asset built.
  Non-mesh assets in the selection are skipped rather than refusing the batch.
- `39476b0` — **tile delegate**, `gridmodel.TileDelegate` + `tile_sizes()`.
  Grid is 16:9, image bottom-aligned, name in a fixed two-line block with
  middle elision.
- `strip_tokens` gained the mesh formats, so names stopped ending in `_fbx`.
- Gotchas **15** and **16**; `architecture.md` §7b; the B1 measurement into
  `ROADMAP.md`.

**Decided.** The multi-select dialog reads its options from the **first**
selected asset and applies them to all — Felix asked for it and named the
hazard in the same breath, so it is stated **on screen** rather than hidden,
and `ROADMAP.md` carries it as marked-not-solved. Per-asset greying is switched
off when several are selected, because the asset the dialog was read from may
be the only one *without* an opacity map. The tile grid is **one aspect for the
whole view**, not per tile, because `setUniformItemSizes(True)` is what keeps
it fast (gotcha 12). Name elision is **middle**, because two plants here differ
by their Megascans hash alone and eliding the tail would make them identical.

**Open.**

- **The tile delegate has never been seen.** Geometry is verified arithmetically
  — at every zoom the image gets exactly its declared height — and the
  two-line splits are verified for real names, but no window has painted one.
  Watch for the text block feeling cramped at zoom 96, and whether
  bottom-aligning the image reads better than top.
- **Houdini must be restarted to see any of it.** The panel's `ui.*` modules
  are already imported; recreating the pane tab reuses the old code.
- **B1 is 18 of a few hundred.** VaultCache has **four more top-level folders**
  beyond `Plants`. `Maya/assets` is ~70 folders and much messier — vendor names
  are inconsistent there in a way Megascans is not, so expect the batch
  window's per-row overrides to earn their keep.
- The 17 Plants went in as `vegetation/grass`, which needed **set all** because
  `detect_type` says `scan` — `vegetation.primary_ext` is SpeedTree-only and
  knows nothing about `.fbx`. That mismatch is unresolved: either widen
  `vegetation.primary_ext` (which changes *detection* for model/scan/vegetation
  alike) or accept setting it by hand every batch.
- Gotcha **16 wants widening**. It describes the `AllEditTriggers` case; the
  same cause bit again through `setCurrentIndex` in `_context_menu`. Two doors,
  one bug.
- `tools\budget.bat` **hung** this session on the `pause` that has been sitting
  in *Open bugs* since 2026-09-11. No longer theoretical.

**Next.** Import the rest of VaultCache — four folders, same window, and it is
the source the adapter is best at.

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
