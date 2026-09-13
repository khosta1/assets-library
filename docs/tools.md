<!-- covers: assetlib/apps.py, assetlib/launch.py -->

# Tools in the library

*How a script or tool gets imported, tagged and launched — and what a tool has
to look like for all of that to happen by itself.*

Written for whoever wrote the tool. You do not need to read the library's code
to make this work; everything the library looks at is listed here.

---

## 1. What the library does with a tool

A tool is the first thing this library does not merely **store**. A rock is
finished when it is in the tree. A tool is finished when you can run it.

So a tool asset has a verb the others do not:

```
right-click ▸ Launch <label>…       or just double-click the tile
```

Inside Houdini the library window *is* a Python Panel, so Launch imports your
module and calls it **in that process** — no restart, no package file, nothing
written outside `library/`. From the standalone window, a tool that needs no
host runs in its own interpreter instead.

There is no install step and there is no "deploy to Houdini" button. There was
one for a day; it was removed because Launch does the same job with less
(`docs/History/houdini-package-install-removed.md`).

---

## 2. The short answer

Three things, and the third is the only one that takes effort:

1. **Ship a folder**, not a loose file. The folder is copied verbatim.
2. **Declare the type as `Script / tool`** in the Add window, and pick the
   category — `houdini`, `maya`, `blender`, `nuke`, `unreal`, `standalone` or
   `misc`. That is a human's choice and it is never guessed for you.
3. **Put an `install.json` at the root of your folder.** Without it the library
   guesses, and §5 is what guessing gets you.

A tool with a manifest needs no cooperation from anyone: drop the folder in,
confirm the rows, and it is launchable.

---

## 3. The tree is the asset

A `script` asset uses the `folder_blob` ingest, which means exactly what it
says:

```
your/source/folder/          →    library/script/houdini/<name>/
├─ install.json                   ├─ asset.json      written by the library
├─ manager_tool.png               ├─ preview/
├─ Main_ui/                       │  └─ thumb.jpg    512px, rendered from your icon
│  ├─ manager_ui.py               └─ src/            YOUR TREE, byte for byte
│  └─ widgets.py                     ├─ install.json
└─ Toolkit/                          ├─ manager_tool.png
   └─ helpers.py                     ├─ Main_ui/
                                     │  ├─ manager_ui.py
                                     │  └─ widgets.py
                                     └─ Toolkit/
                                        └─ helpers.py
```

**Nothing is renamed, slotted, contested, flattened or dropped.** Relative
imports, `__init__.py`, `preset/*.json` and `HDAs/` all depend on their
positions, so positions are what survive. This is unlike every other asset type
in the library, where files *are* renamed and sorted.

`src/` rather than the package root, because the root's names are reserved —
`asset.json`, `tex/`, `geo/`, `preview/`, `derived/`, `extra/` — and a tool
shipping its own `preview/` would collide with the package's.

**The one thing that is dropped is build junk**, which is not part of your
source: the folders `__pycache__`, `node_modules`, `build`, `dist`, `.egg-info`
and the extensions `.pyc .pyo .pyd .o .obj`. Everything else travels, including
files the library has no idea about.

**Paths inside `src/` are stable.** Once imported, `src/Main_ui/manager_ui.py`
stays at `src/Main_ui/manager_ui.py` — nothing in the library moves it later.

---

## 4. `install.json` — the contract

One file at the root of your folder. It is the only thing you write, and the
library reads it **as data**. See §7: nothing in it is ever executed, and there
is no field that can make the library run code.

Every path in it is **relative to the manifest's own folder**, because that is
the layout you can see. The library rewrites them to be relative to the package
when it imports (`Main_ui/manager_ui.py` becomes `src/Main_ui/manager_ui.py`).
You never write `src/` yourself.

```jsonc
{
  "schema_version": 1,

  // Which application this tool is FOR. Becomes the tag app:houdini, which
  // decides whether the tool can be offered outside its host at all.
  // houdini | maya | blender | nuke | unreal | standalone
  "app": "houdini",

  // The picture for the tile. A SOURCE, not the thumbnail: the library renders
  // its own 512px preview/thumb.jpg from it, so any size and any format Pillow
  // reads will do. Optional.
  "icon": "manager_tool.png",

  // What Launch offers. One object per thing a person can run.
  "shelf": [
    {
      "entry":    "Main_ui/manager_ui.py",  // the file to run
      "callable": "show",                   // zero-argument function in it
      "label":    "Manager\nTool",          // what the menu entry says
      "icon":     "MISC_python"             // stored, currently unread — §4.3
    }
  ],

  // Folders whose modules get imported by BARE NAME. Put on sys.path before
  // your entry is imported.
  "pythonpath": ["Main_ui", "Layer_generator"],

  // Folders of HDAs. Recorded, and currently loaded by nothing — §4.4.
  "otls": []
}
```

