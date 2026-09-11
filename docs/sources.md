# Sources

What the import pipeline was built against. Most of it is not papers but
**vendor reality**: the naming schemes real asset packs actually ship with,
which is what `config/texture_slots.json` and `config/types.json` encode.

---

## Vendor conventions the matcher is tested against

**ambientCG** — `Concrete014_8K-PNG_Color.png`, `_NormalGL`, `_NormalDX`,
`_Roughness`, `_Displacement`. Ships a bare-stem preview render
(`Concrete014.png`) and a ~2.5 KB `.usdc` sidecar. Both caused gotchas 3 and 1.

**Poly Haven** — `rock_wall_02_diff_8k.jpg`, `_nor_gl_`, `_rough_`, `_ao_`.
The `_diff_` form is why gotcha 2 exists: it was missing from the diffuse
keywords and basecolors fell through unmatched.

**Quixel / Megascans** — LOD tokens in the filename (`_LOD0`…`_LOD3`),
multi-format delivery of the same slot, `.mtlx` sidecars. The source of the
"LOD is a dimension, not part of the name" rule.

**RenderMan `.rma` bundles** — contain their own `asset.json`. Gotcha 6.

---

## Formats

**OpenGL vs DirectX normal maps** — an exact green-channel inversion. Storing
only the GL form and flipping on demand saves ~372 MB on one 8K ambientCG
asset; a DX-only source is converted at import so the library stays uniform.

**OpenEXR / Radiance HDR** — linear float. Tonemapping for thumbnails needs
exposure from a high percentile, and the decoder subsamples while reading
because an 8K HDR is ~400 MB as float32. Gotcha 11.

**UDIM tiles** — `.<1001>.` in the filename, preserved through renaming.

**xxHash (xxh3)** — chosen over SHA-256 for content hashing: ~10× faster, and
this is duplicate detection rather than security. `blake2b` from the stdlib is
the fallback, and the digest carries its algorithm as a prefix (gotcha 8).

**USD** — the intended format for `derived/`. Vendor `.mtlx`/`.usdc` are
discarded at import because they reference the original filenames; ours are to
be generated after the rename.

---

## Looked at and not used

**Reading the FBX's internal texture paths** — routinely absolute, stale or
simply wrong. `asset.json` owns the texture→slot binding instead.

**A vendor-agnostic "material schema" library** — every candidate assumes it
owns the folder layout, which is exactly the decision this project has already
taken for itself. See `docs/decisions.md`.
