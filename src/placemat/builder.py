"""The studio's board builder, as pure functions: records in, records out, no pcbnew and no web code.

Every click of the builder becomes an `Edit` (suggestions.Edit) or a list of them, applied through the suggestions engine's one
path (digest check, atomic write, applied log). This module makes those edits from structured requests (an outline, a fact, an
intent for a subject and a target) and reads the state back from the script and the plan (a part's status, the relation it is
placed by). Nothing here writes a coordinate: a place is an edge, a relation or a reference, and a number is a named constant
with a comment saying where it came from (the one position the builder writes is a polygon outline's own vertices, a named
constant list the user chose).

The module is in sections: the outline and the size suggestion, the script's first write, the facts, the parts list, the intents,
searching the rest, editing a placed item, and the turn suggestion."""
from __future__ import annotations

import ast
import math
import re
import textwrap
from pathlib import Path

from . import script_edit
from .script_edit import EditRefused
from .suggestions import Edit, Target

BUILDER = "the studio's board builder"
WRAP = 110                      # a comment's text wraps here, so a line with its "# " is under 115 columns

SHAPES = ("rect", "rect_chamfer", "rect_round", "disc", "disc_bore", "slot", "polygon")
EDGES = ("NORTH", "EAST", "SOUTH", "WEST")
ALONG = ("START", "MID", "END")


class BuilderRefused(Exception):
    """A request the builder does not make, with the rule it breaks. Nothing is written."""

    def __init__(self, reason: str, rule: str = ""):
        super().__init__(reason)
        self.reason, self.rule = reason, rule


# ------------------------------------------------------------------ small helpers
def _form(name, *args, **kwargs) -> dict:
    out = {"form": name, "args": list(args)}
    if kwargs:
        out["kwargs"] = dict(kwargs)
    return out


def _enum(text) -> dict:
    return {"enum": text}


def _name(text) -> dict:
    return {"name": text}


def _str(text) -> dict:
    return {"str": text}


def _num(v) -> dict:
    return {"num": v}


def _part(key) -> dict:
    """A part written inline, as `api.md`'s examples write one: a new script has no spelling of its own yet."""
    return _form("Part", _str(key))


def _cell(key) -> dict:
    return _form("Cell", _str(key))


def wrap(text: str) -> str:
    """A comment's text on lines of its own, as a person writes a long one."""
    return "\n".join(textwrap.wrap(text, WRAP, break_long_words=False, break_on_hyphens=False))


def mm(v) -> str:
    """A length as the comments write it: no trailing zeros."""
    return ("%.3f" % float(v)).rstrip("0").rstrip(".")


def _identifier(text: str) -> str:
    out = re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").upper()
    if not out or out[0].isdigit():
        out = "H_" + out
    return out


def taken_names(text: str) -> set:
    mod = script_edit._parse(text)
    return script_edit._bound_names(mod)


def unique(name: str, taken: set) -> str:
    return script_edit._unique(name, taken)


def _positive(spec: dict, key: str) -> float:
    v = spec.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not v > 0:
        raise BuilderRefused("%s is a positive number of mm, not %r" % (key.replace("_", " "), v), "the outline's sizes are positive")
    return float(v)


# ------------------------------------------------------------------ sizes
def round_up(v: float, grid: float) -> float:
    """`v` rounded up to a multiple of `grid` (the step the studio's `builder_grid_mm` sets)."""
    if grid <= 0:
        return round(v, 4)
    n = math.ceil(v / grid - 1e-9)
    return round(n * grid, 6)


