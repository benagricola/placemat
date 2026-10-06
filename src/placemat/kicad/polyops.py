"""Polygon booleans for the planner, by KiCad's own SHAPE_POLY_SET.

placemat has no boolean library of its own; a fitted pour's reach (the
outline grown into the room round it, cut back by other nets' clearance
outlines) is the one place the plan needs one. This is the single place
the plan reaches pcbnew, and only when a pour declares `reach=`.
"""
from __future__ import annotations

_NM = 1_000_000.0           # nanometres a millimetre: SHAPE_POLY_SET holds integers


def available() -> bool:
    try:
        import pcbnew      # noqa: F401
    except Exception:
        return False
    return True


def _set(pcbnew, polys):
    out = pcbnew.SHAPE_POLY_SET()
    for poly in polys:
        out.NewOutline()
        for x, y in poly:
            out.Append(int(round(x * _NM)), int(round(y * _NM)))
    return out


def _loop(chain) -> tuple:
    return tuple((round(p.x / _NM, 6), round(p.y / _NM, 6)) for p in chain.CPoints())


def grow_and_cut(outline, reach: float, sag: float, cutters) -> list:
    """`outline` (a simple polygon, mm) grown by `reach` with arcs no more than
    `sag` off, less every polygon of `cutters`, and of what is left the
    pieces that touch `outline`: each a simple polygon as KiCad fractures one
    (a hole is joined to the outside by a bridge of no width). The first is
    the largest."""
    import pcbnew
    region = _set(pcbnew, [outline])
    base = _set(pcbnew, [outline])
    region.Inflate(int(round(reach * _NM)), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                   max(1, int(round(sag * _NM))))
    if cutters:
        region.BooleanSubtract(_set(pcbnew, cutters))
    # a sliver at the rounding of a coordinate (a nanometre) is not copper
    region.Simplify()
    joined = []
    for i in range(region.OutlineCount()):
        one = pcbnew.SHAPE_POLY_SET()
        one.AddOutline(region.Outline(i))
        for h in range(region.HoleCount(i)):
            one.AddHole(region.Hole(i, h))
        touch = pcbnew.SHAPE_POLY_SET(one)
        touch.BooleanIntersection(base)
        if touch.Area() <= 0.0:
            continue
        one.Fracture()
        joined.append((one.Area(), _loop(one.Outline(0))))
    joined.sort(key=lambda t: -t[0])
    return [loop for _, loop in joined]


def cut_holes(outline, holes, min_width: float, max_error: float, members) -> tuple:
    """`outline` (a simple polygon, mm) with each polygon of `holes` cut out of it, as KiCad's zone filler cuts other
    nets' clearances out of a zone's fill (pcbnew/zone_filler.cpp, 10.0, ZONE_FILLER::fillCopperZone): the clearance
    holes subtracted (:3051), features under `min_width` pruned by deflating by half of it less a micron with chamfered
    corners (:3058-3060) and inflating back with round ones (:3159-3160), trimmed to the outline and the holes
    subtracted again (:3181-3182), and fractured into simple polygons (:3237). The zone filler's thermal reliefs,
    hatching and island removal are not ported: a fitted pour has none of them, and a pour that falls apart is
    refused instead. Returns (loops, joined): the pieces left, each a simple polygon (a hole joined to the outside by
    a bridge of no width), and whether they are one piece that every polygon of `members` touches."""
    import pcbnew
    base = _set(pcbnew, [outline])
    cut = _set(pcbnew, holes)
    fill = _set(pcbnew, [outline])
    fill.BooleanSubtract(cut)
    epsilon = int(round(0.001 * _NM))
    half = int(round(min_width / 2.0 * _NM))
    err = max(1, int(round(max_error * _NM)))
    if half - epsilon > epsilon:
        fill.Deflate(half - epsilon, pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, err)
        fill.Inflate(half - epsilon, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, err, True)
    fill.BooleanIntersection(base)
    fill.BooleanSubtract(cut)
    fill.Simplify()
    joined = fill.OutlineCount() == 1
    for m in members if joined else ():
        touch = pcbnew.SHAPE_POLY_SET(fill)
        touch.BooleanIntersection(_set(pcbnew, [m]))
        if touch.Area() <= 0.0:
            joined = False
            break
    fill.Fracture()
    return [_loop(fill.Outline(i)) for i in range(fill.OutlineCount())], joined
