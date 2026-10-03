"""The .zen dialect of the splicing editor: the facts a board's `.zen` holds (its stackup and its pair net classes), edited as
minimal splices of the file's own text.

A `.zen` is Zener source, which writes calls and lists the way Python does, so `ast` gives every node's position and
`script_edit`'s `Src` and `_Seq` give the layout of what is written (the same machinery the layout scripts use). The edit
names a `Board(name=...)` call and follows `config` -> `BoardConfig` -> `stackup` -> `Stackup` -> `layers`, or `config` ->
`BoardConfig` -> `design_rules` -> `DesignRules` -> `netclasses`. Each step must be a literal call; one that is a name, a merge
or a function result is not edited, and the refusal names the expression. A missing branch is made in place, and the names it
needs are added to the file's `load("@stdlib/board_config.zen", ...)` (a line of its own where there is none).

What is written follows the file: a keyword is written as the file writes the keywords of the `Board(...)` call (`a = 1` or
`a=1`), new elements take the indent of their neighbours, a number is a literal with a comment saying where it came from.
Two checks stand between an edit and the caller: the edited text must parse, and the `ast` of everything outside `Board(config=)`
and the `load(...)` statements must equal the original's."""
from __future__ import annotations

import ast
import re

from .script_edit import (EditRefused, Src, _call_seq, _list_seq, _nl_of, _parse, _splice, _func_name)

STDLIB_CONFIG = "@stdlib/board_config.zen"
BUILDER_NOTE = "chosen in the studio's board builder"
DEFAULT_MATERIAL = "FR4"      # a dielectric names a material of the stackup's `materials` list: the generator refuses one that is not there
OZ_MM = 0.035                  # one ounce per square foot of copper is 35 um, the figure fabs quote


def oz_to_mm(oz: float) -> float:
    return round(float(oz) * OZ_MM, 4)


def mm_to_oz(mm: float):
    """The standard weight a thickness is (0.5, 1, 2 oz and the like), else None."""
    oz = float(mm) / OZ_MM
    for std in (0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        if abs(oz - std) < 0.01:
            return std
    return None


# ------------------------------------------------------------------ finding things
def _top_calls(mod, func: str) -> list:
    """The calls of `func` that are statements of the module (bare, or assigned to a name)."""
    out = []
    for st in mod.tree.body:
        v = st.value if isinstance(st, (ast.Expr, ast.Assign)) else None
        if isinstance(v, ast.Call) and _func_name(v) == func:
            out.append(v)
    return out


def _kw(call, name):
    return next((k for k in call.keywords if k.arg == name), None)


def _literal_name(call):
    k = _kw(call, "name")
    return k.value.value if k is not None and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str) else None


def board_call(mod, name: str):
    """The one `Board(name=<name>)` call of the file."""
    boards = _top_calls(mod, "Board")
    hits = [c for c in boards if _literal_name(c) == name]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        others = [c for c in _top_calls(mod, "Project") + _top_calls(mod, "Layout") if _literal_name(c) == name]
        if others:
            raise EditRefused("%s is declared with %s(...), which has no config= to hold a stackup or net classes: the facts "
                              "belong in a Board(config=)" % (name, _func_name(others[0])))
        raise EditRefused("the file has no Board(name=%r) at its top level" % name)
    raise EditRefused("the file declares Board(name=%r) %d times, not once" % (name, len(hits)))


def _expr(src: Src, node) -> str:
    return src.code(node)


def _step(src: Src, call, kw: str, func: str):
    """The literal `func(...)` call that `call` gives as `kw=`, or None where it does not give it."""
    k = _kw(call, kw)
    if k is None:
        return None
    if not (isinstance(k.value, ast.Call) and _func_name(k.value) == func):
        raise EditRefused("%s= is %s, not a literal %s(...): it is not edited there" % (kw, _expr(src, k.value), func))
    return k.value


def _leaf(src: Src, call, kw: str):
    """The list the call gives as `kw=` (a literal list), or None."""
    k = _kw(call, kw)
    if k is None:
        return None
    if not isinstance(k.value, ast.List):
        raise EditRefused("%s= is %s, not a literal list: it is not edited there" % (kw, _expr(src, k.value)))
    return k.value


def _style(src: Src, board) -> str:
    """How the file writes a keyword's `=`: the text between the name and the value of a keyword of the `Board(...)` call."""
    for k in board.keywords:
        s = src.off(k.value.lineno, k.value.col_offset)
        m = re.search(r"(\s*=\s*)$", src.text[max(0, s - 6):s])
        if m:
            return m.group(1)
    return " = "


