"""Lint a reference script: the rules of "The rules for a reference script" (README.md), read from the script's AST.

    .venv/bin/python fixtures/reference/lint.py <board name>

The script is parsed, never run. It is found in fixtures/reference/boards/<name>/. Every declaration (a placement, a
link or a piece of copper) is listed with its basis, and a problem is any of:
- coordinate: a number that says where a part goes (`Location`, a numeric `Centre`, `Pin(key, x, y)`, an `X()`/`Y()` with
  an offset, `OnEdge(along=<number>)`, `.point()`/`.local()`/`.offset()`, a bare `(x, y)`) on a part the manifest does not
  list as fixed, or in the points of copper (track, via, pour...), a keepout or a push;
- no_why: a declaration with no `why=`;
- basis: a `why=` that does not start with one of BASES followed by a colon (a `figure`'s: `datasheet:`);
- steering: `priority=`, `Priority`, `Near(` or an order call, which no basis permits;
- syntax: the script does not parse.

Exits 1 on any problem.
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import pathlib
import sys

if __package__ in (None, ""):   # run as a script: the repository root, for `fixtures.reference`
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fixtures.reference import fetch   # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
BOARDS_DIR = HERE / "boards"
BASES = ("mechanical", "datasheet", "physics", "capture")
# Calls that declare something: each takes `why=`.
DECLARING = frozenset({"place", "row", "ring", "link", "push", "track", "pair", "via", "vias", "stitch", "pour", "plane",
                       "finger", "keepout", "figure", "fanout", "escape", "rule", "group", "unit", "exclude", "accept"})
# Declarations that put parts: the first argument names them (a list for row and ring).
PLACING = {"place": "at", "row": "start", "ring": None, "escape": None, "fanout": None}
ORDER_CALLS = frozenset({"order", "before", "after"})   # on `board`
STEERING_KEYWORDS = frozenset({"priority", "order"})
# Calls whose points are positions of copper or sources; a typed one is never allowed, as no part is fixed there.
POINTED = frozenset({"track", "pair", "via", "vias", "stitch", "pour", "plane", "finger", "keepout", "push"})
COORDINATE_OFFSETS = frozenset({"point", "local", "offset"})   # methods whose numbers are typed positions


@dataclasses.dataclass(frozen=True)
class Decl:
    line: int
    call: str
    refs: tuple[str, ...]
    basis: str | None   # one of BASES, or None when `why=` is missing or has no basis
    coordinate: bool


@dataclasses.dataclass(frozen=True)
class Problem:
    line: int
    rule: str   # coordinate, no_why, basis, steering or syntax
    ref: str
    detail: str = ""


@dataclasses.dataclass
class LintReport:
    script: pathlib.Path
    declarations: list[Decl]
    problems: list[Problem]


class LintError(Exception):
    pass


def _name(node: ast.AST) -> str | None:
    """The called name of `Part(...)` or `board.place(...)`."""
    if isinstance(node, ast.Call):
        f = node.func
        return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
    return None


def _is_number(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, ast.UnaryOp):
        return _is_number(node.operand)
    if isinstance(node, ast.BinOp):
        return _is_number(node.left) and _is_number(node.right)
    return False


def _assignments(tree: ast.Module) -> dict[str, ast.AST]:
    return {t.id: s.value for s in tree.body if isinstance(s, ast.Assign) and len(s.targets) == 1
            and isinstance(t := s.targets[0], ast.Name)}


def _expand(node: ast.AST, assigns: dict[str, ast.AST], seen: frozenset = frozenset()):
    """The nodes under `node`, following a module-level name to the value it is assigned."""
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in assigns and n.id not in seen:
            yield from _expand(assigns[n.id], assigns, seen | {n.id})
        else:
            yield n


def _resolve(node: ast.AST, assigns: dict[str, ast.AST]) -> ast.AST:
    seen = set()
    while isinstance(node, ast.Name) and node.id in assigns and node.id not in seen:
        seen.add(node.id)
        node = assigns[node.id]
    return node


def _coordinate_forms(node: ast.AST, assigns: dict[str, ast.AST]) -> list[str]:
    """The typed positions in `node`, each as source text."""
    found = []
    for n in _expand(node, assigns):
        if not isinstance(n, ast.Call):
            continue
        name = _name(n)
        values = list(n.args) + [k.value for k in n.keywords]
        if name == "Location" and any(_is_number(m) for v in values for m in _expand(v, assigns)):
            found.append(ast.unparse(n))
        elif name == "Centre" and (any(_is_number(v) for v in n.args[:2]) or any(
                k.arg == "coordinates" and isinstance(k.value, ast.Constant) and k.value.value is True for k in n.keywords)):
            found.append(ast.unparse(n))
        elif name == "Pin" and len(n.args) >= 3 and any(_is_number(v) for v in n.args[1:]):
            found.append(ast.unparse(n))
        elif name in ("X", "Y") and isinstance(n.func, ast.Name) and (len(n.args) >= 2 or n.keywords):
            found.append(ast.unparse(n))
        elif name == "OnEdge":
            along = next((k.value for k in n.keywords if k.arg == "along"), n.args[1] if len(n.args) > 1 else None)
            if along is not None and (_is_number(along) or _name(along) == "Fraction"):
                found.append(ast.unparse(n))
        elif name in COORDINATE_OFFSETS and isinstance(n.func, ast.Attribute) and any(_is_number(v) for v in values):
            found.append(ast.unparse(n))
    return found


def _refs(node: ast.AST | None, assigns: dict[str, ast.AST]) -> tuple[str, ...]:
    """The references a placement names: `Part("j1")` and `Cell("mcu")` by name, anything else by its source."""
    if node is None:
        return ()
    node = _resolve(node, assigns)
    if isinstance(node, (ast.List, ast.Tuple)):
        return tuple(r for e in node.elts for r in _refs(e, assigns))
    if _name(node) in ("Part", "Cell") and node.args and isinstance(node.args[0], ast.Constant) \
            and isinstance(node.args[0].value, str):
        return (node.args[0].value,)
    return (ast.unparse(node),)


def _why_text(node: ast.AST, assigns: dict[str, ast.AST]) -> str | None:
    """The start of a `why=` that can be read without running anything, else None."""
    node = _resolve(node, assigns)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        first = node.values[0] if node.values else None
        return first.value if isinstance(first, ast.Constant) else ""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _why_text(node.left, assigns)
    return None


def _basis(text: str | None) -> str | None:
    return next((b for b in BASES if text is not None and text.startswith(b + ":")), None)


def _steering(node: ast.AST) -> list[tuple[ast.AST, str]]:
    """The steering under `node`: the node it is found at, and what it is."""
    found = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id == "Priority":
            found.append((n, "Priority"))
        elif _name(n) == "Near":
            found.append((n, "Near("))
        elif isinstance(n, ast.Call):
            found += [(k.value, k.arg + "=") for k in n.keywords if k.arg in STEERING_KEYWORDS]
            if _name(n) in ORDER_CALLS and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "board":
                found.append((n, "board.%s(" % _name(n)))
    return found


def lint(script: pathlib.Path, fixed) -> LintReport:
    """Read `script` and report its declarations and problems. `fixed` are the references a coordinate is allowed on."""
    script = pathlib.Path(script)
    held = {r.lower() for r in fixed}
    try:
        tree = ast.parse(script.read_text(), filename=str(script))
    except SyntaxError as e:
        return LintReport(script, [], [Problem(e.lineno or 1, "syntax", "", e.msg)])
    assigns = _assignments(tree)
    decls: list[Decl] = []
    problems: dict[tuple, Problem] = {}

    def problem(line, rule, ref, detail=""):
        problems.setdefault((line, rule, ref), Problem(line, rule, ref, detail))

    covered: set[int] = set()
    for node in ast.walk(tree):
        name = _name(node)
        if name not in DECLARING or not isinstance(node.func, ast.Attribute):
            continue
        covered.update(id(n) for n in ast.walk(node))
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        refs = _refs(kw.get("item") or (node.args[0] if node.args else None), assigns) if name in PLACING else ()
        why = kw.get("why")
        text = _why_text(why, assigns) if why is not None else None
        basis = _basis(text)
        forms = _coordinate_forms(node, assigns)
        where = kw.get(PLACING.get(name) or "at") if name in PLACING else None
        if where is None and name == "place" and len(node.args) > 1:
            where = node.args[1]
        if where is not None:
            where = _resolve(where, assigns)
            if isinstance(where, ast.Tuple) and len(where.elts) == 2 and all(_is_number(e) for e in where.elts):
                forms.append(ast.unparse(where))
        decls.append(Decl(node.lineno, name, refs, basis, bool(forms)))
        ref = ",".join(refs)
        if why is None:
            problem(node.lineno, "no_why", ref)
        elif basis is None and name != "figure":
            problem(node.lineno, "basis", ref, "why starts %r" % (text[:24] if text is not None else "(not a literal)"))
        if forms and name in PLACING:
            for r in refs:
                if r.lower() not in held:
                    problem(node.lineno, "coordinate", r, forms[0])
        elif forms and name in POINTED:
            problem(node.lineno, "coordinate", "", forms[0])
        if name == "figure" and why is not None and not (text or "").startswith("datasheet:"):
            problem(node.lineno, "basis", ref, "a figure's why starts datasheet:, got %r" % (text or "")[:24])
        for at, what in _steering(node):
            problem(at.lineno, "steering", ref, what)
    for at, what in _steering(tree):   # outside any declaration: a constant, a helper
        if id(at) not in covered:
            problem(at.lineno, "steering", "", what)
    return LintReport(script, sorted(decls, key=lambda d: d.line), sorted(problems.values(), key=lambda p: (p.line, p.rule)))


def find_script(name: str, boards_dir: pathlib.Path = BOARDS_DIR) -> pathlib.Path:
    """The layout script of a board: the one .py in its folder."""
    folder = pathlib.Path(boards_dir) / name
    if not folder.is_dir():
        raise LintError("%s: no reference script folder %s" % (name, folder))
    scripts = sorted(folder.glob("*.py"))
    if len(scripts) != 1:
        raise LintError("%s: %s holds %d .py files, expected one layout script" % (name, folder, len(scripts)))
    return scripts[0]


def _fixed_of(name: str) -> tuple[str, ...]:
    for board in fetch.load_manifest():
        if board.name == name:
            return board.fixed
    raise LintError("%s: not a board of the manifest" % name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lint a reference script.")
    ap.add_argument("board", help="board name; its script is under fixtures/reference/boards/<name>/")
    ap.add_argument("--boards-dir", type=pathlib.Path, default=BOARDS_DIR)
    ap.add_argument("--fixed", help="comma-separated references held fixed, instead of the manifest's")
    args = ap.parse_args(argv)
    try:
        script = find_script(args.board, args.boards_dir)
        fixed = [r for r in args.fixed.split(",") if r] if args.fixed is not None else _fixed_of(args.board)
    except LintError as e:
        print(e)
        return 1
    report = lint(script, fixed)
    by_basis: dict[str, list[Decl]] = {}
    for d in report.declarations:
        by_basis.setdefault(d.basis or "no basis", []).append(d)
    for basis, decls in by_basis.items():
        print("%s (%d)" % (basis, len(decls)))
        for d in decls:
            print("  line %d %s %s%s" % (d.line, d.call, " ".join(d.refs), "  [coordinate]" if d.coordinate else ""))
    for p in report.problems:
        print("%s:%d: %s %s%s" % (script.name, p.line, p.rule, p.ref, " - " + p.detail if p.detail else ""))
    print("%d declarations, %d problems" % (len(report.declarations), len(report.problems)))
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
