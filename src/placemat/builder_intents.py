"""The builder's intents: for a subject and a target, the menu of relations that can be written, each as the structured edits that
write it (a suggestion without a finding); searching the rest; changing and taking off a placed item.

Every statement is a call placemat already has (`board.place`, `board.link`, `board.row`), written the way the repository's scripts
write them. A place is an edge, a relation or a reference: never a `Location`, a numeric `Centre`, a `.local()` or `.offset()`.
A number the user types (a gap, a link's limit, a radius) is a named constant whose comment says who chose it and why."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import builder_parts as bp, script_edit as se
from .builder import (BUILDER, EDGES, BuilderRefused, _cell, _enum, _form, _identifier, _name, _part, _str, _Names, wrap)
from .suggestions import Edit, FileChange, Suggestion, Target

SEARCHED_NOTE = "Searched from their links."
ALONGS = ("START", "MID", "END")
FACES = ("BACK", "EITHER")
PRIORITIES = ("HIGH", "LOW")
TURNS = (0, 90, 180, 270)


# ------------------------------------------------------------------ the context a request is answered in
class Ctx:
    """What a request is made against: the script and the files it reads (as the plan saw them), the generated board's parts and
    cells, the plan, the parts list built from them, and the outline."""

    def __init__(self, texts: dict, script: str, plan: dict | None, board: dict):
        self.texts = texts                                   # {name as the plan names it: text}
        self.script = Path(script).resolve()
        self.base = self.script.parent
        self.name = next((n for n in texts if Path(self.base / n).resolve() == self.script), self.script.name)
        self.text = texts[self.name]
        self.plan, self.board = plan, board
        self.listing = bp.parts_rows(board, plan, texts, self.base, script_name=self.name)
        self.rows = {r["key"]: r for r in self.listing["rows"]}
        self.outline = bp.read_outline(self.text)
        self.digests = {str(self.script): se.digest(self.text)}
        self.parts = {p["key"]: p for p in board["parts"]}
        self.cells = {c["key"]: c for c in board["cells"]}
        self.bound_items, self.use_names = self._spelling()
        self.plain = self._plain()

    # -------- the script as it is written
    def _spelling(self) -> tuple:
        """({item key: the name the script binds it to (`U1 = Part("u1")`)}, whether the script writes its parts by those names): a script
        that places by name, or has bindings and no literal, gets the name; one that mixes, or writes literals, gets the literal."""
        import ast
        mod = se._parse(self.text)
        bound = {}
        for st in mod.tree.body:
            v = st.value if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name) else None
            if isinstance(v, ast.Call) and se._func_name(v) in ("Part", "Cell") and v.args and isinstance(v.args[0], ast.Constant) \
                    and isinstance(v.args[0].value, str):
                bound.setdefault(v.args[0].value, st.targets[0].id)
        names = literals = 0
        for st in mod.tree.body:
            c = st.value if isinstance(st, ast.Expr) else None
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in ("place", "row", "ring") and c.args:
                a = c.args[0]
                items = a.elts if isinstance(a, (ast.List, ast.Tuple)) else [a]
                for it in items:
                    if isinstance(it, ast.Name):
                        names += 1
                    elif isinstance(it, ast.Call):
                        literals += 1
        return bound, bool(bound) and literals == 0

    def _plain(self) -> bool:
        """Whether the script is of the shape the builder writes (a header, constants, bindings and board calls at the top level, no loop
        or function): its statements go in the decided and searched regions. Any other is a hand-written script, and a statement goes
        after the right statement of it (`insertion_anchor`)."""
        import ast
        ok = (ast.Assign, ast.Import, ast.ImportFrom)
        for st in se._parse(self.text).tree.body:
            if isinstance(st, ok) or se._is_docstring(st):
                continue
            c = st.value if isinstance(st, ast.Expr) else None
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name) and c.func.value.id == "board":
                continue
            return False
        return True

    def module_level(self, line: int) -> bool:
        return any(st.lineno == line for st in se._parse(self.text).tree.body)

    def insertion_anchor(self, refs: dict):
        """Where a new statement goes in a hand-written script, as `(a Target to insert after, None)` or `(None, a region)`: after the
        statement that declares what it names (the last of them, when it names several) if that is at the top level; else after the last
        top-level `place`, `row`, `ring` or `block`; else after the outline; and where the only placements are in functions or loops, at
        the end of the module."""
        import ast
        cands = [t for t in refs.values() if t.file == str(self.script) and self.module_level(t.line)]
        if cands:
            return max(cands, key=lambda t: t.line), None
        last = None
        for st in se._parse(self.text).tree.body:
            c = st.value if isinstance(st, (ast.Expr, ast.Assign)) else None
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in ("place", "row", "ring", "block") \
                    and se._stands_alone(se._parse(self.text).src, st):
                last = (c.func.attr, st.lineno)
        if last is not None:
            return Target(last[0], "", str(self.script), last[1], 1, se.digest(self.text)), None
        if self.outline["kind"] is not None and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("place", "row")
                                                  for n in ast.walk(se._parse(self.text).tree)):
            return None, "end"
        return None, "outline"

    # -------- naming
    def label(self, key) -> str:
        r = self.rows.get(key)
        return r["ref"] if r else key

    def form(self, key) -> dict:
        """An item written inline, `Part("u1")`: or, where the script writes its parts by the names it binds, that name."""
        if self.use_names and key in self.bound_items:
            return _name(self.bound_items[key])
        return _cell(key) if key in self.cells else _part(key)

    def abs(self, name) -> str:
        return str(Path(self.base / name).resolve())

    def declared(self, key):
        """The `place` declaration of `key` as a Target, where the script declares it by a statement the builder reads."""
        r = self.rows.get(key)
        if r is None or not r["line"] or r["status"] in ("unplaced", "by hand") and not r["file"]:
            return None
        text = self.texts.get(r["file"])
        if text is None or se.site_calls(text, r["line"])[:1] != ["place"] or not self.module_level(r["line"]) or r["file"] != self.name:
            return None
        shared = sum(1 for o in self.rows.values() if o["file"] == r["file"] and o["line"] == r["line"])
        return Target("place", key, self.abs(r["file"]), r["line"], shared, se.digest(text))

    def item(self, key, refs: dict) -> dict:
        """An item as an expression: the script's own spelling of it where it declares it, else written inline."""
        t = self.declared(key)
        if t is not None and t.shared == 1:
            refs[key] = t
            return {"item": key}
        return self.form(key)

    def pad_key(self, key, number=None, net=None):
        """How a pad is written: by net where the part has exactly one pad on it, else by number."""
        part = self.parts[key]
        if net is not None:
            on = [p for p in part["pad_list"] if p["net"] == net]
            if len(on) == 1:
                return {"str": net}
            if on:
                number = on[0]["number"]
        num = str(number)
        return {"num": int(num)} if num.isdigit() else {"str": num}

    def padref(self, key, pad, refs):
        part = self.parts.get(key)
        if part is None:
            raise BuilderRefused("%s is not a part: a pad is a pad of a part, not of a cell" % self.label(key))
        by_net = next((p for p in part["pad_list"] if p["net"] == pad.get("net")), None) if pad.get("net") else None
        return _form("PadRef", self.item(key, refs), self.pad_key(key, pad.get("number"), pad.get("net") if by_net else None))

    # -------- the geometry of what is placed (for choosing a side by where a pad lands)
    def item_doc(self, key):
        return next((i for i in (self.plan or {}).get("items", ()) if i["key"] == key), None)


