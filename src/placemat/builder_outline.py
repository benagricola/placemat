"""Changing the outline of a script that has one: a size (the constant changes in place, its comment saying who chose the number
now), a corner (a keyword added or taken off with its constant), or the shape (the statement and the constants only it used are
replaced as one multi-edit). A shape change that makes placements by edge invalid lists them first and is made only with a choice
for each: search it, or place it on the rim or the edge that replaces the one it was on."""
from __future__ import annotations

from . import builder, builder_intents as bi, builder_parts as bp, script_edit as se
from .builder import BUILDER, BuilderRefused, EDGES, SHAPES, _comment_for, _Names, _constant, wrap
from .suggestions import Edit, Target

FAMILY = {"rect": "rect", "rect_chamfer": "rect", "rect_round": "rect", "disc": "disc", "disc_bore": "disc", "slot": "slot", "polygon": "polygon"}
DIM_KEYS = {"rect": ("width", "height"), "disc": ("diameter",), "slot": ("length", "width"), "polygon": ()}
WHAT = {"width": "The board's width", "height": "The board's height", "diameter": "The board's diameter", "length": "The board's length",
        "chamfer": "The board's corner chamfer", "radius": "The board's corner radius",
        "bore": "The diameter of the hole through the middle of the board", "web": "The material kept round a hole"}
BASE = {"width": "BOARD_WIDTH_MM", "height": "BOARD_HEIGHT_MM", "diameter": "BOARD_DIAMETER_MM", "length": "BOARD_LENGTH_MM",
        "chamfer": "BOARD_CHAMFER_MM", "radius": "BOARD_CORNER_RADIUS_MM", "bore": "BOARD_BORE_MM", "web": "BOARD_WEB_MM"}
KWARG = {"chamfer": "chamfer", "radius": "radius", "bore": "hole", "web": "web"}


def _target(ctx, outline) -> Target:
    kind = {"rect": "rect", "disc": "disc", "outline": "outline"}.get(outline["kind"])
    if kind is None:
        raise BuilderRefused("this script's outline is %s: the builder edits a rectangle, a disc, a slot or a list of vertices"
                             % ("a fit frame, derived from its content" if outline["kind"] == "fit" else "not one of those"))
    shared = 1
    return Target(kind, "outline", str(ctx.script), outline["line"], shared, se.digest(ctx.text))


def affected_placements(ctx, old_shape: str, new_shape: str) -> list:
    """The placements that stop being valid when the outline goes from `old_shape` to `new_shape`: those that name an edge of a
    rectangle (on a disc or a shaped board), a rim or a bore (on a rectangle or a shaped board)."""
    old, new = FAMILY[old_shape], FAMILY[new_shape]
    if old == new:
        return []
    out = []
    for r in ctx.listing["rows"]:
        rel = r.get("relation") or {}
        k = rel.get("kind")
        bad = False
        if k == "on_edge" and rel.get("edge") and new != "rect":
            bad = True
        if k in ("on_rim", "on_bore") and new != "disc":
            bad = True
        if k in ("row", "ring"):
            bad = True
        if bad:
            out.append({"key": r["key"], "label": r["ref"], "phrase": r["phrase"], "kind": k, "edge": rel.get("edge"),
                        "choices": _choices(k, new)})
    return out


def _choices(kind: str, new: str) -> list:
    if kind in ("row", "ring"):
        return []
    if kind == "on_edge" and new == "disc":
        return ["search", "rim"]
    if kind in ("on_rim", "on_bore") and new == "rect":
        return ["search", "edge"]
    return ["search"]


def _dims_of(spec: dict) -> dict:
    keys = list(DIM_KEYS[FAMILY[spec["shape"]]])
    if spec["shape"] == "rect_chamfer":
        keys.append("chamfer")
    if spec["shape"] == "rect_round":
        keys.append("radius")
    if spec["shape"] == "disc_bore":
        keys.append("bore")
    return {k: float(spec[k]) for k in keys}


