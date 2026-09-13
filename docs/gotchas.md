# Gotchas — found the hard way, do not re-learn

Split out of `CONTEXT.md` §8 on **2026-09-11**. Numbering is preserved: entries
are referred to by number, so nothing is ever renumbered.

---

**1. A sidecar format decided the type** — 2026-08-20

ambientCG ships a 2.5 KB `.usdc` next to its textures. Counting it as geometry
classified a texture set as a `material`, which ran the generic planner, which
had no variant filtering — so NormalDX and NormalGL both landed on
`tex/concrete014_normal.png` and one silently overwrote the other.

**Cause:** a file's mere *presence* was taken as evidence of what the asset is.

**Fix:** `SIDECAR_EXTS`; one shared slot-resolution function for both planners;
and `conflicts()` now refuses to commit a plan where two files claim one
destination at all.

**Rule:** a small file that merely accompanies an asset never determines what
that asset is.

---

**2. `_diff_` was missing from the diffuse keywords** — 2026-08-20

Poly Haven basecolors fell through unmatched.

**Rule:** test slot keywords against real vendor data, not against the naming
scheme you would have chosen.

---

**3. A bare stem is a preview** — 2026-08-20

`Concrete014.png` beside `Concrete014_8K-PNG_Color.png` is ambientCG's preview
render. It matches no slot keyword, and it must not: it is a picture *of* the
asset, not a channel of it.

---

**4. Slot order in `texture_slots.json` is significant** — 2026-08-20

First match wins, so `diffuse` MUST stay last as the catch-all, or
`subsurface_color` and `specular_color` get mis-slotted as diffuse.

**Rule:** when a matcher is first-match-wins, its config file is code, and
reordering it is a behaviour change.

---

**5. `verify` must skip subfolders inside a package** — 2026-08-20

`tex/` and `preview/` are not drift. Drift is files in `library/` *outside* any
package.

---

**6. A package can contain another `asset.json`** — 2026-08-21

RenderMan `.rma` bundles ship one, and `folder_blob` payloads land in `extra/`
verbatim. A plain `rglob` indexed the payload as a second, deeper asset, and
`verify` called it a depth violation. Real case:
`library/ies/spot/*/extra/asset.json`.

**Fix:** `iter_assets()` stops descending once it finds a package.

**Rule:** anything kept verbatim may contain the tool's own file formats. Treat
`extra/` as opaque, always.

---

**7. Writes must not share the thread pool with thumbnail decoding** — 2026-08-21

Opening Contents queues a decode per file. Twenty 8K TIFFs occupy every thread
for a minute, a write job queued behind them never starts, and the progress
dialog hangs forever.

**Fix:** `ui/writepool.py`, deliberately single-threaded and separate.

**Rule:** a job the user is *waiting on* never shares a queue with work that is
merely nice to have.

---

**8. Verification must recompute with the algorithm the digest was written
with** — 2026-08-21

Found by testing the external-disk scenario: assets imported while `xxhash` was
absent carry `b2:` digests. Verifying after installing xxhash recomputed
`xxh3:` and reported **every file as corrupted**.

**Fix:** `hashing.matches()` parses the prefix and raises `UnavailableAlgorithm`
when it cannot compute — reported as **"cannot check"** (a warning), never
"corrupted".

**Rule:** *unverifiable is not the same as corrupted*, and a stored digest must
carry its algorithm.

---

**9. A thumbnail cache keyed by uuid needs explicit invalidation** — 2026-08-21

A uuid deliberately survives an edit, so without `invalidate()`/`forget()` an
edited asset shows its old icon forever.

**Rule:** every identifier chosen because it is *stable* creates a cache that
must be invalidated by hand.

---

**10. An edit can be handed a file already at its destination** — 2026-08-21

For example a file dragged out of `derived/`. Copying it would open the same
file for reading and writing at once and destroy it.

**Fix:** `edit.apply()` checks for this before copying.

---

**11. Float images cannot be clamped to 8 bits** — 2026-08-21

A linear 32-bit equirect needs exposure and gamma, and the exposure must come
from a **high percentile** — otherwise one bright sun disc drags the whole sky
to black. An 8K HDR would also be 400 MB as float32, so the decoder subsamples
while reading.

