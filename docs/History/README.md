<!-- TEMPLATE ------------------------------------------------------------
Keep this README in the folder. It defines what belongs here and in what
shape. The folder itself fills up by /retire.
--------------------------------------------------------------------- -->

# History — removed code, and why

Code that was built, worked or half-worked, and was taken out. One file per
removal, written **at the moment of removal** — never reconstructed later, when
the reasons have softened into "it wasn't great".

**Check this folder before proposing an idea.** Half of what an agent proposes
on a mature project has already been tried here.

---

## What goes in

- A subsystem or feature that was deleted, with the argument for deleting it.
- A design that was built, measured, and lost to a simpler one.
- A roadmap or doc that has been superseded — moved here, with a line at the
  top saying what replaced it and when. **Archived is not the same as wrong**;
  say which it is.
- The working code itself, quoted, when re-implementing it would otherwise mean
  re-deriving it. A removed feature whose problem has not gone away is the
  strongest candidate.

## What does not

- Fixed bugs. That is `gotchas.md`.
- Ideas never built. That is `decisions.md`, *Rejected — do not reopen*.
- Anything git already tells you plainly. The value here is the **argument**,
  not the diff.

---

## The shape of an entry

```markdown
# {{What it was}}

Removed {{YYYY-MM-DD}} ({{commit}}).

## What it did
{{Enough that a reader can judge whether the problem is the one they have.}}

## Why it went
{{The argument. Be specific: what it cost, what replaced it, what stopped
being true. "It was complex" is not an argument.}}

## What the problem was, and whether it has gone away
{{The critical half. A feature removed because its problem disappeared stays
removed. A feature removed because something else covered it comes straight
back when that something else changes — and then this file is the spec.}}

## The code
{{Quoted, if re-deriving it would be expensive.}}
```

---

## Naming

`{{subject}}.md`, lower case, one subject per file — `river-graph.md`,
`mobile-props-removed.md`, `world-forge.md`. A second file on the same subject
means the first one was not finished.
