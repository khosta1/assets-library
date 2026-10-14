---
name: check-and-report
description: How to verify a change in this project before calling it ready - there is no build step, so the cheapest verifier is a compile+import pass - and what a report may and may not claim. Use before presenting a change as finished, when an import or syntax error appears, or when something "should work" and has not been checked.
---

# Checking a change to Assets Library

## There is no build

It is Python. Nothing compiles, which removes the cheapest verifier most
projects have — so the equivalent has to be run deliberately:

```
runtime\python.exe -m compileall -q assetlib ui
```

That catches syntax errors in every file, including the ones today's change did
not open. It is fast, it writes only `__pycache__` (gitignored), and it has no
other side effects.

For the layering rule, which is the one that fails silently on this machine and
loudly on another:

```
runtime\python.exe -c "import assetlib.analyse, assetlib.commit, assetlib.index, assetlib.verify, sys; print('qt loaded:', any(m.startswith('PySide6') for m in sys.modules))"
```

It must print `qt loaded: False`. If it prints `True`, `assetlib` has grown a
Qt import and invariant 2 is broken — see `docs/architecture.md` §2.

## What that does not prove

Nothing about behaviour. Not whether the plan table shows the right rows, not
whether the thumbnail looks right, not whether the import landed where it
should. **Felix runs the app and observes it.**

So: **no probe script, no test file, no benchmark written for the occasion
without asking first.** Asking costs one line and is often answered yes.

## Reading a failure

1. **The first traceback, not the last.** A Qt crash chain usually has the real
   cause at the top.
2. **Quote it.** The actual text, not "an error about types".
3. If the app dies at startup with no window, the output is in `launch.log` —
   the `.vbs` launcher redirects there precisely so a crash leaves something to
   read (`docs/decisions.md`).

## What the report says

- **Checked clean** — say what was compiled and that the Qt-free import passed.
- **Checked with a warning** — quote it; do not round up to clean.
- **Failed** — the traceback verbatim, the file and line, and what you intend
  to do about it.
- **Not checked** — say so explicitly, and say what is unverified as a result.
  Never let "not checked" read as "works".

Then, before calling it finished: `/invariants` — twelve of them, and
`verify.py` only enforces three.
