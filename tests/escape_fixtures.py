"""A QFN-32 for the escape-lane tests: eight pads a side at 0.5 mm pitch, each 0.25 x 0.7 mm with its
long side out, pad centres 2.45 mm from the middle. Pins run counter-clockwise from the north row's east
end: north 25..32 (east to west), west 1..8 (north to south), south 9..16, east 17..24. At (30, 30) the
north row's tips are at y = 27.2 and its westmost pad is pin 32 at x = 28.25."""
import dataclasses
import math

from placemat.board_geometry import Footprint, NetClass
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Face, Location, Part
from tests.fixtures import board_geometry, pad

PITCH, PAD_W, PAD_L, RING = 0.5, 0.25, 0.7, 2.45
TRACK, CLEAR, VIA, DRILL = 0.2, 0.2, 0.45, 0.2


def qfn(ref="U1", inst="pd", cx=30.0, cy=30.0, nets=None, face=Face.FRONT):
    """The QFN-32. `nets` maps a pin number to its net (default: net `N<pin>`)."""
    nets = nets or {}
    pads = []
    for k in range(8):
        off = (3.5 - k) * PITCH                       # 1.75 .. -1.75
        for number, (x, y, w, h) in {
                25 + k: (cx + off, cy - RING, PAD_W, PAD_L),         # north: 25 east .. 32 west
                1 + k: (cx - RING, cy + off * -1.0, PAD_L, PAD_W),   # west: 1 north .. 8 south
                9 + k: (cx - off, cy + RING, PAD_W, PAD_L),          # south: 9 west .. 16 east
                17 + k: (cx + RING, cy + off, PAD_L, PAD_W)}.items():   # east: 17 south .. 24 north
            pads.append(pad(ref, inst, number, nets.get(number, "N%d" % number), x, y, w, h, face=face))
    body = Box(cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5)
    phys = Box.union([body] + [p.box for p in pads])
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, face, body, body.inflate(0.1), phys, tuple(pads))


def board_with(parts, track=TRACK, clearance=CLEAR, width=60, height=60, nets=(), classes=None, **kw):
    """A Board over `parts`, every net's class `track` wide with `clearance`; `classes` overrides some."""
    geom = board_geometry(parts, width=width, height=height, clearance=clearance, extra_nets=nets)
    # a board given via_size/via_drill has classes with those vias, as a project's would
    netclasses = {n: NetClass("Default", track, clearance, kw.get("via_size", VIA), kw.get("via_drill", DRILL))
                  for n in geom.nets}
    netclasses.update(classes or {})
    geom = dataclasses.replace(geom, netclasses=netclasses)
    kw.setdefault("via_size", VIA)
    kw.setdefault("via_drill", DRILL)
    return Board(geom, edge_margin=1.0, **kw)


PD_NETS = {32: "VOUT", 31: "SENSE", 30: "PGOOD"}


def pd_board(**kw):
    """The north-row model: a QFN whose pins 32, 31, 30 are VOUT, SENSE, PGOOD, placed at (30, 30)."""
    b = board_with([qfn(nets=PD_NETS)], **kw)
    b.place(Part("pd"), at=Location(30, 30))
    return b


def small_part(ref, inst, nets, cx=45.0, cy=50.0, span=1.0, size=0.3):
    """A two-pad part with square `size` pads `span` apart (an 0402's worth), pad 1 to the west."""
    pads = (pad(ref, inst, 1, nets[0], cx - span / 2, cy, size, size), pad(ref, inst, 2, nets[1], cx + span / 2, cy, size, size))
    body = Box(cx - span / 2 - 0.2, cy - 0.4, cx + span / 2 + 0.2, cy + 0.4)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)


# A 0.4 mm pitch QFN-56 (fourteen pads a side, each 0.2 x 0.665 with its long side out, pad centres 3.41 mm from the
# middle) and the fan model on its west row: pins 43..56 run north to south down the west side, 1..14 west to east along
# the south, 15..28 south to north up the east and 29..42 east to west along the north.
PITCH56, PAD_W56, PAD_L56, RING56 = 0.4, 0.2, 0.665, 3.41
TRACK56, CLEAR56 = 0.16, 0.16


