"""Synthetic placed boards for the pin map study's tests: a square part with pins on its sides and the parts its nets run
to, as PlacedPads and PlacedParts (pinmap_input), so the study is tested without a resolve."""
from dataclasses import replace

from placemat.pinmap_input import PlacedPad, PlacedPart, build
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Location

SIDES = ("E", "S", "W", "N")


def settings(**kw):
    """The defaults, with a budget no test meets unless it says so."""
    base = dict(pins_budget_ms=60000)
    base.update(kw)
    return replace(Settings(), **base)


def pad(ref, number, net, x, y, size=0.6, layer=CopperLayer.F, no_connect=False) -> PlacedPad:
    o = ((x - size / 2, y - size / 2), (x + size / 2, y - size / 2), (x + size / 2, y + size / 2), (x - size / 2, y + size / 2))
    return PlacedPad(ref, str(number), net, frozenset([layer]), (o,), Box.of_points(o), Location(x, y), no_connect)


def quad(ref, cx, cy, sides: dict, fields=None, body=4.0, pitch=1.0, rotation=0.0, face="front", may_flip=False) -> tuple:
    """(pads, PlacedPart) of a part `body` mm square centred at (cx, cy), its courtyard 0.25 mm round it, with pins on
    its sides: `sides` {"E" | "S" | "W" | "N": [net, ...]}, each side's pins in order north to south (E, W) or west to
    east (N, S), numbered from 1 in the order E, S, W, N. A net of "" is a pin with none."""
    pads, n, h = [], 0, body / 2.0 - 0.3
    for side in SIDES:
        nets = sides.get(side, ())
        for i, net in enumerate(nets):
            off = -(len(nets) - 1) / 2.0 * pitch + i * pitch
            x, y = {"E": (cx + h, cy + off), "W": (cx - h, cy + off), "N": (cx + off, cy - h), "S": (cx + off, cy + h)}[side]
            n += 1
            pads.append(pad(ref, n, net, x, y))
    c = body / 2.0 + 0.25
    return pads, PlacedPart(ref, Box(cx - c, cy - c, cx + c, cy + c), rotation, face, may_flip, dict(fields or {}))


def two_pad(ref, net_a, net_b, x, y) -> list:
    """A passive centred at (x, y): pad 1 on `net_a` 0.5 mm west, pad 2 on `net_b` 0.5 mm east."""
    return [pad(ref, 1, net_a, x - 0.5, y), pad(ref, 2, net_b, x + 0.5, y)]


def point_pad(ref, net, x, y) -> list:
    return [pad(ref, 1, net, x, y)]


def complete(pads, parts) -> dict:
    """`parts` with every other part the pads name made up from its pads: a box 0.1 mm round them."""
    parts = dict(parts)
    for p in pads:
        if p.ref not in parts:
            b = Box.union([q.box for q in pads if q.ref == p.ref])
            parts[p.ref] = PlacedPart(p.ref, b.inflate(0.1), 0.0, "front")
    return parts


def input_of(pads, parts, quiet=frozenset(), partners=None, netclasses=None, names=None, follow=True) -> tuple:
    """`build` with every other placed part made up from its pads."""
    return build(pads, complete(pads, parts), names or {}, frozenset(quiet), partners or {}, netclasses or {}, follow)


def reversed_four(fields=None) -> tuple:
    """U1 with nets A-D on its east side, north to south, and four test points due east of it in the opposite order:
    every pair of airwires crosses (6 crossings) until A and D, B and C trade pins."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C", "D"]}, {"Pm.PinPool": "1-4"} if fields is None else fields)
    for i, net in enumerate(["D", "C", "B", "A"]):
        pads += point_pad("TP%d" % (i + 1), net, 20, 8.5 + i)
    return pads, {"U1": u1}


def quad_footprint(ref, cx, cy, sides: dict, fields=None, inst=None):
    """`quad` as a generated board's Footprint, for a BoardGeometry (tests.fixtures.board_geometry) or a resolve."""
    from placemat.board_geometry import Footprint, PadGeom
    from placemat.values import Face
    inst = inst or ref.lower()
    pads, part = quad(ref, cx, cy, sides, fields)
    geoms = tuple(PadGeom(ref, inst, p.number, p.net, p.layers, p.outlines, p.box, False, anchor=p.anchor) for p in pads)
    body = part.courtyard.inflate(-0.25)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, part.courtyard, body, geoms,
                     fields=dict(fields or {}))
