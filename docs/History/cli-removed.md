# The command line

Removed **2026-08-21**, when the tool became GUI-first and self-contained.
`assetlib/cli.py` and `requirements.txt` were deleted.

## What it did

A full command-line front end over `assetlib`:

| command | what it did |
|---|---|
| `init` | materialise the library tree |
| `import` | run analyse + commit on a folder |
| `verify` / `verify --deep` | invariant checks, optionally recomputing digests |
| `index --rebuild` | rebuild `.assetlib/index.db` from the packages |
| `search` | query FTS5 |
| `stats` | counts per type and category |

Every one of them exists in the window today:

| old command | now |
|---|---|
| `init` | automatic — the tree is materialised at startup |
| `import` | **Add asset…** (Ctrl+N) |
| `verify` / `--deep` | Library ▸ Verify / Verify (deep) |
| `index --rebuild` | F5 |
| `search` | the search box |
| `stats` | the sidebar counts |

## Why it went

The CLI's real job was never to be used. It was **scaffolding for a rule**: as
long as every operation had to work without a window, `assetlib` could not grow
a Qt import. That worked, and the rule is now stated directly —

> `assetlib` imports no Qt and no `hou`. `ui/` depends on `assetlib`, never the
> reverse.

— and it is checkable by reading the imports at the top of nine files. A second
front-end maintained to prove a one-line rule is a second front-end to keep
working, and a second place for behaviour to diverge.

The other half of the argument is the runtime. Once the app shipped its own
Python 3.11 and launched from a `.vbs` with no console, `requirements.txt` was
describing an installation nobody performs, and the CLI was an entry point into
an interpreter that is not on `PATH`.

## What the problem was, and whether it has gone away

**The problem was import-direction discipline, and it has not gone away** — it
is simply enforced differently. If `assetlib` ever grows a Qt import, nothing
will fail loudly on this machine; it will fail on the day someone runs it
headless, or inside Houdini, which is the whole point of the layer.

So: **do not bring the CLI back to enforce this.** If enforcement ever needs
teeth, the cheap version is a check in `verify.py` (or a two-line test) that
imports `assetlib` with `sys.modules` poisoned against `PySide6` and `hou`.
That is the same guarantee for twenty lines instead of a front-end.

A headless *batch* entry point is a different feature with a different reason —
the bulk migration (`B1`) will want one, to run for hours without a window. If
it appears, it is a batch runner, not a CLI, and it should not grow a `search`
command.