---

**12. Qt performance is not optional** — 2026-08-21

`QListView` + `QAbstractListModel` (never `QListWidget`),
`setUniformItemSizes(True)`, decoding on a pool, and search that queries FTS5
only.

**Rule:** the window must never walk the filesystem during interaction.

---

**13. A regex in a JSON config needs its backslash doubled, and a heredoc
eats one more** — 2026-09-12

`"_\d+ppm"` is not valid JSON: `\d` is not an escape the parser knows, so the
file fails to load with `Invalid \escape` and a line number pointing at the
config, not at the code that wrote it. It must be `"_\\d+ppm"` — **two**
backslashes in the file — which the parser hands to `re` as `_\d+ppm`.

Writing that config *through a shell heredoc* eats a further layer, so the
string that looked right in the script landed in the file with one backslash.
It happened twice on the same evening, to `texture_slots.json` and then to
`library.json`.

**Rule:** after writing any config that contains a regex, `json.load` it and
`re.compile` every pattern before doing anything else. Both failures were
silent until the next read, and the second one only looked different because
the line number moved.

---

**14. Verifying during a migration reports the migration as damage**
— 2026-09-12

`Asset.write()` is atomic: `mkstemp` beside `asset.json`, write, `os.replace`.
So during a schema migration every package holds a `.asset-*.tmp` for a few
milliseconds, and a handful of packages are still on the old version at any
instant.

`verify` run at that moment reported in-flight temp files as orphans and the
not-yet-rewritten packages as schema skew. Nothing was wrong. The app had been
launched in another process and was migrating 57 assets while the check ran.

**Rule:** an orphan check skips `.asset-*.tmp`, and a version-skew report is
only trustworthy when nothing else is writing. Neither is a reason to stop
verifying — it is a reason to look at what else is running before believing it.

---

**15. A backslash escape written through a shell heredoc arrives as one
character less** — 2026-09-12

A two-backslash `\\d` typed into a script, passed through `<<'EOF'`, lands in
the file as a one-backslash `\d`. A regex in JSON then fails to parse; and a
newline escape inside a Python string literal arrives as an actual line break,
so the file will not compile — `SyntaxError: unterminated string literal`.

This entry was itself mangled by the trap on first writing, which is the
clearest demonstration available that reading about it is not enough.

It happened **three times in one evening** - `texture_slots.json`,
`library.json`, and a `setToolTip` in `ui/app.py` - each time looking like a
different bug, because the error surfaces at the reader rather than the writer
and the line number points at the innocent file.

**Rule:** do not write escape sequences through a heredoc. Use the editor tool
for any line containing a backslash, and after writing a config that holds a
regex, `json.load` it and `re.compile` every pattern before doing anything
else. Gotcha 13 is the JSON half of this; this is the general case.

---

**16. The click that starts an edit destroys the selection it was meant for**
— 2026-09-12

A `QTableView` with `ExtendedSelection` and `AllEditTriggers`: select twenty
rows, click a cell to change it, and the plain click collapses the selection to
that one row **before** the editor opens. Any code that then reads
`selectedRows()` to spread the edit sees one row and the change looks like it
silently failed.

Two halves to the fix: edit triggers that do not fire on a bare click
(`SelectedClicked | DoubleClicked | EditKeyPressed`), and remembering the last
**multi-row** selection so the spread has something to aim at. Restore the
selection afterwards, or the user cannot see that the edit applied to all of
them. Only multi-row selections are worth remembering - a single row is not a
batch and must not resurrect an older one.

**It bit a second time the same evening, through a different door.** The grid's
context-menu handler called `view.setCurrentIndex(index)` unconditionally, which
clears the selection and selects the tile under the cursor - so *Import 12 to
Houdini* became one asset between the right-click and the menu appearing.
Right-clicking inside a selection now uses
`selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)`, which
moves the current index without touching what is selected; outside it, replacing
the selection is still what a click means.

**Rule, generalised:** before acting on a selection, ask what the gesture that
triggered the action did to that selection first. `setCurrentIndex`,
`AllEditTriggers` and a plain left click all quietly collapse one, and each
failure looks like the action silently doing nothing.

---

**17. robocopy copied nothing and complained about a drive nobody mentioned**
— 2026-09-12