# ------------------------------------------------------------------ edits from expressions
def _names_in(v, out: set) -> None:
    if isinstance(v, dict):
        if "form" in v and not v["form"].startswith("board."):
            out.add(v["form"].split(".")[0])
        if "enum" in v:
            out.add(v["enum"].split(".")[0])
        for x in v.values():
            _names_in(x, out)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _names_in(x, out)


def imports_for(ctx, *values) -> Edit | None:
    """The edit that has the script import the names the expressions use (`ensure_import` skips what it already imports)."""
    names: set = set()
    for v in values:
        _names_in(v, names)
    names.discard("board")
    return Edit("ensure_import", None, {"names": sorted(names)}, None, {}, str(ctx.script)) if names else None


def _with_file(edit: Edit, file: str) -> Edit:
    from dataclasses import replace
    return replace(edit, file=file) if not edit.file and edit.target is None else edit


def _suggestion(ctx: Ctx, text: str, edits: list) -> Suggestion:
    return Suggestion(text=text, edits=tuple(_with_file(e, str(ctx.script)) for e in edits), lever="builder",
                      digests=dict(ctx.digests))


def preview(ctx: Ctx, s: Suggestion) -> dict:
    """What the suggestion writes, in memory: the statements added or changed (text only), and the whole new text. Nothing is read from
    disk and nothing is written."""
    texts = {ctx.abs(n): t for n, t in ctx.texts.items()}
    changed = se.apply_edits(s.edits, lambda p: texts[str(Path(p).resolve())] if str(Path(p).resolve()) in texts else (_ for _ in ()).throw(OSError(p)))
    out = {}
    for path, (before, after) in changed.items():
        fc = FileChange(path, before, after)
        lines = after.splitlines()
        out[path] = {"added": [lines[n - 1] for n in fc.new_lines], "removed": [(before or "").splitlines()[n - 1] for n in fc.old_lines],
                     "text": after}
    return out


# ------------------------------------------------------------------ checks on a request
def depends_on(ctx: Ctx, key: str, on: str, seen=None) -> bool:
    """Whether `key` is placed by a relation to `on`, directly or through a chain of them."""
    seen = seen or set()
    if key in seen:
        return False
    seen.add(key)
    rel = (ctx.rows.get(key) or {}).get("relation") or {}
    refs = [rel.get("target")] + [x["item"] for x in (rel.get("pad"), rel.get("align_pad"), rel.get("side_of")) if x]
    for r in refs:
        if r == on or (r and depends_on(ctx, r, on, seen)):
            return True
    return False


def check_request(ctx: Ctx, subjects: list, target: dict | None) -> None:
    if not subjects:
        raise BuilderRefused("choose what to place first")
    for k in subjects:
        if k not in ctx.rows:
            raise BuilderRefused("%s is not a part or a cell of this board" % k)
    if target is None:
        return
    kind = target.get("kind")
    if kind in ("part", "pad"):
        t = target.get("key")
        if t not in ctx.rows:
            raise BuilderRefused("%s is not a part or a cell of this board" % t)
        if t in subjects:
            raise BuilderRefused("a part is not placed by itself", "a target is another item")
        if ctx.rows[t]["status"] == "unplaced":
            raise BuilderRefused("%s is not placed yet, so there is no place to be beside: place it first" % ctx.label(t),
                                 "an unplaced item is not a target")
        for k in subjects:
            if depends_on(ctx, t, k):
                raise BuilderRefused("%s is placed by a relation to %s, so %s cannot be placed by a relation to it" % (
                    ctx.label(t), ctx.label(k), ctx.label(k)), "a target that depends on the subject is not offered")
    elif kind == "edge":
        if ctx.outline["kind"] == "fit":
            raise BuilderRefused("a fit frame's outline is derived from its content, so it has no edges to place on")
    else:
        raise BuilderRefused("a target is an edge, a part or a pad, or none")


