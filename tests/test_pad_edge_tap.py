"""A track point on a pad's edge, touching it: PadRef(..., edge=, along=).
For a sense track that must meet its pad at one chosen edge (a shunt's
inner edge) and nowhere else."""
import pytest

from placemat.values import Along, Edge, Part, PadRef


def test_along_without_an_edge_is_refused():
    with pytest.raises(TypeError):
        PadRef(Part("r1"), 1, along=Along.END)


def test_an_edge_is_an_edge_and_along_is_an_along():
    with pytest.raises(TypeError):
        PadRef(Part("r1"), 1, edge="south")
    with pytest.raises(TypeError):
        PadRef(Part("r1"), 1, edge=Edge.SOUTH, along="end")


def test_a_plain_padref_digests_as_before():
    from placemat.reuse import canonical
    text = str(canonical(PadRef(Part("r1"), 1)))
    assert "edge" not in text and "along" not in text


def test_offset_and_local_keep_the_edge():
    p = PadRef(Part("r1"), 1, edge=Edge.SOUTH, along=Along.END)
    for q in (p.offset(0.1, 0.0), p.local(0.0, 0.1)):
        assert q.edge is Edge.SOUTH and q.along is Along.END


import dataclasses

from placemat.copper import Track
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Location, Net, Past
from tests.fixtures import board_geometry, footprint

F = CopperLayer.F
W, OVER = 0.2, 0.005          # the fixture's track width; how far a tap's copper overlaps its pad


def _board(round_pad=False, rotation=0.0):
    """R1 at (20, 20): pad 1 (net A) x 18.1 to 19.1, pad 2 (net B) x 20.9 to
    21.9, both y 19.5 to 20.5. `round_pad`: pad 1 a disc of radius 0.5."""
    r1 = footprint("R1", 20, 20, w=4, h=2, inst="r1", nets=("A", "B"))
    if round_pad:
        disc = circle_polygon(Location(18.6, 20.0), 0.5, 32)
        r1 = dataclasses.replace(r1, pads=(dataclasses.replace(r1.pads[0], outlines=(disc,), box=Box.of_points(disc)),
                                           r1.pads[1]))
    b = Board(board_geometry([r1], width=60, height=60), edge_margin=1.0)
    b.place(Part("r1"), at=Location(20, 20), rotation=rotation)
    return b


def _legs(plan):
    return [op for op in plan.copper if isinstance(op, Track)]


def _pad_box(plan, number):
    return next(s.box for s in plan.occupancy.items["R1"].shapes if s.label == str(number) and s.kind == "pad")


def test_a_tap_lies_against_its_edge_and_meets_the_pad_nowhere_else():
    b = _board()
    b.track(Net("A"), [PadRef(Part("r1"), 1, edge=Edge.EAST), Location(19.1 + W / 2 - OVER, 25)], layer=F, chamfer=0)
    plan = b.resolve()
    first = _legs(plan)[0]
    assert (first.start.x, first.start.y) == pytest.approx((19.1 + W / 2 - OVER, 20.0))
    assert min(x for leg in _legs(plan) for x, _ in leg.polygon) == pytest.approx(19.1 - OVER, abs=1e-6)


def test_a_tap_at_the_end_of_its_edge_is_flush_with_the_pads_side():
    b = _board()
    b.track(Net("A"), [PadRef(Part("r1"), 1, edge=Edge.SOUTH, along=Along.END), Location(19.0, 25)],
            layer=F, chamfer=0)
    plan = b.resolve()
    first = _legs(plan)[0]
    assert (first.start.x, first.start.y) == pytest.approx((19.1 - W / 2, 20.5 + W / 2 - OVER))
    assert max(x for x, _ in first.polygon) == pytest.approx(19.1, abs=1e-6)


def test_the_edge_is_the_board_frames_on_a_turned_part():
    b = _board(rotation=90)
    b.track(Net("A"), [PadRef(Part("r1"), 1, edge=Edge.SOUTH), Location(25, 0)], layer=F, chamfer=0)
    plan = b.resolve()
    box = _pad_box(plan, 1)
    first = _legs(plan)[0]
    assert (first.start.x, first.start.y) == pytest.approx((box.center.x, box.bottom + W / 2 - OVER))


def test_past_across_a_tap_lies_level_with_it():
    b = _board()
    tap = PadRef(Part("r1"), 1, edge=Edge.SOUTH, along=Along.END)
    b.track(Net("A"), [tap, Past([PadRef(Part("r1"), 1)], Edge.EAST, across=tap), Location(19.4, 25)],
            layer=F, chamfer=0)
    first = _legs(b.resolve())[0]
    assert first.start.y == pytest.approx(20.5 + W / 2 - OVER)
    assert first.end.y == pytest.approx(first.start.y) and first.end.x == pytest.approx(19.1 + 0.2 + W / 2)


def test_a_round_pad_is_tapped_at_the_middle_of_an_edge_and_not_at_its_end():
    b = _board(round_pad=True)
    b.track(Net("A"), [PadRef(Part("r1"), 1, edge=Edge.SOUTH), Location(18.6, 25)], layer=F, chamfer=0)
    first = _legs(b.resolve())[0]
    assert first.start.y == pytest.approx(20.5 + W / 2 - OVER)
    b = _board(round_pad=True)
    b.track(Net("A"), [PadRef(Part("r1"), 1, edge=Edge.SOUTH, along=Along.END), Location(18.6, 25)], layer=F)
    with pytest.raises(ValueError, match="R1"):
        b.resolve()


def test_a_tap_anywhere_but_a_track_point_or_pasts_across_is_refused():
    b = _board()
    b.via(Net("A"), PadRef(Part("r1"), 1, edge=Edge.EAST))
    with pytest.raises(ValueError, match="edge="):
        b.resolve()
    b = _board()
    with pytest.raises(TypeError, match="edge="):
        b.track(Net("A"), [PadRef(Part("r1"), 1), Past([PadRef(Part("r1"), 1, edge=Edge.EAST)], Edge.EAST),
                           Location(25, 25)], layer=F)