def shape_area(spec: dict) -> float:
    """The board's area in mm2 for a typed outline: the figure a typed size is judged by."""
    shape = spec.get("shape")
    if shape in ("rect", "rect_chamfer", "rect_round"):
        w, h = float(spec["width"]), float(spec["height"])
        area = w * h
        if shape == "rect_chamfer":
            c = float(spec.get("chamfer", 0))
            area -= 2 * c * c
        elif shape == "rect_round":
            r = float(spec.get("radius", 0))
            area -= (4 - math.pi) * r * r
        return area
    if shape in ("disc", "disc_bore"):
        d = float(spec["diameter"])
        b = float(spec.get("bore", 0)) if shape == "disc_bore" else 0.0
        return math.pi * (d * d - b * b) / 4.0
    if shape == "slot":
        length, w = float(spec["length"]), float(spec["width"])
        return (length - w) * w + math.pi * w * w / 4.0
    if shape == "polygon":
        pts = spec["points"]
        return abs(_shoelace(pts))
    raise BuilderRefused("%r is not an outline shape" % (shape,))


def _shoelace(pts) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])) / 2.0


def suggest_size(total_area: float, faces: int, fill: float, aspect: float, shape: str, grid: float, *, slot_aspect: float = None,
                 template: dict = None) -> dict:
    """The board size the parts' courtyards suggest: `area = total_area / (faces * fill)`, then for a rectangle `width =
    sqrt(area * aspect)` and `height = area / width`, for a disc `diameter = sqrt(4 * area / pi)`, for a slot the length and
    width in the proportion of `slot_aspect` (length over width), for a polygon template its named dimensions scaled together
    to the area. Each size is rounded up to `grid`. Returns the figures and the numbers they came from."""
    if faces not in (1, 2):
        raise BuilderRefused("components go on one face or two, not %r" % (faces,))
    if not (0 < fill <= 1):
        raise BuilderRefused("the fill is a share above 0 and at most 1, not %r" % (fill,))
    if total_area <= 0:
        raise BuilderRefused("the parts have no courtyard area to size a board from")
    area = total_area / (faces * fill)
    out = {"area": area, "total_area": total_area, "faces": faces, "fill": fill, "aspect": aspect, "shape": shape}
    if shape in ("rect", "rect_chamfer", "rect_round"):
        if aspect <= 0:
            raise BuilderRefused("the aspect is a positive ratio, not %r" % (aspect,))
        w = math.sqrt(area * aspect)
        out.update(width=round_up(w, grid), height=round_up(area / w, grid))
    elif shape in ("disc", "disc_bore"):
        out.update(diameter=round_up(math.sqrt(4.0 * area / math.pi), grid))
    elif shape == "slot":
        a = slot_aspect if slot_aspect and slot_aspect > 1 else 2.0
        w = math.sqrt(area / (a - 1.0 + math.pi / 4.0))
        out.update(width=round_up(w, grid), length=round_up(a * w, grid), slot_aspect=a)
    elif shape == "polygon" and template:
        out.update(template_scale(template["kind"], area, grid))
    else:
        raise BuilderRefused("a free vertex list has no template to scale, so no size is suggested for it")
    return out


def resulting_fill(total_area: float, faces: int, spec: dict) -> float:
    """The fill a typed size gives: the courtyard area over the faces times the board's area."""
    return total_area / (faces * shape_area(spec))


# polygon templates: a named set of dimensions that scale together, and the vertices they give
TEMPLATES = {
    # an L: the full width and height, the arm's width and the step's height
    "l_shape": {"dims": ("width", "height", "notch_width", "notch_height"), "ratios": (1.0, 0.8, 0.4, 0.5),
                "label": "L shape"},
    # a rectangle with a notch cut from the top edge
    "notch": {"dims": ("width", "height", "notch_width", "notch_depth"), "ratios": (1.0, 0.7, 0.3, 0.3), "label": "notched edge"},
    # a rectangle with its corners cut
    "cut_corners": {"dims": ("width", "height", "cut"), "ratios": (1.0, 0.7, 0.1), "label": "cut corners"},
}