Seeding the 75 packages onto the Rocky box over SMB. The command named `H:` and
`Y:` and nothing else, and it died instantly with

```
ERREUR : Désolé... Paramètre non valide #3 : "E:/"
```

Exit code **16**. Zero bytes copied, and the `/LOG:` file was never even
created — so the obvious next move, "read the log", had nothing to read.

**Cause:** the Bash tool here is Git Bash, and MSYS rewrites any argument that
starts with a single `/` into a Windows path before the program ever sees it.
`/E` became `E:/`. So did every other switch: the one line robocopy *did* print
showed `/R:1000000 /W:30`, its defaults, because `/R:2` and `/W:2` had been
eaten the same way. The error names a drive letter that appears nowhere in the
command, which is what makes it unrecognisable — `E:` is not a typo, it is
`/E` after the shell got to it.

**Fix:** call native Windows executables from the PowerShell tool, never from
the Bash tool. The seed ran unchanged from PowerShell and finished at 112 MB/s.

**The tell, when it happens again:** robocopy echoes an `Options :` line into
its own log listing the switches it actually received. If that line does not
match what was typed, the shell ate them — do not go looking at the command.

**Rule:** in this repo the Bash tool is Git Bash, so a `/SWITCH` argument is not
safe there. `robocopy`, `net`, `reg`, `xcopy`, `sc` and friends all take that
form and all lose it. Bash for POSIX tools, PowerShell for Windows ones; the
failure is silent in the sense that matters, because the program runs, reports
a real error, and blames something that was never in the command.

---

**18. A folder that cannot be deleted, by an app that is not running**
— 2026-09-13

`J:\Assets_library` refused to be deleted or even renamed: *"Le processus ne
peut pas accéder au fichier, car il est utilisé par un autre processus."* The
window had been closed. Nothing was in the taskbar. Nothing was on screen.

`pythonw.exe` was still running from `J:\Assets_library\runtime\`, twenty
minutes after the window went away.

**Cause:** network jobs on a `QThreadPool` with no way to interrupt them. Qt
waits for running pool jobs before the process can exit, and a thumbnail fetch
blocked on a sleeping server holds its thread for the full socket timeout —
fifteen seconds, or a hundred and twenty for a file transfer. One tile
scrolling past an unreachable box was enough.

**What made it invisible rather than merely slow** is the *other* fix from the
same day: `Asset Library.vbs` now launches `pythonw.exe` so no console can ever
appear. With a console there would have been a black window sitting there
saying "still here". Without one, the only symptom the user ever sees is a
folder Explorer will not delete, and nothing anywhere points at the app.

**Fix:** `ui/netpool.py` gained `stopping()` and `shutdown()`. `closeEvent`
calls `shutdown()` first — before the databases, which close instantly — which
sets the flag, `clear()`s the queue, and waits 1.5 s. Every long job polls
`netpool.stopping()` between chunks. If the pool still has not drained, the
window is already gone and continuing to wait is continuing to lie, so
`os._exit(0)`: `sys.exit` unwinds, and the unwinding is exactly what blocks.
Nothing is lost — the databases were just closed, `asset.json` is written at
commit time, and a partial download is a `.part` that resumes.

**Rule:** a blocking call on a thread pool is a process that will not exit. The
timeout you chose for the network is also the time your app takes to close, and
under a windowless interpreter that time is invisible. Anything that waits on
another machine needs a stop flag it checks itself — nothing outside it can
interrupt a socket read — and a hard exit as the backstop.


---

**19. The unix way to say "add but not delete" does not exist on this disk**
— 2026-09-13

The library on the box lives on `/srv/data2`, an NTFS disk mounted by
ntfs-3g. The obvious way to let friends contribute without letting them wipe
the library is the one every unix admin reaches for: write permission on the
directory plus the sticky bit, so a user may create files and may only delete
their own.

It cannot work there. ntfs-3g is FUSE and maps the whole tree to a single
uid/gid — there is no per-file ownership for a sticky bit to compare against,
so "their own" has no meaning and the bit protects nothing. The same is true of
every plan built on POSIX ACLs on that mount.

**What does work is Samba's own check**, because it happens in `smbd`, above
the filesystem, before `open()` is ever called:

```ini
[assets]
   path = /srv/data2/assets
   read only = yes
   write list = felix          # the entire admin gate