def qfn56(ref="U1", inst="mcu", cx=30.0, cy=30.0, nets=None, face=Face.FRONT, exposed=False):
    """The QFN-56. `nets` maps a pin number to its net (default: net `N<pin>`); `exposed` adds the 5.7 mm exposed pad,
    pin 57, on net GND."""
    nets = nets or {}
    pads = [pad(ref, inst, 57, nets.get(57, "GND"), cx, cy, 5.7, 5.7, face=face)] if exposed else []
    for k in range(14):
        off = -2.6 + k * PITCH56                                    # -2.6 .. 2.6
        for number, (x, y, w, h) in {
                1 + k: (cx + off, cy + RING56, PAD_W56, PAD_L56),           # south: 1 west .. 14 east
                15 + k: (cx + RING56, cy - off, PAD_L56, PAD_W56),          # east: 15 south .. 28 north
                29 + k: (cx - off, cy - RING56, PAD_W56, PAD_L56),          # north: 29 east .. 42 west
                43 + k: (cx - RING56, cy + off, PAD_L56, PAD_W56)}.items():  # west: 43 north .. 56 south
            pads.append(pad(ref, inst, number, nets.get(number, "N%d" % number), x, y, w, h, face=face))
    body = Box(cx - 3.5, cy - 3.5, cx + 3.5, cy + 3.5)
    phys = Box.union([body] + [p.box for p in pads])
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, face, body, body.inflate(0.1), phys, tuple(pads))


def fan_board(parts=(), nets=(), exposed=False, pin_nets=None, **kw):
    """The QFN-56 at (30, 30) among `parts`, track 0.16 and clearance 0.16, placed; `pin_nets` maps a pin to its net."""
    b = board_with([qfn56(nets=pin_nets, exposed=exposed), *parts], track=TRACK56, clearance=CLEAR56, nets=nets, **kw)
    b.place(Part("mcu"), at=Location(30, 30))
    return b


def one_pad(ref, inst, net, x, y, size=0.3, other=None):
    """A part with one square pad of `size` centred at (x, y), net `net` (and, with `other` = (net, dx, dy), a second pad
    of that net at that offset from the first)."""
    pads = [pad(ref, inst, 1, net, x, y, size, size)]
    if other is not None:
        pads.append(pad(ref, inst, 2, other[0], x + other[1], y + other[2], size, size))
    body = Box.union([p.box for p in pads]).inflate(0.1)
    return Footprint(ref, inst, None, ref, Location(x, y), 0.0, Face.FRONT, body, body.inflate(0.1), body, tuple(pads))


def turned_pad(owner, inst, number, net, cx, cy, w, h, degrees):
    """A pad of `w` x `h` centred at (cx, cy), its w side along the direction `degrees` from +x toward +y (a part turned 135
    in KiCad's frame stands its pads' w side along (1, 1) / sqrt 2: 45 here)."""
    from placemat.board_geometry import PadGeom
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    poly = tuple((cx + x * c - y * s, cy + x * s + y * c) for x, y in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)))
    return PadGeom(owner, inst, str(number), net, frozenset([CopperLayer.F]), (poly,), Box.of_points(poly), False, 0.0)


def bypass_135(ref, inst, nets, cx, cy, size=(0.56, 0.62)):
    """A two-pad part turned 135 (an 0402 bypass's pads, 0.56 x 0.62, 0.96 apart) at (cx, cy): pad 1 south-east of the
    middle, pad 2 north-west."""
    d = 0.48 / math.sqrt(2.0)
    pads = (turned_pad(ref, inst, 1, nets[0], cx + d, cy + d, *size, 45.0),
            turned_pad(ref, inst, 2, nets[1], cx - d, cy - d, *size, 45.0))
    body = Box.union([p.box for p in pads])
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)


