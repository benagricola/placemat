"""A pad walled in is a finding naming what walls it; a pad that copper of its own net already leaves (a track
from it, a via in it, a pour over it) has its way out, and what walls a pad is named as a refusal names it."""
import dataclasses


from placemat.board_geometry import Footprint
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Edge, Face, Location, Net, PadRef, Part
from tests.escape_fixtures import pd_board
from tests.fixtures import board_geometry, footprint, pad
from tests.test_escape_findings import _walled_in

F = CopperLayer.F


def _board(fps, **kw):
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False)
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=cfg, keep_going=True, **kw)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    return b


def _walled(plan):
    return [str(f) for f in plan.findings if f.kind == "escape_walled"]


IN = PadRef(Part("u9"), 1)


def test_the_walled_pad_of_the_fixture_is_still_a_finding():
    assert _walled(_board(_walled_in(0.1)).resolve()) == ["U9 pin 1 (IN): walled off by R9"]


def test_a_via_in_the_pad_is_a_way_out():
    b = _board(_walled_in(0.1))
    b.via(Net("IN"), IN, why="the pad's own via")
    assert _walled(b.resolve()) == []


def test_a_pour_over_the_pad_is_a_way_out():
    b = _board(_walled_in(0.1))
    b.pour(Net("IN"), [Location(29.9, 29.9), Location(30.1, 29.9), Location(30.1, 30.1)], layer=F,
           why="its own pour")
    assert _walled(b.resolve()) == []


def test_copper_of_another_net_on_the_pad_is_not_a_way_out():
    b = _board(_walled_in(0.1))
    b.track(Net("Z"), [Location(30.0, 29.9), Location(30.0, 30.0)], layer=F, why="another net's track on the pad")
    assert _walled(b.resolve())


def _ring_open_south():
    """U9's IN pad at (30, 30) ringed 0.1 mm off by R9's pads, the south one left out for a track."""
    fps = _walled_in(0.1)
    ring = fps[1]
    keep = tuple(p for p in ring.pads if abs(p.box.center.x - 30.0) > 0.1 or p.box.center.y < 30.5)
    assert len(keep) == len(ring.pads) - 1
    fps[1] = Footprint(ring.ref, ring.inst, None, ring.ref, ring.location, 0.0, Face.FRONT, ring.body_box,
                       ring.courtyard_box, ring.phys_box, keep)
    return fps


def test_a_track_from_the_pad_out_of_the_ring_is_a_way_out():
    b = _board(_ring_open_south())
    b.track(Net("IN"), [IN, Location(30.0, 32.0)], layer=F, why="a track from the pad through the gap")
    assert _walled(b.resolve()) == []


def test_a_track_from_the_pad_that_ends_in_the_wall_is_walled_off():
    """A track that goes nowhere is the pad's copper, and the way out is looked for from where it ends."""
    b = _board(_walled_in(0.1))
    b.track(Net("IN"), [IN, Location(30.0, 30.1)], layer=F, why="a track from the pad that goes nowhere")
    assert _walled(b.resolve()) == ["U9 pin 1 (IN): walled off by R9"]


def test_a_track_of_the_script_that_walls_a_pad_is_named_as_a_refusal_names_it():
    b = _board(_ring_open_south())
    b.track(Net("RING"), [Location(29.0, 30.85), Location(31.0, 30.85)], layer=F, width=0.2, why="across the way out")
    (found,) = _walled(b.resolve())
    assert found == "U9 pin 1 (IN): walled off by R9, track RING"


def test_a_pour_of_the_script_that_walls_a_pad_is_a_pour():
    b = _board(_ring_open_south())
    b.pour(Net("RING"), [Location(29.0, 30.6), Location(31.0, 30.6), Location(31.0, 31.1), Location(29.0, 31.1)],
           layer=F, why="a pour across the way out")
    (found,) = _walled(b.resolve())
    assert found == "U9 pin 1 (IN): walled off by R9, pour RING"


def test_an_escape_lane_that_walls_a_pad_is_named_by_its_pin():
    """The lanes of an escape are reserved as copper of no owner; a finding says whose lane it is."""
    b = pd_board()
    b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="north row")
    plan = b.resolve()
    lanes = {plan.occupancy.blame_owner(s) for s in plan.occupancy.copper if s.lane}
    assert {str(l) for l in lanes} == {"the escape lane of U1 pin 32", "the escape lane of U1 pin 31", "the escape lane of U1 pin 30"}


# A pad's own lane may run between two other nets' 45 lines laid at the least pitch the clearance allows (an escape's
# lanes are): the way out is the lane carried on, with no room to spare on either side.
def _pitch(net_width, clearance):
    """How far apart (x - y) two parallel 45 lines of `net_width` tracks stand when their edges are `clearance` apart."""
    return (net_width + clearance) * 2 ** 0.5


def _one_pad(ref, net, cx, cy, w, h):
    box = Box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return Footprint(ref, ref.lower(), None, ref, Location(cx, cy), 0.0, Face.FRONT, box, box, box,
                     (pad(ref, ref.lower(), 1, net, cx, cy, w, h),))


def _between_two_45s(pitch):
    fps = [_one_pad("U9", "IN", 30, 30, 0.2, 0.2), _one_pad("X1", "D", 30, 29.2, 0.4, 0.2),
           footprint("T1", 50, 50, inst="t1", nets=("B", "C"))]
    b = _board(fps)
    line = -0.6                                                            # x - y along the pad's own lane
    b.track(Net("IN"), [IN, Location(30.0, 30.6), Location(31.4, 32.0)], layer=F, width=0.2, why="the pad's lane")
    # the neighbours' lines run from a riser each side of the pad to well past the lane, and the north is shut
    for net, x, off in (("B", 29.5, -pitch), ("C", 30.5, pitch)):
        y = x - (line + off)
        b.track(Net(net), [Location(x, 28.0), Location(x, y), Location(x + 2.4, y + 2.4)], layer=F, width=0.2,
                why="the neighbour's line")
    return b


def test_a_lane_between_two_45_lines_at_the_least_pitch_has_its_way_out():
    b = _between_two_45s(_pitch(0.2, 0.2))
    assert _walled(b.resolve()) == []


def test_a_lane_between_two_45_lines_a_hair_too_close_is_walled():
    b = _between_two_45s(_pitch(0.2, 0.2) - 0.01)
    assert _walled(b.resolve())