# ------------------------------------------------------------------ rendering
def _num(v) -> str:
    return repr(round(float(v), 6))


def _layer_source(row: dict, sep: str, extra: str = "") -> str:
    kind = row["kind"]
    if kind == "copper":
        return "CopperLayer(thickness%s%s, role%s%s)" % (sep, _num(row["thickness_mm"]), sep, '"%s"' % row["role"])
    form = ", form%s%s" % (sep, '"%s"' % row["form"]) if row.get("form") else ""
    mat = ", material%s%s" % (sep, '"%s"' % row["material"]) if row.get("material") else extra
    return "DielectricLayer(thickness%s%s%s%s)" % (sep, _num(row["thickness_mm"]), mat, form)


def _note_of(row: dict) -> str:
    if row.get("note"):
        return row["note"]
    return "%s oz" % ("%g" % row["oz"]) if row.get("oz") else BUILDER_NOTE


def _validate_rows(rows) -> None:
    if not rows:
        raise EditRefused("a stackup has at least one layer")
    for r in rows:
        if r.get("kind") not in ("copper", "dielectric"):
            raise EditRefused("a stackup layer is copper or dielectric, not %r" % (r.get("kind"),))
        t = r.get("thickness_mm")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or t <= 0:
            raise EditRefused("a layer's thickness is a positive number of mm, not %r" % (t,))
        if r["kind"] == "copper" and r.get("role") not in ("signal", "power", "mixed", "ground"):
            raise EditRefused("a copper layer's role is signal, power, mixed or ground, not %r" % (r.get("role"),))
        if r["kind"] == "dielectric" and r.get("form") not in (None, "core", "prepreg"):
            raise EditRefused("a dielectric is core or prepreg, not %r" % (r.get("form"),))
        if r["kind"] == "dielectric" and not r.get("material"):
            r["material"] = DEFAULT_MATERIAL


# ------------------------------------------------------------------ loads
def _loaded(mod) -> dict:
    """{name: the load call's module path} of every `load(path, "Name", ...)` statement."""
    out = {}
    for st in mod.tree.body:
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and _func_name(st.value) == "load":
            args = st.value.args
            if args and isinstance(args[0], ast.Constant):
                for a in args[1:]:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        out[a.value] = args[0].value
                for k in st.value.keywords:
                    out[k.arg] = args[0].value
    return out


def _ensure_loads(text: str, names) -> str:
    """`text` loading each of `names` from board_config.zen: added to its `load` of that file, or a `load` line of its own
    after the last `load` (at the top where there is none)."""
    mod = _parse(text)
    have = _loaded(mod)
    need = [n for n in names if n not in have]
    if not need:
        return text
    src = mod.src
    for st in mod.tree.body:
        v = st.value if isinstance(st, ast.Expr) else None
        if isinstance(v, ast.Call) and _func_name(v) == "load" and v.args and isinstance(v.args[0], ast.Constant) \
                and v.args[0].value == STDLIB_CONFIG:
            seq = _call_seq(src, v)
            out = text
            splices = seq.append(", ".join('"%s"' % n for n in need))
            return _splice(out, splices)
    nl = _nl_of(text)
    line = 'load("%s", %s)%s' % (STDLIB_CONFIG, ", ".join('"%s"' % n for n in need), nl)
    loads = [st for st in mod.tree.body if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
             and _func_name(st.value) == "load"]
    if loads:
        end = loads[-1].end_lineno
        at = src.starts[end] if end < len(src.starts) else len(text)
        if at == len(text) and not text.endswith("\n"):
            return text + nl + line
        return _splice(text, [(at, at, line)])
    # none yet: after a header comment that is set off by a blank line (it describes the file), else at the top
    lines = text.splitlines(keepends=True)
    k = 0
    while k < len(lines) and lines[k].lstrip().startswith("#"):
        k += 1
    at = 0
    if 0 < k < len(lines) and lines[k].strip() == "":
        while k < len(lines) and lines[k].strip() == "":
            k += 1
        at = sum(len(l) for l in lines[:k])
        return _splice(text, [(at, at, line + nl)])
    return _splice(text, [(at, at, line + nl)])