# An SOIC-8 (1.27 mm pitch, pads 1.55 x 0.6 with their long side out, pad centres 2.7 mm either side of the middle) and
# 0402s round its pin 1 for the surface-lane tests. Pins 1..4 run north to south down the west side, 5..8 south to north
# up the east. At (30, 30) pin 1 is at (27.3, 28.095), its outer edge at x = 26.525, its normal west.
SOIC_PITCH, SOIC_PAD_L, SOIC_PAD_W, SOIC_ROW = 1.27, 1.55, 0.6, 2.7
PIN1_EDGE = 30.0 - SOIC_ROW - SOIC_PAD_L / 2       # x of pin 1's outer edge
PIN1_Y = 30.0 - 1.5 * SOIC_PITCH


def soic8(ref="U1", inst="u1", cx=30.0, cy=30.0, nets=None):
    """The SOIC-8. `nets` maps a pin number to its net (default: net `N<pin>`)."""
    nets = nets or {}
    pads = []
    for k in range(4):
        y = cy + (k - 1.5) * SOIC_PITCH
        pads.append(pad(ref, inst, 1 + k, nets.get(1 + k, "N%d" % (1 + k)), cx - SOIC_ROW, y, SOIC_PAD_L, SOIC_PAD_W))
        pads.append(pad(ref, inst, 8 - k, nets.get(8 - k, "N%d" % (8 - k)), cx + SOIC_ROW, y, SOIC_PAD_L, SOIC_PAD_W))
    body = Box(cx - 1.95, cy - 2.45, cx + 1.95, cy + 2.45)
    phys = Box.union([body] + [p.box for p in pads])
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body, phys, tuple(pads))


def c0402(ref, inst, nets, cx, cy, across=True):
    """An 0402: two 0.6 mm square pads 1.0 mm apart, along y when `across` (across a west-facing pin's normal), else
    along x; the courtyard tight round the pads."""
    off = ((0.0, -0.5), (0.0, 0.5)) if across else ((-0.5, 0.0), (0.5, 0.0))
    pads = tuple(pad(ref, inst, k + 1, nets[k], cx + dx, cy + dy, 0.6, 0.6) for k, (dx, dy) in enumerate(off))
    body = Box.union([p.box for p in pads])
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body, body, pads)


def ic_with_cap_board(offset_mm=1.5, lateral_mm=0.0, room=True, pin1_net="SIG", plane=False, **kw):
    """The SOIC-8 at (30, 30), its pin 1 on `pin1_net` joined to T1 10 mm west, and C1, an 0402 across pin 1's normal
    `offset_mm` clear of the pin's outer edge and `lateral_mm` south of its centre line. `room=False` adds C2 and C3,
    0402s along the normal, centred 1.0 mm out from the middle of the pin's edge at 45 degrees either side of the normal
    and moved 0.7 mm further to that side, clear of C1: they stand across the pin's two diagonal lanes west and leave
    the via spot at its edge clear. `plane` puts a plane on `pin1_net`, making it quiet. Every part is placed where it is
    drawn."""
    from placemat.values import Net
    fps = [soic8(nets={1: pin1_net}),
           c0402("C1", "c1", ("CA", "CB"), PIN1_EDGE - offset_mm - 0.3, PIN1_Y + lateral_mm),
           small_part("T1", "t1", (pin1_net, "TZ"), cx=PIN1_EDGE - 10.0, cy=PIN1_Y)]
    if not room:
        d = 1.0 / math.sqrt(2.0)
        fps += [c0402("C2", "c2", ("DA", "DB"), PIN1_EDGE - d - 0.8, PIN1_Y - d - 0.7, across=False),
                c0402("C3", "c3", ("EA", "EB"), PIN1_EDGE - d - 0.8, PIN1_Y + d + 0.7, across=False)]
    b = board_with(fps, keep_going=True, **kw)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    if plane:
        b.plane(Net(pin1_net), [CopperLayer.B], why="the net's plane")
    return b


def ic_with_cap(**kw):
    """`ic_with_cap_board`'s board resolved: (its occupancy, the Escapes the findings are judged with)."""
    from placemat.escapes import judging
    occ = ic_with_cap_board(**kw).resolve().occupancy
    return occ, judging(occ)
