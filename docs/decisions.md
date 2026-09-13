# Decisions

Every choice an agent — or a future Felix — could plausibly re-propose, with
the reasoning that settled it.

Split out of `CONTEXT.md` §2–§3 on **2026-09-11**.

---

## The central decision

> **The library is prescriptive, not adaptive. It builds and owns its own
> hierarchy. Source folder layout is read for information and then discarded.**

An explicit choice by Felix, made **after an alternative was proposed and
rejected**. It is the decision every other one hangs off. Do not re-open it:

- ❌ **Do NOT build a read-only browser over existing folders.** This was
  proposed and rejected. `H:/3D/Maya/assets` is a **source to import from**,
  not a library to display.
- ❌ **Do NOT make the library adapt to how source assets were organised.**
- ❌ **Do NOT mirror the source tree.**
- ✅ The tool creates every folder and names every file inside `library/`.

Two decisions taken later sharpen it:

> **The user declares what an asset IS; the tool decides where its files go.**

Type, category and name are typed into the Add window — never inferred and
silently committed. What the tool automates is the tedious half: which image is
the basecolor, which format wins, what everything must be renamed to. Every one
of those appears as a row that can be overridden.

> **Disk is truth, database is a cache.**

`asset.json` is authoritative; `.assetlib/index.db` is derived and rebuildable
(F5). The library stays readable, portable and hand-editable without the tool.

---

## Locked, with the reasoning