# ------------------------------------------------------------------ the check
def _mask(tree, name: str):
    """The tree with the `load(...)` statements and the `config=` of `Board(name=<name>)` taken out."""
    body = []
    for st in tree.body:
        v = st.value if isinstance(st, (ast.Expr, ast.Assign)) else None
        if isinstance(st, ast.Expr) and isinstance(v, ast.Call) and _func_name(v) == "load":
            continue
        if isinstance(v, ast.Call) and _func_name(v) == "Board" and _literal_name(v) == name:
            v.keywords = [k for k in v.keywords if k.arg not in ("config", "layers")]
        body.append(st)
    return ast.dump(ast.Module(body, []))


def _check(before: str, after: str, name: str, what: str) -> None:
    try:
        new = ast.parse(after)
    except SyntaxError as e:
        raise EditRefused("the edited file would not parse: %s" % e)
    if _mask(ast.parse(before), name) != _mask(new, name):
        raise EditRefused("the edit would change more than the board's %s" % what)


# ------------------------------------------------------------------ making a missing branch
def _chain(path, leaf: str, sep: str) -> str:
    """The source of `kw = Func(kw = Func(... leaf = [])))` for the steps of `path`, a list of (keyword, function)."""
    text = "%s%s%s(" % (path[0][0], sep, path[0][1])
    close = ")"
    for kw, fn in path[1:]:
        text += "%s%s%s(" % (kw, sep, fn)
        close += ")"
    return text + "%s%s[]%s" % (leaf, sep, close)


def _ensure_branch(text: str, name: str, path, leaf: str) -> str:
    """`text` with the path from the `Board(...)` call to the list `leaf` made where it is missing: the first missing step is
    added to the call that lacks it, with the rest of the chain inside it and an empty list at the end."""
    mod = _parse(text)
    board = board_call(mod, name)
    sep = _style(mod.src, board)
    call, k = board, 0
    while k < len(path):
        nxt = _step(mod.src, call, path[k][0], path[k][1])
        if nxt is None:
            return _splice(text, _call_seq(mod.src, call).append(_chain(path[k:], leaf, sep)))
        call, k = nxt, k + 1
    if _leaf(mod.src, call, leaf) is None:
        return _splice(text, _call_seq(mod.src, call).append("%s%s[]" % (leaf, sep)))
    return text


def _find_list(text: str, name: str, path, leaf: str):
    mod = _parse(text)
    call = board_call(mod, name)
    for kw, fn in path:
        call = _step(mod.src, call, kw, fn)
        if call is None:
            return mod, None, None
    return mod, call, _leaf(mod.src, call, leaf)


STACKUP = (("config", "BoardConfig"), ("stackup", "Stackup"))
DESIGN = (("config", "BoardConfig"), ("design_rules", "DesignRules"))


def _indent_for(src: Src, node) -> str:
    return src.indent_of(src.span(node)[0])


def _rewrite_list(mod, lst, items: list, step: str = "    ") -> list:
    """The splice that gives the list `lst` exactly `items` ((source, trailing comment)), one to a line, indented a step in from
    the line the list opens on (or as its first element is where it has some)."""
    src = mod.src
    s, e = src.span(lst)
    nl = src.newline_at(s)
    ind = src.indent_of(s)
    if lst.elts and src.text[src.line_start(src.span(lst.elts[0])[0]):src.span(lst.elts[0])[0]].strip() == "":
        inner = src.indent_of(src.span(lst.elts[0])[0])
    else:
        inner = ind + step
    body = "".join("%s%s,%s%s" % (inner, text, "  # " + note if note else "", nl) for text, note in items)
    return [(s, e, "[" + nl + body + ind + "]")]


# ------------------------------------------------------------------ the stackup
def _number(node):
    return float(node.value) if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
        and not isinstance(node.value, bool) else None


def _string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _row_of(call) -> dict | None:
    """A stackup element as a row, or None where it is not a literal CopperLayer or DielectricLayer."""
    f = _func_name(call)
    if f not in ("CopperLayer", "DielectricLayer") or call.args:
        return None
    kws = {k.arg: k.value for k in call.keywords}
    t = _number(kws.get("thickness"))
    if t is None:
        return None
    if f == "CopperLayer":
        role = _string(kws.get("role"))
        return {"kind": "copper", "thickness_mm": t, "role": role} if role else None
    return {"kind": "dielectric", "thickness_mm": t, "form": _string(kws.get("form")), "material": _string(kws.get("material"))}


