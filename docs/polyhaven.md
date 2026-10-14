# Fetching from Poly Haven

How assets get from Poly Haven's API into `_inbox/`, ready for `port.py`.
Written **2026-10-14** during the first run — *Ground & Terrain*, 147 textures.
It is a procedure: an agent should be able to repeat it for another category
without re-deriving anything. Importing what was fetched is `docs/porting.md`;
this document stops at the door of `_inbox/`.

---

## What Poly Haven offers

A public API at `https://api.polyhaven.com`, free, and every asset is **CC0**:
no attribution, commercial use allowed. On 2026-10-14 it listed **2 387
assets — 997 HDRIs, 869 textures, 521 models**.

| endpoint | gives |
|---|---|
| `/assets?type=textures&category=ground-terrain` | every asset in a category, with name, tags, description, `category` path, `dimensions` (mm), `max_resolution`, `thumbnail_url` |
| `/files/<slug>` | every downloadable file by map → resolution → format, each with `url`, `size`, `md5` |
| `/taxonomy/<type>` | the category tree; `slugPath` is what `category=` takes |
| `/info/<slug>` | one asset's metadata (the list already carries it) |

**What the terms ask of us** (`Public-API/ToS.md`):

- every call names the software in its **User-Agent** (§2.4);
- nothing that degrades the API (§2.6) — hence one connection, serial;
- the "Powered by Poly Haven" credit applies to apps that show **live** API
  content. Downloaded CC0 assets need nothing, ever (§2.5).

The real cost to them is bandwidth, not requests: Ground & Terrain was ~40 GB.
Poly Haven runs on donations; giving back is a choice, not a condition.

---

## What to fetch, and what not

Map keys as `/files` names them, decided 2026-10-14:

| map | fetched? | why |
|---|---|---|
| `diff` `nor_gl` `rough` `ao` `disp` | yes | the surface |
| `spec` `bump` | yes | own slots (mud family ships them) |
| `ref` | yes | matches no slot, lands in `extra/` — kept, not interpreted |
| `nor_dx` | **no** | the library stores OpenGL normals only; it would be rejected |
| `arm` | **no** | packed AO/rough/metal; the unpacked maps are there and win anyway |
| `rough_ao` | **no** | roughness × AO in one image, shipped beside both — see trap below |
| `rough_diff` | **no** | a second roughness-derived map, same trap (`rocks_ground_05`) |
| `col` `height` | yes | the older naming of base colour and displacement (`rocks_ground_02`, `snow_field_aerial`); `col` needed a keyword — porting trap 9 |
| `sss` `mask` | yes | translucency on snow, opacity on grass |
| `blend` `gltf` `mtlx` | **no** | sidecars naming the original files, which the import renames |

- **Resolutions: 1k, 4k, 8k** (Felix). The library keeps several sizes per slot
  and binds the biggest (invariant 13). 34 of the 147 go to 16k on Poly Haven;
  8k is the ceiling we took.
- **Format: the first of jpg → png → exr** each map offers. Displacement is
  therefore 8-bit jpg — accepted for now; revisit if a render shows stepping.
- **Thumbnail:** `thumbnail_url` re-asked at 512 px png, saved as
  `<slug>_thumb.png`. `thumb` is a `preview_stems` token, so it becomes
  `preview/thumb.jpg` at import with no rule added.
- **Already in the library:** skipped by folder name before anything is
  fetched (`mud_forest`, `rocky_terrain_02` on this run).

**Trap — `rough_ao`.** Fifteen aerial assets and two coral ones ship it. The
matcher tries slots in config order and roughness comes before AO, so it
competes with `rough` for the roughness slot; `_settle_competing` breaks the tie
alphabetically, where a shared prefix means the **longer** stem wins. The baked
product would have taken the slot and the real roughness gone to `extra/` —
porting trap 3's shape exactly. Dropped at download rather than with a slot
rule: one vendor, and porting trap 5 says a rule waits for the second example.

---

## Where it lands

```
_inbox/
  polyhaven-download.log                  progress, one line per asset
  polyhaven/
    ground-terrain/                       the port.py root: one folder per asset
      brick_gravel/
        brick_gravel_diff_1k.jpg ... _8k.jpg
        brick_gravel_thumb.png
    ground-terrain.meta.json              the /assets response + in_library flag
```

The meta file sits **beside** the root, not in it: `port.py plan` reads every
folder in the root as an asset.

---

## The downloader