| Decision | Why |
|---|---|
| **Python** for everything | The only language that runs inside Houdini/Maya/Blender/Nuke. USD has first-class bindings. Felix already knows it. |
| **Python 3.11**, and the app ships its own | The only version shared by Houdini 20.5, 21.0 and 22.0, so `assetlib` stays importable by `hou`. Bundling it also makes the whole folder run anywhere. Avoid 3.12+ syntax. |
| **PySide6** | The same widgets run standalone, as a Houdini python panel, or docked in Maya. |
| **`assetlib` imports no Qt and no `hou`** | The arrow direction is the whole discipline. `ui/` depends on `assetlib`, never the reverse. Breaking it breaks headless use and DCC embedding. |
| **GUI-first, no CLI** | The CLI existed to force the core to stay UI-free; that job is done and the discipline is now enforced by the import rule above. See `docs/History/cli-removed.md`. |
| **Three-level tree, always** | `library/{type}/{category}/{asset}/`. No deeper nesting, no per-type exceptions. |
| **ONE category folder level, the rest are tags** | Deep taxonomies calcify and every asset eventually belongs in two places. The category is also in `asset.json`, so restructuring later is a command, not a weekend. |
| **Closed category vocabulary** | Only a category listed in `categories.json` can be assigned, so the tree cannot sprawl on its own. |
| **`lower_snake` names** | Windows is case-insensitive, Linux is not. The day this library is read from the Rocky box, `Concrete014` and `concrete014` become two assets. |
| **Strip resolution/format tokens from names** | `Concrete014_8K-PNG` → `concrete014`, so a future 4K version resolves to the SAME name and merges as a variant. Resolution lives in metadata as a searchable field. |
| **LOD is a dimension, not part of the name** | Four levels are ONE asset. The token is stripped wherever a vendor put it, so all 25 files of a 4-LOD asset agree on one name, and are re-emitted as `_lodN`. |
| **Types are DATA, not code** | 18 types in `types.json`. Adding SpeedTree/Marvelous/GAEA support = editing JSON. Only the *precedence between types* is code. |
| **Five ingest strategies only** | `mesh_plus_textures`, `texture_set`, `single_file`, `sequence`, `folder_blob`. |
| **Nothing is discarded — unknown files become bonus files** | Anything the library cannot interpret lands verbatim in `extra/` rather than being dropped. The user decides, not the tool. |
| **Normalise texture filenames to slot names at import** | ambientCG `_Color.png` and Poly Haven `_diff_8k.jpg` both become `<asset>_basecolor.png`. **The guessing happens ONCE, at import.** Every adapter afterwards reads a fixed layout with zero heuristics. This is the entire payoff of an owned hierarchy. |
| **`asset.json` owns the texture→slot binding, not the FBX** | FBX-internal texture paths are routinely absolute, stale or wrong. Never trust them. |
| **Store OpenGL normals only** | DirectX is an exact green-channel inversion, regenerated on demand. Saves ~372 MB on one 8K ambientCG asset. A DX-only source is converted at import so the library stays uniform. |
| **One file per slot, per LOD, per resolution** | When a slot ships in several formats, `format_priority` picks the winner. The loser is **reported, never silently deleted**. Several *sizes* of one map are not a contest: all are kept (2026-09-12). |
| **USD is optional and derived** | Format-agnostic packages. Vendor `.mtlx`/`.usdc` are **discarded** at import because they reference the original filenames and break the moment we rename — we generate our own into `derived/`. |
| **`xxh3` hashing, not SHA-256** | 10× faster, and this is duplicate detection, not security. Falls back to stdlib `blake2b`; the prefix stops cross-algorithm comparison (gotcha 8). |
| **Nothing is auto-deleted** | Deletions are always an explicit, confirmed action with the file list shown first. |
| **`.vbs` launcher, not `.bat`** | Windows gives every batch file a console window, which flashes on screen even when the batch starts `pythonw.exe`. A script host process gets no console at all. |
| **`python.exe`, not `pythonw.exe`**, inside that launcher | `pythonw` discards stderr, so a crash would leave nothing to look at. Instead the console is never shown (Run window style 0) and output is redirected to `launch.log` — silent when all is well, diagnosable when it is not. |
| **Do not copy a venv onto the disk** | Venvs hardcode absolute paths. The bundled `runtime/` is a full Python, which does not. |
| **Git, and one folder = one repo** | Added 2026-09-11. The code existed in exactly one place, on a disk with no backup. `library/`, `runtime/` and `.assetlib/` stay out of it — they are data and are large. |
| **A variant is kept; a texture `variant` is discarded** | Added 2026-09-12. Two words, two opposite meanings. `variants` in `texture_slots.json` names something the library stores **one** of — normals are OpenGL-only. A geometry variant is a **second version of the asset that must be kept**: Megascans ships `DactylisGlomerata_hznoe_Big_lod0` and `_Small_lod0`, three levels each, sharing one texture set, and before this the Small lost the `(ext, lod)` contest and half the asset never imported. Detected from `variant_patterns` in `library.json` as a **pre-fill only** — the Var column in the Add window decides, because a token that looks like a variant but is part of the real name is a mistake a person catches at a glance and a pattern never will. |
| **Geometry routes on the extension, detection on the type** | Added 2026-09-12. `geometry_ext` in `types.json` says what lands in `geo/`, whatever the asset's type; each type's `primary_ext` says what makes that type *detectable*; `mesh_extensions()` additionally drops USD sidecars so a 2.5 KB `.usdc` cannot make a texture set look like a model. Three lists because there are three questions. Conflating the first two sent **every** `.fbx`, `.obj` and `.abc` in a `vegetation` asset to `extra/` — vegetation is declared by `.spm/.st/.st9/.srt` alone and knew nothing about mesh formats. |
| **Houdini 22+ only** | Added 2026-09-12, stated by Felix. Drops 20.5 and 21.0 as targets. 22 ships **PySide6**, the same binding `ui/` uses, so the PySide2 compatibility shim the old shelf tool needed is not written, and a Python Panel becomes possible rather than only a subprocess. **The 3.11 pin stays**: it is a floor, not a target — `assetlib` is written to 3.11 syntax and imported cleanly on the 3.13 build of 22.0.368, and the bundled `runtime/` is 3.11 regardless. Dropping the pin would buy 3.12+ syntax and cost the one property that made the first `import assetlib` inside Houdini work on the first try. |
| **The Houdini panel reads and builds; writing stays standalone** | Added 2026-09-12, measured not assumed. Houdini 22's interpreter has PySide6, Pillow, numpy and OpenEXR but **not xxhash**. Browsing and building need none of it; `commit.py` hashes every file and would silently fall back to stdlib `blake2b`, writing digests in a second algorithm into a library that is otherwise xxh3 — legal, since a digest carries its algorithm (gotcha 8), and pointless. Importing belongs in the standalone window regardless: that is where the plan table is. |
| **Dark is forced, not followed** | Added 2026-09-12. The content of this window is images and much of it is colour-critical — a basecolor being judged, an HDRI's exposure, a normal map checked for a green-channel mistake. Light chrome shifts how those read, which is why every DCC this library feeds ships dark. Following the OS would also make one library look different depending on which machine the external disk reaches, against the same portability the window title protects. One line in `main()`; every colour decision lives in `ui/theme.py`. No toggle, no preference file. |

