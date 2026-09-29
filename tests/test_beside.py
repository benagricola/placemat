"""Beside(item, side, align=, gap=): a part or cell stands off another
item's drawn envelope, a gap off it, aligned across the side. `item` may
be a part, a cell or a keepout. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.cutouts import Path
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Along, Beside, Cell, Edge, Freedom, Location, PadRef, Part
from tests.fixtures import board_geometry, footprint


def make_board(**kw):
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 40, 40, w=3, h=1.3, inst="r1", nets=("A", "GND"))]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, **kw)


def _pad_offset_footprint(ref, cx, cy, nets, dy=(0.0, 0.0)):
    """A two-pad part like fixtures.footprint(), but each pad's y is offset
    from the body centre, so a pad-anchored alignment reads differently from
    a body-centred one."""
    from placemat.board_geometry import Footprint
    from placemat.values import Box, Face
    from tests.fixtures import pad as _pad
    body = Box(cx - 2.0, cy - 1.0, cx + 2.0, cy + 1.0)
    pads = (_pad(ref, ref.lower(), 1, nets[0], cx - 1.4, cy + dy[0]),
            _pad(ref, ref.lower(), 2, nets[1], cx + 1.4, cy + dy[1]))
    return Footprint(ref, ref.lower(), None, ref, Location(cx, cy), 0.0, Face.FRONT,
                     body, body.inflate(0.1), body, pads)


def test_default_gap_touches_envelopes_mid_aligned():
    """No gap=: courtyards touching (0.1 mm excess a side, as a row's
    default gap does). No align=: MID of the item's side."""
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST))
    plan = b.resolve()
    u1, r1 = plan.box("u1"), plan.box("r1")
    assert r1.left - u1.right == pytest.approx(0.2)
    assert r1.center.y == pytest.approx(u1.center.y)


def test_west_side():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.WEST))
    plan = b.resolve()
    u1, r1 = plan.box("u1"), plan.box("r1")
    assert u1.left - r1.right == pytest.approx(0.2)


def test_north_and_south_sides():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.SOUTH))
    plan = b.resolve()
    u1, r1 = plan.box("u1"), plan.box("r1")
    assert r1.top - u1.bottom == pytest.approx(0.2)
    assert r1.center.x == pytest.approx(u1.center.x)


def test_explicit_gap_replaces_the_envelopes_own():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST, gap=1.0))
    plan = b.resolve()
    u1, r1 = plan.box("u1"), plan.box("r1")
    assert r1.left - u1.right == pytest.approx(1.0 + 0.2)   # the gap plus both courtyard excesses


def test_align_start_sits_at_the_items_near_end():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST, align=Along.START))
    plan = b.resolve()
    u1, r1 = plan.box("u1"), plan.box("r1")
    assert r1.center.y == pytest.approx(u1.top - 0.1)   # u1's envelope's near (north) edge


def test_align_end_sits_at_the_items_far_end():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST, align=Along.END))
    plan = b.resolve()
    u1, r1 = plan.box("u1"), plan.box("r1")
    assert r1.center.y == pytest.approx(u1.bottom + 0.1)


def test_align_pad_lines_up_the_own_pad_on_the_same_net():
    u1 = _pad_offset_footprint("U1", 20, 20, ("A", "B"), dy=(0.0, 0.5))    # pad B at y 20.5
    r1 = _pad_offset_footprint("R1", 40, 40, ("C", "B"), dy=(0.0, -0.8))  # own pad B, local offset -0.8
    b = Board(board_geometry([u1, r1], width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST, align=PadRef(Part("u1"), "B")))
    plan = b.resolve()
    u1_b = plan.occupancy.pad_location("U1", "2")
    r1_b = plan.occupancy.pad_location("R1", "2")
    assert r1_b.y == pytest.approx(u1_b.y)
    assert plan.box("r1").center.y == pytest.approx(21.3)   # not the same as u1's or r1's body centre


def test_align_pads_lines_up_named_pads_of_different_nets():
    u1 = _pad_offset_footprint("U1", 20, 20, ("A", "B"), dy=(0.0, 0.5))
    r1 = _pad_offset_footprint("R1", 40, 40, ("C", "D"), dy=(0.0, -0.8))   # no net in common
    b = Board(board_geometry([u1, r1], width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST, align=(2, PadRef(Part("u1"), "A"))))
    plan = b.resolve()
    u1_a = plan.occupancy.pad_location("U1", "1")
    r1_d = plan.occupancy.pad_location("R1", "2")
    assert r1_d.y == pytest.approx(u1_a.y)


