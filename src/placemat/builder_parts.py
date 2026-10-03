"""What the builder reads back from the script and the plan: the outline as the builder's forms write it, a placement as a relation
(a structured record the page renders as a phrase), and the parts list with each part's status.

Nothing here parses a sentence: the script is read by `ast` (script_edit.read_intent and read_call) and the plan is the plan's own
JSON. A declaration outside the builder's closed vocabulary is `by hand`, shown with its source line and read only."""
from __future__ import annotations

import ast
from pathlib import Path
import re

from . import script_edit as se
from .suggestions import Target

STATUSES = ("unplaced", "searched", "decided", "by hand")
SIDE = {"NORTH": "north", "EAST": "east", "SOUTH": "south", "WEST": "west"}
ALONG_WORD = {"START": "at the start", "MID": "in the middle", "END": "at the end"}


# ------------------------------------------------------------------ the outline
def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return -float(node.operand.value)
    return None


def _constants(tree) -> dict:
    out = {}
    for st in tree.body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            out[st.targets[0].id] = st.value
    return out


def _dim(node, consts):
    """(value, constant name) of a number the outline gives: a literal, or a name of a literal constant; (None, name) where it is
    computed."""
    v = _literal(node)
    if v is not None:
        return v, None
    if isinstance(node, ast.Name) and node.id in consts:
        v = _literal(consts[node.id])
        if v is not None:
            return v, node.id
        return None, node.id
    return None, None