---

## Comment register: caveman for WHAT, prose for WHY

Taken **2026-09-12**.

> **A comment that describes is written in caveman. A comment that argues is
> written in prose. The second kind is never compressed.**

Caveman drops articles, copulas, pronouns standing in for code, and hedges.
It keeps identifiers exact, numbers exact, and units:

```python
# CAVEMAN - describes. No argument in it to lose.
# decode: shared pool. write: own pool, 1 thread.
# analyse: read-only. commit: only writer.
# src ext -> slot via texture_slots.json, first match wins.

# PROSE - argues. Compressing this destroys the reason.
# Twenty 8K TIFFs occupy every thread for a minute, and a write job queued
# behind them never starts, so the progress dialog sits there forever and
# the signal that would close it never fires. That is gotcha 7.
```

**Why this and not caveman everywhere.** The descriptive half of a comment is
filler that survived because nobody charged it rent — it restates the line
below it and goes stale the moment that line changes. The arguing half is the
only thing in this repo that cannot be recovered by reading the code, and it is
what `docs/gotchas.md` exists to protect. Compressing both treats them as the
same material. They are not: one is worth 40 tokens, the other is worth an
afternoon.

**Exempt, always, and not by judgement call:**

- any comment giving a reason, a history, or a thing that failed before
- everything under `docs/` — those documents argue by definition
- user-facing strings: window text, tooltips, dialogs, status messages. Felix
  reads those while something is going wrong, not while studying the code.
- `asset.json` field names and config keys — data, not prose

**Not applied retroactively.** The convention governs new code and any comment
whose line is being touched anyway. A sweep over 5 050 lines would rewrite
hundreds of comments nobody asked about, and every one of those diffs is a
chance to delete an argument by mistake.

---

## Pushing onto the master

Taken **2026-09-13**, after the local library kept growing past the seed.

> **A push is a diff by uuid, not a mirror by path. It adds, updates and moves.
> It never deletes.**

The box is the master and its API is read-only, so the only way an asset gets
onto it is a file copy over SMB on the LAN. The tempting tool is
`robocopy /MIR`, and it is the wrong one for a reason that is structural rather
than a matter of flags: a path is not an identity here. Re-categorising an
asset changes `library/{type}/{category}/{asset}` while the asset stays the
same asset — same uuid, same `asset.json`. A mirror sees a new path and a
missing old one, and answers by re-uploading gigabytes and then deleting the
original.

Diffing by uuid turns the same edit into **a rename on the share**: zero bytes
on the wire for a 1 GB asset that moved from `rock/` to `ground/`. And it turns
"on the server, not on this disk" into a **report** instead of a deletion,
which is the half that matters — the library is 1.7 TB with no off-site copy,
and a local `library/` that someone tidied out must not be able to take the
master with it.

**Both sides are read from disk, not from an index.** `asset.json` is truth and
`index.db` is a cache (invariant 1); the box re-indexes daily, so a diff taken
against `/api/catalog` would be a diff against yesterday. Overwriting or
removing 38 GB on the strength of a stale row is not a trade worth making. The
cost is one `asset.json` read per package over SMB, and the `hashes` dict makes
the rest of the comparison free for everything that did not change.

