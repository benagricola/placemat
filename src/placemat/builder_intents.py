"""The builder's intents: for a subject and a target, the menu of relations that can be written, each as the structured edits that
write it (a suggestion without a finding); searching the rest; changing and taking off a placed item.

Every statement is a call placemat already has (`board.place`, `board.link`, `board.row`), written the way the repository's scripts
write them. A place is an edge, a relation or a reference: never a `Location`, a numeric `Centre`, a `.local()` or `.offset()`.
A number the user types (a gap, a link's limit, a radius) is a named constant whose comment says who chose it and why."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import builder_parts as bp, script_edit as se
from .builder import (BUILDER, EDGES, BuilderRefused, _cell, _enum, _form, _identifier, _name, _num, _part, _str, _Names, wrap, mm)
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

    # -------- naming
    def label(self, key) -> str:
        r = self.rows.get(key)
        return r["ref"] if r else key

    def form(self, key) -> dict:
        return _cell(key) if key in self.cells else _part(key)

    def abs(self, name) -> str:
        return str(Path(self.base / name).resolve())

    def declared(self, key):
        """The `place` declaration of `key` as a Target, where the script declares it by a statement the builder reads."""
        r = self.rows.get(key)
        if r is None or not r["line"] or r["status"] in ("unplaced", "by hand") and not r["file"]:
            return None
        text = self.texts.get(r["file"])
        if text is None or se.site_calls(text, r["line"])[:1] != ["place"]:
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
def modifier_kwargs(params: dict) -> dict:
    """The keyword arguments of a placement the user may add: rotation (a quarter turn), face, priority, required and why."""
    kw = {}
    rot = params.get("rotation")
    if rot not in (None, ""):
        if rot not in TURNS:
            raise BuilderRefused("a rotation is a quarter turn: 0, 90, 180 or 270", "rotation is a quarter turn")
        if rot != 0:
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
    args = {"after": {"region": "decided" if decided else "searched"}}
    if not decided:
        args["comment"] = SEARCHED_NOTE
    return Edit("insert_statement", None, args, {"block": stmts} if len(stmts) > 1 else stmts[0], dict(refs), str(ctx.script))


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
    needs: list = field(default_factory=list)       # what the user must still say: "own_pad"
    notes: list = field(default_factory=list)
    edits: list = field(default_factory=list)


def _edge_offers(ctx: Ctx, target: dict) -> list:
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
    raise BuilderRefused("this board's outline is not a rectangle or a disc, so its sides are chosen by the stretch of edge they face: "
                         "choose a run of the edge", "a shaped board's sides are chosen, not named")


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
    imp = imports_for(ctx, o.at, o.before, list(mods.values()), ctx.form(subject), [ctx.form(k) for k in o.refs])
    if imp is not None:
        edits.insert(0, imp)
    return edits


def menu(ctx: Ctx, subjects: list, target: dict | None, params: dict | None = None) -> list:
    """The offers for (subjects, target): each an `Offer` with its edits built. `params` are what the user has typed or picked (gap,
    gap_note, own_pad, side, rotation, face, priority, required, why, limit_mm, radius). An offer with `needs` cannot be applied
    yet."""
    params = params or {}
    check_request(ctx, subjects, target)
    if len(subjects) != 1:
        raise BuilderRefused("a row of several items is written from the row's own dialog", "")
    subject = subjects[0]
    names = _Names(ctx.text)
    if target is None:
        offers = [Offer("searched", "leave it to the search, from its links", None)]
    elif target["kind"] == "edge":
        offers = _edge_offers(ctx, target)
    elif target["kind"] == "part":
        offers = _part_offers(ctx, subject, target, params, names)
    else:
        offers = _pad_offers(ctx, subject, target, params, names)
    mods = modifier_kwargs(params)
    for o in offers:
        if not o.needs:
            o.edits = _finish(ctx, subject, o, mods)
    return offers


def offer_suggestion(ctx: Ctx, o: Offer, subject: str) -> Suggestion:
    return _suggestion(ctx, "%s %s" % ("Place %s" % ctx.label(subject), o.text), o.edits)


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
