"""A track's 45 past a Corner is judged against the copper on the track's
own layer: pads on other faces name the lane, but only copper the track
shares a layer with can be passed too close. Pure: synthetic boards."""
import dataclasses
import math


from placemat.board_geometry import Footprint
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Corner, Face, Location, Net, PadRef, Part, Past
from tests.fixtures import board_geometry, pad

F, B = CopperLayer.F, CopperLayer.B
IN1, IN2 = CopperLayer.IN1, CopperLayer.IN2
FOUR = (F, IN1, IN2, B)


def _one_pad_part(ref, inst, net, cx, cy, w, h):
    p = pad(ref, inst, 1, net, cx, cy, w, h)
    body = Box(cx - w / 2 - 0.5, cy - h / 2 - 0.5, cx + w / 2 + 0.5, cy + h / 2 + 0.5)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _board(with_via):
    pa = _one_pad_part("PA", "pa", "MID", 10.0, 20.0, 1.0, 1.0)       # F.Cu only: box (9.5, 19.5)-(10.5, 20.5)
    geom = dataclasses.replace(board_geometry([pa], width=60, height=60, extra_nets=["SIG", "GND"]), layers=FOUR)
    b = Board(geom, edge_margin=1.0)
    items = [PadRef(Part("pa"), 1)]
    if with_via:
        items.append(b.via(Net("GND"), at=Location(12.0, 22.0), size=0.45))     # through: on every layer
    return b, items


def _corner_findings(b, items, layer, corner_x):
    # due north through the point past the south-east corner: the leg runs along the east side,
    # 0.1 + 0.2 mm off the corner on each axis
    px = math.ceil((corner_x + 0.3 / math.sqrt(2)) * 1e6 - 1e-3) / 1e6
    b.track(Net("SIG"), [Location(px, 30.0), Past(items, Corner.SE), Location(px, 5.0)], layer=layer, chamfer=0)
    return [str(f) for f in b.resolve().findings if "45 past" in str(f)]


def test_an_inner_track_past_the_corner_of_front_only_pads_has_no_finding():
    b, items = _board(False)
    assert _corner_findings(b, items, IN2, 10.5) == []


def test_an_inner_track_is_judged_against_a_via_that_spans_its_layer():
    b, items = _board(True)
    found = _corner_findings(b, items, IN2, 12.3059)
    assert len(found) == 1, found
    assert "via GND" in found[0] and "PA.1" not in found[0], found


def test_a_front_track_past_the_same_pads_still_has_the_finding():
    b, items = _board(False)
    found = _corner_findings(b, items, F, 10.5)
    assert len(found) == 1 and "PA.1" in found[0], found