def _own_pads(ctx: Ctx, subject: str, other_pad: dict) -> list:
    """The subject's pads on the net of `other_pad`."""
    part = ctx.parts.get(subject)
    if part is None:
        return []
    return [p for p in part["pad_list"] if p["net"] and p["net"] == other_pad.get("net")]


def _shared_nets(ctx: Ctx, a: str, b: str) -> set:
    ra, rb = ctx.rows.get(a), ctx.rows.get(b)
    return set(ra["nets"]) & set(rb["nets"]) if ra and rb else set()


# ------------------------------------------------------------------ constants the user types
def _typed_number(params: dict, key: str, what: str):
    v = params.get(key)
    if v in (None, ""):
        return None
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not v > 0:
        raise BuilderRefused("%s is a positive number of mm, not %r" % (what, v))
    return float(v)


def _gap_constant(ctx: Ctx, names: _Names, subject: str, target: str, params: dict, edits: list):
    """The gap's named constant, with the note as its comment: `{"name": ...}` for the call, or None where no gap is asked."""
    gap = _typed_number(params, "gap", "a gap")
    if gap is None:
        return None
    note = (params.get("gap_note") or "").strip()
    if not note:
        raise BuilderRefused("a gap carries the reason it is there: what needs it", "every larger gap names what needs it")
    name = names.take("%s_GAP_MM" % _identifier(subject))
    edits.append(Edit("set_constant", None, {"name": name, "comment": wrap(
        "The gap between %s and %s: %s. Chosen in %s." % (ctx.label(subject), ctx.label(target), note.rstrip("."), BUILDER))}, gap, {},
        str(ctx.script)))
    return _name(name)


def _radius_constant(ctx: Ctx, names: _Names, subject: str, target: str, params: dict, edits: list):
    r = _typed_number(params, "radius", "a radius")
    if r is None:
        return None
    name = names.take("%s_NEAR_RADIUS_MM" % _identifier(subject))
    edits.append(Edit("set_constant", None, {"name": name, "comment": wrap(
        "How far from %s %s may stand, chosen in %s." % (ctx.label(target), ctx.label(subject), BUILDER))}, r, {}, str(ctx.script)))
    return _name(name)


def _limit_constant(ctx: Ctx, names: _Names, subject: str, target: str, params: dict, edits: list):
    limit = _typed_number(params, "limit_mm", "a link's limit")
    if limit is None:
        return None
    name = names.take("%s_LINK_LIMIT_MM" % _identifier(subject))
    edits.append(Edit("set_constant", None, {"name": name, "comment": wrap(
        "The longest the link from %s to %s may run, chosen in %s." % (ctx.label(subject), ctx.label(target), BUILDER))}, limit, {},
        str(ctx.script)))
    return _name(name)


# ------------------------------------------------------------------ modifiers
def modifier_kwargs(params: dict, ctx=None, subject: str = "") -> dict:
    """The keyword arguments of a placement the user may add: rotation (a quarter turn, `facing` a pad toward an edge, or `turned`
    with another part), face, priority, required and why."""
    kw = {}
    f, t = params.get("facing"), params.get("turned")
    if f or t:
        if ctx is None:
            raise BuilderRefused("a rotation by a pad or by another part needs the board's parts")
        if f and t:
            raise BuilderRefused("a rotation is one of: a quarter turn, a pad facing an edge, or turned with another part")
        if f:
            if f.get("edge") not in EDGES:
                raise BuilderRefused("a pad faces NORTH, EAST, SOUTH or WEST")
            part = ctx.parts.get(subject)
            pad = _find_pad(part, f.get("pad")) if part else None
            if pad is None:
                raise BuilderRefused("%s has no pad %s to turn by" % (ctx.label(subject), f.get("pad")))
            kw["rotation"] = _form("Facing", ctx.padref(subject, pad, {}), _enum("Edge." + f["edge"]))
        else:
            if t.get("key") not in ctx.rows or t["key"] == subject:
                raise BuilderRefused("turn with another part of the board")
            if ctx.rows[t["key"]]["status"] == "unplaced":
                raise BuilderRefused("%s is not placed yet, so there is no turn to follow" % ctx.label(t["key"]), "an unplaced item is not a target")
            if t.get("degrees", 0) not in TURNS:
                raise BuilderRefused("a rotation is a quarter turn: 0, 90, 180 or 270", "rotation is a quarter turn")
            kw["rotation"] = _form("Turned", ctx.item(t["key"], {}) if ctx.declared(t["key"]) else _part(t["key"]), t.get("degrees", 0))
    rot = params.get("rotation")
    if rot not in (None, ""):
        if rot not in TURNS:
            raise BuilderRefused("a rotation is a quarter turn: 0, 90, 180 or 270", "rotation is a quarter turn")
        if rot != 0 and "rotation" not in kw:
            kw["rotation"] = rot
    if params.get("face"):
        if params["face"] not in FACES:
            raise BuilderRefused("a face is BACK or EITHER (the front is the default and is never written)")
        kw["face"] = _enum("Face." + params["face"])
    if params.get("priority"):
        if params["priority"] not in PRIORITIES:
            raise BuilderRefused("a priority is HIGH or LOW")
        if not (params.get("why") or "").strip():
            raise BuilderRefused("a priority carries its reason: why does this go before the rest", "a priority is explained")
        kw["priority"] = _enum("Priority." + params["priority"])
    if params.get("required"):
        kw["required"] = True
    if (params.get("why") or "").strip():
        kw["why"] = _str(params["why"].strip())
    return kw


