# Installing tools into Houdini as a package — removed

**Built and removed 2026-09-13, on the same day.** Felix: *"since the houdini
script and tools can be directly launched from the library get rid of the
installation part."*

---

## What it was

`assetlib/install.py`, plus *Install to Houdini 22.0 / 21.0 / 20.5* and
*Uninstall from …* in the grid's context menu.

Installing wrote **one JSON** into `$HOUDINI_USER_PREF_DIR/packages/`:

```json
{ "enable": true,
  "env": [ {"PYTHONPATH": {"value": "<asset>",        "method": "append"}},
           {"PYTHONPATH": {"value": "<asset>/src/…",  "method": "append"}},
           {"HOUDINI_OTLSCAN_PATH": {"value": "<asset>/src/…/HDAs;&",
                                     "method": "append"}} ],
  "path": "<asset>" }
```

Houdini reads `packages/*.json` at startup and contributes each package's
`toolbar/`, `python_panels/` and `otls/`. So the asset also carried a generated
`toolbar/<name>.shelf`, emitted from `fields.shelf` with **no path inside it** —
the package had already put the folder on `PYTHONPATH`, so the snippet was just
`import <module>; <module>.show()`.

Uninstalling deleted that one file. Nothing of the user's was ever edited: no
shelf of theirs appended to, no `userSetup.py` line inserted.

It was verified as far as text — package JSON and shelf XML emitted, parsed, and
matching the shape of the eleven third-party packages already on the machine.
**No button was ever clicked in Houdini.** It never ran.

## Why it went

The library runs as a Houdini Python Panel. Inside that panel *Launch* imports
the module and calls it **in the process the tool wants to run in** — no package
file, no restart, nothing written outside `library/`. Against that, installing
is a second route to the same place that costs a restart and leaves state in the
user's preferences folder.

The panel is also *in* Houdini, so the shelf button it replaced was never far
from the browser that could launch the same tool directly.

## What was lost, precisely

**HDAs.** `HOUDINI_OTLSCAN_PATH` is read at startup, so no in-process launch can
make a tool's digital assets loadable. Only a package could.

This cost nothing on the day: `otls` is manifest-only and never inferred (see
`docs/decisions.md`), and the one real tool — `Manager_tool` — deliberately
omits the field, because which of its 30 HDAs are Felix's and which are vendored
is unresolved on the tool side.

**So the day this matters is the day someone declares `otls`.** That is the
trigger to reconsider, and the reason this file exists rather than a line in a
changelog.

Also lost, and smaller: a shelf button that persists without the library window
open, and any tool that would want to be present at Houdini startup. Neither has
a user.

## If it comes back

It should come back as `otls` support, not as a general installer — the shape
was right and it is preserved above. The pieces that survived the removal and
would be needed again:

- `apps.unresolved()` — checks that declared paths exist. Moved to `apps.py`,
  still used by `verify`, and it was written for install.
- `launch.search_paths()` — the same folder list the package put on
  `PYTHONPATH`. Deliberately identical, so a launched tool and an installed one
  resolved imports the same way.
- `config/apps.json` — `pref_dirs` and the `install` key were removed with it.
  The `detect` half stays; it is what proposes `app:` tags.

`git show` the removal commit for the emitters themselves.
