"""A QFN-32 for the escape-lane tests: eight pads a side at 0.5 mm pitch, each 0.25 x 0.7 mm with its
long side out, pad centres 2.45 mm from the middle. Pins run counter-clockwise from the north row's east
end: north 25..32 (east to west), west 1..8 (north to south), south 9..16, east 17..24. At (30, 30) the
north row's tips are at y = 27.2 and its westmost pad is pin 32 at x = 28.25."""
import dataclasses

from placemat.board_geometry import Footprint, NetClass
from placemat.layout import Board
from placemat.values import Box, Face, Location, Part
from tests.fixtures import board_geometry, footprint, pad

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
    netclasses = {n: NetClass("Default", track, clearance, VIA, DRILL) for n in geom.nets}
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