def test_the_item_may_be_a_cell():
    fps = [footprint("U1", 0, 0, w=4, h=2, inst="pd.u1", nets=("A", "B"), cell="pd"),
           footprint("R1", 40, 40, w=3, h=1.3, inst="r1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, cells=["pd"], width=60, height=60), edge_margin=1.0)
    b.place(Cell("pd"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Cell("pd"), Edge.EAST))
    plan = b.resolve()
    pd, r1 = plan.box("pd"), plan.box("r1")
    assert r1.left - pd.right == pytest.approx(0.2)
    assert r1.center.y == pytest.approx(pd.center.y)


def test_a_cell_may_be_placed_beside_a_part():
    fps = [footprint("U1", 0, 0, w=4, h=2, inst="pd.u1", nets=("A", "B"), cell="pd"),
           footprint("R1", 20, 20, w=3, h=1.3, inst="r1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, cells=["pd"], width=60, height=60), edge_margin=1.0)
    b.place(Part("r1"), at=Location(20, 20))
    b.place(Cell("pd"), at=Beside(Part("r1"), Edge.EAST))
    plan = b.resolve()
    r1, pd = plan.box("r1"), plan.box("pd")
    assert pd.left - r1.right == pytest.approx(0.2)
    assert pd.center.y == pytest.approx(r1.center.y)


def test_the_item_may_be_a_keepout():
    b = make_board()
    k = b.keepout(Path([(-3.0, -2.0), (3.0, -2.0), (3.0, 2.0), (-3.0, 2.0)]), "clr",
                  at=Location(20.0, 20.0), why="a clearance")
    b.place(Part("r1"), at=Beside(k, Edge.EAST))
    plan = b.resolve()
    r1 = plan.box("r1")
    assert r1.left == pytest.approx(23.1)     # the keepout's east edge (23), plus r1's own courtyard excess
    assert r1.center.y == pytest.approx(20.0)  # MID of the keepout's east side (18..22)


def test_a_keepout_has_no_pads_to_align_on():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    k = b.keepout(Path([(-3.0, -2.0), (3.0, -2.0), (3.0, 2.0), (-3.0, 2.0)]), "clr",
                  at=Location(20.0, 20.0), why="a clearance")
    with pytest.raises(TypeError, match="no pads"):
        b.place(Part("r1"), at=Beside(k, Edge.EAST, align=PadRef(Part("u1"), "A")))


def test_physical_envelope_widens_the_gap_to_the_clearance_rule():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"), excess=0.0),
           footprint("R1", 40, 40, w=3, h=1.3, inst="r1", nets=("A", "GND"), excess=0.0)]
    settings = dataclasses.replace(Settings(), place_envelope="physical")
    b = Board(board_geometry(fps, width=60, height=60, silk_clearance=0.05),
             edge_margin=1.0, settings=settings, component_spacing=0.3)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST))
    plan = b.resolve()
    u1, r1 = plan.box("u1"), plan.box("r1")
    assert r1.left - u1.right == pytest.approx(0.3)   # component_spacing is the widest of the rules here


def test_beside_waits_for_an_item_declared_later():
    b = make_board()
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST))
    b.place(Part("u1"), at=Location(20, 20))
    plan = b.resolve()
    u1, r1 = plan.box("u1"), plan.box("r1")
    assert r1.left - u1.right == pytest.approx(0.2)
    assert plan.steps[0].item == "u1"       # placed first, though declared second


def test_beside_is_a_firm_placement_like_pin():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST))
    plan = b.resolve()
    assert plan.step("r1").freedom is Freedom.FIXED


def test_beside_keeps_the_rotation_the_script_gave():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST), rotation=90)
    plan = b.resolve()
    assert plan.placement("r1").rotation == 90


def test_beside_refuses_a_side_that_is_not_an_edge():
    with pytest.raises(TypeError, match="Edge"):
        Beside(Part("u1"), "east")


def test_beside_refuses_an_item_that_is_not_a_part_cell_or_keepout():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    with pytest.raises(TypeError, match="Part, a Cell or a keepout"):
        b.place(Part("r1"), at=Beside("u1", Edge.EAST))


def test_beside_refuses_when_the_new_part_carries_no_pad_on_the_aligned_net():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    with pytest.raises(ValueError, match="carries no pad"):
        b.place(Part("r1"), at=Beside(Part("u1"), Edge.EAST, align=PadRef(Part("u1"), "B")))


def test_beside_align_pad_refuses_for_a_cell():
    fps = [footprint("U1", 0, 0, w=4, h=2, inst="pd.u1", nets=("A", "B"), cell="pd"),
           footprint("R1", 40, 40, w=3, h=1.3, inst="r1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, cells=["pd"], width=60, height=60), edge_margin=1.0)
    b.place(Part("r1"), at=Location(20, 20))
    with pytest.raises(TypeError, match="a cell has none"):
        b.place(Cell("pd"), at=Beside(Part("r1"), Edge.EAST, align=PadRef(Part("r1"), "A")))