**Removal exists, and it is deliberately not part of a sync.** One asset at a
time, admin only, the name typed to confirm, and it is a rename into `_trash/`
on the share rather than a delete. Invariant 7 applies with more force on the
master than anywhere else.

### Who may do it is decided by smbd, not by the app

> **Admin is an SMB account, not a setting. The app reads the permission; it
> never grants one.**

The alternative — a flag in `config/`, or a password the app checks — was
rejected for being a lie that looks like a lock. Anyone holding the folder can
edit a JSON file, and a portable library is *designed* to be held by whoever
has the disk. What the app would be enforcing is its own good manners.

So the gate is the share:

```ini
[assets]        read only = yes,  write list = felix     # the library
[assets-inbox]  read only = no                           # the drop box
```

`smbd` refuses a non-listed account at the protocol, before a syscall reaches
the disk, and no local setting changes that answer. `sync.probe()` writes a
temporary file into `library/` on the share to find out which side of that line
this account is on, and the window says so in words. Note that the unix
alternative — a sticky bit, so others may create but not delete — **cannot**
work here: the library sits on ntfs-3g, which has no per-file ownership, and
setting the bit succeeds while granting nothing (gotcha 19).

Contributors therefore add through a **drop box**: a second, writable share
that is not the library. Whoever promotes a package out of it decides the
library changed. "They can add but not delete" is then a share definition
rather than a rule this app is trusted to keep — and it keeps holding when the
app is not the thing doing the copying.

### What this supersedes

`server/client-contract.md` §"Importing INTO the cloud library" describes the
path as: mount the share, point the library root at it, import as usual, leave
`roots.state` local. That still works and is still the fastest way to put a
vendor dump straight onto the box. It is no longer the only way, and it is not
the one to use for a library that has already been imported locally — pointing
the root at the share does not move what is already under `library/`, and it
cannot express a move at all. `server/` is owned by the server-panel side, so
that file is left for them to amend.

---

## Rejected — do not reopen

