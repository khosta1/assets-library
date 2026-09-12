# The client contract

What the app has to implement to use the cloud library, and the decisions that
constrain it. The server half (`server/`) is written and compiles; this is the
other half.

Decisions were taken on **2026-09-12** and are recorded in the server panel's
`docs/decisions.md`. The three that shape everything here:

- **The box is the single master.** `/srv/data2/assets/library/` is *the*
  library.
- **The API is read-only.** Assets enter over SMB on the LAN, through this app.
- **HTTP, not a mounted share**, for everything remote.

---

## What that means for `H:`

`H:/Code/Assets_library/library/` **stops being a library.** It becomes a
cache of assets pulled down from the box.

- Materialise imports into a new root, `_cache/{type}/{category}/{asset}/` —
  same three levels, same package layout, so `houdini/build.py` reads it
  without being told anything.
- **Keep the uuid.** A materialised asset is the same asset, not a new one.
  This is the whole point of a single master: an asset has one identity
  everywhere, and `_cache/` is a copy, not a fork.
- `library/` on the PC ends up empty and can be dropped from the config once
  the existing assets are seeded onto the box. **Seeded 2026-09-12: 75
  packages, 1 039 files, 38.3 GB.** (An earlier draft of this file said 58 —
  that number predated the Plants batch.)

The obvious shortcut — import the downloaded package through the normal commit
path — is the one to avoid: `Asset.new()` mints a fresh uuid and the copy stops
being the same asset.

---

## Endpoints

Base `http://10.209.73.177:8083`, every request carrying
`Authorization: Bearer <token>`. Everything is `GET`; errors are JSON.

| route | returns |
|---|---|
| `/api/health` | `assets`, `indexed_at`, `free_bytes` |
| `/api/catalog` | `{etag, count, assets:[index rows]}` |
| `/api/asset/<uuid>` | `{asset: asset.json, files:[{path,size,hash}], bytes}` |
| `/api/thumb/<uuid>` | `preview/thumb.jpg` |
| `/api/file/<uuid>/<relpath>` | one file, Range-capable |

`files[]` excludes `derived/` — it is regenerable and never transferred.

---

## The three tiers

Keeping these apart is the design; collapsing them is how it becomes slow.

**1. Catalogue.** `GET /api/catalog`, store the rows in a *second* SQLite at
`.assetlib/remote/<host>.db` with the same schema `index.py` already creates.
Send `If-None-Match: <etag>` and honour the 304. Search then runs locally
against local ∪ remote — **no network call per keystroke**, and browsing keeps
working when the box is asleep, which matters because Wake-on-LAN does not
reach it from outside the LAN.

**2. Thumbnails.** `GET /api/thumb/<uuid>`, lazily, only for visible tiles,
cached at `.assetlib/remote/thumbs/<uuid>.jpg` and never re-fetched — the
server sends a week of `max-age` and the uuid is a safe cache key. Feed them
through the existing `thumbcache` / `writepool` rather than a second mechanism.

**3. Files.** Only on an explicit import. `GET /api/asset/<uuid>` for the
manifest, then one `GET /api/file/...` per entry:

- Write to `<name>.part` and use `Range: bytes=<got>-` to resume. The server
  supports it; a 1 GB asset over a relayed ZeroTier link is ~17 minutes and
  will be interrupted eventually.
- Verify against `files[].hash` with `assetlib.hashing` — the hashes come
  straight out of `asset.json`, so this is free integrity checking.
- Two or three concurrent files is the useful amount. More just splits the
  same link.
- Offer **hero LOD + one resolution** as well as the whole package. On a
  Megascans asset that is the difference between 40 MB and 1 GB, and it is the
  single thing that decides whether remote use is pleasant.

---

## UI

- A cloud badge on remote tiles, and a third state for *cached locally* — the
  user needs to know what a double-click will cost before it costs it.
- Show `bytes` from `/api/asset` before starting an import.
- When the box is unreachable, remote assets stay **visible and browsable**
  from the cached catalogue, just not importable. Hiding them would make the
  library look like it lost half its contents every time the box sleeps.
- A *refresh catalogue* action: re-fetch `/api/catalog`. If it comes back
  unchanged after an import, the box has not re-indexed yet — `indexed_at` in
  `/api/health` is the thing to show.

---

## Importing INTO the cloud library

No upload route exists, by decision. The path is:

1. mount `\\192.168.1.13\data2`
2. point the library root at `…/assets/library`
3. **leave `roots.state` local** — an `index.db` on an SMB share hits the same
   WAL-needs-mmap problem that keeps the server's index off the NTFS disk
4. import as usual; then re-index on the box

Worth making that a named configuration in the app rather than something
retyped, because getting step 3 wrong corrupts an index rather than failing
loudly.

---

## Not yours to touch

`server/` is the server half and is deployed by hand to `/opt/assetlib`; it is
owned by the server-panel side of this work. Nothing in it requires a change to
`assetlib/` — the API deliberately reads the existing schema and adds no
column, so the two halves can be built at the same time without collision.
