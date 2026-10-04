"""How much room a searched item has: an estimate of how many legal spots its declaration leaves it, for `place.order = "room"`.

The count is made from what the declaration says and from the board as it stands when the first searched item is
reached (the firm items placed, their keepouts and reservations in). No spot is judged: a judgment per spot per item
is the search itself. A line, an edge, a run, a rim, a ring, a spoke is a length (less the item's own size, which
cannot reach the ends of it); a `Near` hint, a `Polar` band and an item left to the whole board are an area (the
board's free area for the last), less what the declaration and the board take out of it: a `board.push` hard-limit disc
and each reservation that does not let the item in. A length counts `length / place.room_pitch` spots and an area
`area / place.room_pitch ** 2`; a turn searched on a point counts its turns. An overlap of a cut with its region is the
overlap of their boxes, taken as a share of the cut (a region whose place is not known takes the share of the board it is), so the figure says how tight an item is and no more.

The result is one record, `{"form", "spots", "cut_mm2"}`; `level` turns spots into the band items are compared in.
"""
from __future__ import annotations

import math

from .values import Disc, Edge, Face, Location


def level(spots: float, ratio: float) -> int:
    """The band a spot count falls in: -1 for fewer than one spot, else how many times `ratio` goes into it. Items in one
    band are level."""
    if spots < 1.0:
        return -1
    return int(math.floor(math.log(spots) / math.log(ratio) + 1e-9))


def _poly_area(poly) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))) / 2.0


def _share(inner, outer) -> float:
    """The share of the box `inner` that `outer` covers."""
    w = min(inner.right, outer.right) - max(inner.left, outer.left)
    h = min(inner.bottom, outer.bottom) - max(inner.top, outer.top)
    if w <= 0 or h <= 0 or inner.area <= 0:
        return 0.0
    return min(w * h / inner.area, 1.0)


def _length(board, occ, i, size: float) -> tuple | None:
    """(form, mm) of the line a slide runs along, less the item's own size, or None when the item is searched over an area."""
    box, keep = occ.board_box, board.keep_in
    if i.run is not None:
        return "run", i.run.length - size
    if i.rim is not None:
        disc = board._shape if isinstance(board._shape, Disc) else None
        r = (disc.bore if i.rim == "bore" else disc.radius) if disc is not None else min(box.width, box.height) / 2.0
        return "rim", 2.0 * math.pi * r - size
    if i.radius_at is not None:
        return "ring", 2.0 * math.pi * float(i.radius_at) - size
    if i.angle is not None:
        if i.band is not None:
            lo, hi = i.band
        elif isinstance(board._shape, Disc):
            lo, hi = board._shape.bore + keep, board._shape.radius - keep
        else:
            lo, hi = 0.0, max(box.width, box.height)
        return "spoke", hi - lo - size
    if i.edge is not None:
        along = box.width if i.edge in (Edge.NORTH, Edge.SOUTH) else box.height
        return "edge", along - 2.0 * keep - size
    if i.pin_x is not None or i.pin_y is not None:
        along = box.height if i.pin_x is not None else box.width
        return "line", along - 2.0 * keep - size
    return None


def measure(board, occ, i, pitch: float) -> dict:
    """The room item `i` has: `{"form", "spots", "cut_mm2"}` (`cut_mm2` only when something was taken out of an area)."""
    item = i.item.anchor if i.kind == "block" else i.item
    geom = occ._geometry(item)
    size = (geom.body.width + geom.body.height) / 2.0
    if i.turns_on_point:
        return {"form": "turns", "spots": float(len(board._turns(i)))}
    line = _length(board, occ, i, size)
    if line is not None:
        form, mm = line
        return {"form": form, "spots": max(mm, 0.0) / pitch}
    box = occ.board_box
    whole = occ.free_area(i.face if i.face in (Face.FRONT, Face.BACK) else Face.FRONT)
    located = True              # whether the region's place on the board is known
    if i.band is not None:
        lo, hi = i.band
        form, area = "band", math.pi * (float(hi) ** 2 - float(lo) ** 2)
        region, located = box, False
    elif i.near is not None:
        form, area = "near", math.pi * i.radius ** 2
        region, located = box, False
        if isinstance(i.near, Location) and i.near.x is not None and i.near.y is not None:
            region, located = type(box)(i.near.x - i.radius, i.near.y - i.radius,
                                        i.near.x + i.radius, i.near.y + i.radius), True
            area *= _share(region, box)
    else:
        form, area, region = "board", whole, box
    area = min(area, whole)
    # Where the region lies is not known: a cut is taken to be spread evenly over the board, so the region has its share.
    spread = 1.0 if located or whole <= 0 else area / whole
    cut = 0.0
    for p in i.pushes:
        limit = p.limit if p.hard_limit is None else p.hard_limit
        if limit > 0:
            try:
                radius = p.r_ref * (p.v_ref / limit) ** (1.0 / p.falloff) - p.slack
            except OverflowError:
                continue
            cut += math.pi * max(radius, 0.0) ** 2 * spread
    for r in occ.reservations:
        if (r.layer is not None and r.layer.face not in (None, i.face)) or occ.let_in(r, geom):
            continue
        cut += _poly_area(r.poly) * _share(r.box, region) * spread
    cut = min(cut, area)
    out = {"form": form, "spots": max(area - cut, 0.0) / (pitch * pitch)}
    if cut > 0:
        out["cut_mm2"] = cut
    return out