# ------------------------------------------------------------------ writing a placement
def _place_form(ctx, key, at, mods):
    kwargs = {}
    if at is not None:
        kwargs["at"] = at
    kwargs.update(mods)
    out = {"form": "board.place", "args": [ctx.form(key)]}
    if kwargs:
        out["kwargs"] = kwargs
    return out


def _target_of(ctx, row) -> Target:
    t = ctx.declared(row["key"])
    if t is None:
        raise BuilderRefused("%s is declared by a statement the builder does not edit (%s): replace it by a relation in the script" % (
            ctx.label(row["key"]), row.get("source") or "by hand"), "a declaration the builder cannot read is shown as written")
    return t


def is_decided(at) -> bool:
    """Whether a place is decided before the search: any relation or edge, but not `Near` (a hint the search starts from)."""
    return at is not None and not (isinstance(at, dict) and at.get("form") == "Near")


def _insert(ctx, stmts: list, decided: bool, refs: dict) -> Edit:
    value = {"block": stmts} if len(stmts) > 1 else stmts[0]
    if not ctx.plain:                       # a hand-written script: after the right statement of it, with no comment of the builder's
        target, region = ctx.insertion_anchor(refs)
        if target is not None:
            return Edit("insert_statement", target, {}, value, dict(refs), str(ctx.script))
        return Edit("insert_statement", None, {"after": {"region": region}}, value, dict(refs), str(ctx.script))
    args = {"after": {"region": "decided" if decided else "searched"}}
    if not decided:
        args["comment"] = SEARCHED_NOTE
    return Edit("insert_statement", None, args, value, dict(refs), str(ctx.script))


def placement_edits(ctx: Ctx, key: str, at, mods: dict, refs: dict, before: list = ()) -> list:
    """The edits that put `key` at `at` (an expression, or None to leave it to the search) with the modifiers `mods`: a new statement
    where it has none; the statement it has changed in place; and, where that moves it between the decided and the searched part of
    the script, the statement taken out and written again in its region with the keywords it had. `before` are statements written
    with it, above it (a link)."""
    row = ctx.rows[key]
    decided = is_decided(at)
    if row["status"] == "unplaced" or not row["line"]:
        return [_insert(ctx, list(before) + [_place_form(ctx, key, at, mods)], decided, refs)]
    target = _target_of(ctx, row)
    file = str(ctx.script)
    status = row["status"]
    in_place = []
    if status == "by hand":
        if at is None:
            raise BuilderRefused("a declaration the builder cannot read is replaced by a relation, not by the search", "by hand is shown as written")
        move = False
    else:
        move = (status == "decided") != decided
    if not move:
        if at is not None:
            in_place.append(Edit("set_kwarg", target, {"name": "at"}, at, dict(refs), file))
        elif row["relation"] and row["relation"]["kind"] != "searched":
            in_place.append(Edit("remove_kwarg", target, {"name": "at"}, None, {}, file))
        for name, value in mods.items():
            in_place.append(Edit("set_kwarg", target, {"name": name}, value, dict(refs), file))
        if before:
            in_place.append(Edit("insert_statement", target, {}, {"block": list(before)} if len(before) > 1 else before[0], dict(refs), file))
        return in_place
    call = se.read_call(ctx.texts[row["file"]], target)
    kept = {k: v for k, v in call["kwargs"].items() if k != "at"}
    if any(v is None for v in kept.values()) or call.get("spread"):
        raise BuilderRefused("%s has an argument the builder cannot read, so it is not moved between the decided and the searched part "
                             "of the script: edit it in the script" % ctx.label(key), "a declaration the builder cannot read is shown as written")
    kept.update(mods)
    return [Edit("remove_statement", target, {}, None, {}, file), _insert(ctx, list(before) + [_place_form(ctx, key, at, kept)], decided, refs)]


# ------------------------------------------------------------------ the menu
@dataclass
class Offer:
    intent: str
    text: str
    at: object = None                               # the `at=` expression; None leaves the item to the search
    pre: list = field(default_factory=list)         # edits made first: the constants a typed number needs
    before: list = field(default_factory=list)      # statements written with the placement, above it (a link)
    refs: dict = field(default_factory=dict)        # the declarations the expressions name, for the script's own spelling
    group: object = None                            # a row or a ring: the whole statement, placed in the decided part of the script
    needs: list = field(default_factory=list)       # what the user must still say: "own_pad"
    notes: list = field(default_factory=list)
    edits: list = field(default_factory=list)


def edge_bindings(ctx: Ctx) -> dict:
    """{(facing, outermost): name} of the module-level `name = board.edge(facing=Edge.X[, outermost=True])` statements of the script."""
    import ast
    out = {}
    for st in se._parse(ctx.text).tree.body:
        v = st.value if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name) else None
        if isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "edge" and not v.args:
            kw = {k.arg: k.value for k in v.keywords}
            f = kw.get("facing")
            if set(kw) <= {"facing", "outermost"} and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "Edge":
                om = isinstance(kw.get("outermost"), ast.Constant) and kw["outermost"].value is True
                out[(f.attr, om)] = st.targets[0].id
    return out


