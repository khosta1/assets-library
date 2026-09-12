"""Plan-driven bulk import, one asset at a time, from a terminal.

This is a command line, and the command line was removed on purpose
(`docs/History/cli-removed.md`). It comes back here for one job only, at
Felix's instruction (2026-09-13), and the scope is the point:

    it imports a folder of assets against a PLAN THAT ALREADY EXISTS
    it declares nothing itself - every type and category comes from the plan
    it writes only with --apply, one asset per invocation
    it has no other subcommands and must not grow any

The reason it exists rather than the Add window: a porting run is an agent
driving 37 imports while a person reads what each one did. The window is built
for a person doing it; this is built for a person *checking* it. Anything that
is a decision still belongs in the window.

`assetlib` does the work. This file only sequences it, which is why it is 300
lines and not 3 000 - the old CLI's mistake was growing logic of its own.

    port.py plan                 (re)build the plan from the source folder
    port.py status               what is done, what is left
    port.py next                 show the next asset's plan. WRITES NOTHING.
    port.py apply <folder>       import that one asset
    port.py set <folder> --type T --category C     amend the plan
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from assetlib import analyse, index as idx                     # noqa: E402
from assetlib.commit import commit                             # noqa: E402
from assetlib.config import find_config                        # noqa: E402
from assetlib.model import Asset                               # noqa: E402

PLAN = Path("context/port-plan.json")
LOG = Path("port.log")


# --------------------------------------------------------------------- state


def state_path(cfg) -> Path:
    """Per-copy state, beside the index. Not in the plan file.

    The plan is a statement of intent and is regenerated freely; what has
    already been imported is a fact about this disk and must survive that.
    """
    return cfg.state / "port-state.json"


def read_state(cfg) -> dict:
    try:
        return json.loads(state_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"done": {}}


def write_state(cfg, state: dict) -> None:
    state_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    state_path(cfg).write_text(json.dumps(state, indent=2), encoding="utf-8")


def read_plan() -> dict:
    if not PLAN.is_file():
        raise SystemExit(f"no plan at {PLAN} - run: port.py plan")
    return json.loads(PLAN.read_text(encoding="utf-8"))


def log(line: str) -> None:
    """Everything, to a file Felix can watch while this runs."""
    stamp = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp}  {line}\n")
    print(line)


def human(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ---------------------------------------------------------------------- plan


def build_plan(cfg, root: Path, declarations: dict) -> dict:
    """analyse() every candidate. READ-ONLY - invariant 3, nothing is written."""
    assets, skipped = [], []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        files = [p for p in folder.rglob("*") if p.is_file()]
        if not files:
            skipped.append([folder.name, "empty folder"])
            continue
        if not any(p.suffix.lower() in (".fbx", ".gltf") for p in files):
            why = ("usdz only" if any(p.suffix.lower() == ".usdz" for p in files)
                   else "no mesh")
            skipped.append([folder.name, why])
            continue
        dec = declarations.get(folder.name)
        if not dec:
            skipped.append([folder.name, "NO DECLARATION - add one with `set`"])
            continue
        if dec.get("skip"):
            skipped.append([folder.name, dec.get("why") or "skipped by hand"])
            continue
        plan = analyse.analyse(folder, cfg, type_hint=dec["type"],
                               category_hint=dec["category"])
        keep = [a for a in plan.actions if a.action == "keep"]
        assets.append({
            "folder": folder.name,
            "name": plan.name,
            "type": dec["type"],
            "category": dec["category"],
            "src_files": len(files),
            "src_bytes": sum(p.stat().st_size for p in files),
            "geo": sorted(a.dest for a in keep if (a.dest or "").startswith("geo/")),
            "tex": sorted(a.dest for a in keep if (a.dest or "").startswith("tex/")),
            "derived": sum(1 for a in keep if (a.dest or "").startswith("derived/")),
            "extra": sum(1 for a in plan.actions if a.action == "bonus"),
            "reject": sum(1 for a in plan.actions if a.action == "reject"),
            "kept_bytes": sum(a.size or 0 for a in keep),
            "warnings": plan.warnings,
        })
    return {"root": str(root), "built": datetime.now(timezone.utc).isoformat(),
            "assets": assets, "skipped": skipped}


def show(entry: dict, cfg, verbose: bool = True) -> None:
    """What this asset becomes. The thing Felix is actually verifying."""
    name = entry["name"]
    print("=" * 72)
    print(f"{entry['folder']}")
    print(f"  ->  library/{entry['type']}/{entry['category']}/{name}/")
    print(f"  {entry['src_files']} source file(s), {human(entry['src_bytes'])}"
          f"   ->   kept {human(entry['kept_bytes'])}")

    dest = cfg.library / entry["type"] / entry["category"] / name
    if dest.exists():
        print(f"  !! {dest} ALREADY EXISTS - commit would create a _02 beside it")

    geo, tex = entry["geo"], entry["tex"]
    print(f"  geo      {len(geo)}")
    if verbose:
        for g in geo[:8]:
            print(f"             {Path(g).name}")
        if len(geo) > 8:
            print(f"             … {len(geo) - 8} more")
    print(f"  tex      {len(tex)}")
    if verbose:
        for t in tex:
            print(f"             {Path(t).name}")
    print(f"  derived  {entry['derived']}")
    print(f"  extra    {entry['extra']}")
    print(f"  reject   {entry['reject']}")
    for w in entry["warnings"]:
        print(f"  !  {w}")


# ------------------------------------------------------------------ commands


def cmd_plan(args, cfg) -> None:
    decl = json.loads(Path(args.declarations).read_text(encoding="utf-8"))
    plan = build_plan(cfg, Path(decl["root"]), decl["assets"])
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    kept = sum(a["kept_bytes"] for a in plan["assets"])
    src = sum(a["src_bytes"] for a in plan["assets"])
    print(f"{len(plan['assets'])} asset(s) planned, {len(plan['skipped'])} skipped")
    print(f"source {human(src)} -> kept {human(kept)}")
    print(f"written to {PLAN}")


def remaining(plan: dict, state: dict) -> list:
    return [a for a in plan["assets"] if a["folder"] not in state["done"]]


def cmd_status(args, cfg) -> None:
    plan, state = read_plan(), read_state(cfg)
    left = remaining(plan, state)
    done = len(plan["assets"]) - len(left)
    print(f"{done} / {len(plan['assets'])} imported, {len(left)} left")
    for a in left[:10]:
        print(f"   next: {a['folder']:<42} {a['type']}/{a['category']}")
        break
    for folder, info in state["done"].items():
        print(f"   done: {folder:<42} {info['dest']}")


def cmd_next(args, cfg) -> None:
    """Show the next asset and stop. The whole point of stepping."""
    plan, state = read_plan(), read_state(cfg)
    left = remaining(plan, state)
    if not left:
        print("nothing left - every asset in the plan is imported")
        return
    entry = left[0]
    show(entry, cfg)
    print()
    print(f"  approve with:  port.py apply {entry['folder']}")
    print(f"  or amend:      port.py set {entry['folder']} --category <name>")
    print(f"  {len(left)} of {len(plan['assets'])} remaining")


def cmd_set(args, cfg) -> None:
    """Amend one asset's DECLARATION, then rebuild the plan from it.

    Writes to the declarations file, not to the plan. The plan is derived and
    is regenerated on every `plan` run, so an amendment made there survives
    until the next one and then silently vanishes - which is the worst failure
    a migration can have, because the asset imports with the value you thought
    you had changed.

    `--skip` lives here rather than as a sixth subcommand: skipping IS a
    declaration about an asset, and the decision recorded for this tool says
    five subcommands and no more. A flag on the command that already edits
    declarations is the honest place for it.
    """
    path = Path(args.declarations)
    decl = json.loads(path.read_text(encoding="utf-8"))
    entry = decl["assets"].get(args.folder)
    if entry is None:
        raise SystemExit(f"{args.folder} has no declaration")

    if args.skip:
        entry["skip"] = True
        if args.why:
            entry["why"] = args.why
    if args.unskip:
        entry.pop("skip", None)
        entry.pop("why", None)
    if args.type:
        entry["type"] = args.type
    if args.category:
        entry["category"] = args.category
    if not entry.get("skip") and not cfg.valid_category(entry["type"], entry["category"]):
        raise SystemExit(
            f"{entry['category']!r} is not valid for {entry['type']!r}: "
            + ", ".join(cfg.categories_for(entry["type"])))

    path.write_text(json.dumps(decl, indent=2), encoding="utf-8")
    if entry.get("skip"):
        print(f"{args.folder} -> SKIPPED ({entry.get('why') or 'by hand'})")
    else:
        print(f"{args.folder} -> {entry['type']}/{entry['category']}")

    plan = build_plan(cfg, Path(decl["root"]), decl["assets"])
    PLAN.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"plan rebuilt: {len(plan['assets'])} to import, {len(plan['skipped'])} skipped")


def cmd_apply(args, cfg) -> None:
    """Import exactly one asset, re-analysing rather than trusting the plan.

    The plan is a report, not an instruction set: it was built from a read-only
    pass and the source could have moved since. analyse() runs again here with
    the plan's DECLARATIONS - which is the only part a person authored - so
    what is written is always derived from the files that exist right now.
    """
    plan, state = read_plan(), read_state(cfg)
    entry = next((a for a in plan["assets"] if a["folder"] == args.folder), None)
    if entry is None:
        raise SystemExit(f"{args.folder} is not in the plan")
    if entry["folder"] in state["done"]:
        raise SystemExit(f"{args.folder} is already imported - see `status`")

    source = Path(plan["root"]) / entry["folder"]
    fresh = analyse.analyse(source, cfg, type_hint=entry["type"],
                            category_hint=entry["category"])

    if not args.apply:
        show(entry, cfg)
        print("\n  DRY RUN - nothing written. Add --apply to import.")
        return

    log(f"IMPORT {entry['folder']} -> {entry['type']}/{entry['category']}")
    asset_dir = commit(fresh, cfg)
    asset = Asset.read(asset_dir)

    conn = idx.connect(cfg)
    idx.upsert(conn, asset, asset_dir, cfg.library)
    conn.close()

    state["done"][entry["folder"]] = {
        "dest": str(asset_dir.relative_to(cfg.library)).replace("\\", "/"),
        "uuid": asset.uuid,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    write_state(cfg, state)

    files = [p for p in asset_dir.rglob("*") if p.is_file()]
    log(f"  OK {asset_dir.relative_to(cfg.library)}  "
        f"{len(files)} file(s), {human(sum(p.stat().st_size for p in files))}, "
        f"uuid {asset.uuid}")
    left = len(remaining(plan, state))
    log(f"  {len(plan['assets']) - left}/{len(plan['assets'])} done, {left} left")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="(re)build the plan - writes nothing to library/")
    p.add_argument("declarations", help="json: {root, assets:{folder:{type,category}}}")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("status", help="what is done and what is left")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("next", help="show the next asset. Writes nothing.")
    p.set_defaults(fn=cmd_next)

    p = sub.add_parser("set", help="amend one asset's declaration, and replan")
    p.add_argument("folder")
    p.add_argument("--declarations", default="port-declarations.json")
    p.add_argument("--type")
    p.add_argument("--category")
    p.add_argument("--skip", action="store_true", help="do not import this one")
    p.add_argument("--unskip", action="store_true")
    p.add_argument("--why", help="note recorded beside a --skip")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("apply", help="import one asset")
    p.add_argument("folder")
    p.add_argument("--apply", action="store_true",
                   help="actually write - without it this is a dry run")
    p.set_defaults(fn=cmd_apply)

    args = ap.parse_args()
    args.fn(args, find_config(Path(__file__).resolve().parent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
