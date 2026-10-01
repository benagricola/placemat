"""A label gives way to a part placed firmly beside it: it slides along its
declared side, then tries the item's other sides, always next to its item;
with no clear spot it stays and is a finding. A part never moves for a
label. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.copper import Text
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Along, Beside, Cell, Edge, Face, Location, Part
from tests.fixtures import board_geometry, footprint

SILK = 0.2


def texts(plan):
    return [op for op in plan.copper if isinstance(op, Text)]


def make_board(width_of_text=4.4, label=True, blocker=False, other_face=Face.FRONT, **kw):
    """Cell conn: a labelled connector J1 (x 28..32, y 29..31) beside a taller
    member P, so the cell's envelope reaches above the notch the label stands
    in. Cell other, placed Beside conn's east side, is tall enough to stand
    beside the notch."""
    size = (width_of_text - 0.15) / (5 * 0.914 + 2 / 9)
    fps = [footprint("J1", 30, 30, w=4, h=2, inst="conn.j1", nets=("A", "B"), cell="conn"),
           footprint("P1", 25, 28, w=4, h=6, inst="conn.p1", nets=("C", "D"), cell="conn"),
           footprint("U2", 0, 0, w=3, h=5, inst="other.u2", nets=("E", "F"), cell="other",
                     silk_boxes=((-1.5, -2.5, 1.5, 2.5),)),
           ] + ([footprint("R1", 30, 33, w=14, h=2, inst="r1", nets=("G", "H"))] if blocker else [])
    b = Board(board_geometry(fps, cells=["conn", "other"], width=80, height=80, silk_clearance=SILK),
              edge_margin=1.0, settings=dataclasses.replace(Settings(), place_envelope="physical"), **kw)
    b.place(Cell("conn"), at=Location(27, 28))
    if label:
        b.label(Part("conn.j1"), "USB-C", side=Edge.NORTH, align=Along.START, knockout=True, size=size)
    if blocker:
        b.place(Part("r1"), at=Location(30, 33))
    b.place(Cell("other"), at=Beside(Cell("conn"), Edge.EAST, align=Along.START), face=other_face)
    return b


def silk_gap(plan, t):
    """The least distance from the label's box to the silk of the other cell's part."""
    out = []
    for ref, g in plan.occupancy.items.items():
        for s in g.shapes:
            if ref != "U2":
                continue
            if s.kind == "silk":
                a, c = s.box, t.box
                out.append(max(a.left - c.right, c.left - a.right, a.top - c.bottom, c.top - a.bottom))
    return min(out)


def test_a_label_slides_along_its_side_for_a_part_placed_beside_it():
    b = make_board()
    plan = b.resolve()
    (t,) = texts(plan)
    ref = make_board(label=False).resolve()
    assert plan.box("other") == ref.box("other")                   # the part stays where Beside puts it
    assert not [f for f in plan.findings if "label" in str(f)], list(plan.findings)
    j1, other = plan.occupancy.items["J1"].reach, plan.box("other")
    assert t.side is Edge.NORTH and t.box.bottom < j1.top
    assert silk_gap(plan, t) >= SILK - 1e-6
    assert t.box.left >= j1.left - 0.5 and t.box.right <= j1.right + 0.5      # still over its connector
    assert "moved" in plan.step("label conn.j1 USB-C").note


def test_a_label_with_no_room_on_its_side_moves_to_another_side():
    plan = make_board(width_of_text=5.2).resolve()
    (t,) = texts(plan)
    j1 = plan.occupancy.items["J1"].reach
    assert t.side is Edge.SOUTH and t.box.top > j1.bottom
    assert t.box.top - j1.bottom == pytest.approx(SILK, abs=1e-6)             # its gap off the connector, as declared
    assert not [f for f in plan.findings if "label" in str(f)], list(plan.findings)
    assert "moved" in plan.step("label conn.j1 USB-C").note and "south" in plan.step("label conn.j1 USB-C").note


def test_a_label_with_no_room_anywhere_stays_and_is_a_finding():
    plan = make_board(width_of_text=5.2, blocker=True, keep_going=True).resolve()
    (t,) = texts(plan)
    assert t.side is Edge.NORTH
    said = [str(f) for f in plan.findings if "label conn.j1 USB-C" in str(f) and "no clear spot" in str(f)]
    assert said and "other" in said[0], list(plan.findings)


def test_a_label_on_the_far_side_is_left_alone():
    b = make_board()
    plan = b.resolve()
    far = make_board()
    far._intents.clear()
    far.place(Cell("conn"), at=Location(27, 28))
    far.place(Cell("other"), at=Beside(Cell("conn"), Edge.WEST, align=Along.START))
    p = far.resolve()
    (t,) = texts(p)
    assert t.side is Edge.NORTH and "moved" not in p.step("label conn.j1 USB-C").note


def test_a_label_on_the_other_face_is_left_alone():
    plan = make_board(other_face=Face.BACK).resolve()
    assert "moved" not in plan.step("label conn.j1 USB-C").note


def test_a_replayed_run_ends_with_the_label_where_the_fresh_run_put_it():
    first = make_board().resolve()
    again = make_board().resolve(reuse=first.reuse)
    assert again.reuse["reused"] > 0
    assert texts(again) == texts(first)
    assert again.step("label conn.j1 USB-C").note == first.step("label conn.j1 USB-C").note
    assert again.findings == first.findings
