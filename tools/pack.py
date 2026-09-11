#!/usr/bin/env python3
"""Generate context/*.md : the code flattened into documents an agent can read.

Drives repomix through npx, so nothing is installed permanently.

The point is that a SINGLE document does not work on a real project: a medium
source tree exceeds a context window, and the half that gets truncated is
chosen by the tool rather than by you. So the code is cut into PER-TOPIC packs,
each of which fits comfortably, and the one matching today's work is the one
that gets attached.

Packs are declared in packs.json at the project root -- never in this file.
That is what makes this script copyable between projects unchanged.

    python tools/pack.py              every pack except 'all'
    python tools/pack.py water        one pack
    python tools/pack.py --list       what each pack contains, and why
    python tools/pack.py --all        including 'all', which is usually too big

Output: context/<name>.md, gitignored -- regenerate after a big move. A stale
pack is a confident description of code that no longer exists.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "context"
PACKS_FILE = ROOT / "packs.json"

# Above this, a pack is two topics wearing a trenchcoat. Not an error -- some
# projects genuinely have one large subsystem -- but it is worth being told.
BIG_PACK_TOKENS = 80_000


def load_packs():
    if not PACKS_FILE.exists():
        sys.exit("no packs.json at %s -- copy the one from the template" % PACKS_FILE)

    with PACKS_FILE.open(encoding="utf-8") as fh:
        raw = json.load(fh)

    # Keys starting with '_' are comments: JSON has none, and a config file
    # nobody can annotate is a config file nobody edits correctly.
    packs = {k: v for k, v in raw.items() if not k.startswith("_")}

    if "brief" not in packs:
        sys.exit("packs.json has no 'brief' pack. It is mandatory: it is what "
                 "gets attached first, always.")
    return packs


def run_pack(name, spec):
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / (name + ".md")
    patterns = spec["include"]

    cmd = [
        "npx", "-y", "repomix@latest",
        "--style", "markdown",
        "--include", ",".join(patterns),
        "-o", str(out),
    ]
    # shell=True on Windows: npx is a .cmd, not an .exe, and CreateProcess
    # will not run it directly.
    proc = subprocess.run(
        cmd, cwd=str(ROOT), shell=(sys.platform == "win32"),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        print("  FAILED:", (proc.stderr or proc.stdout).strip()[-400:])
        return

    tokens = parse_tokens(proc.stdout or "")
    size_kb = out.stat().st_size // 1024 if out.exists() else 0
    flag = ""
    if tokens and tokens > BIG_PACK_TOKENS:
        flag = "   <-- over %dk, consider splitting" % (BIG_PACK_TOKENS // 1000)
    print("  -> context/%s.md   %s tokens   (%d kb)%s"
          % (name, "{:,}".format(tokens) if tokens else "?", size_kb, flag))


def parse_tokens(stdout):
    """Pull the token count out of repomix's summary.

    repomix separates thousands with a narrow no-break space, which the Windows
    console (cp1252) cannot encode -- hence stripping everything non-digit
    rather than parsing the number as printed.
    """
    for line in stdout.splitlines():
        if "Total Tokens" not in line:
            continue
        raw = line.split(":", 1)[1]
        raw = re.sub(r"\x1b\[[0-9;]*m", "", raw)          # colour codes
        digits = re.sub(r"[^\d]", "", raw.split("tokens")[0])
        return int(digits) if digits else None
    return None


def main():
    packs = load_packs()
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]

    if "--list" in flags:
        width = max(len(k) for k in packs)
        for name, spec in packs.items():
            print("%-*s  %s" % (width, name, spec.get("description", "")))
            print("%s  %s" % (" " * width, ", ".join(spec["include"])))
        return

    if args:
        wanted = args
    elif "--all" in flags:
        wanted = list(packs)
    else:
        # 'all' is opt-in: it exists to be measured, not routinely attached.
        wanted = [k for k in packs if k != "all"]

    for name in wanted:
        if name not in packs:
            print("unknown pack: %s   (try --list)" % name)
            continue
        print("%s : %s" % (name, packs[name].get("description", "")))
        run_pack(name, packs[name])


if __name__ == "__main__":
    main()