```

A non-listed account is refused at the SMB protocol with `ACCESS_DENIED` and
never reaches the disk, whatever the disk's permissions say. Add-only for
everyone else is then a *second share* pointing at a drop box, not a
permission bit on the library.

**Why this is worth a number:** the failure mode is not an error. Setting the
sticky bit on an ntfs-3g mount succeeds — `chmod +t` returns 0 and `ls` shows
the `t` — and grants exactly nothing. A gate that looks applied and is not is
worse than no gate, because nobody checks it again.

The app reads the answer rather than deciding it: `sync.probe()` writes a
temporary file into `library/` on the share and removes it. A permission read
would have answered about the filesystem, which is the layer that does not
know.

---

**20. The tool launched fine. It had been dead for a second and a half.**
— 2026-09-13

First tool ever launched out of the library: a tkinter tool, from the
standalone window. Pressed Launch, confirmed the dialog, status bar said
`launched point_clean_tool`, and **no window opened**. Nothing in `launch.log`,
nothing on screen, no error anywhere. It looked exactly like a tool that had
started and drawn nothing.

**Cause.** `Popen` returns a live object the instant the process is *created*,
which says nothing about whether the process then survived its first import.
The child is created with `CREATE_NO_WINDOW` — deliberately, so a tool does not
flash a black console on every launch — so its traceback went to a stdout that
was not attached to anything. `as_subprocess` returned, `_launch_tool` reported
success, and the `ModuleNotFoundError` was written to a handle nobody held.

**Fix.** `launch.as_subprocess()` now sends the child's stdout and stderr to a
log in the temp folder and returns a `Started(proc, log, python)`.
`launch.died()` reads the exit code back, and `ui/app.py:_watch_launch()` asks
it once, 1.5 s later, from a `QTimer` — **not** by waiting on the process, since
a tool that works runs for an hour and blocking on it would freeze the window
for precisely the launches that went right. Dead with a non-zero code gets a
dialog with the tail of what it wrote.

**RULE. A process being started is not a process running.** Anything launched
without a console has to be asked, a moment later, whether it is still alive —
otherwise the most common failure (dies immediately, on import) is the one that
produces no signal at all.

---

**21. The bundled runtime is not general Python** — 2026-09-13

The same launch, once it could speak, said:

```
ModuleNotFoundError: No module named 'tkinter'
```

Which reads as a broken asset, and is not one. Felix asked the right question
at it — *is this script really standalone?* — and the answer is yes: `app:
standalone` is about the **host**, meaning the tool needs no DCC, and says
nothing about which interpreter runs it.

**Cause.** `runtime\python.exe` is a trimmed 3.11 carrying PySide6, Pillow,
numpy, OpenEXR and xxhash. **It has no tcl/tk at all**, so no stdlib `tkinter`
— and `as_subprocess` defaulted to `sys.executable`, which in the standalone
app *is* that runtime. Any tool written against a normal Python installation
can hit this; tkinter is simply the most likely, because it is the one thing
people assume is always there.

**Fix.** `install.json` gained `"python"`, carried through `apps.from_manifest`
→ `analyse._record_tool` → `fields.python` → `launch._python()`. A **bare name**
is resolved on `PATH` at launch rather than stored as a path, because an asset
syncs to a shared master and an absolute path out of one machine's AppData is
wrong on every other. Declaring it also routes the launch out of process even
inside Houdini (`launch.in_host()`), which is separately correct: a tkinter
mainloop would sit on the thread Houdini needs. `launch.died()` now appends
what the runtime actually ships when the missing module was missing from *it*.

**RULE. "No install, no pip, no system Python" is a promise about the APP, not
about anything the app runs.** The runtime is sized for this project's own
imports; everything else it meets is someone else's dependency list, and the
only honest answer is to let that someone declare what they need.

**Worth knowing separately:** a core module changed on disk does not reach a
running app. The asset that failed here was imported 37 seconds *after* the
commit that added the field, by a process started before it — so `analyse.py`
was still the old module in memory and the field was never written. Restart
after touching `assetlib/`, not only after touching the UI.