def read_stackup(text: str, name: str):
    """The board's stackup layers as rows, `{"kind", "thickness_mm", "role"|"form", "oz"}`, or None where the file declares
    none or declares it in a form that is not literal (the reason is `stackup_state`)."""
    try:
        mod, _call, lst = _find_list(text, name, STACKUP, "layers")
    except EditRefused:
        return None
    if lst is None:
        return None
    rows = []
    for el in lst.elts:
        r = _row_of(el) if isinstance(el, ast.Call) else None
        if r is None:
            return None
        if r["kind"] == "copper":
            r["oz"] = mm_to_oz(r["thickness_mm"])
        rows.append(r)
    return rows


def stackup_state(text: str, name: str) -> dict:
    """Whether and how the board's `.zen` declares its stackup: `{"state": "literal"}` (a literal `Stackup(layers=[...])` in the
    `Board`'s own `config=`, which the builder edits), `"none"` (none declared: the generator's default is what the board has),
    `"elsewhere"` (declared through a name, a merge or a function: not edited here, with the expression in `why`) or `"unreadable"`
    (the file is not Python-readable, with the reason)."""
    try:
        mod = _parse(text)
        board = board_call(mod, name)
    except EditRefused as e:
        return {"state": "unreadable", "why": e.reason}
    src = mod.src
    cfg = _kw(board, "config")
    if cfg is None:
        return {"state": "none"}
    if not (isinstance(cfg.value, ast.Call) and _func_name(cfg.value) == "BoardConfig"):
        return {"state": "elsewhere", "why": "config= is %s" % src.code(cfg.value)}
    st = _kw(cfg.value, "stackup")
    if st is None:
        return {"state": "none"}
    if not (isinstance(st.value, ast.Call) and _func_name(st.value) == "Stackup"):
        return {"state": "elsewhere", "why": "stackup= is %s" % src.code(st.value)}
    lay = _kw(st.value, "layers")
    if lay is None:
        return {"state": "none"}
    if not isinstance(lay.value, ast.List):
        return {"state": "elsewhere", "why": "layers= is %s" % src.code(lay.value)}
    return {"state": "literal"}


def read_copper_layers(text: str, name: str):
    """The `layers=` the Board call gives, or None."""
    try:
        call = board_call(_parse(text), name)
    except EditRefused:
        return None
    k = _kw(call, "layers")
    return int(k.value.value) if k is not None and isinstance(k.value, ast.Constant) and isinstance(k.value.value, int) else None


def stackup_edit(text: str, name: str, rows: list, copper_layers: int | None = None) -> str:
    """`text` with the board's stackup layers given by `rows`. Layers that are as asked are left as they are, comments included;
    a layer that differs is rewritten (its `material=` kept) with the comment saying where the weight came from; a different
    number of layers rewrites the list."""
    _validate_rows(rows)
    original = text
    need = ["BoardConfig", "Stackup", "CopperLayer"] + (["DielectricLayer"] if any(r["kind"] == "dielectric" for r in rows) else [])
    text = _ensure_branch(text, name, STACKUP, "layers")
    mod, call, lst = _find_list(text, name, STACKUP, "layers")
    src = mod.src
    sep = _style(src, board_call(mod, name))
    have = [(_row_of(el) if isinstance(el, ast.Call) else None) for el in lst.elts]
    same_shape = len(have) == len(rows) and all(h is not None and h["kind"] == r["kind"] for h, r in zip(have, rows))
    if same_shape:
        seq = _list_seq(src, lst) if lst.elts else None
        splices = []
        for i, (el, h, r) in enumerate(zip(lst.elts, have, rows)):
            same = abs(h["thickness_mm"] - r["thickness_mm"]) < 1e-9 and (h.get("role") == r.get("role") if r["kind"] == "copper"
                                                                          else (h.get("form") == r.get("form") and h.get("material") == r.get("material")))
            if same:
                continue
            extra = ""
            mat = _kw(el, "material")
            if mat is not None:
                extra = ", material%s%s" % (sep, src.code(mat.value))
            es, ee = src.span(el)
            splices.append((es, ee, _layer_source(r, sep, extra)))
            it = seq.items[i]
            new_note = _note_of(r) if r["kind"] == "copper" else BUILDER_NOTE
            if it.note:
                splices.append((it.note[0], it.note[1], "# " + new_note))
            else:
                splices.append(seq._tack(it, "# " + new_note))
        out = _splice(text, splices) if splices else text
    else:
        items = [(_layer_source(r, sep), _note_of(r) if r["kind"] == "copper" else BUILDER_NOTE) for r in rows]
        out = _splice(text, _rewrite_list(mod, lst, items))
    if copper_layers is not None:
        out = _set_copper_layers(out, name, copper_layers)
    mats = {r["material"]: r.get("permittivity") for r in rows if r["kind"] == "dielectric"}
    if mats:
        out = _ensure_materials(out, name, mats)
        need.append("Material")
    out = _ensure_loads(out, need)
    _check(original, out, name, "stackup")
    return out


