#!/usr/bin/env python3
"""Generate docs/codemap.html : a structural map of the source.

Answers the questions that otherwise cost a file read each -- what types exist,
what fields they hold, which file defines what, what includes what, and where
the weight is -- for the price of one page in a browser.

No compiler, no language server, no dependency. Two backends:

    .py                 exact, via the stdlib `ast`
    .h .hpp .c .cpp     structural, via patterns -- good enough to navigate,
                        not a parser. It will miss a macro-generated type and
                        it does not care.

    python tools/codemap.py                 auto-detect the source roots
    python tools/codemap.py src engine      explicit roots

Output: docs/codemap.html, gitignored -- regenerate, never commit. A map of
code that has moved is worse than no map, because it is believed.
"""

import ast
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "codemap.html"

SKIP_DIRS = {".git", ".venv", "venv", "runtime", "build", "build-prof", "dist",
             "__pycache__", "node_modules", "context", "third_party", "extern",
             "vendor", ".claude"}

CPP_EXT = {".h", ".hpp", ".hh", ".c", ".cpp", ".cc", ".cxx", ".inl"}
PY_EXT = {".py"}


# --------------------------------------------------------------------------
# Python backend -- ast, so it is exact and stays exact.
# --------------------------------------------------------------------------

def parse_python(path, rel):
    src = path.read_text(encoding="utf-8", errors="replace")
    entry = {"rel": rel, "lines": src.count("\n") + 1, "lang": "py",
             "imports": [], "types": [], "funcs": []}
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        entry["error"] = "syntax error line %s" % exc.lineno
        return entry

    for node in tree.body:
        if isinstance(node, ast.Import):
            entry["imports"] += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            entry["imports"].append(node.module)
        elif isinstance(node, ast.ClassDef):
            entry["types"].append(parse_py_class(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entry["funcs"].append({"name": node.name, "line": node.lineno,
                                   "sig": py_signature(node),
                                   "doc": first_line(ast.get_docstring(node))})
    return entry


def parse_py_class(node):
    t = {"kind": "class", "name": node.name, "line": node.lineno,
         "doc": first_line(ast.get_docstring(node)),
         "bases": [ast.unparse(b) for b in node.bases],
         "fields": [], "methods": []}
    for item in node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            t["fields"].append({
                "type": ast.unparse(item.annotation),
                "name": item.target.id,
                "default": ast.unparse(item.value) if item.value else "",
                "line": item.lineno})
        elif isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    t["fields"].append({"type": "", "name": target.id,
                                        "default": ast.unparse(item.value),
                                        "line": item.lineno})
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            t["methods"].append({"name": item.name, "line": item.lineno,
                                 "sig": py_signature(item),
                                 "doc": first_line(ast.get_docstring(item))})
            # A field first assigned in __init__ is still a field; it is the
            # normal way Python objects are shaped, and omitting them would
            # make the map useless for exactly the classes that matter.
            if item.name == "__init__":
                t["fields"] += init_fields(item)
    return t


def init_fields(func):
    out = []
    for node in ast.walk(func):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"):
                out.append({
                    "type": ast.unparse(node.annotation) if isinstance(node, ast.AnnAssign) and node.annotation else "",
                    "name": target.attr,
                    "default": ast.unparse(node.value) if node.value else "",
                    "line": node.lineno})
    return out


def py_signature(node):
    try:
        args = ast.unparse(node.args)
    except Exception:
        args = "..."
    ret = " -> " + ast.unparse(node.returns) if node.returns else ""
    return "(%s)%s" % (args, ret)


def first_line(doc):
    return doc.strip().splitlines()[0] if doc else ""


# --------------------------------------------------------------------------
# C / C++ backend -- patterns. Structural, not semantic: it reads the shape of
# a header the way a person skimming it does.
# --------------------------------------------------------------------------

INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"')
TYPE_OPEN_RE = re.compile(
    r"^\s*(?:template\s*<[^>]*>\s*)?"
    r"(struct|class|union)\s+([A-Za-z_]\w*)\s*"
    r"(?::\s*[^{]*)?\{")
ENUM_RE = re.compile(r"^\s*enum\s+(?:class\s+|struct\s+)?([A-Za-z_]\w*)[^;{]*\{")
FIELD_RE = re.compile(
    r"^\s*(?:(?:mutable|static|inline|constexpr|const|volatile|thread_local)\s+)*"
    r"([A-Za-z_][\w:]*(?:\s*<[^;]*>)?(?:\s*(?:\*|&|const))*)\s+"
    r"([A-Za-z_]\w*)\s*((?:\[[^\]]*\])*)\s*"
    r"(?:=\s*(.+?)\s*)?;\s*$")
FUNC_RE = re.compile(
    r"^\s*(?:(?:static|inline|constexpr|virtual|explicit|friend)\s+)*"
    r"(?:([\w:<>,\s\*&]+?)\s+)?([A-Za-z_~]\w*)\s*\(([^;{]*)\)\s*"
    r"(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?(?:\{|;|$)")
KEYWORDS = {"if", "for", "while", "switch", "return", "else", "do", "catch",
            "sizeof", "case", "using", "namespace", "template", "typedef"}


def strip_comment(line):
    """Remove a trailing // comment and hand it back -- it documents the field."""
    in_str = False
    for i, ch in enumerate(line):
        if ch == '"' and (i == 0 or line[i - 1] != "\\"):
            in_str = not in_str
        elif not in_str and ch == "/" and line[i:i + 2] == "//":
            return line[:i].rstrip(), line[i + 2:].strip()
    return line, ""


def parse_cpp(path, rel):
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    entry = {"rel": rel, "lines": len(lines), "lang": "cpp",
             "imports": [], "types": [], "funcs": []}

    current = None          # the type whose body we are inside
    depth = 0               # brace depth inside that type
    pending_doc = []        # // lines immediately above a declaration

    for n, raw in enumerate(lines, 1):
        line, trailing = strip_comment(raw)
        stripped = line.strip()

        if raw.strip().startswith("//"):
            pending_doc.append(raw.strip()[2:].strip())
            continue

        inc = INCLUDE_RE.match(raw)
        if inc:
            entry["imports"].append(inc.group(1))
            pending_doc = []
            continue

        if current is None:
            m = TYPE_OPEN_RE.match(line)
            if m:
                current = {"kind": m.group(1), "name": m.group(2), "line": n,
                           "doc": " ".join(pending_doc)[:160],
                           "bases": [], "fields": [], "methods": []}
                depth = line.count("{") - line.count("}")
                pending_doc = []
                if depth <= 0:                     # one-liner
                    entry["types"].append(current)
                    current = None
                continue

            m = ENUM_RE.match(line)
            if m:
                entry["types"].append({"kind": "enum", "name": m.group(1),
                                       "line": n, "doc": " ".join(pending_doc)[:160],
                                       "bases": [], "fields": [], "methods": []})
                pending_doc = []
                continue

            m = FUNC_RE.match(line)
            if m and m.group(2) not in KEYWORDS and stripped:
                entry["funcs"].append({"name": m.group(2), "line": n,
                                       "sig": "(%s)" % m.group(3).strip(),
                                       "doc": " ".join(pending_doc)[:160]})
            pending_doc = []
            continue

        # --- inside a type body ---
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            entry["types"].append(current)
            current = None
            pending_doc = []
            continue

        m = FUNC_RE.match(line)
        if m and m.group(2) not in KEYWORDS:
            current["methods"].append({"name": m.group(2), "line": n,
                                       "sig": "(%s)" % m.group(3).strip(),
                                       "doc": (trailing or " ".join(pending_doc))[:160]})
            pending_doc = []
            continue

        m = FIELD_RE.match(line)
        if m and m.group(1).split()[0] not in KEYWORDS:
            current["fields"].append({
                "type": m.group(1).strip() + (m.group(3) or ""),
                "name": m.group(2),
                "default": (m.group(4) or "").strip(),
                "doc": (trailing or " ".join(pending_doc))[:160],
                "line": n})
        pending_doc = []

    return entry


# --------------------------------------------------------------------------

def find_roots(argv):
    if argv:
        return [ROOT / a for a in argv]
    for name in ("src", "source", "lib", "app"):
        if (ROOT / name).is_dir():
            return [ROOT / name]
    return [ROOT]


def collect(roots):
    files = []
    for root in roots:
        if not root.exists():
            print("  skipped, not found: %s" % root)
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in CPP_EXT | PY_EXT:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            rel = path.relative_to(ROOT).as_posix()
            files.append(parse_python(path, rel) if path.suffix in PY_EXT
                         else parse_cpp(path, rel))
    return files


# --------------------------------------------------------------------------

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>codemap - %(project)s</title>
<style>
:root { color-scheme: light dark; --bg:#fff; --fg:#1a1a1a; --dim:#6b7280;
        --line:#e5e7eb; --accent:#2563eb; --chip:#f3f4f6; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16181d; --fg:#e5e7eb; --dim:#9096a2; --line:#2a2e37;
          --accent:#7aa2f7; --chip:#232730; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:13px/1.55
       ui-monospace, SFMono-Regular, Consolas, monospace; }
header { position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line);
         padding:12px 20px; display:flex; gap:14px; align-items:baseline; flex-wrap:wrap; }
h1 { font-size:15px; margin:0; font-weight:600; }
#q { flex:1; min-width:200px; padding:6px 10px; border:1px solid var(--line);
     border-radius:6px; background:var(--chip); color:var(--fg); font:inherit; }