def _run_target(ctx: Ctx, edge: str, names: _Names):
    """(the expression naming the stretch of a shaped board facing `edge`, the edits that bind it where the script has no binding)."""
    from . import builder_runs as br
    loops = ((ctx.plan or {}).get("board") or {}).get("loops") or []
    got = br.nameable(loops, edge)
    if not got["ok"]:
        raise BuilderRefused(got["why"], "a shaped board's sides are chosen, not named: a stretch that cannot be named without a number is greyed")
    have = edge_bindings(ctx)
    key = (edge, got["outermost"])
    if key in have:
        return _name(have[key]), []
    bound = names.take("%s_edge" % bp.SIDE[edge])
    kwargs = {"facing": _enum("Edge." + edge)}
    if got["outermost"]:
        kwargs["outermost"] = True
    pre = Edit("insert_statement", None, {"after": {"region": "outline"}, "bind": bound}, _form("board.edge", **kwargs), {}, str(ctx.script))
    return _name(bound), [pre]


def _edge_offers(ctx: Ctx, target: dict, names: _Names) -> list:
    kind = ctx.outline["kind"]
    edge = target.get("edge")
    if kind == "rect":
        if edge not in EDGES:
            raise BuilderRefused("an edge of a rectangle is NORTH, EAST, SOUTH or WEST")
        side = bp.SIDE[edge]
        out = []
        for along, word in ((None, "somewhere on the %s edge" % side), ("START", "at the start of the %s edge" % side),
                            ("MID", "in the middle of the %s edge" % side), ("END", "at the end of the %s edge" % side)):
            kw = {"along": _enum("Along." + along)} if along else {}
            out.append(Offer("on_edge_" + (along or "any").lower(), word, _form("OnEdge", _enum("Edge." + edge), **kw)))
        return out
    if kind == "disc":
        out = []
        if target.get("bore"):
            if edge not in EDGES:
                raise BuilderRefused("a place at the bore is a compass side of it")
            return [Offer("on_bore", "at the bore, %s side" % bp.SIDE[edge], _form("OnBore", _enum("Edge." + edge)))]
        if edge in EDGES:
            out.append(Offer("on_rim", "on the rim, facing %s" % bp.SIDE[edge], _form("OnRim", _enum("Edge." + edge))))
        out.append(Offer("on_rim_any", "anywhere on the rim", _form("OnRim")))
        return out
    if kind == "outline":
        if edge not in EDGES:
            raise BuilderRefused("choose the side the stretch faces: NORTH, EAST, SOUTH or WEST")
        run, pre = _run_target(ctx, edge, names)
        side = bp.SIDE[edge]
        out = []
        for along, word in ((None, "somewhere on the edge facing %s" % side), ("START", "at the start of the edge facing %s" % side),
                            ("MID", "in the middle of the edge facing %s" % side), ("END", "at the end of the edge facing %s" % side)):
            kw = {"along": _enum("Along." + along)} if along else {}
            out.append(Offer("on_edge_" + (along or "any").lower(), word, _form("OnEdge", run, **kw), list(pre)))
        return out
    raise BuilderRefused("this board's outline is not one the builder places on", "an outline the builder cannot read is shown as written")


def _part_offers(ctx: Ctx, subject: str, target: dict, params: dict, names: _Names) -> list:
    t, side = target["key"], target.get("side")
    if side not in EDGES:
        raise BuilderRefused("choose a side of %s: click its north, east, south or west" % ctx.label(t))
    pre: list = []
    refs: dict = {}
    gap = _gap_constant(ctx, names, subject, t, params, pre)
    kw = {"gap": gap} if gap else {}
    tgt = ctx.item(t, refs)
    s = bp.SIDE[side]
    out = [Offer("beside", "beside %s, %s" % (ctx.label(t), s), _form("Beside", tgt, _enum("Edge." + side), **kw), list(pre), refs=refs)]
    for al in ALONGS:
        out.append(Offer("beside_" + al.lower(), "beside %s, %s, flush to the %s" % (ctx.label(t), s, al.lower()),
                         _form("Beside", tgt, _enum("Edge." + side), **kw, align=_enum("Along." + al)), list(pre), refs=refs))
    return out


def _find_pad(part: dict, pad) -> dict | None:
    for p in part["pad_list"]:
        if p["number"] == str(pad) or (p["net"] and p["net"] == pad):
            return {"number": p["number"], "net": p["net"]}
    return None


