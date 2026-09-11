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
| **Types are DATA, not code** | 17 types in `types.json`. Adding SpeedTree/Marvelous/GAEA support = editing JSON. Only the *precedence between types* is code. |
| **Five ingest strategies only** | `mesh_plus_textures`, `texture_set`, `single_file`, `sequence`, `folder_blob`. |
| **Nothing is discarded — unknown files become bonus files** | Anything the library cannot interpret lands verbatim in `extra/` rather than being dropped. The user decides, not the tool. |
| **Normalise texture filenames to slot names at import** | ambientCG `_Color.png` and Poly Haven `_diff_8k.jpg` both become `<asset>_basecolor.png`. **The guessing happens ONCE, at import.** Every adapter afterwards reads a fixed layout with zero heuristics. This is the entire payoff of an owned hierarchy. |
| **`asset.json` owns the texture→slot binding, not the FBX** | FBX-internal texture paths are routinely absolute, stale or wrong. Never trust them. |
| **Store OpenGL normals only** | DirectX is an exact green-channel inversion, regenerated on demand. Saves ~372 MB on one 8K ambientCG asset. A DX-only source is converted at import so the library stays uniform. |
| **One file per slot, per LOD** | When a slot ships in several formats, `format_priority` picks the winner. The loser is **reported, never silently deleted**. |
| **USD is optional and derived** | Format-agnostic packages. Vendor `.mtlx`/`.usdc` are **discarded** at import because they reference the original filenames and break the moment we rename — we generate our own into `derived/`. |
| **`xxh3` hashing, not SHA-256** | 10× faster, and this is duplicate detection, not security. Falls back to stdlib `blake2b`; the prefix stops cross-algorithm comparison (gotcha 8). |
| **Nothing is auto-deleted** | Deletions are always an explicit, confirmed action with the file list shown first. |
| **`.vbs` launcher, not `.bat`** | Windows gives every batch file a console window, which flashes on screen even when the batch starts `pythonw.exe`. A script host process gets no console at all. |
| **`python.exe`, not `pythonw.exe`**, inside that launcher | `pythonw` discards stderr, so a crash would leave nothing to look at. Instead the console is never shown (Run window style 0) and output is redirected to `launch.log` — silent when all is well, diagnosable when it is not. |
| **Do not copy a venv onto the disk** | Venvs hardcode absolute paths. The bundled `runtime/` is a full Python, which does not. |
| **Git, and one folder = one repo** | Added 2026-09-11. The code existed in exactly one place, on a disk with no backup. `library/`, `runtime/` and `.assetlib/` stay out of it — they are data and are large. |
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

## Rejected — do not reopen

| Idea | Why it was rejected | When |
|---|---|---|
| A read-only browser over `H:/3D/Maya/assets`, leaving the folders as they are | It is the strong version of "do not make me reorganise 1.9 TB", and it loses the one thing that makes the rest possible: with source layout preserved, every downstream adapter must re-guess texture roles forever. Normalising once at import is what buys zero heuristics everywhere else. | before 2026-08-20 |
| Mirroring the source tree inside `library/` | Same objection, one step weaker: the tree would then encode how a vendor happened to zip a file. | before 2026-08-20 |
| Keeping vendor `.mtlx` / `.usdc` sidecars | They reference the original filenames, which are exactly what the import renames. They break at the moment of import and look like our bug. | 2026-08-20 |
| Storing both OpenGL and DirectX normals | DX is an exact green-channel inversion of GL. It is ~372 MB of duplicate data on a single 8K asset, to avoid a per-channel flip that takes milliseconds. | 2026-08-20 |
| SHA-256 for file digests | This is duplicate detection, not security. xxh3 is ~10× faster over terabytes. | 2026-08-20 |

---

## Reversed

| What changed | From → to | When and why |
|---|---|---|
| The interface | CLI + GUI → **GUI only** | 2026-08-21. The CLI's real job was forcing `assetlib` to stay UI-free; that discipline is now stated as an import rule and does not need a second front-end to prove it. `docs/History/cli-removed.md`. |
| Where the tool lives | "somewhere on H:" → its own git repo | 2026-09-11. |
| Comment register | one register → **two: caveman for WHAT, prose for WHY** | 2026-09-12. Not a reversal of "comments argue" but a narrowing of it: the arguing comments are exempt from compression, so the rule that protects them is unchanged. What loses its articles is the descriptive filler that was never carrying a reason. |
