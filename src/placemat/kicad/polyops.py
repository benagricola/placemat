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