Comments are shown here for explanation only — write real JSON. A manifest that
does not parse is **not** fatal: the library warns and falls back to guessing,
because a tool is not un-importable because its metadata has a trailing comma.

### 4.1 `shelf` — the part that matters

This is what Launch runs, and each entry must satisfy three conditions:

| field | rule |
|---|---|
| `entry` | a **file that exists in what you import**. Relative to `install.json`. |
| `callable` | a function defined at module level taking **no arguments**. Defaults to `show`. |
| `label` | free text. `\n` is allowed — it reads as a shelf button, and menus flatten it to a space. |

What actually happens at launch, in order:

```
sys.path gets:  the package root, then your pythonpath folders,
                then the folder your entry sits in
import <stem of entry>          manager_ui.py  →  import manager_ui
importlib.reload(that module)
getattr(module, callable)()
```

Three consequences worth knowing before they bite:

- **The module is imported by its basename**, not by a path. Name your entry
  file something unlikely to collide — `manager_ui.py` is safe, `types.py`,
  `json.py` or `parser.py` are not.
- **`sys.path` entries are appended, never inserted at position 0.** Inside
  Houdini this is not your process, it is Houdini's, with thousands of modules
  already loaded, and a folder of yours shadowing one of them would be a
  failure with no visible cause. If your tool relies on winning a name race,
  it will lose here.
- **The module is reloaded on every launch**, so a tool launched twice in a
  session runs the code on disk rather than the copy imported an hour ago.
  Module-level state does not survive; if that matters, keep it in the object
  your `show()` returns.

**One button, not ten, is usually right.** Declare the entry points a person
should pick from, not every module that happens to be runnable. If your suite
has one launcher and nine tools it lists, declare the launcher.

**If your tools run under `if __name__ == "__main__"`** rather than exposing a
function, `entry`+`callable` cannot express them — importing such a module
defines some functions and opens nothing. Standalone launches run the file
through `runpy` as `__main__` and so work anyway; in-process launches do not.
A launcher that execs them is the shape that works in both.

### 4.2 `pythonpath`

Only the folders whose modules are imported **by bare name**. Not every folder
you have.

The folder your entry sits in is added automatically, so it does not need
declaring. A folder on `sys.path` that nothing imports is a name collision
waiting in a process that already has thousands of modules.

### 4.3 `shelf[].icon` — stored, unread

It names a Houdini shelf-button icon, from back when the library wrote a shelf
file. Nothing reads it today. It is kept because the field being
present-and-unused is honest, and because a field that vanishes with its
consumer is one somebody has to rediscover. Set it or omit it; it changes
nothing. **The `icon` you actually want is the top-level one**, which becomes
the tile.

### 4.4 `otls` — declare deliberately, or not at all

**The library never infers this.** It used to fill it from any `.hda` it found,
and that was wrong twice over: declaring a folder of HDAs both puts them on
Houdini's path *and* ships them onto a shared master for other people to load.
Whether a bundled `.hda` may be redistributed is its owner's decision, not
something an importer settles by noticing a file extension.

**And today nothing loads them.** `HOUDINI_OTLSCAN_PATH` is read **once, at
Houdini startup**, so an in-process launch cannot put HDAs on it — that is the
single capability the removed installer had and Launch does not. Your `.hda`
files travel with the package and `verify` checks the folder is there; loading
them is a manual step.

Declaring it is still worth doing when the answer is known: it records where
they are, for the day something loads them.

---

## 5. What happens with no manifest

The library falls back to guessing, and the guess is weaker than it looks.

**Tags** come from `config/apps.json` — three signals, any one of which is
enough: an extension only that application uses (`.hda`, `.mel`, `.blend`), an
`import` statement naming its Python module (`hou`, `maya.cmds`, `bpy`), or a
folder name it looks for by convention (`otls/`, `shelves/`, `addons/`).
Imports are matched as **statements**, not substrings, and folder names are
matched **inside your asset**, never against the absolute path — otherwise
every tool kept under `…/Maya/Scripts/` would be tagged for Maya. A tool that
matches nothing gets `app:standalone`, because every tool runs somewhere.

**Entry points** come from scanning every `.py` for a zero-argument `show()`,
`launch()` or `main()` defined at top level.

This is where it goes wrong: scanning a real ten-tool suite proposed **five**
entry points when exactly one was meant to be called, because these tools do
their work at module level. You then delete four rows by hand, every time you
re-import.