def change_outline(ctx, spec: dict, params: dict) -> dict:
    """The suggestion that makes the script's outline `spec` (builder.outline_edits' request), with the placements it invalidates
    in `affected` (each needs a choice in `params["choices"]`: {key: "search"|"rim"|"edge"})."""
    old = ctx.outline
    if old["kind"] is None:
        raise BuilderRefused("the script has no outline to change")
    if not old["editable"]:
        raise BuilderRefused("the outline is read only: %s" % old["why"], "an outline the builder cannot read is shown as written")
    if spec.get("shape") not in SHAPES:
        raise BuilderRefused("%r is not an outline shape the builder writes (%s)" % (spec.get("shape"), ", ".join(SHAPES)))
    affected = affected_placements(ctx, old["shape"], spec["shape"])
    choices = (params or {}).get("choices") or {}
    missing = [a for a in affected if a["key"] not in choices]
    if affected and missing:
        raise BuilderRefused("%d placement(s) stop being valid on this outline: choose what happens to %s" % (
            len(missing), ", ".join(a["label"] for a in missing)), "OnEdge is refused on a disc or a shaped board, OnRim on a rectangle",
            affected=affected)
    for a in affected:
        c = choices[a["key"]]
        if c not in a["choices"]:
            raise BuilderRefused("%s: %r is not offered (%s)" % (a["label"], c, ", ".join(a["choices"]) or "take it out of the row first"),
                                 "a row is taken apart before its board changes shape", affected=affected)
    file = str(ctx.script)
    edits = []
    # the placements first (their statements are found by line; the engine carries each line through the edits before it)
    for a in affected:
        c = choices[a["key"]]
        if c == "search":
            edits += bi.placement_edits(ctx, a["key"], None, {}, {})
        elif c == "rim":
            edits += bi.placement_edits(ctx, a["key"], builder._form("OnRim", builder._enum("Edge." + a["edge"])) if a["edge"] in EDGES else
                                        builder._form("OnRim"), {}, {})
        elif c == "edge":
            edits += bi.placement_edits(ctx, a["key"], builder._form("OnEdge", builder._enum("Edge." + (a["edge"] or "NORTH"))), {}, {})
    edits += _outline_edits(ctx, old, spec, file)
    imports = bi.imports_for(ctx, *[e.value for e in edits if e.value is not None and not isinstance(e.value, (int, float, list))])
    if imports is not None:
        edits.insert(0, imports)
    s = bi._suggestion(ctx, "Change the outline to %s" % spec["shape"].replace("_", " "), edits)
    return {"suggestion": s, "affected": affected}


def _outline_edits(ctx, old: dict, spec: dict, file: str) -> list:
    family_old, family_new = FAMILY[old["shape"]], FAMILY[spec["shape"]]
    names = _Names(ctx.text)
    target = _target(ctx, old)
    if family_old != family_new or family_old in ("slot", "polygon") and old["shape"] != spec["shape"]:
        if old["holes"]:
            raise BuilderRefused("the outline has holes (%s): take them out before the shape changes" % ", ".join(old["holes"]),
                                 "a hole is placed by the shape's own edges")
        edits = [Edit("remove_statement", target, {}, None, {}, file)]
        for name in old["constants_used"]:
            edits.append(Edit("remove_constant", None, {"name": name}, None, {}, file))
        # the new outline against the script as it stands once those are gone
        after = se.apply_edits(edits, lambda p: ctx.text)[file][1]
        edits += builder.outline_edits(after, spec, file)
        return edits
    # the same kind of outline: the numbers change in place, a corner or a bore is added or taken off
    edits = []
    want = _dims_of(spec)
    if spec["shape"] == "polygon":
        problems = builder.polygon_problems(spec.get("points"))
        if problems:
            raise BuilderRefused("the outline is not a polygon: %s" % "; ".join(problems))
        const = old["consts"].get("points")
        if const is None:
            raise BuilderRefused("the outline's vertices are written in the call, not as a constant: change them in the script")
        edits.append(Edit("set_constant", None, {"name": const, "existing": True, "replace_comment": True,
                                                 "comment": wrap("The outline's vertices, chosen in %s: mm from the board's top-left, y down." % BUILDER)},
                          [list(map(float, p)) for p in spec["points"]], {}, file))
        return edits
    for key, value in want.items():
        if key in ("chamfer", "radius", "bore"):
            continue
        cur = old["dims"].get(key)
        if cur is not None and abs(cur - value) < 1e-9:
            continue
        name = old["consts"].get(key)
        comment = _comment_for(WHAT[key], spec, key)
        if name:
            edits.append(Edit("set_constant", None, {"name": name, "existing": True, "replace_comment": True, "comment": comment}, value, {}, file))
        else:
            edits.append(Edit("set_kwarg", target, {"name": KWARG.get(key, key)},
                              {"const": {"name": BASE[key], "value": value, "comment": comment}}, {}, file))
    for key in ("chamfer", "radius", "bore"):
        had, has = key in old["dims"], key in want
        if has and not had:
            name = names.take(BASE[key])
            edits.append(_constant(file, name, want[key], _comment_for(WHAT[key], spec, key)))
            edits.append(Edit("set_kwarg", target, {"name": KWARG[key]}, {"name": name}, {}, file))
        elif has and had and abs(old["dims"][key] - want[key]) > 1e-9:
            name = old["consts"].get(key)
            if name:
                edits.append(Edit("set_constant", None, {"name": name, "existing": True, "replace_comment": True,
                                                         "comment": _comment_for(WHAT[key], spec, key)}, want[key], {}, file))
            else:
                edits.append(Edit("set_kwarg", target, {"name": KWARG[key]}, {"const": {"name": BASE[key], "value": want[key],
                                                                                         "comment": _comment_for(WHAT[key], spec, key)}}, {}, file))
        elif had and not has:
            edits.append(Edit("remove_kwarg", target, {"name": KWARG[key]}, None, {}, file))
            name = old["consts"].get(key)
            if name and name in old["constants_used"]:
                edits.append(Edit("remove_constant", None, {"name": name}, None, {}, file))
    if not edits:
        raise BuilderRefused("the outline is as it was: nothing to change")
    return edits
