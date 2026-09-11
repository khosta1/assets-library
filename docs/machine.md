# Machine facts

**WILL DIFFER on another computer.** Nothing outside this file should assume
any of it.

Last checked: **2026-09-11**, on the `felix` Windows 11 machine.

---

## Paths

```
project root      H:/Code/Assets_library
source library    H:/3D/Maya/assets          (priority: its texture/ subfolder)
debug data        H:/Code/Assets_library/Concrete/
```

Every path the app resolves is relative: `config/library.json` roots are
relative, `find_config()` walks up from `assetlib/` to locate the library,
`index.db` stores asset paths relative to `library/`, and `run_ui.bat` does
`cd /d "%~dp0"`. **The drive letter is irrelevant** — that is what makes the
folder portable.

The one absolute path anywhere is `origin.source` in `asset.json`, recording
where an asset came from. That is provenance, not a reference: nothing resolves
it, so a stale value is harmless.

### The source library, as found

`H:/3D/Maya/assets` top level: `AOVS HDA HDRIs IES LookDEV STUDIO VDB lighties
model paper texture`. Its `texture/` subfolder: `Cloth Concrete Dirts Grass
Rocks SUBdesigner Snow damagematerial decalsdamage floors foliage imperfection
metals plaster wood imagesprops`. Those folder names seeded the `texture`
category list in `categories.json`.

Other fragments scattered elsewhere: `H:/3D/HOUDINI/megascantest`,
`H:/download/uploads_files_3376288_Textures`, `H:/3DHome/Scan/Textures`,
`G:/3d/blender/Texture`, `H:/3D/Insect/Texture`.

⚠ **`J:/3d` appears to be a FreeFileSync mirror of `H:/3D`** (there is a
`sync.ffs_db`), so much of the source data exists **twice**. Content-hash dedup
will matter during the bulk migration.

---

## Toolchain

| tool | version | where |
|---|---|---|
| Python (bundled) | 3.11.9 | `runtime\python.exe` |
| PySide6 | 6.11.2 | bundled |
| Pillow | 12.3.0 | bundled |
| numpy | 2.4.6 | bundled |
| OpenEXR | 3.4.14 | bundled |
| xxhash | 4.0.1 | bundled |
| Houdini | 20.5.684, 21.0.512, 22.0.368 | installed |

Houdini's bundled Pythons: 20.5 → 3.7/3.9/3.11, 21.0 → 3.7/3.9/3.11, 22.0 →
3.10/3.11/3.13. **3.11 is the only version all three share** — which is why the
project pins it; the reason lives in `docs/decisions.md`.

Outside the bundled runtime: `pip install PySide6 Pillow numpy openexr xxhash`.
Only PySide6 and Pillow are truly required — without numpy/OpenEXR you lose HDR
and EXR thumbnails, and xxhash falls back to blake2b.

---

## Disks

```
H:  1.9 TB, ~208 GB free   - the project, the source library
C:  ~22 GB free            - system only; nothing here belongs on it
```

---

## Moving the whole thing on an external disk

**Copy the project folder wholesale, `runtime/` included.**

- `.gitignore` excludes `runtime/` — that means *do not version it*, NOT *do
  not copy it*. Without `runtime/` nothing launches.
- Skip `__pycache__/`. `.assetlib/index.db` travels fine and is rebuildable
  (F5).
- Filesystem: **NTFS**, or **exFAT** if it must also be read on Mac/Linux.
  **Not FAT32** — its 4 GB per-file limit will be hit by VDB caches and EXR
  sequences.
- After plugging the disk into a new machine, run Library ▸ Verify once.