```
runtime\python.exe fetch_polyhaven.py textures ground-terrain > _inbox\polyhaven-download.log
```

`fetch_polyhaven.py`, beside `port.py`. A **fetcher**, not a front-end
(`decisions.md`, Reversed, 2026-10-14): it writes only into `_inbox/`, imports
nothing from `assetlib`, and declares nothing. The category is Poly Haven's
`slugPath` (`ground-terrain`, or one level down: `ground-terrain/sand`).
`textures` only — HDRIs and models get their own rules before it accepts them.
Ground & Terrain itself ran from a scratchpad copy before it moved here.

- stdlib `urllib` only, so `runtime\python.exe` runs it;
- `/assets?type=…&category=…` once, then `/files/<slug>` per asset;
- **serial**: one file at a time, never parallel; 1 s pause between assets;
- User-Agent `AssetsLibrary/1.0 (personal asset library, CC0 port)`;
- every file checked against its `md5`, written to `.part` and renamed, so a
  cut download never looks complete;
- **resumable**: a file already on disk with the right size and md5 is skipped,
  so a rerun after a stop costs one `/files` call per finished asset and no
  bytes;
- three attempts per file, 5 / 10 / 15 s apart.

Measured: ~6–7 MB/s on one stream, 225–330 MB per asset at 1k + 4k + 8k jpg,
**~40 GB and ~2 h** for Ground & Terrain.

---

## Declarations

`port-declarations-polyhaven.json` at the repo root, generated from the meta
file: `type: texture`, category from **Poly Haven's second level** through this
table. Felix confirmed every row as is (2026-10-14).

| Poly Haven | library |
|---|---|
| Forest Floor | `forest_floor` |
| Grass & Vegetation | `grass` |
| Gravel & Pebbles | `gravel` |
| Regolith | `regolith` |
| Rocky Ground | `rocky_ground` |
| Sand | `sand` |
| Snow | `snow` |
| Soil & Mud | `dirt` |

Five categories were added to `categories.json` for this (`forest_floor`,
`gravel`, `regolith`, `rocky_ground`, `sand`); `dirt`, `grass` and `snow` were
reused rather than doubled. All eight sit under the `ground_and_terrain`
**sidebar group** — a heading, never a folder (`decisions.md`).

The vendor's category is a pre-fill like any other: **a person confirms the
declarations before `port.py plan`**. Another Poly Haven category means another
table, and any category it needs is added to the closed vocabulary by Felix.

---

## Laya — tried, shelved

Laya (Convai's choice model, installed in `H:/Code/laya_benchmark_test/.venv`)
gave a second opinion once, reading name + tags + description and never Poly
Haven's category: **112 / 147 agreed (76%)**; at confidence ≥ 0.5 it covered
86 assets at **91%**. `rocky_ground` absorbed 25 of its 35 disagreements.

Not used here — Poly Haven's categories are human labels and beat it. Kept
**as a tool for sources with no categories** (VaultCache, own folders), where it
would be the only pre-fill, and still only a pre-fill. It runs in its own venv
and the library never imports it: torch is not in `runtime/`, and `runtime/`
cannot ship a new dependency.

---

## Then

1. **Port** — `docs/porting.md`. A sample can start on folders whose download
   has finished while the rest is still arriving; never on the folder being
   written.
2. **`verify`**, warnings read by class.
3. **Delete `_inbox/polyhaven/<category>/`** once verify is clean (Felix,
   2026-10-14). `origin.source` in each `asset.json` keeps the path as
   provenance.
4. **Push to the server** is its own step, asked for by name. The box's config
   must have the new categories first, or its `verify` flags every asset.

## The first run, 2026-10-14

Ground & Terrain: **147 fetched (28 GB on the wire, 33 GB on disk), 147
imported, 0 failed**, 32.6 GB kept in `library/texture/{8 categories}/`.
Sampled first — one per category plus the aerial, spec + bump and `ref`
sets — which found traps 8 (`rough_diff`) and 9 (`_col`) before the loop.
Deep `verify`: **0 errors on the 147**; its only warnings on them were
Karma's `.jpg.rat` beside three samples already rendered in Houdini (porting
trap 6). `_inbox/polyhaven/` deleted after.

## Not fetched yet

The rest of the textures (720), the HDRIs (997 — type `hdri`, its own
categories) and the models (521 — a format choice among `fbx`, `usd`, `gltf`).
Each needs its own category table before anything is downloaded.