def template_vertices(kind: str, dims: dict) -> list:
    """The vertices (mm from the board's top-left, y down) of a template with these dimensions."""
    d = {k: float(v) for k, v in dims.items()}
    w, h = d["width"], d["height"]
    if kind == "l_shape":
        nw, nh = d["notch_width"], d["notch_height"]
        return [[0.0, 0.0], [w, 0.0], [w, h - nh], [w - nw, h - nh], [w - nw, h], [0.0, h]]
    if kind == "notch":
        nw, nd = d["notch_width"], d["notch_depth"]
        left = (w - nw) / 2.0
        return [[0.0, 0.0], [left, 0.0], [left, nd], [left + nw, nd], [left + nw, 0.0], [w, 0.0], [w, h], [0.0, h]]
    if kind == "cut_corners":
        c = d["cut"]
        return [[c, 0.0], [w - c, 0.0], [w, c], [w, h - c], [w - c, h], [c, h], [0.0, h - c], [0.0, c]]
    raise BuilderRefused("%r is not a polygon template" % (kind,))


def template_scale(kind: str, area: float, grid: float) -> dict:
    """The template's dimensions, in their proportions, scaled so its area is `area`, each rounded up to `grid`."""
    t = TEMPLATES.get(kind)
    if t is None:
        raise BuilderRefused("%r is not a polygon template" % (kind,))
    unit = dict(zip(t["dims"], t["ratios"]))
    a1 = abs(_shoelace([tuple(p) for p in template_vertices(kind, unit)]))
    k = math.sqrt(area / a1)
    dims = {name: round_up(r * k, grid) for name, r in unit.items()}
    return {"dims": dims, "points": template_vertices(kind, dims)}


def polygon_problems(points) -> list:
    """Why a vertex list is not an outline: fewer than three vertices, a repeated vertex, a self-intersection or no area."""
    out = []
    pts = [tuple(float(v) for v in p) for p in points or ()]
    if len(pts) < 3:
        return ["an outline has at least three vertices"]
    if len(set(pts)) != len(pts):
        out.append("a vertex is repeated")
    if abs(_shoelace(pts)) < 1e-9:
        out.append("the outline has no area")
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            c, d = pts[j], pts[(j + 1) % n]
            if _segments_cross(a, b, c, d):
                out.append("the legs from vertex %d and vertex %d cross" % (i + 1, j + 1))
    return out


def _segments_cross(a, b, c, d) -> bool:
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


# ------------------------------------------------------------------ the outline's edits
def _comment_for(what: str, spec: dict, key: str, unit: str = "mm") -> str:
    """The comment above a size constant: where the number came from."""
    origin = spec.get("origin") or {}
    if origin.get("mode") == "suggested" and key in ("width", "height", "diameter", "length"):
        faces = "two faces" if origin.get("faces") == 2 else "one face"
        text = "%s, suggested by %s from the parts' courtyard area: %s mm2 on %s, at most %d%% filled per face" % (
            what, BUILDER, mm(round(origin["total_area"], 1)), faces, round(origin["fill"] * 100))
        if origin.get("aspect") is not None and spec.get("shape", "").startswith("rect"):
            text += ", aspect %s" % mm(origin["aspect"])
        return wrap(text + ".")
    return wrap("%s, chosen in %s." % (what, BUILDER))


class _Names:
    """The names a batch of edits gives its constants, never one the file already binds or an earlier edit took."""

    def __init__(self, text: str):
        self.taken = set(taken_names(text)) if text else set()

    def take(self, base: str) -> str:
        name = unique(base, self.taken)
        self.taken.add(name)
        return name


def _constant(file, name, value, comment) -> Edit:
    return Edit("set_constant", None, {"name": name, "comment": comment}, value, {}, file)


