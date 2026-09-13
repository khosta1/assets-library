# Assets Library

A standalone 3D asset catalog and library manager in Python 3.11 + PySide6, at
`H:/Code/Assets_library`. It imports a large personal library of 3D assets —
textures, models, HDRIs, IES profiles, VDBs, HDAs, scans — into a **strictly
structured, self-owned hierarchy**, and will later feed them into DCCs
(Houdini/Karma first, then Maya, Blender, Unreal). The app is standalone, every
asset package is standalone, and the whole folder is portable: code, bundled
runtime and library travel together on an external disk.

## Read this first

**`docs/architecture.md` is the source of truth.** It describes the joins
between the layers, marks design rules **RULE**, and ends with the
**invariants** every change is checked against. Do not duplicate it here.

| doc | subject |
|---|---|
| `docs/architecture.md` | the map + the invariants — **read before touching anything** |
| `docs/decisions.md` | what was decided and why, and the **central decision that must not be reopened** |
| `docs/gotchas.md` | twenty-one traps that each cost an hour once |
| `docs/features.md` | what is LIVE / DORMANT / VESTIGIAL / REMOVED |
| `docs/History/` | removed code and why — the CLI, the original draft |
| `docs/machine.md` | paths, Houdini versions, disks — the only machine-specific file |
| `docs/journal.md` | one dated entry per session |
| `docs/sources.md` | vendor conventions and the formats they ship |
| `docs/porting.md` | **how to run a bulk import** — `port.py`, the procedure, the traps |
| `docs/tools.md` | **what a tool must look like** to be imported, tagged and launched — written for the tool's author |
| `ROADMAP.md` | what is being built next, and the open bugs |

## The code

12 368 lines. `ui/` and `houdini/` import `assetlib`;
**`assetlib` imports no Qt and no `hou`** — that rule is what lets Houdini's
own interpreter import the core directly.

| file | role |
|---|---|
| `assetlib/config.py` | loads `config/*.json`, strips `_note` keys, owns paths |
| `assetlib/naming.py` | `normalise()`, `split_lod()`, `unique_name()`, `guess_category()` |
| `assetlib/slots.py` | `SlotMatcher` — the **only** place that guesses about textures |
| `assetlib/hashing.py` | xxh3 with blake2b fallback, algorithm-aware verification |
| `assetlib/analyse.py` | source files → `ImportPlan` (READ-ONLY), rebind, set_lod |
| `assetlib/commit.py` | `ImportPlan` → new package; `bind()`, `_promote_hero_lod()` |
| `assetlib/edit.py` | mutate an existing package; `delete_asset()` |
| `assetlib/model.py` | `asset.json` (schema v4), `migrate()`, `roles()`, `iter_assets()` |
| `assetlib/upgrade.py` | brings every `asset.json` **on disk** up to schema; `.assetlib/state.json` marks the version last fully applied |
| `assetlib/index.py` | SQLite + FTS5, search filters, counts |
| `assetlib/verify.py` | invariant checks |
| `assetlib/remote.py` | HTTP client for a server — **stdlib `urllib`, no Qt** |
| `assetlib/sync.py` | push this library onto the master over SMB — diffs by **uuid**, never deletes |
| `assetlib/catalog.py` | syncs a remote catalogue into `.assetlib/remote/<host>.db` |
| `assetlib/materialise.py` | download an asset into `_cache/` — **never imports `commit.py`** |
| `assetlib/deploy.py` | what travels when a new library copy is made |
| `assetlib/shortcut.py` | Desktop shortcut, written via `wscript.exe` |
| `assetlib/thumbnail.py` | `.hdr`/`.exr` decoding + tonemap → icons |
| `ui/app.py` | the browser: sidebar, grid, search, Library menu |
| `ui/batch_add.py` | import a folder of assets — one row per subfolder |
| `ui/import_houdini.py` | the Import-to-Houdini options — **the decisions live here, not in Houdini** |
| `ui/theme.py` | the one place that decides a colour; dark is forced |
| `ui/add_asset.py` | the Add window — drop zones, plan table, per-row overrides |
| `ui/edit_asset.py` | subclasses `AddAssetDialog` so the two cannot drift |
| `ui/asset_view.py` | "Contents" — every file labelled by its ROLE |
| `ui/gridmodel.py`, `ui/thumbcache.py`, `ui/writepool.py` | grid model + tile delegate, preview cache, single-threaded write pool |
| `ui/netpool.py` | the 3 threads that talk to a server, and the shutdown that must not hang (gotcha 18) |
| `ui/remote_libraries.py`, `ui/import_remote.py` | declare a server; download one asset |
| `ui/sync_server.py` | the Push window — what a push would change, then the copy |
| `ui/first_run.py`, `ui/new_library.py` | setup on a fresh copy; make a fresh copy |
| `houdini/` | the adapter — one package file to install; `build.py` makes Karma/MTLX/Solaris nodes. See `houdini/README.md` |
| `config/*.json` | the tree, 18 types, 114 categories, 20 texture slots — **data, not code** |