def _pad_offers(ctx: Ctx, subject: str, target: dict, params: dict, names: _Names) -> list:
    t, pad = target["key"], target["pad"]
    tpart = ctx.parts.get(t)
    if tpart is None:
        raise BuilderRefused("%s is a cell: choose a part of it, or the cell itself" % ctx.label(t), "a pad is a pad of a part")
    tpad = _find_pad(tpart, pad)
    if tpad is None:
        raise BuilderRefused("%s has no pad %s" % (ctx.label(t), pad))
    refs: dict = {}
    padref_t = ctx.padref(t, tpad, refs)
    tgt = ctx.item(t, refs)
    own = _own_pads(ctx, subject, tpad)
    own_key = params.get("own_pad")
    if own_key in (None, "") and len(own) == 1:
        own_key = own[0]["number"]
    out = []
    side = params.get("side") or _side_of_pad(ctx, t, tpad)
    if side in EDGES:
        pre: list = []
        gap = _gap_constant(ctx, names, subject, t, params, pre)
        kw = {"gap": gap} if gap else {}
        out.append(Offer("beside_pad_side", "beside %s, on the side of its pad %s" % (ctx.label(t), pad),
                         _form("Beside", tgt, _form("SideOf", padref_t), **kw), pre, refs=refs))
        level = Offer("beside_level", "beside %s, %s, level with its pad %s" % (ctx.label(t), bp.SIDE[side], pad), None, list(pre), refs=refs)
        if len(own) == 1 and own[0]["number"] == str(own_key):
            align = padref_t                                  # the part's own pad is on the same net: the pad alone says it
        elif own_key not in (None, ""):
            align = {"tuple": [ctx.pad_key(subject, number=own_key), padref_t]}
        else:
            align = None
            level.needs.append("own_pad")
        level.at = _form("Beside", tgt, _enum("Edge." + side), **kw, **({"align": align} if align else {}))
        out.append(level)
    shared = _shared_nets(ctx, subject, t)
    if shared:
        close = Offer("close_to_pad", "close to %s pad %s: a short link, the part searched from it" % (ctx.label(t), pad), None, refs=refs)
        if own_key in (None, ""):
            close.needs.append("own_pad")
        else:
            kw = {"weight": _enum("LinkWeight.SHORT")}
            lim = _limit_constant(ctx, names, subject, t, params, close.pre)
            if lim:
                kw["limit_mm"] = lim
            rec = next((p for p in ctx.parts[subject]["pad_list"] if p["number"] == str(own_key)), {"number": str(own_key), "net": None})
            own_ref = ctx.padref(subject, rec, {})
            close.before = [{"form": "board.link", "args": [own_ref, padref_t], "kwargs": kw}]
        out.append(close)
    else:
        pre = []
        rad = _radius_constant(ctx, names, subject, t, params, pre)
        out.append(Offer("near_pad", "near %s pad %s (they share no net)" % (ctx.label(t), pad),
                         _form("Near", padref_t, **({"radius": rad} if rad else {})), pre, refs=refs))
    for axis, word in (("X", "column"), ("Y", "row")):
        at = _form("Centre", _form("X", padref_t), None) if axis == "X" else _form("Centre", None, _form("Y", padref_t))
        out.append(Offer("in_line_" + axis.lower(), "in line with %s pad %s, sliding along its %s" % (ctx.label(t), pad, word), at, refs=refs))
    return out


