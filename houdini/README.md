<!-- covers: houdini/** -->

# Houdini integration

State on **2026-09-12**: **P0 only.** The seam test and the browser launcher
exist. No node building is ported yet — see `ROADMAP.md` `A1`.

## Install — one file

Copy (or symlink) **one** file into Houdini's prefs:

```
houdini\packages\assets_library.json  ->  %HOUDINI_USER_PREF_DIR%\packages\
```

Nothing else is copied. The package sets `$ASSETLIB` and puts
`$ASSETLIB/houdini` on Houdini's `path`, so the shelf and the Python module are
read straight out of the repo. Update the repo, Houdini picks it up — there is
no second copy to drift.

**Edit the path inside that json** if the repo is not at `H:/Code/Assets_library`.
That is the only machine-specific line, and it is deliberately a variable rather
than a hardcoded path in the code: the whole folder is meant to move to another
disk and keep working.

### Why the module folder is called `python/` and lives on `PYTHONPATH`

Houdini auto-scans `<path>/pythonX.Ylibs` only when `X.Y` matches the Python it
is **actually running**. The folder was first called `python3.11libs`, which
Houdini 22 never looked in — it runs **3.13.10** — and the failure was
`ModuleNotFoundError: No module named 'assetlib_hou'` *after the shelf had
loaded*, which reads like a broken module rather than a folder nobody opened.
Found 2026-09-12, on the first run.

The folder is now called `python/`, which matches no version and is therefore
never auto-scanned, and it is named on `PYTHONPATH` outright. One mechanism
instead of two, and no filename that has to agree with a Houdini release.

### Which Python the seam test actually saw

| Houdini | build launched | seam test |
|---|---|---|
| 22.0.368 | Python **3.13.10** | passes, host Qt PySide6 |
| 21.0.512 | — | **not a target** |
| 20.5.684 | — | **not a target** |

**22+ only** (decided 2026-09-12, `docs/decisions.md`). That removes the whole
PySide2 problem: 22 ships PySide6, the same binding `ui/` uses. No compatibility
shim gets written, and the browser is no longer *forced* out of process.

A Houdini version does not have *one* Python: 22.0 ships 3.10, 3.11 and 3.13
builds, and you get whichever you launch. `docs/machine.md` has the full table.
**3.11 is still the only version all three releases share**, which is why the
project pins it — that decision is unchanged.

What the run proves is the direction of the constraint: 3.11 is a **floor**, not
a target. `assetlib` is written to 3.11 syntax (*avoid 3.12+*, per
`docs/decisions.md`) and imported cleanly on 3.13. Writing to the oldest shared
version is what makes every newer one work for free.

The seam test checks `>= 3.11` for exactly that reason. Its first version
asserted `== 3.11` and failed a seam that was working.

## Measured: what Houdini's interpreter has

```
panel deps    PySide6 PIL numpy OpenEXR -xxhash
```

Four of five, on 22.0.368. **Only `xxhash` is missing**, and that decides the
split cleanly:

| in a Python Panel | verdict |
|---|---|
| browse, search, preview, Contents | **fine** — PySide6, Pillow, numpy and OpenEXR are all present, so HDR and EXR thumbnails decode |
| right-click → build in Houdini | **fine** — reads `asset.json`, hashes nothing |
| **Add / Edit an asset** | **no** — `commit.py` hashes every file, and without xxhash it falls back to blake2b |
| **Verify (deep)** | **no** — xxh3 digests report as unverifiable |

`hashing.py` falls back to stdlib `blake2b` and the digest carries its algorithm
(gotcha 8), so nothing breaks or lies. But importing from a panel would write
blake2b digests into a library whose other 58 assets are xxh3, for no reason
other than which process happened to run.

**Rule: the panel READS and BUILDS. Writing stays in the standalone app**, on
the bundled runtime, which has xxhash. That is not a workaround — the standalone
app is where importing belongs anyway, since it is where the plan table lives.

## Then

### The panel — one click

**Windows ▸ Python Panel ▸ Assets Library**, or drop it in a pane tab.

This is the path worth using. The window runs in Houdini's process, so
`import hou` succeeds, and right-click ▸ *Import to Houdini* builds the nodes
**directly** — no request file, no second button.

It is the same `ui.app.MainWindow` as the standalone app. Two things the panel
deliberately does not do: it never puts `runtime/` on `sys.path` (a second
PySide6 in the host's process crashes it), and it never calls `ui.theme.apply()`
— that forces a colour scheme on the whole `QApplication`, which in here is
Houdini's. The standalone app owns its process and may restyle it; a guest does
not restyle the host.

**Add and Edit still belong in the standalone app** — Houdini has no xxhash.

### The shelf — three buttons

**Seam test** — run this first, once per Houdini version. It checks the four
things everything else assumes:

| check | why it matters |
|---|---|
| Python is 3.11 | the version `assetlib` is pinned to; 20.5, 21.0 and 22.0 all offer it |
| `import assetlib` works | invariant 2 — the core imports no Qt and no `hou`, which is what makes this possible at all |
| the library reads | `find_config()` walks up and finds `config/library.json` |
| **`runtime/` is NOT on `sys.path`** | the dangerous one, see below |

**Browse library** — opens the window as a **separate process** on the bundled
runtime.

## The one thing that can crash Houdini

`runtime/` holds PySide6. Houdini 20.5 ships **PySide2**. Two Qt libraries in
one process do not raise an ImportError — they crash the host, usually later and
somewhere that looks unrelated.

So `runtime/` must never reach `sys.path` inside Houdini, and the browser runs
out of process rather than as a Python Panel. The seam test reports pollution as
a failure even though nothing has gone wrong yet, because by the time it does go
wrong the cause is invisible.

Nothing under `houdini/` may import Qt at module level. When the options dialog
is ported it imports Houdini's **own** PySide2/6, with the `try/except` shim the
original shelf tool already uses.

## The arrow

`assetlib` knows about no DCC. `assetlib_hou` depends on `assetlib`, never the
reverse — the same rule that keeps `ui/` out of the core, pointed at a second
consumer. Breaking it breaks headless use and every other adapter.

## What is not here yet

The Karma/MaterialX/Solaris builders. They exist, working, in
`H:/3D/Maya/Scripts/Manager_tool/assets_manager/Assets_manager_var01.py` —
roughly 1 050 lines of node-graph knowledge to port, and roughly 230 lines of
filename guessing to delete, because `asset.json` already holds the answers that
file re-derives on every run.