## Run

```
Asset Library.vbs            double-click: no console, log to launch.log
runtime\python.exe -m ui.app  console run, for watching output live
                              (python.exe, not pythonw - the .vbs uses pythonw
                              so no console can ever appear)
```

No install, no pip, no system Python: it runs the bundled `runtime\python.exe -m
ui.app`. There is **no command line** — everything the old CLI did is in the
window (see `docs/History/cli-removed.md`).

**Who builds:** there is nothing to build. The cheapest verifier here is
`runtime\python.exe -m compileall assetlib ui`, which catches syntax and import
errors before the window opens. It is not a test: **Felix runs the app and
observes the behaviour.**

## Data

`library/{type}/{category}/{asset}/` — three levels, always, tool-owned.
`asset.json` inside each package is **truth**; `.assetlib/index.db` is a cache,
rebuildable at any time with F5. `library/`, `_inbox/`, `_quarantine/`,
`.assetlib/` and `runtime/` are gitignored — but `runtime/` **must** travel on
the external disk, or nothing launches.

## Tools

```
tools\pack.bat --list        context packs (packs.json) -> context\*.md
tools\codemap.bat            structural map -> docs\codemap.html
tools\stale.bat              docs older than the code they cover
tools\recall.bat <query>     search past sessions
tools\shot.bat "Asset"       screenshot the window -> .claude\shots\
tools\budget.bat             what each doc costs
```

Everything they write is generated and gitignored. The scripts are a copy of
`H:\Code\AI_base_workflow`; `tools\update-tools.bat` re-copies when asked.

**Checking an API.** Before writing a PySide6, Pillow, OpenEXR or USD call, ask
**context7** for that library's current documentation rather than recalling it.
Pinned versions: Python 3.11, PySide6 6.11.2, Pillow 12.3.0, numpy 2.4.6,
OpenEXR 3.4.14, xxhash 4.0.1.

## Rituals

```
/handoff     close the session: journal entry + roadmap
/decide      record a decision, its reasoning, what it rejects
/gotcha      record a trap, dated and numbered
/retire      remove code properly: argument -> History/, line -> features.md
/invariants  check the current change against architecture §invariants
/pack /map /stale /recall    regenerate, and judge what comes back
```

## How to work here

- **`plan` at the end of a request means plan only.** Write the approach, change
  nothing — no edits, no commits. Reading and searching to build the plan is
  fine. Absent the word, work as normal.
- **`short` at the end of a request means ultra concise.** Answer in the fewest
  words that carry the answer — no preamble, no restatement, no options. Absent
  the word, answer as normal.
- **`ask` at the end of a request means decide nothing alone.** Collect every
  open question the request leaves — everything that would otherwise be settled
  by assumption — and put them to Felix as one multiple-choice block, each
  question carrying its candidate answers. Ask them together, once, before any
  work; do not proceed on a default while a question is still pending. Absent
  the word, make the routine calls yourself.
- **No verification loops.** Do not write or run a test, a benchmark or a probe
  script without asking first. One pass, one report; Felix observes the app.
- **Check `docs/gotchas.md` before debugging an import.** Twenty-one of them
  are already written down, and they are the expensive ones.
- **Check `docs/decisions.md` before proposing a design.** The central decision
  — the library is prescriptive, not adaptive — has already been challenged
  once and settled.
- **Check the change against the invariants** in `docs/architecture.md` before
  presenting it as finished.
- **Comments argue.** They say why a decision was taken and what failed before.
  Those are never compressed.
- **Caveman for WHAT, prose for WHY.** A comment that only describes drops
  articles, copulas, pronouns and hedges — `# decode: shared pool. write: own
  pool, 1 thread.` A comment that gives a reason stays full prose. Exempt:
  everything in `docs/`, and every user-facing string. New and touched code
  only, never a retroactive sweep. `docs/decisions.md`.
- Language: English everywhere — prose, code, comments.
