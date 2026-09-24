"""The cleanup pass weighs crossings and escapes as the search does, may move
a block's satellite within its limit of its pin, and swaps any two parts by
lifting both and searching each round the other's old spot."""
import dataclasses

from placemat.board_geometry import Footprint
from placemat.cleanup import cleanup
from placemat.layout import Board
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Box, Face, LinkWeight, Location, PadRef, Part
from tests.fixtures import board_geometry, pad


def two_pad(ref, inst, cx, cy, nets, pitch=1.0, size=0.5, body=(1.5, 0.6)):
    """A small two-pad part: `size` mm pads `pitch` apart along x, pad 1 west."""
    pads = (pad(ref, inst, 1, nets[0], cx - pitch / 2, cy, size, size),
            pad(ref, inst, 2, nets[1], cx + pitch / 2, cy, size, size))
    body = Box(cx - body[0] / 2, cy - body[1] / 2, cx + body[0] / 2, cy + body[1] / 2)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)


def west_row(ref, inst, cx, cy, nets):
    """A chip's west pin row: eight 0.8 x 0.25 pads 0.5 apart at x = cx - 2.4,
    pin 1 northmost; the body east of them."""
    pads = tuple(pad(ref, inst, k + 1, nets.get(k + 1, ""), cx - 2.4, cy - 1.75 + 0.5 * k, 0.8, 0.25) for k in range(8))
    body = Box(cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)


def _crossed(occ, a, b) -> int:
    from placemat.ratsnest import crossings
    rn = occ.ratsnest()
    return int(crossings([e for e in rn.edges() if e.net in (a, b)])[0])


def _brief():
    """The brief's case: EN's capacitor under pins 3-4 and the RF supply's inductor
    under pin 6, so VDD_RF from pin 3 crosses MCU_EN from pin 4."""
    fps = [west_row("U2", "mcu", 30, 30, {3: "VDD_RF", 4: "MCU_EN"}),
           two_pad("C2", "c_en", 26.1, 29.5, ("GND", "MCU_EN")),          # MCU_EN, pad 2, faces the pins
           two_pad("L2", "l_rf", 26.1, 30.75, ("VRF_IN", "VDD_RF"))]
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False)
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=cfg)
    for inst, at in (("mcu", (30, 30)), ("c_en", (26.1, 29.5)), ("l_rf", (26.1, 30.75))):
        b.place(Part(inst), at=Location(*at))
    b.link(PadRef(Part("l_rf"), "VDD_RF"), PadRef(Part("mcu"), 3), weight=LinkWeight.SHORT, limit_mm=2.0)
    plan = b.resolve()
    return b, plan


def _pins(b, plan):
    occ = plan.occupancy
    quiet = occ.quiet_nets
    pins = {}
    for fp in b.geometry.footprints:
        for p in fp.pads:
            if p.net and p.net not in quiet:
                pins.setdefault(p.net, []).append((fp.ref, p.number))
    return {n: v for n, v in pins.items() if len(v) > 1}


def _gap(occ, a, b) -> float:
    pa = [s.box for s in occ.items[a[0]].shapes if s.kind == "pad" and s.label == a[1]][0]
    pb = [s.box for s in occ.items[b[0]].shapes if s.kind == "pad" and s.label == b[1]][0]
    dx = max(pa.left - pb.right, pb.left - pa.right, 0.0)
    dy = max(pa.top - pb.bottom, pb.top - pa.bottom, 0.0)
    return (dx * dx + dy * dy) ** 0.5


def test_the_briefs_crossing_is_gone_after_cleanup_and_the_satellite_stays_within_its_limit():
    b, plan = _brief()
    occ = plan.occupancy
    assert _crossed(occ, "VDD_RF", "MCU_EN") == 1                     # as placed
    movable = {"c_en": b.geometry.footprint("C2"), "l_rf": b.geometry.footprint("L2")}
    limits = {"c_en": (("U2", "4"), ("C2", "2"), 2.0)}
    s = b.settings
    r = cleanup(occ, movable, _pins(b, plan), list(b._links), None, 2, 3.0, 0.25,
                turns={"c_en": (0, 90, 180, 270), "l_rf": (0, 90, 180, 270)}, limits=limits, settings=s)
    assert _crossed(occ, "VDD_RF", "MCU_EN") == 0, r
    assert _gap(occ, ("U2", "4"), ("C2", "2")) <= 2.0 + 1e-9
    link = next(l for l in b._links)
    assert occ.pad_location(*link.a).distance(occ.pad_location(*link.b)) <= 2.0 + 1e-9


