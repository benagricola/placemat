"""A module's arrangement note read for the board that stamped the cell: the members' places by delta from where the stamp put them, the
module's copper from its ops, and the CellGeom that stands for the arrangement. Pure: the reader (kicad/read.py) hands it the texts."""
from __future__ import annotations

import dataclasses

from . import arrangement_note as note
from .board_geometry import Arrangement, CellGeom, CopperItem, MemberPose, RuleArea, resolve_marker, stamped_net
from .copper import Pour, Track, Via, Zone, stroked_outlines
from .geometry import pose_transform, transform_box
from .placement import Placement
from .settings import active
from .values import Box, Face, Location

_TOL = 1e-3
_MALFORMED = (KeyError, TypeError, ValueError, IndexError, AttributeError, note.NoteError)
_ALLOWED_TYPES = ("tracks", "vias", "pads")     # what a keepout's allow= nets may keep (kicad/write.py _relaxed)


def _problem(reason: str, ident: str = "") -> dict:
    return {"reason": reason, "ids": [ident] if ident else []}


def _member(cell: CellGeom, inst: str):
    """The stamped member the note's instance path names: `<cell>.<inst>`, else the one member whose path ends in `.<inst>`."""
    exact = [fp for fp in cell.members if fp.inst == "%s.%s" % (cell.name, inst)]
    if exact:
        return exact[0]
    ends = [fp for fp in cell.members if fp.inst.endswith("." + inst)]
    return ends[0] if len(ends) == 1 else None


def _shift(op, dx: float, dy: float, net: str):
    moved = lambda p: Location(p.x + dx, p.y + dy) if isinstance(p, Location) else (p[0] + dx, p[1] + dy)
    if isinstance(op, Track):
        return dataclasses.replace(op, net=net, start=moved(op.start), end=moved(op.end),
                                   mid=None if op.mid is None else moved(op.mid))
    if isinstance(op, Via):
        return dataclasses.replace(op, net=net, at=moved(op.at))
    if isinstance(op, (Pour, Zone)):
        return dataclasses.replace(op, net=net, points=tuple(moved(p) for p in op.points))
    return dataclasses.replace(op, at=moved(op.at))                 # a text


def _copper_item(op, owner: str, layers):
    """The CopperItem the board reader would hold for `op` (kicad/read.py _copper); None for a text."""
    if isinstance(op, Track):
        return CopperItem("track", op.net, frozenset([op.layer]), (op.polygon,), op.box, owner, op.width, 0.0,
                          ((op.start.x, op.start.y), (op.end.x, op.end.y)), op.length)
    if isinstance(op, Via):
        return CopperItem("via", op.net, frozenset(op.layers) if op.layers else frozenset(layers), (op.polygon,), op.box, owner,
                          op.size, op.drill, ((op.at.x, op.at.y),))
    if isinstance(op, Pour):
        # a filled graphic polygon grown by its stroke (plus the arc tolerance outside), its box from that; the reader merges
        # the pieces into one polygon, which covers the same copper
        outs = stroked_outlines([op.points], op.stroke + 2 * active().geometry_arc_error_nm / 1e6, True) if op.stroke > 0 \
            else (op.points,)
        return CopperItem("poly", op.net, frozenset([op.layer]), outs, Box.of_points([p for o in outs for p in o]), owner,
                          op.stroke, 0.0, (), 0.0, (op.points,), True)
    if isinstance(op, Zone):                    # the reader gives a zone no owner: it is no cell's, and a plane to layout
        return CopperItem("zone", op.net, frozenset([op.layer]), (op.points,), op.box, None)
    return None


def _rule_area(k, cell: str, dx: float, dy: float, nets, layers) -> RuleArea:
    """A note's keepout as the board reader reads the stamped zone the fragment wrote for it (kicad/read.py _rule_areas):
    named `keepout <name>`, its declared layers resolved on this board, its allow= nets in this board's names and the copper
    types they keep relaxed."""
    have, missing = resolve_marker("*" if k.layers is None else tuple(k.layers), layers)
    relaxed = tuple(t for t in _ALLOWED_TYPES if t in k.excludes) if k.allow else ()
    allow = frozenset(n for n in (stamped_net(a, cell, nets) for a in k.allow) if n is not None)
    return RuleArea("keepout %s" % k.name, cell, tuple((x + dx, y + dy) for x, y in k.poly), have, frozenset(k.excludes),
                    missing, (), allow, relaxed)