.stats { color:var(--dim); }
main { padding:16px 20px 80px; }
details { border-bottom:1px solid var(--line); }
summary { cursor:pointer; padding:7px 0; display:flex; gap:10px; align-items:baseline; }
summary::-webkit-details-marker { display:none; }
summary b { font-weight:600; }
.n { color:var(--dim); font-size:11px; }
.body { padding:4px 0 14px 18px; }
.t { margin:10px 0 4px; }
.t b { color:var(--accent); }
table { border-collapse:collapse; width:100%%; max-width:1100px; }
td { padding:1px 10px 1px 0; vertical-align:top; }
td.ty { color:var(--dim); white-space:nowrap; }
td.df { color:var(--dim); }
td.dc { color:var(--dim); font-style:italic; }
.m { color:var(--dim); }
.m b { color:var(--fg); font-weight:500; }
.chips { display:flex; flex-wrap:wrap; gap:4px; margin:4px 0; }
.chip { background:var(--chip); border-radius:4px; padding:1px 6px; font-size:11px;
        color:var(--dim); }
.hidden { display:none; }
</style>
<header>
  <h1>codemap &middot; %(project)s</h1>
  <input id="q" placeholder="filter files, types, fields, functions...">
  <span class="stats" id="stats"></span>
</header>
<main id="out"></main>
<script>
const DATA = %(data)s;
const out = document.getElementById('out'), q = document.getElementById('q');

