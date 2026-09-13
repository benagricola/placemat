"""Positions said in terms of other things: a part at the midpoint of two
pads, a row centred on a pad pair or butted before or after another row,
a row that ends at a pad. No number a pad already knows is typed."""
import pytest

from placemat.layout import Board
from placemat.values import Edge, Location, Mid, Part, PadRef, X, Y
from tests.fixtures import board_geometry, footprint


def make_board():
    fps = [footprint("J1", 10, 5, w=12, h=4, inst="j1", nets=("A", "B")),        # pads at x 4.6 and 15.4 when at 10
           footprint("R1", 30, 30, w=3, h=1.3, inst="r1", nets=("A", "M")),
           footprint("R2", 40, 30, w=3, h=1.3, inst="r2", nets=("M", "B")),
           footprint("H1", 50, 30, w=4, h=2, inst="h1", nets=("B", "A")),
           footprint("C1", 20, 40, w=3, h=1.3, inst="c1", nets=("M", "GND"))]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=2.0)


def test_a_part_may_be_placed_at_the_midpoint_of_two_pads():
    b = make_board()
    b.place(Part("j1"), edge=Edge.NORTH, along=20.0, rotation=0, clearance=2.0)
    b.place(Part("c1"), center=(X(Mid(PadRef(Part("j1"), "A"), PadRef(Part("j1"), "B"))), Y(PadRef(Part("j1"), "A"), 6.0)),
            rotation=90)
    plan = b.resolve()
    pa, pb = plan.occupancy.pad_location("J1", "1"), plan.occupancy.pad_location("J1", "2")
    assert plan.box("c1").center.x == pytest.approx((pa.x + pb.x) / 2)
    assert plan.box("c1").center.y == pytest.approx(pa.y + 6.0)


def test_a_row_may_be_centred_on_a_reference_and_another_butted_before_it():
    b = make_board()
    b.place(Part("j1"), edge=Edge.NORTH, along=30.0, rotation=0, clearance=2.0)
    pa, pb = PadRef(Part("j1"), "A"), PadRef(Part("j1"), "B")
    pair = b.row([Part("r1"), Part("r2")], Edge.NORTH, gap=1.0, clearance=10.0, rotation=0, centre=X(Mid(pa, pb)))
    b.row([Part("h1")], Edge.NORTH, gap=1.0, clearance=10.0, rotation=0, before=pair)
    plan = b.resolve()
    ja, jb = plan.occupancy.pad_location("J1", "1"), plan.occupancy.pad_location("J1", "2")
    r1, r2, h1 = plan.box("r1"), plan.box("r2"), plan.box("h1")
    assert (r1.right + r2.left) / 2 == pytest.approx((ja.x + jb.x) / 2)      # the gap between them is under the midpoint
    assert h1.right == pytest.approx(r1.left - 1.0)                            # butted before, one gap away


def test_a_row_may_end_at_a_reference():
    b = make_board()
    b.place(Part("j1"), edge=Edge.NORTH, along=40.0, rotation=0, clearance=2.0)
    b.row([Part("r1"), Part("r2")], Edge.NORTH, gap=1.0, clearance=10.0, rotation=0,
          end=X(PadRef(Part("j1"), "A"), -2.0))
    plan = b.resolve()
    ja = plan.occupancy.pad_location("J1", "1")
    assert plan.box("r2").right == pytest.approx(ja.x - 2.0)


def test_two_firm_placements_that_collide_stop_the_resolve_before_anything_is_searched():
    """A FIXED or EDGE item that lands on another is a script error: the
    resolve stops there with the collisions, instead of spending minutes
    placing the rest onto a broken skeleton. `keep_going=True` records
    them as findings and carries on, the old behaviour."""
    import pytest
    from placemat.layout import PlacementCollision
    fps = [footprint("U1", 10, 10, w=4, h=2), footprint("U2", 30, 10, w=4, h=2), footprint("R1", 40, 40, w=2, h=1)]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("u2"), at=Location(21, 20))                  # on top of u1
    b.place(Part("r1"))
    with pytest.raises(PlacementCollision) as e:
        b.resolve()
    assert "u2" in str(e.value) and "U1" in str(e.value)
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("u2"), at=Location(21, 20))
    b.place(Part("r1"))
    plan = b.resolve()
    assert any("u2 (fixed)" in f for f in plan.findings) and plan.placement("r1") is not None


def test_a_seeded_part_wired_to_a_pad_numbered_with_a_prime_still_seeds():
    """Some footprints number a mechanically doubled leg "1'": a pad number
    that is not all digits must not be read as a net name."""
    from placemat.board_geometry import Footprint
    from placemat.values import Box, Face
    from tests.fixtures import pad
    pads = (pad("SW2", "sw2", "1", "A", 9.4, 10), pad("SW2", "sw2", "1'", "A", 10.6, 10), pad("SW2", "sw2", "2", "B", 12, 10))
    body = Box(8, 9, 13, 11)
    sw = Footprint("SW2", "sw2", None, "SW2", Location(10.5, 10), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)
    r = footprint("R1", 30, 30, nets=("A", "C"))
    b = Board(board_geometry([sw, r], width=60, height=60), edge_margin=1.0)
    b.place(Part("sw2"), at=Location(20, 20))
    b.place(Part("r1"))
    plan = b.resolve()
    assert "seeded on A" in plan.step("r1").note


def test_an_unplaced_item_pulls_nothing_and_blocks_nothing():
    """A part that found no legal spot is not committed at its hint: it is
    left off the board, so nothing later seeds toward it or collides with it."""
    fps = [footprint("U1", 10, 10, w=4, h=2, nets=("A", "B")), footprint("U9", 30, 30, w=30, h=30, nets=("B", "C")),
           footprint("R1", 50, 50, nets=("B", "D"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=1.0)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("u9"))                                      # 30 x 30 on a 40 board with u1 in the corner: nowhere fits
    b.place(Part("r1"))                                      # wired to u1 and u9: seeds toward u1 only
    plan = b.resolve()
    assert "UNPLACED" in plan.step("u9").note and plan.placement("u9") is None
    assert "seeded on B" in plan.step("r1").note and plan.box("r1").center.distance(Location(10, 10)) < 8