| Idea | Why it was rejected | When |
|---|---|---|
| Letting the icon be found by scanning, since it already is | `install.json` declares `icon`, and the scan would find `manager_tool.png` anyway — `preview_stems` already treats a file named after the asset as its preview. So the field looks redundant, and is not: the scan works **only while the asset name and the file name agree**, and the asset name is typed by hand in the Add window. Rename either side and the asset loses its picture with nothing said. The declaration is what survives that. Same shape as `otls` and the shelf entries — the author states it, the library does not guess it. | 2026-09-13 |
| Flattening icon transparency onto white, or onto whatever Pillow leaves there | `convert("RGB")` does not composite: it drops the alpha channel and keeps whatever RGB the exporter wrote underneath, which no format guarantees. Measured on one image saved two ways — black underneath gave `(0,0,0)`, white underneath gave `(255,255,255)`, same alpha. So the output was decided by the exporter rather than by anyone, and the white case puts a bright square around a rounded icon on a forced-dark grid. Now composited onto `(58,58,58)`, matching `theme.tile_colour()` by value because `assetlib` holds no Qt and cannot ask. No ground is right for every case — a tile is also drawn selected, and blue when the asset is on a server — so this is the common case **chosen**, not inherited. | 2026-09-13 |
| A launch/install **script** shipped with each tool, which the library runs | Felix's own first sketch, and the generalisation is genuinely attractive: any tool, however odd, describes its own installation and the library needs no installer per application. Rejected on three grounds, the third decisive. It is the *adaptive* model the central decision rejects — the library doing whatever each asset tells it. It is also what already exists: `Main_ui.txt`, `corrupted_framecheck.shelf` and a 43 KB paste-header are four hand-maintained install shapes, every path-based one hardcoding `H:\3D\Maya\Scripts`, none surviving a copy — so it is the status quo rather than the fix. And assets arrive by **download** now: `materialise.py` pulls packages from the box, so a library that ran code an asset carried would make *downloading* an asset mean *running its code*. Kept instead: the asset **declares** in `install.json`, the library **executes** — invariant 15. | 2026-09-13 |
| Inferring `otls` from any `.hda` found in a tool | It looks like ordinary autodetect and it is a redistribution decision in disguise. Declaring a folder *installs* what is in it, and an asset syncs to the master at `/srv/data2` that other people read — so guessing would have taken 30 vendored third-party HDAs out of one tool's folder and served them from a shared box, silently, because an importer noticed a file extension. Whether a bundled `.hda` may be shared is its owner's call. Raised by the manager-tool session, who had the argument I had not made. `otls` is manifest-only; the files still travel, and the import says they are present but not on Houdini's path. | 2026-09-13 |
| The script asset carrying the whole tool repo, or a manifest naming folders outside itself | The `Manager_tool` adapter lives in `houdini/`, a sibling of the `suite/` that becomes the asset, so a library copy gets the launcher and not the bridge. Taking the repo drags `.claude/`, `docs/`, `ROADMAP.md` and `tools/` into `library/` — the same split `deploy.py` makes for this project, undone. Letting the manifest name folders outside itself means `..` in a manifest, and one that can climb out of its own folder can reach anywhere. Accepted instead: the asset carries `suite/` only, and the library route installs the launcher and all ten tools but not the outside-in `run_tool` bridge — which has a working user in place already. If the bridge ever has to travel, the shape is an `include: [...]` **allowlist** in a manifest at the repo root: no `..`, still descends only. | 2026-09-13 |
| A read-only browser over `H:/3D/Maya/assets`, leaving the folders as they are | It is the strong version of "do not make me reorganise 1.9 TB", and it loses the one thing that makes the rest possible: with source layout preserved, every downstream adapter must re-guess texture roles forever. Normalising once at import is what buys zero heuristics everywhere else. | before 2026-08-20 |
| Mirroring the source tree inside `library/` | Same objection, one step weaker: the tree would then encode how a vendor happened to zip a file. | before 2026-08-20 |
| ~~Keeping vendor `.mtlx` / `.usdc` sidecars~~ — **reversed 2026-09-13, see below** | They reference the original filenames, which are exactly what the import renames. They break at the moment of import and look like our bug. | 2026-08-20 |
| Storing both OpenGL and DirectX normals | DX is an exact green-channel inversion of GL. It is ~372 MB of duplicate data on a single 8K asset, to avoid a per-channel flip that takes milliseconds. | 2026-08-20 |
| SHA-256 for file digests | This is duplicate detection, not security. xxh3 is ~10× faster over terabytes. | 2026-08-20 |
| Shipping the app as a single frozen `.exe` (PyInstaller / Nuitka) | It is the obvious answer to "a beginner should be able to install this", and it breaks the seam the whole architecture is built on: `houdini/` puts `$ASSETLIB` on PYTHONPATH so Houdini's own interpreter does `import assetlib`, and a frozen bundle has no importable `assetlib/` on disk. The source would have to ship anyway, leaving a second copy of the app free to drift from the first. Practically also 150–250 MB, a visible unpack-to-temp on every launch, and SmartScreen on anything unsigned — worse friction for a beginner than the folder it replaces. What was built instead: a first-run setup panel, *Create a new library…*, and a Desktop shortcut. | 2026-09-13 |
| Two entries for one server, one per address (LAN and ZeroTier) | It looks like sensible redundancy and it corrupts a catalogue: the host name IS the database filename, so both map to `rocky.db`. They do not merge, they fight — each sync wipes the other's rows while keeping its own ETag, so the next sync gets a 304 and reports "unchanged" over a catalogue that was deleted. Now refused on save and de-duplicated on load. If one box ever genuinely needs two addresses, it is one host with a fallback URL list, not two hosts. | 2026-09-13 |
| `robocopy /MIR` to keep the server's library in step with this one | It is the tool everyone reaches for and it mirrors PATHS. A path is not an identity here: re-categorising an asset keeps its uuid and changes its path, so a mirror re-uploads gigabytes and then deletes the original — and an asset removed from this disk is deleted from the master, which holds the only copy of 1.7 TB. `assetlib/sync.py` diffs by uuid instead: a move becomes a rename on the share, and "missing here" becomes a line in a report. | 2026-09-13 |
| An app-side admin password or `config/` flag gating destructive edits | A lie that looks like a lock. Anyone holding the folder can edit a JSON file, and a portable library is designed to be held by whoever has the disk — the app would be enforcing its own good manners. The gate is Samba's `write list` on the box, which `smbd` applies before a syscall reaches the disk; `sync.probe()` only reads which side of it this account is on. | 2026-09-13 |
| A sticky bit (or POSIX ACLs) on the server's `library/`, so friends may add but not delete | The unix answer, and it cannot work on that disk: ntfs-3g maps the whole tree to one uid, so there is no per-file ownership for the bit to compare against. `chmod +t` succeeds and grants nothing — a gate that looks applied and is not (gotcha 19). Add-only is a second, writable share used as a drop box instead. | 2026-09-13 |
| An upload route on the API, so a push works from outside the LAN | Felix, asked directly: LAN/SMB is enough. It would reopen "the API is read-only", which is what keeps a token leak from being able to damage 1.7 TB that has no off-site copy. Reconsider only when pushing from outside the LAN is a real need, and reopen the decision in writing first. | 2026-09-13 |

