"""The stretches of a shaped board's edge, from the plan's outline, for the builder's edge targets.

On a rectangle the four sides are `Edge.NORTH/EAST/SOUTH/WEST`. On a shaped board (a slot, a polygon) a side is chosen, not named: a
stretch of the outline is `board.edge(facing=Edge.NORTH)`, the one stretch whose outward side points within 45 degrees of north. The
page may offer a stretch only where that call names it exactly once, or with `outermost=True` where the stretch whose middle lies
furthest out that way is unique; otherwise it is greyed with the reason (the script narrows `within=` or picks from `board.edges()`).
This reads the plan's outline polygon, so an arc is its small straight legs: an estimate that the engine's own answer settles when the
statement is tried or resolved."""
from __future__ import annotations

import math

WITHIN = 45.0           # board.edge's default `within`, degrees
FACING = {"NORTH": (0.0, -1.0), "EAST": (1.0, 0.0), "SOUTH": (0.0, 1.0), "WEST": (-1.0, 0.0)}      # y grows downward


def _area(poly) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1])) / 2.0


def outer_loop(loops):
    """The board's own edge: the loop of the largest area (the others are holes)."""
    return max(loops, key=lambda l: abs(_area([tuple(p) for p in l])), default=None)


def runs(loops, facing: str, within: float = WITHIN) -> list:
    """The stretches of the outline facing `facing` within `within` degrees, each `{"middle": (x, y), "reach": how far out its middle
    lies that way}`, in the order the outline runs."""
    poly = outer_loop(loops)
    if poly is None or facing not in FACING:
        return []
    pts = [tuple(p) for p in poly]
    n = len(pts)
    fx, fy = FACING[facing]
    sign = 1.0 if _area(pts) > 0 else -1.0        # which side of a leg the inside is, for this winding in a y-down frame
    flags, mids = [], []
    for i in range(n):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-9:
            flags.append(False)
            mids.append(((x1 + x2) / 2, (y1 + y2) / 2))
            continue
        nx, ny = sign * dy / length, -sign * dx / length          # the outward normal
        ang = math.degrees(math.acos(max(-1.0, min(1.0, nx * fx + ny * fy))))
        flags.append(ang <= within + 1e-6)
        mids.append(((x1 + x2) / 2, (y1 + y2) / 2))
    if not any(flags):
        return []
    start = next((i for i in range(n) if not flags[i]), None)
    groups, cur = [], []
    order = range(n) if start is None else [(start + 1 + k) % n for k in range(n)]
    for i in order:
        if flags[i]:
            cur.append(i)
        elif cur:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        xs = [mids[i][0] for i in g]
        ys = [mids[i][1] for i in g]
        mid = (sum(xs) / len(xs), sum(ys) / len(ys))
        out.append({"middle": mid, "reach": mid[0] * fx + mid[1] * fy, "legs": len(g)})
    return out


def nameable(loops, facing: str, within: float = WITHIN) -> dict:
    """How `board.edge(facing=)` can name the stretch: `{"ok": True, "outermost": False}` where exactly one faces that way,
    `{"ok": True, "outermost": True}` where several do and one lies furthest out, else `{"ok": False, "why": ...}`."""
    rs = runs(loops, facing, within)
    word = facing.lower()
    if not rs:
        return {"ok": False, "why": "no part of this board's edge faces %s within %g degrees" % (word, within), "count": 0}
    if len(rs) == 1:
        return {"ok": True, "outermost": False, "count": 1}
    best = max(r["reach"] for r in rs)
    top = [r for r in rs if abs(r["reach"] - best) < 1e-6]
    if len(top) == 1:
        return {"ok": True, "outermost": True, "count": len(rs)}
    return {"ok": False, "count": len(rs), "why": "%d stretches face %s and none lies furthest out: it cannot be named without a number" % (len(rs), word)}