def test_a_satellite_never_leaves_its_limit_even_for_a_better_cost():
    b, plan = _brief()
    occ = plan.occupancy
    movable = {"c_en": b.geometry.footprint("C2"), "l_rf": b.geometry.footprint("L2")}
    limits = {"c_en": (("U2", "4"), ("C2", "2"), 0.4)}                  # tight: it may barely move
    cleanup(occ, movable, _pins(b, plan), list(b._links), None, 2, 3.0, 0.25,
            turns={"c_en": (0,), "l_rf": (0, 90, 180, 270)}, limits=limits, settings=b.settings)
    assert _gap(occ, ("U2", "4"), ("C2", "2")) <= 0.4 + 1e-9


def _filler(ref, inst, x0, x1, west_net, east_net):
    """A fixed part filling the channel from x0 to x1, a pad at either end."""
    cy = 30.0
    pads = (pad(ref, inst, 1, west_net, x0 + 0.4, cy, 0.5, 0.5), pad(ref, inst, 2, east_net, x1 - 0.4, cy, 0.5, 0.5))
    body = Box(x0, cy - 0.3, x1, cy + 0.3)
    return Footprint(ref, inst, None, ref, Location((x0 + x1) / 2, cy), 0.0, Face.FRONT, body, body, body, pads)


def _channel():
    """A channel one part wide, filled but for two slots side by side: the big
    part in the west slot pulled east, the small one in the east slot pulled
    west. Neither can move anywhere but the other's slot, so only a swap helps;
    the larger is searched round the smaller's old spot first."""
    walls = []
    k = 1
    for x in range(20, 41):                    # rows of unconnected pads north and south of the channel
        walls.append(pad("W", "w", k, "", float(x), 29.25, 0.8, 0.2)); k += 1
        walls.append(pad("W", "w", k, "", float(x), 30.75, 0.8, 0.2)); k += 1
    body = Box(19.6, 29.15, 40.4, 30.85)
    wall = Footprint("W", "w", None, "W", Location(30, 30), 0.0, Face.FRONT, body, Box(19.6, 29.15, 40.4, 29.3),
                     body, tuple(walls))
    west = _filler("F1", "west_fill", 20.0, 27.7, "WEST", "Z1")          # WEST at its far end, x 20.4
    east = _filler("F2", "east_fill", 32.3, 40.0, "Z2", "EAST")          # EAST at its far end, x 39.6
    big = two_pad("B1", "big", 28.9, 30.0, ("X1", "EAST"), pitch=1.2, size=0.5, body=(1.8, 0.7))
    small = two_pad("S1", "small", 31.2, 30.0, ("WEST", "X2"))
    fps = [wall, west, east, big, small]
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False)
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=cfg)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    return b, b.resolve()


def test_two_parts_each_wanting_the_others_spot_are_swapped():
    b, plan = _channel()
    occ = plan.occupancy
    movable = {"big": b.geometry.footprint("B1"), "small": b.geometry.footprint("S1")}
    # wire alone: in a channel this tight every pad is walled in somewhere, which is not the question here
    wire = dataclasses.replace(b.settings, score_escape_crossed=0.0, score_escape_closed=0.0, score_escape_walled=0.0)
    r = cleanup(occ, movable, _pins(b, plan), [], None, 1, 1.0, 0.25,
                turns={"big": (0,), "small": (0,)}, settings=wire)
    assert r.swaps == [("big", "small")] or r.swaps == [("small", "big")]
    assert occ.items["B1"].reference.location.x > 30 and occ.items["S1"].reference.location.x < 30


def test_fixed_parts_are_never_offered_to_the_cleanup():
    b, plan = _brief()
    from placemat.layout import Board as _B
    assert "mcu" not in b._cleanup_movable(plan)