---

## Reversed

| What changed | From → to | When and why |
|---|---|---|
| The interface | CLI + GUI → **GUI only** | 2026-08-21. The CLI's real job was forcing `assetlib` to stay UI-free; that discipline is now stated as an import rule and does not need a second front-end to prove it. `docs/History/cli-removed.md`. |
| Where the tool lives | "somewhere on H:" → its own git repo | 2026-09-11. |
| A command line | **none → one, `port.py`, for bulk porting only** | 2026-09-13. Felix asked for it so an agent can drive a 37-asset migration while he reads what each one did. The 2026-08-21 removal stands for everything else: the CLI's real job was forcing `assetlib` to stay UI-free, that is now an import rule, and every *decision* still belongs in the window. What this is allowed to be is narrow and the narrowness is the decision: it imports against a plan that already exists, it declares nothing itself — type and category come from `port-declarations.json`, authored by a person — it writes only with `--apply`, one asset per invocation, and it has five subcommands that must not become six. It contains no logic of its own; `analyse()` and `commit()` do the work, which is exactly what the old CLI stopped doing before it was removed. `apply` re-runs `analyse()` rather than replaying the plan, so what lands is always derived from the files that exist at that moment — the plan is a report, not an instruction set. If it ever grows a way to decide something, delete it. |
| Vendor `.mtlx` / `.usd` / `.usda` / `.usdc` / `.mtl` sidecars | **deleted at import → kept verbatim in `extra/`** | 2026-09-13. Felix: "I don't want .usdc and .mtlx discarded." The 2026-08-20 reasoning is not wrong and is not what changed — those files genuinely do reference filenames the import renames, and resolving one still hands an adapter missing textures. What changed is the conclusion drawn from it: *unusable* was treated as *worthless*, and deletion is the one outcome that cannot be undone later. It also stood as a silent exception to invariant 6, "nothing is discarded — what the library cannot interpret lands verbatim in `extra/`". They are kept **unbound**: nothing in `asset.json` points at one, so no adapter can load one by accident, and our own material is still regenerated into `derived/`. Routed **before** the geometry branch, because `.usd*` is in `geometry_ext` and would otherwise land in `geo/` and be bound — which is the original objection arriving through a different door. Texture-set planner only; beside a mesh a `.usd` is plausibly the asset itself and still goes to `geo/`. Config key renamed `discard_on_import` → `vendor_sidecars`, since a key that no longer discards must not still be called that. |
| Comment register | one register → **two: caveman for WHAT, prose for WHY** | 2026-09-12. Not a reversal of "comments argue" but a narrowing of it: the arguing comments are exempt from compression, so the rule that protects them is unchanged. What loses its articles is the descriptive filler that was never carrying a reason. |