def _side_of_pad(ctx: Ctx, key: str, pad: dict):
    """The side of the placed item `key` its pad is nearest, read from the plan's own shapes: a side to start from, never a position
    that is written."""
    item = ctx.item_doc(key)
    if item is None:
        return None
    centre, xs, ys = None, [], []
    for m in item.get("members", ()):
        for sh in m.get("shapes", ()):
            pts = sh.get("poly") or []
            if sh.get("kind") in ("pad", "through") and (sh.get("number") == pad.get("number")) and centre is None:
                centre = ((min(p[0] for p in pts) + max(p[0] for p in pts)) / 2, (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2)
            if sh.get("kind") == "courtyard":
                xs += [p[0] for p in pts]
                ys += [p[1] for p in pts]
    if centre is None or not xs:
        return None
    d = {"WEST": centre[0] - min(xs), "EAST": max(xs) - centre[0], "NORTH": centre[1] - min(ys), "SOUTH": max(ys) - centre[1]}
    return min(d, key=d.get)


def _finish(ctx: Ctx, subject: str, o: Offer, mods: dict) -> list:
    edits = list(o.pre) + placement_edits(ctx, subject, o.at, mods, o.refs, o.before)
    imp = imports_for(ctx, o.at, o.before, list(mods.values()), ctx.form(subject), [ctx.form(k) for k in o.refs], [e.value for e in o.pre])
    if imp is not None:
        edits.insert(0, imp)
    return edits


def menu(ctx: Ctx, subjects: list, target: dict | None, params: dict | None = None) -> list:
    """The offers for (subjects, target): each an `Offer` with its edits built. `params` are what the user has typed or picked (gap,
    gap_note, own_pad, side, rotation, face, priority, required, why, limit_mm, radius). An offer with `needs` cannot be applied
    yet."""
    params = params or {}
    check_request(ctx, subjects, target)
    names = _Names(ctx.text)
    if len(subjects) != 1:
        return group_menu(ctx, subjects, target, params, names)
    subject = subjects[0]
    if target is None:
        offers = [Offer("searched", "leave it to the search, from its links", None)]
    elif target["kind"] == "edge":
        offers = _edge_offers(ctx, target, names)
    elif target["kind"] == "part":
        offers = _part_offers(ctx, subject, target, params, names)
    else:
        offers = _pad_offers(ctx, subject, target, params, names)
    mods = modifier_kwargs(params, ctx, subject)
    for o in offers:
        if not o.needs:
            o.edits = _finish(ctx, subject, o, mods)
    return offers


def group_menu(ctx: Ctx, subjects: list, target: dict | None, params: dict, names: _Names) -> list:
    """Several unplaced items and an edge or a part's side: a row (`board.row(items, edge)`), or on a disc's rim a ring. The items go in
    the selection's order, which `params["order"]` changes. A gap is left out (courtyards touch) unless the user gives one with its
    reason."""
    order = list(params.get("order") or subjects)
    if sorted(order) != sorted(subjects):
        raise BuilderRefused("the row's order names the items selected")
    for k in order:
        if ctx.rows[k]["status"] != "unplaced":
            raise BuilderRefused("%s is placed already: take it off the board before it joins a row" % ctx.label(k), "a row is made of unplaced items")
    if target is None or target.get("kind") not in ("edge", "part"):
        raise BuilderRefused("a row goes along an edge or beside a part: choose one", "")
    items = {"list": [ctx.form(k) for k in order]}
    pre: list = []
    refs: dict = {}
    kw_common = {}
    gap = _gap_constant(ctx, names, order[0], target.get("key") or order[0], params, pre) if params.get("gap") else None
    if gap:
        kw_common["gap"] = gap
    why = (params.get("why") or "").strip()
    rot = params.get("rotation")
    if rot not in (None, "", 0):
        if rot not in TURNS:
            raise BuilderRefused("a rotation is a quarter turn: 0, 90, 180 or 270", "rotation is a quarter turn")
        kw_common["rotation"] = rot
    if why:
        kw_common["why"] = _str(why)
    out = []
    if target["kind"] == "edge" and ctx.outline["kind"] == "disc":
        edge = target.get("edge")
        kw = dict(kw_common)
        if edge in EDGES:
            kw["start"] = _enum("Edge." + edge)
        out.append(Offer("ring", "in a ring round the rim" + ((", starting %s" % bp.SIDE[edge]) if edge in EDGES else ""), None, list(pre)))
        out[-1].group = _form("board.ring", items, **{k: v for k, v in kw.items() if k != "gap"})
    else:
        if target["kind"] == "edge":
            edge = target.get("edge")
            if ctx.outline["kind"] == "outline":
                where, p2 = _run_target(ctx, edge, names)
                pre = pre + p2
            elif edge in EDGES:
                where = _enum("Edge." + edge)
            else:
                raise BuilderRefused("a row goes along NORTH, EAST, SOUTH or WEST")
            label, extra = "along the %s edge" % bp.SIDE.get(edge, "?"), {}
        else:
            side = target.get("side")
            if side not in EDGES:
                raise BuilderRefused("choose a side of %s" % ctx.label(target["key"]))
            where = _enum("Edge." + side)
            extra = {"of": ctx.item(target["key"], refs)}
            label = "along %s, %s" % (ctx.label(target["key"]), bp.SIDE[side])
        for al, word in ((None, "from the start"), ("MID", "centred"), ("END", "from the end")):
            kw = dict(extra)                                  # in the order row() takes them: of, gap, align, rotation, why
            if "gap" in kw_common:
                kw["gap"] = kw_common["gap"]
            if al:
                kw["align"] = _enum("Along." + al)
            kw.update({k: v for k, v in kw_common.items() if k != "gap"})
            o = Offer("row_" + (al or "start").lower(), "a row %s, %s" % (label, word), None, list(pre), refs=refs)
            o.group = _form("board.row", items, where, **kw)
            out.append(o)
    for o in out:
        imp = imports_for(ctx, o.group, [ctx.form(k) for k in order], [ctx.form(k) for k in o.refs], [e.value for e in o.pre])
        o.edits = ([imp] if imp is not None else []) + list(o.pre) + [Edit("insert_statement", None, {"after": {"region": "decided"}}, o.group, dict(o.refs), str(ctx.script))]
    return out


def offer_suggestion(ctx: Ctx, o: Offer, subject) -> Suggestion:
    """The offer as a suggestion; `subject` is the item, or the list of items a row is made of."""
    who = ", ".join(ctx.label(k) for k in subject) if isinstance(subject, (list, tuple)) else ctx.label(subject)
    return _suggestion(ctx, "Place %s %s" % (who, o.text), o.edits)


# ------------------------------------------------------------------ searching the rest
def search_rest(ctx: Ctx, keys: list | None = None, either_face: bool = False) -> dict:
    """One plain `board.place(item)` for each item left to the search (every unplaced item, or those of `keys`), cells first in name
    order, then loose parts in natural order of reference, in the searched block under one comment line: one edit, one undo."""
    pool = [r for r in ctx.listing["rows"] if r["status"] == "unplaced" and (keys is None or r["key"] in keys)]
    if not pool:
        raise BuilderRefused("nothing is left to search: every item is placed or searched already")
    cells = sorted((r for r in pool if r["kind"] == "cell"), key=lambda r: bp.natural(r["key"]))
    parts = sorted((r for r in pool if r["kind"] == "part"), key=lambda r: bp.natural(r["ref"]))
    stmts = []
    for r in cells + parts:
        kw = {"face": _enum("Face.EITHER")} if either_face else {}
        stmts.append(_form("board.place", ctx.form(r["key"]), **kw))
    edits = [Edit("insert_statement", None, {"after": {"region": "searched"}, "comment": SEARCHED_NOTE},
                  {"block": stmts} if len(stmts) > 1 else stmts[0], {}, str(ctx.script))]
    imp = imports_for(ctx, stmts)
    if imp is not None:
        edits.insert(0, imp)
    s = _suggestion(ctx, "Search the rest (%d)" % len(stmts), edits)
    return {"suggestion": s, "count": len(stmts), "keys": [r["key"] for r in cells + parts]}


# ------------------------------------------------------------------ the modifiers of a placed item
def item_mods(ctx: Ctx, key: str, params: dict) -> Suggestion:
    """Rotation, face, priority, required and why of an item the script places, set where `params` gives a value and taken out where
    it gives "" (or false for `required`): `set_kwarg` and `remove_kwarg` on its call, so the rest of the call is as it was."""
    row = ctx.rows.get(key)
    if row is None or row["status"] == "unplaced":
        raise BuilderRefused("%s is not placed by a statement of the script yet" % ctx.label(key))
    target = _target_of(ctx, row)
    have = row.get("mods") or {}
    file = str(ctx.script)
    edits = []
    want = modifier_kwargs({k: v for k, v in params.items() if v not in ("", None, False)}, ctx, key)
    for name in ("rotation", "face", "priority", "required", "why"):
        given = params.get(name, None)
        if name in want:
            edits.append(Edit("set_kwarg", target, {"name": name}, want[name], {}, file))
        elif name in params and given in ("", False) and name in have:
            edits.append(Edit("remove_kwarg", target, {"name": name}, None, {}, file))
    if params.get("rotation") == 0 and "rotation" in have and not any(e.args.get("name") == "rotation" for e in edits):
        edits.append(Edit("remove_kwarg", target, {"name": "rotation"}, None, {}, file))
    if not edits:
        raise BuilderRefused("nothing to change: the call is as asked")
    imp = imports_for(ctx, *[e.value for e in edits if isinstance(e.value, dict)])
    if imp is not None:
        edits.insert(0, imp)
    return _suggestion(ctx, "Change how %s is placed" % ctx.label(key), edits)


# ------------------------------------------------------------------ the order of decided statements, and a row's members
def move_offer(ctx: Ctx, key: str, direction: str) -> Suggestion:
    """A decided placement moved up or down among the decided placements (they go down as declared, so the order is meaningful): the
    statement and its trailing comment move; the rest of the file is as it was."""
    if direction not in ("up", "down"):
        raise BuilderRefused("a statement moves up or down")
    row = ctx.rows.get(key)
    if row is None or row["status"] != "decided" or (row["relation"] or {}).get("kind") in ("row", "ring"):
        raise BuilderRefused("only a decided placement is moved among the decided ones")
    mine = _target_of(ctx, row)
    seen, decided = set(), []                      # the decided statements in file order: a row is one statement whoever its members are
    for r in sorted((r for r in ctx.rows.values() if r["status"] == "decided" and r["line"] and r["file"] == row["file"]), key=lambda r: r["line"]):
        if r["line"] not in seen:
            seen.add(r["line"])
            decided.append(r)
    i = next(k for k, r in enumerate(decided) if r["key"] == key)
    j = i - 1 if direction == "up" else i + 1
    if not 0 <= j < len(decided):
        raise BuilderRefused("%s is already the %s of the decided placements" % (ctx.label(key), "first" if direction == "up" else "last"))
    nb = decided[j]
    if (nb["relation"] or {}).get("kind") in ("row", "ring"):
        other = Target(nb["relation"]["kind"], nb["key"], ctx.abs(nb["file"]), nb["line"], 1, se.digest(ctx.texts[nb["file"]]))
    else:
        other = _target_of(ctx, nb)
    e = Edit("move_statement", mine, {"before" if direction == "up" else "after": other.to_json()}, None, {}, str(ctx.script))
    return _suggestion(ctx, "Move %s %s" % (ctx.label(key), direction), [e])


def row_edit(ctx: Ctx, key: str, action: str, member: str = "", before: str = "") -> Suggestion:
    """A change to the members of the row `key` is in: take one out (it is unplaced again), add an unplaced item, or move one before
    another: `edit_list` on the row's items, the rest of the call as it was."""
    row = ctx.rows.get(key)
    rel = (row or {}).get("relation") or {}
    if row is None or rel.get("kind") != "row":
        raise BuilderRefused("%s is not in a row the builder wrote" % ctx.label(key))
    text = ctx.texts[row["file"]]
    target = Target("row", key, ctx.abs(row["file"]), row["line"], 1, se.digest(text))
    member = member or key
    if member not in ctx.rows:
        raise BuilderRefused("%s is not a part or a cell of this board" % member)
    spec = ctx.form(member)
    edits = []
    file = str(ctx.script)
    if action == "remove":
        if ctx.rows[member]["line"] != row["line"]:
            raise BuilderRefused("%s is not in this row" % ctx.label(member))
        edits.append(Edit("edit_list", target, {"arg": 0, "action": "remove"}, spec, {}, file))
        text_ = "Take %s out of its row" % ctx.label(member)
    elif action == "add":
        if ctx.rows[member]["status"] != "unplaced":
            raise BuilderRefused("%s is placed already: take it off the board before it joins a row" % ctx.label(member))
        edits.append(Edit("edit_list", target, {"arg": 0, "action": "add"}, spec, {}, file))
        text_ = "Add %s to the row" % ctx.label(member)
    elif action == "move":
        if not before or before not in ctx.rows or ctx.rows[before]["line"] != row["line"]:
            raise BuilderRefused("move it before a member of the same row")
        edits.append(Edit("edit_list", target, {"arg": 0, "action": "move", "before": ctx.form(before)}, spec, {}, file))
        text_ = "Move %s before %s in its row" % (ctx.label(member), ctx.label(before))
    else:
        raise BuilderRefused("a row's member is taken out, added or moved")
    return _suggestion(ctx, text_, edits)


# ------------------------------------------------------------------ taking an item off the board
def remove_edits(ctx: Ctx, key: str) -> Suggestion:
    """The statement that places `key` taken out, with a link the builder wrote for it and a constant only it used; the item is
    unplaced again."""
    row = ctx.rows.get(key)
    if row is None or row["status"] == "unplaced":
        raise BuilderRefused("%s is not placed by the script" % (ctx.label(key)))
    target = _target_of(ctx, row)
    used = []
    rel = row.get("relation") or {}
    for c in (rel.get("gap"), rel.get("radius")):
        if c and "const" in c:
            used.append(c["const"])
    edits = [Edit("remove_statement", target, {}, None, {}, str(ctx.script))]
    mod = se._parse(ctx.text)
    # a constant used by nothing else once this statement is gone
    import ast as _ast
    inside = set(range(row["line"], (se.read_call(ctx.text, target).get("end") or row["line"]) + 1))
    for name in used:
        uses = [n.lineno for n in _ast.walk(mod.tree) if isinstance(n, _ast.Name) and n.id == name and isinstance(n.ctx, _ast.Load)]
        if uses and all(l in inside for l in uses):
            edits.append(Edit("remove_constant", None, {"name": name}, None, {}, str(ctx.script)))
    return _suggestion(ctx, "Take %s off the board" % ctx.label(key), edits)