def _points(node, consts):
    if isinstance(node, ast.Name) and node.id in consts:
        node = consts[node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        pts = []
        for e in node.elts:
            if isinstance(e, (ast.Tuple, ast.List)) and len(e.elts) == 2 and all(_literal(v) is not None for v in e.elts):
                pts.append([_literal(e.elts[0]), _literal(e.elts[1])])
            else:
                return None
        return pts
    return None


def read_outline(text: str) -> dict:
    """The outline statement as the editor shows it: `{"kind": "rect"|"disc"|"outline"|"fit"|None, "shape": one of
    builder.SHAPES or "other", "dims": {name: mm}, "consts": {name: the constant's name}, "points", "holes": [names], "editable",
    "why", "line", "constants_used": [names only the outline reads]}`. `kind` is what `Edge` values the board takes: a rect has the
    four sides, a disc a rim, an outline runs off `board.edge(facing=)`. A computed size, arcs, a fit frame are read only."""
    mod = se._parse(text)
    consts = _constants(mod.tree)
    stmt = next((s for s in mod.tree.body if se._is_outline(s)), None)
    if stmt is None:
        return {"kind": None, "shape": None, "dims": {}, "consts": {}, "holes": [], "editable": False, "why": "the script has no outline", "line": 0}
    call = stmt.value
    method = call.func.attr
    kw = {k.arg: k.value for k in call.keywords}
    pos = [a for a in call.args if not isinstance(a, ast.Starred)]
    out = {"kind": method if method != "rect" else "rect", "shape": "other", "dims": {}, "consts": {}, "holes": [], "editable": True,
           "why": "", "line": stmt.lineno, "points": None, "bound": isinstance(stmt, ast.Assign)}

    def put(name, node):
        if node is None:
            return None
        v, c = _dim(node, consts)
        if v is None:
            out["editable"], out["why"] = False, "%s is computed, not a number or a constant of one" % name
        else:
            out["dims"][name] = v
        if c:
            out["consts"][name] = c
        return v
    if "holes" in kw:
        h = kw["holes"]
        out["holes"] = [e.id for e in h.elts if isinstance(e, ast.Name)] if isinstance(h, (ast.List, ast.Tuple)) else []
    if "web" in kw:
        put("web", kw["web"])
    if method == "rect":
        if "fit" in kw and not (isinstance(kw["fit"], ast.Constant) and kw["fit"].value in (False, None)):
            out.update(kind="fit", shape="other", editable=False, why="a fit frame is derived from its content")
            return out
        put("width", kw.get("width", pos[0] if pos else None))
        put("height", kw.get("height", pos[1] if len(pos) > 1 else None))
        ch, ra = put("chamfer", kw.get("chamfer")), put("radius", kw.get("radius"))
        out["shape"] = "rect_chamfer" if ch else "rect_round" if ra else "rect"
        if ch and ra:
            out.update(shape="other", editable=False, why="a chamfer and a radius together are not one of the builder's shapes")
    elif method == "disc":
        put("diameter", kw.get("diameter", pos[0] if pos else None))
        b = put("bore", kw.get("hole"))
        out["shape"] = "disc_bore" if b else "disc"
    else:
        arg = kw.get("path", pos[0] if pos else None)
        if isinstance(arg, ast.Call) and se._func_name(arg) == "Slot" and len(arg.args) == 2:
            put("length", arg.args[0]), put("width", arg.args[1])
            out["shape"] = "slot"
        else:
            pts = _points(arg, consts) if arg is not None else None
            if pts is not None:
                out.update(shape="polygon", points=pts)
                if isinstance(arg, ast.Name):
                    out["consts"]["points"] = arg.id
            else:
                out.update(editable=False, why="this outline is not a rectangle, a disc, a slot or a list of vertices")
    # the constants only the outline statement reads
    uses = {}
    for node in ast.walk(mod.tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            uses.setdefault(node.id, []).append(node.lineno)
    inside = set(range(stmt.lineno, stmt.end_lineno + 1))
    out["constants_used"] = sorted({n for n in out["consts"].values() if all(l in inside for l in uses.get(n, ()))})
    return out


# ------------------------------------------------------------------ a placement as a relation
def _enum_name(v):
    return v["enum"].split(".")[-1] if isinstance(v, dict) and "enum" in v else None


_NAMES: dict = {}          # the names the script binds to items (`U1 = Part("u1")`), for the relation being read


def bound_items(text: str) -> dict:
    """{NAME: item key} of the module-level `NAME = Part("key")` and `NAME = Cell("key")` bindings of a script."""
    out = {}
    for st in se._parse(text).tree.body:
        v = st.value if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name) else None
        if isinstance(v, ast.Call) and se._func_name(v) in ("Part", "Cell") and v.args and isinstance(v.args[0], ast.Constant) \
                and isinstance(v.args[0].value, str):
            out[st.targets[0].id] = v.args[0].value
    return out


def _item_of(v):
    if isinstance(v, dict) and "item" in v:
        return v["item"]
    if isinstance(v, dict) and "name" in v and v["name"] in _NAMES:
        return _NAMES[v["name"]]
    return None


def _pad_of(v):
    if isinstance(v, dict) and "pad" in v:
        return {"item": v["pad"][0], "pad": v["pad"][1]}
    if isinstance(v, dict) and v.get("form") == "PadRef" and len(v.get("args", ())) == 2 and _item_of(v["args"][0]) is not None:
        pad = v["args"][1]
        return {"item": _item_of(v["args"][0]), "pad": pad["str"] if isinstance(pad, dict) and "str" in pad else pad}
    return None


def _num_or_name(v):
    if isinstance(v, dict) and "name" in v:
        return {"const": v["name"]}
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return {"number": v}
    return None


def relation_of(intent, names: dict | None = None):
    """A placement's `at=` (an intent expression, script_edit.read_intent) as a relation record, `{"kind": ...}` with the fields
    that kind has; `{"kind": "searched"}` where it gives none; None where it is not one of the builder's relations (by hand)."""
    _NAMES.clear()
    _NAMES.update(names or {})
    if intent is None:
        return None
    if isinstance(intent, dict) and intent.get("absent"):
        return {"kind": "searched"}
    if not isinstance(intent, dict) or "form" not in intent:
        return None
    form, args, kwargs = intent["form"], intent.get("args", []), intent.get("kwargs", {})
    if form == "OnEdge":
        edge = _enum_name(args[0]) if args else None
        run = args[0].get("name") if args and isinstance(args[0], dict) and "name" in args[0] else None
        if edge is None and run is None:
            return None
        along = kwargs.get("along", args[1] if len(args) > 1 else None)
        return {"kind": "on_edge", "edge": edge, "run": run, "along": _enum_name(along) if along is not None else None}
    if form == "OnRim":
        return {"kind": "on_rim", "edge": _enum_name(args[0]) if args else None}
    if form == "OnBore":
        return {"kind": "on_bore", "edge": _enum_name(args[0]) if args else None}
    if form == "Beside":
        target = _item_of(args[0]) if args else None
        if target is None:
            return None
        rel = {"kind": "beside", "target": target, "side": None, "side_of": None, "gap": None, "align": None, "align_pad": None}
        side = args[1] if len(args) > 1 else None
        if side is not None and isinstance(side, dict) and side.get("form") == "SideOf":
            rel["side_of"] = _pad_of(side["args"][0]) if side.get("args") else None
        else:
            rel["side"] = _enum_name(side)
            if rel["side"] is None:
                return None
        gap = kwargs.get("gap", args[2] if len(args) > 2 else None)
        if gap is not None:
            rel["gap"] = _num_or_name(gap)
            if rel["gap"] is None:
                return None
        al = kwargs.get("align", args[3] if len(args) > 3 else None)
        if al is not None:
            if _enum_name(al):
                rel["align"] = _enum_name(al)
            elif _pad_of(al):
                rel["align_pad"] = _pad_of(al)
            else:
                return None
        return rel
    if form == "Near":
        pad = _pad_of(args[0]) if args else None
        item = _item_of(args[0]) if args else None
        if pad is None and item is None:
            return None
        return {"kind": "near", "target": item, "pad": pad, "radius": _num_or_name(kwargs["radius"]) if "radius" in kwargs else None}
    if form == "Centre" and len(args) == 2 and "coordinates" not in kwargs:
        for axis, v in zip(("x", "y"), args):
            if isinstance(v, dict) and v.get("form") in ("X", "Y") and v.get("args") and _pad_of(v["args"][0]) and not v.get("kwargs"):
                other = args[1] if axis == "x" else args[0]
                if other is None and len(v["args"]) == 1:
                    return {"kind": "in_line", "axis": axis, "pad": _pad_of(v["args"][0])}
        return None
    return None


def modifiers_of(call: dict) -> dict:
    """The keyword arguments of a placement the builder edits: rotation, face, priority, required, why."""
    kw = call.get("kwargs", {})
    out = {}
    rot = kw.get("rotation")
    if isinstance(rot, (int, float)) and not isinstance(rot, bool):
        out["rotation"] = {"turn": rot}
    elif isinstance(rot, dict) and rot.get("form") == "Facing":
        out["rotation"] = {"facing": rot}
    elif isinstance(rot, dict) and rot.get("form") == "Turned":
        out["rotation"] = {"turned": rot}
    elif "rotation" in kw:
        out["rotation"] = {"hand": True}
    for name in ("face", "priority"):
        if name in kw:
            out[name] = _enum_name(kw[name])
    if kw.get("required") is True:
        out["required"] = True
    if isinstance(kw.get("why"), dict) and "str" in kw["why"]:
        out["why"] = kw["why"]["str"]
    return out


def phrase(rel: dict, label=lambda key: key) -> str:
    """A relation as the words the page shows. `label(key)` names an item (its reference)."""
    if rel is None:
        return ""
    k = rel["kind"]
    if k == "searched":
        return "searched from its links"
    if k == "on_edge":
        where = ("on the %s edge" % SIDE[rel["edge"]]) if rel.get("edge") else "on the edge %s" % rel["run"]
        return where + (", %s" % ALONG_WORD[rel["along"]] if rel.get("along") in ALONG_WORD else "")
    if k == "on_rim":
        return "on the rim" + (", facing %s" % SIDE[rel["edge"]] if rel.get("edge") else "")
    if k == "on_bore":
        return "at the bore" + (", %s" % SIDE[rel["edge"]] if rel.get("edge") else "")
    if k == "beside":
        out = "beside %s" % label(rel["target"])
        if rel.get("side"):
            out += ", %s" % SIDE[rel["side"]]
        elif rel.get("side_of"):
            out += ", on the side of its pad %s" % rel["side_of"]["pad"]
        if rel.get("align"):
            out += ", flush to the %s" % rel["align"].lower()
        if rel.get("align_pad"):
            out += ", level with pad %s" % rel["align_pad"]["pad"]
        if rel.get("gap"):
            g = rel["gap"]
            out += ", gap %s" % (g["const"] if "const" in g else "%g mm" % g["number"])
        return out
    if k == "near":
        who = label(rel["target"]) if rel.get("target") else "%s pad %s" % (label(rel["pad"]["item"]), rel["pad"]["pad"])
        return "near %s" % who
    if k == "in_line":
        return "in line with %s pad %s, sliding along the %s" % (label(rel["pad"]["item"]), rel["pad"]["pad"], "column" if rel["axis"] == "x" else "row")
    if k == "row":
        return "in a row%s" % ((" along the %s edge" % SIDE[rel["edge"]]) if rel.get("edge") else "")
    return k


# ------------------------------------------------------------------ finding a declaration
def find_place(text: str, key: str):
    """(line, the `place` call's name) of the `board.place(Part(key)|Cell(key), ...)` statement in the script that declares `key`
    by a literal, else None: for an item the plan has no site for (it did not place)."""
    mod = se._parse(text)
    for st in mod.tree.body:
        c = st.value if isinstance(st, ast.Expr) else None
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "place" and c.args:
            a = c.args[0]
            if isinstance(a, ast.Call) and se._func_name(a) in ("Part", "Cell") and a.args and isinstance(a.args[0], ast.Constant) \
                    and a.args[0].value == key:
                return st.lineno
    return None


# ------------------------------------------------------------------ the parts list
def _abs(base, name) -> str:
    return str(Path(name) if Path(name).is_absolute() else (Path(base) / name).resolve())


def parts_rows(board: dict, plan: dict | None, texts: dict, base, *, script_name: str = "") -> dict:
    """The parts list: a row for each cell and each loose part of the generated board (`builder_worker.board_record`), with its
    status from the plan and the script. `texts` is {file name as the plan names it: text}; `base` the script's folder. Returns
    `{"rows", "counts"}`; a row is `{"key", "kind", "ref", "value", "cell", "w", "h", "area", "pads", "nets", "members", "status",
    "mark", "relation", "phrase", "mods", "line", "file", "source", "rank", "note"}`."""
    items = {i["key"]: i for i in (plan or {}).get("items", ())}
    steps = {s["item"]: s for s in (plan or {}).get("steps", ()) if s.get("kind") in ("part", "cell", "block")}
    unplaced = {u["item"]: u.get("why", "") for u in (plan or {}).get("unplaced", ())}
    sites: dict = {}
    for i in items.values():
        if i.get("file") and i.get("line"):
            sites.setdefault((i["file"], i["line"]), []).append(i["key"])
    by_inst = {p["key"]: p for p in board["parts"]}
    labels = {p["key"]: p["ref"] for p in board["parts"]}
    labels.update({c["key"]: c["key"] for c in board["cells"]})
    label = lambda key: labels.get(key, key)
    rows = []
    for c in board["cells"]:
        members = [{"key": m, "ref": by_inst[m]["ref"], "value": by_inst[m]["value"]} for m in c["members"] if m in by_inst]
        rows.append(dict(key=c["key"], kind="cell", ref=c["key"], value="%d parts" % len(c["members"]), cell=None, w=c["w"], h=c["h"],
                         area=c["area"], pads=c["pads"], nets=c["nets"], members=members, faces=c.get("faces", {})))
    for p in board["parts"]:
        if not p["cell"]:
            rows.append(dict(key=p["key"], kind="part", ref=p["ref"], value=p["value"], cell=None, w=p["w"], h=p["h"], area=p["area"],
                             pads=p["pads"], nets=p["nets"], members=[], faces={}, pad_list=p.get("pad_list", [])))
    name = script_name
    for r in rows:
        key = r["key"]
        step, item = steps.get(key), items.get(key)
        r.update(status="unplaced", mark="", relation=None, phrase="", mods={}, line=0, file="", source="", rank="", note="")
        if step is None:
            continue
        r["rank"] = "%s/%s" % (step.get("rank"), step.get("rank_of")) if step.get("rank") else ""
        r["note"] = step.get("note") or ""
        file, line = (item.get("file"), item.get("line")) if item else ("", 0)
        if not line and name and name in texts:
            line = find_place(texts[name], key) or 0
            file = name if line else ""
        r.update(line=line, file=file)
        decided = step.get("freedom") in ("fixed", "edge")
        if not step.get("placed") or key in unplaced:
            r["mark"] = "did not place: %s" % unplaced.get(key, "") if key in unplaced else "did not place"
        text = texts.get(file) if file else None
        if text is None:
            r["status"] = "decided" if decided else "searched"
            continue
        shared = len(sites.get((file, line), ())) if line else 1
        src_line = text.splitlines()[line - 1].strip() if 0 < line <= len(text.splitlines()) else ""
        kinds = se.site_calls(text, line) if line else []
        kind = kinds[0] if kinds else None
        if kind in ("row", "ring"):                 # its members share the statement by design
            r.update(status="decided", source=src_line, relation={"kind": kind})
            r["phrase"] = phrase(r["relation"], label)
            continue
        if kind != "place" or shared > 1 or line not in {st.lineno for st in se._parse(text).tree.body}:
            r.update(status="by hand", source=src_line)          # a loop, a helper, a conditional: an edit there would change more than this item
            continue
        target = Target("place", key, _abs(base, file), line)
        try:
            call = se.read_call(text, target)
            intent = se.read_intent(text, target)
        except se.EditRefused:
            r.update(status="by hand", source=src_line)
            continue
        rel = relation_of(intent, bound_items(text))
        r["mods"] = modifiers_of(call)
        if rel is None:
            r.update(status="by hand", source=src_line)
            continue
        r["relation"], r["phrase"] = rel, phrase(rel, label)
        r["status"] = "searched" if rel["kind"] in ("searched", "near") else "decided"
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    return {"rows": rows, "counts": counts}


def shared_nets(board: dict, keys) -> dict:
    """{key: how many nets it shares with the items `keys`}: what the list marks when something is selected."""
    sel = set()
    for k in keys:
        for src in (board["parts"], board["cells"]):
            for r in src:
                if r["key"] == k:
                    sel |= set(r["nets"])
    out = {}
    for src in (board["parts"], board["cells"]):
        for r in src:
            if r["key"] not in keys:
                n = len(sel & set(r["nets"]))
                if n:
                    out[r["key"]] = n
    return out


_NATURAL = re.compile(r"(\d+)")


def natural(text: str) -> list:
    """A reference in natural order (`C2` before `C10`)."""
    return [int(p) if p.isdigit() else p.lower() for p in _NATURAL.split(text)]
