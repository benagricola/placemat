"""A lane's via whose lane finds no legal spot for it within reach is not drawn, whether it would stand on another net's
copper or only short of a clearance from it: the finding names the lane and what stands in its way, and a track that ends
on the via is not drawn either. A lane via whose spot is legal is not drawn either where its own lane would run through another net's copper to it, as
that lane is not drawn: the via would join nothing. Pure: synthetic boards."""
from placemat.copper import Via
from placemat.findings import FindingCause as C
from placemat.values import CopperLayer, Edge, Location, Net, Part
from tests.escape_fixtures import Box, Face, Footprint, PD_NETS, board_with, pad, qfn, small_part

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


def _lane_vias(plan):
    return [f for f in plan.findings if f.cause is C.COPPER_NOT_DRAWN and f.facts.get("variant") == "lane_via"]


def test_a_lane_via_that_would_stand_on_another_nets_pad_is_not_drawn():
    plan = _plan(25.5, 24.5)
    assert not [v for v in plan.copper if isinstance(v, Via) and v.net in ("SENSE", "PGOOD")]
    got = _lane_vias(plan)
    assert sorted((f.facts["net"], f.facts["pin"]) for f in got) == [("PGOOD", "30"), ("SENSE", "31")]
    assert all("no legal spot" in str(f) and "GND" in str(f) for f in got)
    assert not [f for f in plan.findings if f.cause is C.COPPER_MEETS and f.facts.get("word") == "via"]


def test_a_lane_via_short_of_a_clearance_is_not_drawn_and_its_track_neither():
    plan = _plan(27, 23.5)
    assert not [v for v in plan.copper if isinstance(v, Via) and v.net == "PGOOD"]
    assert [f.facts["pin"] for f in _lane_vias(plan)] == ["30"]
    lost = [f for f in plan.findings if f.cause is C.COPPER_NOT_DRAWN and f.facts.get("variant") == "via_lost"]
    assert [f.facts["track"] for f in lost] == ["PGOOD"]
    assert [v.net for v in plan.copper if isinstance(v, Via)] == ["SENSE"]


def test_a_lane_via_past_copper_its_lane_would_run_through_is_not_drawn():
    """A GND strip 0.3 mm wide across the lanes from y 26.0 to 26.9 at x 27.8: SENSE's via finds a legal spot past it,
    and its lane runs through it."""
    strip = (pad("R9", "blk", 1, "GND", 27.8, 26.45, 0.3, 0.9),)
    body = Box(27.6, 25.9, 28.0, 27.0)
    blk = Footprint("R9", "blk", None, "R9", Location(27.8, 26.45), 0.0, Face.FRONT, body, body.inflate(0.05), body, strip)
    b = board_with([qfn(nets=PD_NETS), blk])
    b.place(Part("blk"), at=Location(27.8, 26.45))
    b.place(Part("pd"), at=Location(30, 30))
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="a fan")
    for pin, net in ((32, "VOUT"), (31, "SENSE"), (30, "PGOOD")):
        b.track(Net(net), [esc[pin]], layer=F, why="its lane")
    plan = b.resolve()
    assert [v.net for v in plan.copper if isinstance(v, Via)] == ["PGOOD"]
    got, = _lane_vias(plan)
    assert (got.facts["pin"], got.facts["met"]["who"][0]) == ("31", "R9")
    assert "its lane would run through R9 pad 1 (GND)" in str(got)
