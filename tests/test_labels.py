"""A label: silkscreen text beside a part, pad or cell that marks a
user-facing feature (a connector, a jumper, a switch, an LED). It sits on
one side of the item's reach, aligned along that side, on the item's own
face, and may be knocked out of a filled box for legibility."""
import pytest

from placemat.copper import Text
from placemat.layout import Board
from placemat.values import Near, Cell, Edge, Face, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def labels(plan):
    return [op for op in plan.copper if isinstance(op, Text)]


def make_board():
    fps = [footprint("J1", 10, 10, w=8, h=4, inst="j1", nets=("A", "B")),
           footprint("J2", 30, 30, w=8, h=4, inst="j2", nets=("C", "D"), face=Face.BACK),
           footprint("R1", 40, 10, w=2, h=1, inst="r1", nets=("A", "C"))]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)


def test_a_label_sits_north_of_the_part_centred_on_its_reach():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.label(Part("j1"), "MOTOR", side=Edge.NORTH, gap=0.5)
    plan = b.resolve()
    (t,) = labels(plan)
    box = plan.box("j1")
    assert t.text == "MOTOR" and t.at == Location(box.center.x, box.top - 0.5)
    assert t.hjust == "centre" and t.vjust == "bottom" and t.rotation == 0
    assert t.face is Face.FRONT and not t.mirrored and not t.knockout
    assert plan.step("label j1 MOTOR").kind == "copper"


def test_a_label_may_align_to_either_end_of_its_side_and_sit_on_any_side():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.label(Part("j1"), "L", side=Edge.SOUTH, align="start", gap=1.0)
    b.label(Part("j1"), "R", side=Edge.EAST, align="end", gap=1.0)
    b.label(Part("j1"), "W", side=Edge.WEST, gap=1.0, rotation=90)
    plan = b.resolve()
    box = plan.box("j1")
    by = {t.text: t for t in labels(plan)}
    assert by["L"].at == Location(box.left, box.bottom + 1.0) and by["L"].hjust == "left" and by["L"].vjust == "top"
    assert by["R"].at == Location(box.right + 1.0, box.bottom) and by["R"].hjust == "left" and by["R"].vjust == "bottom"
    assert by["W"].at == Location(box.left - 1.0, box.center.y) and by["W"].rotation == 90


def test_a_label_on_a_back_face_part_goes_on_the_back_silk_mirrored():
    b = make_board()
    b.place(Part("j2"), at=Location(30, 30), face=Face.BACK)
    b.label(Part("j2"), "USB", knockout=True)
    (t,) = labels(b.resolve())
    assert t.face is Face.BACK and t.mirrored and t.knockout


def test_a_label_may_mark_one_pad():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.label(PadRef(Part("j1"), "A"), "1", side=Edge.SOUTH, gap=0.3, size=0.6)
    plan = b.resolve()
    (t,) = labels(plan)
    pad = plan.occupancy.pad_location("J1", "1")
    assert t.at.x == pytest.approx(pad.x) and t.at.y == pytest.approx(pad.y + 0.5 + 0.3) and t.size == 0.6


def test_a_fixed_part_on_a_reserved_label_is_a_collision_that_stops_the_run():
    from placemat.layout import PlacementCollision
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 16.4))              # right where a north label goes
    b.label(Part("j1"), "MOTOR", side=Edge.NORTH, gap=0.5)
    with pytest.raises(PlacementCollision) as e:
        b.resolve()
    assert "label j1 MOTOR" in str(e.value) and "r1" in str(e.value)


def test_a_label_on_an_undeclared_part_uses_where_the_board_has_it_but_an_unplaced_one_is_an_error():
    b = make_board()
    b.label(Part("j1"), "MOTOR")                            # j1 stays where the board has it
    (t,) = labels(b.resolve())
    assert t.at.y == pytest.approx(10 - 2 - 0.5)
    b = make_board()
    b.place(Part("j1"), at=Near(Location(30, 30), radius=0.2))
    b.place(Part("j2"), at=Location(30, 30), face=Face.FRONT)  # j1 has nowhere to go
    b.label(Part("j1"), "MOTOR")
    with pytest.raises(ValueError):
        b.resolve()


def test_a_label_reserves_its_space_so_nothing_is_placed_over_it():
    """A label marks what a user must read; a part landing on it is worse
    than a part landing anywhere else. The label is reserved as soon as
    its item is placed, so everything placed later goes round it."""
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.label(Part("j1"), "MOTOR", side=Edge.NORTH, gap=0.5, size=1.2)
    b.place(Part("r1"), at=Near(Location(20, 16.4), radius=6.0))      # the hint is right on the label
    plan = b.resolve()
    (t,) = labels(plan)
    assert plan.findings == []
    assert not plan.box("r1").overlaps(t.box)
    assert any("label j1 MOTOR" in r.why for r in plan.occupancy.reservations)


def test_a_label_may_decline_to_reserve_and_then_only_reports_what_lands_on_it():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.label(Part("j1"), "MOTOR", side=Edge.NORTH, gap=0.5, size=1.2, reserve=False)
    b.place(Part("r1"), at=Near(Location(20, 16.4), radius=0.1))
    plan = b.resolve()
    (t,) = labels(plan)
    assert plan.box("r1").overlaps(t.box)
    assert any("label j1 MOTOR" in f and "R1" in f for f in plan.findings)