def _cutout_form(h: dict, shape_names: dict, const_name: str) -> dict:
    shape = (_form("Circle", _name(shape_names["diameter"])) if h["kind"] == "circle"
             else _form("Slot", _name(shape_names["length"]), _name(shape_names["width"])))
    at = h["at"]
    if "edge" in at:
        if at["edge"] not in EDGES:
            raise BuilderRefused("a hole's edge is NORTH, EAST, SOUTH or WEST")
        if at.get("along", "MID") != "MID":
            raise BuilderRefused("a hole is placed at the middle of an edge: along an edge a hole's place is measured from the keep-in, "
                                 "so one at the start or the end reaches past the corner", "a hole stays inside the board")
        place = _form("OnEdge", _enum("Edge." + at["edge"]), along=_enum("Along.MID"))
    else:
        if at.get("bearing") not in EDGES:
            raise BuilderRefused("a hole on a disc is at a compass bearing: NORTH, EAST, SOUTH or WEST")
        place = _form("Polar", _name(shape_names["radius"]), _enum("Edge." + at["bearing"]))
    return {"form": "Cutout", "args": [shape, _str(h["name"])], "kwargs": {"at": place}, "bind": const_name}


def outline_edits(text: str, spec: dict, file: str) -> list:
    """The edits that give a script with no outline the one `spec` describes: its size constants (each with the comment saying
    where the number came from), a hole's constants and binding, the web, the outline statement, and the names it needs imported.
    `text` is the script they apply to. Sizes are mm; every number is a named constant."""
    shape = spec.get("shape")
    if shape not in SHAPES:
        raise BuilderRefused("%r is not an outline shape the builder writes (%s)" % (shape, ", ".join(SHAPES)))
    names, edits, kw, imports = _Names(text), [], {}, set()

    def size(base, key, what, value=None, outline_key=None):
        v = float(spec[key]) if value is None else value
        name = names.take(base)
        edits.append(_constant(file, name, v, _comment_for(what, spec, outline_key or key)))
        return name

    holes = list(spec.get("holes") or [])
    if shape in ("rect", "rect_chamfer", "rect_round"):
        _positive(spec, "width"), _positive(spec, "height")
        w = size("BOARD_WIDTH_MM", "width", "The board's width")
        h = size("BOARD_HEIGHT_MM", "height", "The board's height")
        kw = {"width": _name(w), "height": _name(h)}
        half = min(spec["width"], spec["height"]) / 2.0
        if shape == "rect_chamfer":
            if not 0 < spec.get("chamfer", 0) < half:
                raise BuilderRefused("the chamfer is above 0 and under half the shorter side")
            kw["chamfer"] = _name(size("BOARD_CHAMFER_MM", "chamfer", "The board's corner chamfer"))
        if shape == "rect_round":
            if not 0 < spec.get("radius", 0) < half:
                raise BuilderRefused("the corner radius is above 0 and under half the shorter side")
            kw["radius"] = _name(size("BOARD_CORNER_RADIUS_MM", "radius", "The board's corner radius"))
        call = "board.rect"
        args = []
    elif shape in ("disc", "disc_bore"):
        _positive(spec, "diameter")
        kw = {"diameter": _name(size("BOARD_DIAMETER_MM", "diameter", "The board's diameter"))}
        if shape == "disc_bore":
            if not 0 < spec.get("bore", 0) < spec["diameter"]:
                raise BuilderRefused("the bore is above 0 and under the diameter")
            kw["hole"] = _name(size("BOARD_BORE_MM", "bore", "The diameter of the hole through the middle of the board"))
        call, args = "board.disc", []
    elif shape == "slot":
        _positive(spec, "length"), _positive(spec, "width")
        if spec["length"] <= spec["width"]:
            raise BuilderRefused("a slot is longer than it is wide")
        length = size("BOARD_LENGTH_MM", "length", "The board's length")
        width = size("BOARD_WIDTH_MM", "width", "The board's width")
        call, args = "board.outline", [_form("Slot", _name(length), _name(width))]
        imports.add("Slot")
    else:
        problems = polygon_problems(spec.get("points"))
        if problems:
            raise BuilderRefused("the outline is not a polygon: %s" % "; ".join(problems), "a polygon outline is a closed shape")
        name = names.take("BOARD_OUTLINE_MM")
        origin = spec.get("origin") or {}
        what = "The outline's vertices, chosen in %s: mm from the board's top-left, y down." % BUILDER
        if origin.get("mode") == "suggested":
            what = wrap("The outline's vertices, scaled by %s from the parts' courtyard area (%s mm2 on %s, at most %d%% filled per "
                        "face): mm from the board's top-left, y down." % (BUILDER, mm(round(origin["total_area"], 1)),
                                                                            "two faces" if origin.get("faces") == 2 else "one face",
                                                                            round(origin["fill"] * 100)))
        else:
            what = wrap(what)
        edits.append(_constant(file, name, [list(map(float, p)) for p in spec["points"]], what))
        call, args = "board.outline", [_name(name)]
    # holes
    hole_names = []
    if holes:
        is_disc = shape in ("disc", "disc_bore")
        for h in holes:
            if h.get("kind") not in ("circle", "slot") or not h.get("name"):
                raise BuilderRefused("a hole is a circle or a slot, with a name")
            at = h.get("at") or {}
            if is_disc and "bearing" not in at or (not is_disc and "edge" not in at):
                raise BuilderRefused("a hole is placed at an edge of a rectangle or at a radius and a bearing on a disc")
        web = spec.get("web")
        if any("edge" in h["at"] for h in holes):
            if not isinstance(web, (int, float)) or isinstance(web, bool) or web <= 0:
                raise BuilderRefused("a hole on an edge needs the web: the material kept round it, above 0 mm",
                                     "a hole that touches the outline is a notch, which belongs in the outline's own path")
        for h in holes:
            base = _identifier(h["name"])
            nm = {}
            if h["kind"] == "circle":
                nm["diameter"] = names.take(base + "_DIAMETER_MM")
                edits.append(_constant(file, nm["diameter"], _positive(h, "diameter"),
                                       wrap("The diameter of the %s hole, chosen in %s." % (h["name"], BUILDER))))
            else:
                nm["length"] = names.take(base + "_LENGTH_MM")
                nm["width"] = names.take(base + "_WIDTH_MM")
                edits.append(_constant(file, nm["length"], _positive(h, "length"),
                                       wrap("The length of the %s slot, chosen in %s." % (h["name"], BUILDER))))
                edits.append(_constant(file, nm["width"], _positive(h, "width"),
                                       wrap("The width of the %s slot, chosen in %s." % (h["name"], BUILDER))))
            if "bearing" in h["at"]:
                nm["radius"] = names.take(base + "_RADIUS_MM")
                edits.append(_constant(file, nm["radius"], _positive(h["at"], "radius"),
                                       wrap("The distance of the %s hole's centre from the middle of the board, chosen in %s."
                                            % (h["name"], BUILDER))))
            bind = names.take(base)
            hole_names.append((bind, _cutout_form(h, nm, bind)))
            imports |= {"Cutout", "Circle" if h["kind"] == "circle" else "Slot"} | ({"OnEdge", "Along", "Edge"} if "edge" in h["at"]
                                                                                    else {"Polar", "Edge"})
        if any("edge" in h["at"] for h in holes):
            kw["web"] = _name(size("BOARD_WEB_MM", "web", "The material kept round a hole", value=float(web)))
        kw["holes"] = {"list": [_name(b) for b, _ in hole_names]}
    outline = {"form": call, "args": args, "kwargs": kw}
    if imports:
        edits.insert(0, Edit("ensure_import", None, {"names": sorted(imports)}, None, {}, file))
    block = [f for _, f in hole_names] + [outline]
    edits.append(Edit("insert_statement", None, {"after": {"region": "outline"}}, {"block": block}, {}, file))
    return edits


def new_script(name: str, description: str, spec: dict, file: str = "layout.py") -> str:
    """The text of a script that has just its outline: the skeleton, the outline's edits applied to it in memory. The same edits
    change an existing script later, so the first write and a later change are one code path."""
    head = script_edit.skeleton(name, description)
    edits = outline_edits(head, spec, file)
    done = script_edit.apply_edits(edits, lambda p: head)
    return done[file][1]