def build(cell: CellGeom, doc: dict, nets, layers):
    """(the Arrangement, None) for note `doc` on the stamped `cell`, or (None, the problem that keeps it from standing)."""
    ident = doc.get("id", "")
    if doc.get("v") != note.VERSION:
        return None, _problem("version", ident)
    stamped = {}
    for m in doc["members"]:
        fp = _member(cell, m["inst"])
        if fp is None:
            return None, _problem("member", ident)
        stamped[m["inst"]] = fp
    if len(doc["members"]) != len(cell.members) or {fp.ref for fp in stamped.values()} != {fp.ref for fp in cell.members}:
        return None, _problem("member", ident)
    offsets = []
    for m in doc["members"]:
        fp, was = stamped[m["inst"]], note.pose_from_json(m["from"])
        turned = ((fp.rotation - was.rotation + 180.0) % 360.0) - 180.0
        if abs(turned) > _TOL or fp.face != was.face:
            return None, _problem("offset", ident)
        offsets.append((fp.location.x - was.location.x, fp.location.y - was.location.y))
    dx, dy = offsets[0]
    if any(abs(x - dx) > _TOL or abs(y - dy) > _TOL for x, y in offsets):
        return None, _problem("offset", ident)
    if note.base_digest([(m["inst"], note.pose_from_json(m["from"])) for m in doc["members"]]) != doc.get("base"):
        return None, _problem("base", ident)
    poses = []
    for m in doc["members"]:
        fp = stamped[m["inst"]]
        poses.append(MemberPose(fp.ref, m["inst"], Placement(Location(m["x"] + dx, m["y"] + dy), m["rotation"], Face(m["face"])),
                                Placement(fp.location, fp.rotation, fp.face)))
    ops, items = [], []
    for raw in doc["ops"]:
        op = note.op_from_json(raw)
        mapped = stamped_net(op.net, cell.name, nets) if op.net else ""
        if op.net and mapped is None:
            return None, _problem("net", ident)
        op = _shift(op, dx, dy, mapped)
        ops.append(op)
        item = _copper_item(op, cell.name, layers)
        if item is not None:
            items.append(item)
    areas = tuple(_rule_area(note.keepout_from_json(d), cell.name, dx, dy, nets, layers) for d in doc["keepouts"])
    by_ref = {fp.ref: fp for fp in cell.members}
    moved = lambda attr: [transform_box(getattr(by_ref[mp.ref], attr), pose_transform(mp.default, mp.pose)) for mp in poses]
    own = [c.box for c in items if c.owner is not None]     # the cell's extents hold its own copper, as the reader's do
    geom = dataclasses.replace(
        cell, box=Box.union(moved("body_box") + own), phys_box=Box.union(moved("phys_box") + own),
        courtyard_box=Box.union(moved("courtyard_box") + own), copper_box=Box.union(own) if own else None,
        arrangements=(), arrangement=ident, poses=tuple((mp.ref, mp.pose) for mp in poses), own_copper=tuple(items),
        arrangement_problems=())
    return Arrangement(ident, doc.get("choices", {}), tuple(poses), tuple(ops), areas, geom), None


def attach(cell: CellGeom, texts, nets, layers) -> CellGeom:
    """`cell` with the arrangements its note texts carry (in the order the module run gave them), and the problems of those that
    could not stand; the cell itself when it has no text."""
    texts = list(texts)
    if not texts:
        return cell
    docs, problems = note.read_notes(texts)
    built = []
    order = lambda d: (d["order"] if isinstance(d.get("order"), int) else 0, str(d["id"]))
    for d in sorted(docs, key=order):
        try:
            arr, problem = build(cell, d, nets, layers)
        except _MALFORMED:              # it parsed, but a key, kind or value is not one the note's form has
            arr, problem = None, _problem("text", d["id"])
        if arr is None:
            problems.append(problem)
        else:
            built.append(arr)
    return dataclasses.replace(cell, arrangements=tuple(built), arrangement_problems=tuple(problems))
