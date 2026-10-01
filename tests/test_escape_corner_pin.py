"""A pin drawn as two lands, one in each of two rows (a QFN's corner pin), stands in an escape by the land
that leads out the way the row does; the pins' ways out must have one in common, and an escape whose pins
have none is refused at its declaration, naming the pin and the ways. Pure: synthetic boards."""
import pytest

from placemat.board_geometry import Footprint
from placemat.copper import Track
from placemat.values import CopperLayer, Edge, Location, Net, Part
from tests.escape_fixtures import PAD_L, PAD_W, RING, board_with, qfn
from tests.fixtures import pad

F = CopperLayer.F
CX = CY = 30.0


def corner_qfn():
    """The QFN-32 with pin 24, the east column's northmost, also drawn as a land in the north row, east of pin 25."""
    fp = qfn(nets={24: "EAST", 23: "E23", 22: "E22", 25: "NORTH"})
    north_land = pad(fp.ref, fp.inst, 24, "EAST", CX + 2.25, CY - RING, PAD_W, PAD_L)
    return Footprint(fp.ref, fp.inst, None, fp.ref, fp.location, 0.0, fp.face, fp.body_box, fp.courtyard_box,
                     fp.phys_box, fp.pads + (north_land,))


def _board():
    b = board_with([corner_qfn()])
    b.place(Part("pd"), at=Location(CX, CY))
    return b


def test_a_corner_pin_stands_in_the_row_by_the_land_that_leads_out_that_way():
    b = _board()
    esc = b.escape(Part("pd"), [24, 23, 22], turn=Edge.NORTH, why="the east column's northmost pins")
    for pin, net in ((24, "EAST"), (23, "E23"), (22, "E22")):
        b.track(Net(net), [esc[pin]], layer=F, why="its lane")
    plan = b.resolve()
    first = next(t for t in plan.copper if isinstance(t, Track) and t.net == "EAST")
    east_land = (CX + RING, CY - 1.75)                  # not the middle of the two lands
    assert (first.start.x, first.start.y) == pytest.approx(east_land)
    assert first.start.y == first.end.y and first.end.x > first.start.x       # straight out east
    assert not [f for f in plan.findings if f.kind in ("copper", "escape_lane")], plan.findings


def test_a_corner_pin_alone_leads_out_two_ways_and_is_refused_naming_them():
    b = _board()
    with pytest.raises(ValueError, match="pins 24 lead out east and north alike"):
        b.escape(Part("pd"), [24], why="a corner pin only")


def test_pins_with_no_way_out_in_common_are_refused_naming_the_pins_and_the_ways():
    b = _board()
    with pytest.raises(ValueError, match=r"pin 8 is not on pin 24's row as the part stands "
                                          r"\(pin 24 leads out east or north, pin 8 west\)"):
        b.escape(Part("pd"), [24, 8], why="two rows")


def test_the_north_row_takes_a_corner_pin_by_its_north_land():
    b = _board()
    esc = b.escape(Part("pd"), [25, 24], turn=Edge.EAST, why="the north row's east end")
    b.track(Net("EAST"), [esc[24]], layer=F, why="its lane")
    plan = b.resolve()
    first = next(t for t in plan.copper if isinstance(t, Track) and t.net == "EAST")
    assert (first.start.x, first.start.y) == pytest.approx((CX + 2.25, CY - RING))
    assert first.start.x == first.end.x and first.end.y < first.start.y         # straight out north