function esc(s){ return (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function renderType(t){
  let h = '<div class="t"><b>' + esc(t.kind) + ' ' + esc(t.name) + '</b>';
  if (t.bases && t.bases.length) h += ' <span class="n">: ' + esc(t.bases.join(', ')) + '</span>';
  h += ' <span class="n">L' + t.line + '</span>';
  if (t.doc) h += ' <span class="dc">' + esc(t.doc) + '</span>';
  h += '</div>';
  if (t.fields.length){
    h += '<table>';
    for (const f of t.fields)
      h += '<tr><td class="ty">' + esc(f.type) + '</td><td>' + esc(f.name) + '</td>'
         + '<td class="df">' + (f.default ? '= ' + esc(f.default) : '') + '</td>'
         + '<td class="dc">' + esc(f.doc || '') + '</td></tr>';
    h += '</table>';
  }
  if (t.methods.length){
    h += '<div class="chips">';
    for (const m of t.methods) h += '<span class="chip">' + esc(m.name + m.sig) + '</span>';
    h += '</div>';
  }
  return h;
}

function render(filter){
  const f = (filter||'').toLowerCase();
  let shown = 0, lines = 0;
  out.innerHTML = DATA.map(file => {
    const blob = JSON.stringify(file).toLowerCase();
    if (f && !blob.includes(f)) return '';
    shown++; lines += file.lines;
    let h = '<details' + (f ? ' open' : '') + '><summary><b>' + esc(file.rel) + '</b>'
          + '<span class="n">' + file.lines + ' lines &middot; '
          + file.types.length + ' types &middot; ' + file.funcs.length + ' functions</span></summary>'
          + '<div class="body">';
    if (file.imports.length){
      h += '<div class="chips">';
      for (const i of file.imports) h += '<span class="chip">' + esc(i) + '</span>';
      h += '</div>';
    }
    for (const t of file.types) h += renderType(t);
    if (file.funcs.length){
      h += '<div class="t"><b>functions</b></div><div class="m">';
      for (const fn of file.funcs)
        h += '<div><b>' + esc(fn.name) + '</b>' + esc(fn.sig)
           + ' <span class="n">L' + fn.line + '</span> ' + esc(fn.doc || '') + '</div>';
      h += '</div>';
    }
    return h + '</div></details>';
  }).join('');
  document.getElementById('stats').textContent =
    shown + ' files, ' + lines.toLocaleString() + ' lines';
}

q.addEventListener('input', () => render(q.value));
render('');
</script>
"""


def main():
    roots = find_roots([a for a in sys.argv[1:] if not a.startswith("-")])
    print("reading: " + ", ".join(str(r.relative_to(ROOT)) if r != ROOT else "."
                                  for r in roots))
    files = collect(roots)
    if not files:
        sys.exit("no source files found -- pass the source directory explicitly")

    files.sort(key=lambda f: -f["lines"])
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(PAGE % {
        "project": html.escape(ROOT.name),
        "data": json.dumps(files, ensure_ascii=False),
    }, encoding="utf-8")

    total = sum(f["lines"] for f in files)
    types = sum(len(f["types"]) for f in files)
    print("  -> %s   %d files, %s lines, %d types   (%d kb)"
          % (OUT.relative_to(ROOT), len(files), "{:,}".format(total), types,
             OUT.stat().st_size // 1024))


if __name__ == "__main__":
    main()
