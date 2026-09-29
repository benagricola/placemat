"""A copper clearance finding for a declared track names the segment by its
ends and layer; when that segment is a chamfer's 45 cut, the finding says
so and points at reducing `chamfer=`. Pure: synthetic boards."""
from placemat.board_geometry import Footprint
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Face, Location, Net, Part, PadRef
from tests.fixtures import board_geometry, footprint, pad


def _small_part(ref, cx, cy, net, size=0.2):
    """A single small pad, so it can sit against one segment of a chamfered
    corner without also reaching the straight legs either side."""
    p = pad(ref, ref.lower(), "1", net, cx, cy, size, size)
    body = Box(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)
    return Footprint(ref, ref.lower(), None, ref, Location(cx, cy), 0.0, Face.FRONT,
                     body, body.inflate(0.1), body, (p,))


def test_the_finding_names_a_plain_segment_by_its_ends_and_layer():
    u1 = footprint("U1", 10, 10, nets=("A", "A"))
    r1 = footprint("R1", 20.9, 10, nets=("B", "B"))          # its pad 1 at (19.5, 10)
    g = board_geometry([u1, r1], width=40, height=40, clearance=0.2)
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"), at=Location(20.9, 10))
    b.track(Net("A"), [PadRef(Part("u1"), 1), Location(19.0, 10.0)], layer=CopperLayer.F, width=0.3, chamfer=0)
    plan = b.resolve()
    hits = [str(f) for f in plan.findings if f.kind == "copper"]
    assert hits and any("track A (8.60, 10.00)-(19.00, 10.00)" in f and "on F.Cu" in f for f in hits)
    assert not any("chamfer" in f for f in hits)


def test_a_conflict_on_the_chamfers_own_cut_says_so():
    """The track turns a right angle at (20, 10); its default chamfer cuts a
    45 from (19, 10) to (20, 11). A small foreign pad at that cut's midpoint
    conflicts with the cut, not with the straight legs either side of it."""
    u1 = footprint("U1", 10, 10, nets=("A", "A"))
    near = _small_part("R1", 19.5, 10.5, "B")
    g = board_geometry([u1, near], width=40, height=40, clearance=0.2)
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Part("u1"), at=Location(10, 10))
    b.track(Net("A"), [PadRef(Part("u1"), 1), (20.0, 10.0), (20.0, 20.0)], layer=CopperLayer.F, width=0.3)
    plan = b.resolve()
    hits = [str(f) for f in plan.findings if f.kind == "copper" and " is " in f and "mm from" in f]
    chamfer_hits = [f for f in hits if "chamfer" in f]
    assert chamfer_hits, hits
    assert any("track A (19.00, 10.00)-(20.00, 11.00)" in f and "on F.Cu" in f for f in chamfer_hits)
    assert all("the 45 of its chamfer at (" in f and "a smaller chamfer= there keeps clear" in f
              for f in chamfer_hits)
    straight_hits = [f for f in hits if f not in chamfer_hits]
    assert not any("chamfer" in f for f in straight_hits)


def test_the_straight_leg_between_two_chamfers_is_not_called_one():
    """(20, 10) and (20, 20) are both chamfered corners on this dogleg; the
    long straight leg between their cuts has a new point at each end (the
    chamfer at either corner), but it is not itself a 45."""
    u1 = footprint("U1", 10, 10, nets=("A", "A"))
    near = _small_part("R1", 20.4, 15.0, "B")
    g = board_geometry([u1, near], width=40, height=40, clearance=0.2)
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Part("u1"), at=Location(10, 10))
    b.track(Net("A"), [PadRef(Part("u1"), 1), (20.0, 10.0), (20.0, 20.0), (30.0, 20.0)],
           layer=CopperLayer.F, width=0.3)
    plan = b.resolve()
    hits = [str(f) for f in plan.findings if f.kind == "copper" and " is " in f and "mm from" in f]
    assert hits
    assert not any("chamfer" in f for f in hits)