Autodetect exists so a tool with no manifest is still importable. It is not the
supported path.

---

## 6. Nothing here decides — you do

Everything above is a **pre-fill**. The Add window shows the app tags as
editable chips and the entry points as rows, and the person importing keeps,
edits or deletes them. That is true of the manifest as well as of the guess:
your `install.json` is the best available proposal, not an instruction.

The same rule governs texture slots and categories elsewhere in the library. A
pattern that looks right and is wrong is exactly the mistake a person catches
at a glance and a rule never will.

What a person must type and the library never infers: **type, category and
name**.

---

## 7. What the library will never do

**Nothing under `library/` is executed by the app of its own accord.** This is
invariant 15 in `docs/architecture.md`, and it is not a precaution — it is
structural. Assets are downloaded from a shared master, so a library that ran
code an asset carried would make *downloading a tool* mean *running it*.

- Your manifest is parsed as JSON. It is never `exec`'d, `eval`'d or imported.
- No import path, no sync, no download, no background job and no analysis
  reaches code inside `library/`.
- A manifest field that cannot express something is a request for a new field,
  never an escape hatch that runs anything.

**Launch is the single exception, and it is bounded to stay one:**

- reached only from a context menu or a double-click — never from code
- the file, the module and the call are **shown and confirmed before anything
  runs**
- a Houdini tool is not offered outside Houdini, because the `ImportError`
  would read as a broken asset rather than as the wrong host
- a tool that raises is reported as the *tool* failing, not the library

---

## 8. Where your fields end up

After import, `library/script/<category>/<name>/asset.json`:

```json
{
  "type": "script",
  "category": "houdini",
  "tags": ["app:houdini"],
  "fields": {
    "files": 61,
    "tree": "src",
    "shelf": [{"entry": "src/Main_ui/manager_ui.py", "callable": "show",
               "label": "Manager\nTool", "icon": "MISC_python"}],
    "pythonpath": ["src/Main_ui", "src/Layer_generator"],
    "otls": []
  }
}
```

| you wrote | lands as | read by |
|---|---|---|
| `app` | a tag `app:<name>` | whether Launch is offered off-host |
| `icon` | `preview/thumb.jpg`, rendered at 512px | the grid tile |
| `shelf[]` | `fields.shelf`, entries prefixed `src/` | `launch.py`, and the menu |
| `pythonpath[]` | `fields.pythonpath`, prefixed `src/` | `launch.py`, before the import |
| `otls[]` | `fields.otls`, prefixed `src/` | nothing yet — §4.4; `verify` checks it exists |

`asset.json` is the truth from here on. If you edit the manifest inside `src/`
afterwards, nothing re-reads it — re-import the asset instead.

---

## 9. Checking it worked

In the library window:

- The tile carries **your icon**, not the generic type icon.
- **Right-click** shows `Launch <your label>…` above everything else.
- **Double-click** launches instead of opening the file listing. More than one
  entry and you are asked which.
- **Library ▸ Verify** reports nothing about the asset. It checks both
  directions: every file has something pointing at it, and every path you
  declared has a file under it. A declared entry that is not in the package is
  an **error**, reported at import and again at verify — that failure used to
  surface three steps later as *"…is not in the package"* at the moment of the
  first click.

If Launch does not appear at all, it is one of three things: the asset has no
`shelf` entries; you are in the standalone window and the tool is tagged for a
DCC; or the type is not a `folder_blob` type, so the tree was never kept.

---

## 10. Traps

- **Import the whole folder, not the files inside it.** Dropping a folder takes
  its entire tree; selecting files takes what you selected, and a manifest that
  names a file you did not import is refused.
- **The shallowest `install.json` wins.** A vendor tree can contain several —
  one per sub-tool, one in a bundled dependency — and the one describing *this
  asset* is the one nearest its root.
- **Declared beats scanned, including for the icon.** Scanning already finds
  `manager_tool.png` beside a manifest in an asset called `manager_tool`, by
  the rule that a file named after the asset is its preview — but only while
  those two names happen to agree. One rename and it stops, silently.
- **A declared icon that is missing is a warning, not a failure.** An asset does
  not fail to import over a picture.
- **A transparent icon is composited onto the tile ground**, not onto white.
  If yours has alpha, what is *under* the alpha no longer matters.
- **`script` is matched last of all the types**, on purpose: `.json` and `.xml`
  are the most generic extensions in the registry, and a script type placed any
  earlier would claim every Megascans folder off its sidecar. So a folder is a
  script because a person said so, not because it contains a `.json`.