def _ensure_materials(text: str, name: str, wanted: dict) -> str:
    """The Stackup's `materials=` list naming each material a dielectric uses (the generator refuses one that is not listed): the list made,
    or the missing ones added, each `Material(name = ...)` with the relative permittivity where the user gave it."""
    mod, call, _lst = _find_list(text, name, STACKUP, "layers")
    sep = _style(mod.src, board_call(mod, name))

    def element(n, perm):
        return "Material(name%s%s%s)" % (sep, '"%s"' % n, (", relative_permittivity%s%s" % (sep, _num(perm))) if perm else "")
    k = _kw(call, "materials")
    if k is None:
        return _splice(text, _call_seq(mod.src, call).append("materials%s[%s]" % (sep, ", ".join(element(n, p) for n, p in wanted.items()))))
    if not isinstance(k.value, ast.List):
        raise EditRefused("materials= is %s, not a literal list: it is not edited there" % mod.src.code(k.value))
    have = set()
    for e in k.value.elts:
        if isinstance(e, ast.Call) and _func_name(e) == "Material":
            n = _literal_name(e)
            if n:
                have.add(n)
    out = text
    for n, p in wanted.items():
        if n in have:
            continue
        mod, call, _l = _find_list(out, name, STACKUP, "layers")
        k = _kw(call, "materials")
        out = _splice(out, _list_seq(mod.src, k.value).append(element(n, p)))
    return out


def _set_copper_layers(text: str, name: str, n: int) -> str:
    mod = _parse(text)
    board = board_call(mod, name)
    k = _kw(board, "layers")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise EditRefused("the copper layer count is a whole number of 1 or more, not %r" % (n,))
    if k is None:
        return _splice(text, _call_seq(mod.src, board).append("layers%s%d" % (_style(mod.src, board), n)))
    if not (isinstance(k.value, ast.Constant) and isinstance(k.value.value, int)):
        raise EditRefused("layers= is %s, not a literal number: it is not edited there" % mod.src.code(k.value))
    if k.value.value == n:
        return text
    s, e = mod.src.span(k.value)
    return _splice(text, [(s, e, str(n))])


# ------------------------------------------------------------------ pair net classes
def _class_of(call) -> dict | None:
    if _func_name(call) != "NetClass" or call.args:
        return None
    kws = {k.arg: k.value for k in call.keywords}
    nets = kws.get("nets")
    if isinstance(nets, ast.List) and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in nets.elts):
        nets = [e.value for e in nets.elts]
    else:
        nets = None
    return {"name": _string(kws.get("name")), "diff_pair_width": _number(kws.get("diff_pair_width")),
            "diff_pair_gap": _number(kws.get("diff_pair_gap")), "nets": nets, "has_pair": "diff_pair_width" in kws
            or "diff_pair_gap" in kws}


def read_netclasses(text: str, name: str):
    """The pair classes the board's `design_rules.netclasses` lists, `{"name", "diff_pair_width", "diff_pair_gap", "nets"}`; []
    where it lists none, None where the file declares the list in a form that is not literal."""
    try:
        mod, _call, lst = _find_list(text, name, DESIGN, "netclasses")
    except EditRefused:
        return None
    if lst is None:
        return []
    out = []
    for el in lst.elts:
        c = _class_of(el) if isinstance(el, ast.Call) else None
        if c is not None and c["has_pair"]:
            out.append({k: c[k] for k in ("name", "diff_pair_width", "diff_pair_gap", "nets")})
    return out


def _class_source(c: dict, sep: str, ind: str, nl: str) -> str:
    nets = "[%s]" % ", ".join('"%s"' % n for n in c["nets"])
    step = "    "
    return nl.join(["NetClass(", "%sname%s\"%s\"," % (ind + step, sep, c["name"]),
                    "%sdiff_pair_width%s%s,  # %s" % (ind + step, sep, _num(c["diff_pair_width"]), BUILDER_NOTE),
                    "%sdiff_pair_gap%s%s,  # %s" % (ind + step, sep, _num(c["diff_pair_gap"]), BUILDER_NOTE),
                    "%snets%s%s," % (ind + step, sep, nets), "%s)" % ind])


