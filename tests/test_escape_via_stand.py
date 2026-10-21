"""A lane's via whose lane finds no legal spot within reach, and that would stand on another net's copper where it is
left, is not drawn, as a via the script gives that would stand on copper is not: the finding names what it would stand
on. A lane via that only falls short of a clearance is drawn, and the copper finding says how far off it is. Pure:
synthetic boards."""
from placemat.copper import Via
from placemat.findings import FindingCause as C
from placemat.values import CopperLayer, Edge, Location, Net, Part
from tests.escape_fixtures import PD_NETS, board_with, qfn, small_part

F = CopperLayer.F


def _plan(cx, cy):
    """The pd QFN's pins 32, 31, 30 escaped west with vias on 31 and 30, past a placed part whose GND pads (3.6 mm square,
    4 mm apart) stand at (cx, cy)."""
    b = board_with([qfn(nets=PD_NETS), small_part("R9", "blk", ("GND", "GND"), cx=cx, cy=cy, span=4.0, size=3.6)])
    b.place(Part("blk"), at=Location(cx, cy))
    b.place(Part("pd"), at=Location(30, 30))
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="a fan")
    for pin, net in ((32, "VOUT"), (31, "SENSE"), (30, "PGOOD")):
        b.track(Net(net), [esc[pin]], layer=F, why="its lane")
    return b.resolve()


def test_a_lane_via_that_would_stand_on_another_nets_pad_is_not_drawn():
    plan = _plan(25.5, 24.5)
    assert not [v for v in plan.copper if isinstance(v, Via) and v.net in ("SENSE", "PGOOD")]
    stand = [f for f in plan.findings if f.cause is C.COPPER_NOT_DRAWN and f.facts.get("variant") == "via_stand"]
    assert sorted(f.facts["net"] for f in stand) == ["PGOOD", "SENSE"]
    assert all(f.facts["met"]["who"][0] == "R9" for f in stand)
    assert not [f for f in plan.findings if f.cause is C.COPPER_MEETS and f.facts.get("word") == "via"]


def test_a_lane_via_short_of_a_clearance_is_drawn_and_said():
    plan = _plan(27, 23.5)
    via, = [v for v in plan.copper if isinstance(v, Via) and v.net == "PGOOD"]
    meets = [f for f in plan.findings if f.cause is C.COPPER_MEETS and f.facts.get("net") == "PGOOD"]
    assert meets and 0.0 < meets[0].facts["hit"]["gap_mm"] < meets[0].facts["hit"]["need_mm"]
