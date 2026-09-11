---
name: run-and-shot
description: Launch the Asset Library window with its output captured, screenshot it, and read the log tail - so a change to the UI can be seen rather than described. Use when asked to run, launch or show the app, to confirm the grid, the Add window or a thumbnail looks right, or when a bug is visual.
---

# Running Assets Library, and looking at it

A picture answers in one read what a paragraph of description gets wrong. One
launch, one capture, and Felix still watching the real thing.

## Launch

```
run_ui.bat
```

The console launcher, so the output is visible. `Asset Library.vbs` is the
silent one for daily use — it writes to `launch.log` instead, which is the file
to read if the window never appears.

Keeping the output for later:

```
run_ui.bat > logs\run.log 2>&1
```

The window takes a moment: the tree is materialised at startup and the grid
decodes thumbnails on a pool.

## Capture

```
python tools\shot.py "Asset"
python tools\shot.py --list          if the title is not what you expected
```

It prints a path under `.claude\shots\`. **Read that file** — the point is to
look at it, not to hand over a filename.

## Read the tail

```
powershell -NoProfile -Command "Get-Content launch.log -Tail 40"
```

## Rules

- **Ask before an action that writes.** Browsing, searching and opening
  Contents are free. **Add, Edit and Delete change the library on disk** — and
  `library/` is not in git. A screenshot is cheap; a mutated package is not.
- **Do not loop.** Launch, capture, read, report. If the answer is not in the
  capture, say what you would need to see instead of running it five more times
  — that burns the window and puts Felix in front of a log instead of the app.
- **Say what you actually see**, including the parts that contradict what the
  change was supposed to do. A capture read optimistically is worse than none.
- **Close the window** when finished, unless Felix is going to keep using it.
- `.claude/shots/` and `logs/` are gitignored: evidence for this session, not
  artefacts.