def _validate_classes(classes) -> None:
    seen = set()
    for c in classes:
        if not c.get("name") or c["name"] in seen or c["name"] == "Default":
            raise EditRefused("a pair class has a name of its own (not repeated, not Default): %r" % (c.get("name"),))
        seen.add(c["name"])
        for key in ("diff_pair_width", "diff_pair_gap"):
            v = c.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                raise EditRefused("%s of %s is a positive number of mm, not %r" % (key, c["name"], v))
        if len(c.get("nets") or ()) != 2 or len(set(c["nets"])) != 2:
            raise EditRefused("a pair class has exactly its two nets: %s has %r" % (c["name"], c.get("nets")))


def netclasses_edit(text: str, name: str, classes: list) -> str:
    """`text` with the board's pair net classes exactly `classes` (`{"name", "diff_pair_width", "diff_pair_gap", "nets"}`):
    a pair class of the file that is not among them is removed, one that is has what differs set, the rest are added; a class
    that is not a pair class (no `diff_pair_*`) is left as it is."""
    _validate_classes(classes)
    original = text
    if classes:
        text = _ensure_branch(text, name, DESIGN, "netclasses")
    mod, call, lst = _find_list(text, name, DESIGN, "netclasses")
    if lst is None:
        return text
    want = {c["name"]: c for c in classes}
    # existing elements first, last to first so offsets hold: re-read after each splice
    keep = set()
    for el in lst.elts:
        c = _class_of(el) if isinstance(el, ast.Call) else None
        if c is not None and c["has_pair"] and c["name"] in want:
            keep.add(c["name"])
    drop = [i for i, el in enumerate(lst.elts) if isinstance(el, ast.Call) and (_class_of(el) or {}).get("has_pair")
            and (_class_of(el) or {}).get("name") not in want]
    out = text
    for i in reversed(drop):
        mod, call, lst = _find_list(out, name, DESIGN, "netclasses")
        out = _splice(out, _list_seq(mod.src, lst).remove(i)[0])
    # set what differs on the ones kept, a keyword at a time, the text read again after each
    for cname in sorted(keep):
        r = want[cname]
        for key in ("diff_pair_width", "diff_pair_gap", "nets"):
            mod, call, lst = _find_list(out, name, DESIGN, "netclasses")
            el = next(e for e in lst.elts if isinstance(e, ast.Call) and (_class_of(e) or {}).get("name") == cname)
            sep = _style(mod.src, board_call(mod, name))
            cur, val = _class_of(el), r[key]
            text_ = "[%s]" % ", ".join('"%s"' % n for n in val) if key == "nets" else _num(val)
            k = _kw(el, key)
            if k is None:
                out = _splice(out, _call_seq(mod.src, el).append("%s%s%s" % (key, sep, text_)))
            elif (cur[key] != val) if key == "nets" or cur[key] is None else abs(cur[key] - val) > 1e-9:
                s_, e_ = mod.src.span(k.value)
                out = _splice(out, [(s_, e_, text_)])
    # add the new ones at the end
    for c in classes:
        if c["name"] in keep:
            continue
        mod, call, lst = _find_list(out, name, DESIGN, "netclasses")
        sep = _style(mod.src, board_call(mod, name))
        seq = _list_seq(mod.src, lst) if lst.elts else None
        src = mod.src
        if seq is not None and seq.items:
            ref = next((it for it in reversed(seq.items) if seq.first_on_line(it)), None)
            ind = src.indent_of(ref.s) if ref is not None else src.indent_of(src.span(lst)[0])
        else:
            ind = src.indent_of(src.span(lst)[0]) + "    "
        item = _class_source(c, sep, ind, src.newline_at(src.span(lst)[0]))
        if seq is None:
            out = _splice(out, _rewrite_list(mod, lst, [(item, "")]))
            # the element source carries its own indent for continuation lines; _rewrite_list indents the first line
        else:
            out = _splice(out, seq.append(item))
    need = (["BoardConfig", "DesignRules", "NetClass"] if classes else [])
    out = _ensure_loads(out, need)
    _check(original, out, name, "net classes")
    return out
