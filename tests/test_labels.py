"""A label: silkscreen text beside a part, pad or cell that marks a
user-facing feature (a connector, a jumper, a switch, an LED). It sits on
one side of the item's reach, aligned along that side, on the item's own
face, and may be knocked out of a filled box for legibility."""
import pytest

from placemat.copper import Text
from placemat.layout import Board
from placemat.values import Near, Cell, Edge, Face, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint, declared_findings


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


def test_a_labels_align_takes_along_or_its_string_spelling():
    """align= is the same vocabulary as a row's: the Along enum, or
    "centre"/"center"/"start"/"end"."""
    from placemat.values import Along
    for align in ("centre", "center", Along.MID):
        b = make_board()
        b.place(Part("j1"), at=Location(20, 20))
        b.label(Part("j1"), "M", side=Edge.NORTH, align=align, gap=0.5)
        (t,) = labels(b.resolve())
        assert t.hjust == "centre", align


def test_a_labels_align_refuses_an_unknown_spelling():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    with pytest.raises(ValueError):
        b.label(Part("j1"), "M", side=Edge.NORTH, align="middle")


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


def test_a_label_gives_way_to_a_fixed_part_declared_on_it():
    """The part stays where it was put; the label, a user's mark, moves next
    to its item."""
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 16.4))              # right where a north label goes
    b.label(Part("j1"), "MOTOR", side=Edge.NORTH, gap=0.5)
    plan = b.resolve()
    (t,) = labels(plan)
    assert plan.box("r1").center == Location(20, 16.4)
    assert t.side is not Edge.NORTH and not t.box.overlaps(plan.box("r1"))
    assert "moved from north" in plan.step("label j1 MOTOR").note and "R1" in plan.step("label j1 MOTOR").note
    assert not [f for f in plan.findings if "label" in str(f)], list(plan.findings)


def test_a_label_on_an_undeclared_part_uses_where_the_board_has_it_but_an_unplaced_ones_is_a_finding():
    b = make_board()
    b.label(Part("j1"), "MOTOR")                            # j1 stays where the board has it
    (t,) = labels(b.resolve())
    assert t.at.y == pytest.approx(10 - 2)
    b = make_board()
    b.place(Part("j1"), at=Near(Location(30, 30), radius=0.2))
    b.place(Part("j2"), at=Location(30, 30), face=Face.FRONT)  # j1 has nowhere to go
    b.label(Part("j1"), "MOTOR")
    plan = b.resolve()                                       # the run goes on, as j1's own refusal does
    assert not labels(plan)
    assert [f for f in plan.findings if f.kind == "label" and "MOTOR" in f and "no place" in f], list(plan.findings)


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
    assert declared_findings(plan) == []
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


def test_a_labels_gap_defaults_to_touching_its_item():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.label(Part("j1"), "MOTOR", side=Edge.NORTH)
    (t,) = labels(b.resolve())
    assert t.at.y == pytest.approx(20 - 2)                       # the reach's top: no gap unless asked


def test_labels_of_several_items_share_one_line_past_the_deepest_of_them():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))                       # 4 tall: its reach ends at 22
    b.place(Part("r1"), at=Location(30, 20))                       # 1 tall: its reach ends at 20.5
    b.label([Part("j1"), Part("r1")], ["MOTOR", "LED"], side=Edge.SOUTH, gap=0.5)
    ts = labels(b.resolve())
    assert [t.text for t in ts] == ["MOTOR", "LED"]
    assert ts[0].at == Location(20.0, 22.5) and ts[1].at == Location(30.0, 22.5)   # one line, each over its own item


def test_a_label_group_needs_one_text_per_item():
    b = make_board()
    with pytest.raises(ValueError):
        b.label([Part("j1"), Part("r1")], ["MOTOR"], side=Edge.SOUTH)


def test_a_knockout_label_is_boxed_as_kicad_draws_it():
    from placemat.copper import Text
    plain = Text("MOTOR", Location(20, 20), Face.FRONT, 1.0, 0.15, vjust="top")
    boxed = Text("MOTOR", Location(20, 20), Face.FRONT, 1.0, 0.15, vjust="top", knockout=True)
    assert boxed.box.height > plain.box.height              # the knockout frame stands round the glyphs
    assert boxed.box.top == plain.box.top                   # anchored on the same edge


def test_pad_labels_may_stand_off_their_part_instead_of_their_pads():
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))                       # body 8 x 4: reach top at 18
    b.label([PadRef(Part("j1"), "A"), PadRef(Part("j1"), "B")], ["A", "B"], side=Edge.NORTH, line=Part("j1"))
    ts = labels(b.resolve())
    pa, pb = b.resolve().occupancy.pad_location("J1", "1"), b.resolve().occupancy.pad_location("J1", "2")
    assert ts[0].at == Location(pa.x, 18.0) and ts[1].at == Location(pb.x, 18.0)   # over their pads, off the part's reach


@pytest.mark.parametrize("face", [Face.FRONT, Face.BACK])
@pytest.mark.parametrize("side", [Edge.NORTH, Edge.SOUTH, Edge.EAST, Edge.WEST])
def test_a_label_keeps_the_silk_clearance_from_its_own_part(side, face):
    """The reach holds the part's silk; a label at no gap touched it, which
    KiCad reports as silk overlapping silk."""
    fps = [footprint("J1", 10, 10, w=8, h=4, inst="j1", nets=("A", "B"), face=face)]
    b = Board(board_geometry(fps, width=60, height=60, silk_clearance=0.2), edge_margin=1.0)
    b.place(Part("j1"), at=Location(20, 20), rotation=90, face=face)
    b.label(Part("j1"), "MOTOR", side=side)
    plan = b.resolve()
    (t,) = labels(plan)
    reach = plan.occupancy.items["J1"].reach
    gap = {Edge.NORTH: reach.top - t.box.bottom, Edge.SOUTH: t.box.top - reach.bottom,
           Edge.EAST: t.box.left - reach.right, Edge.WEST: reach.left - t.box.right}[side]
    assert gap >= 0.2 - 1e-9


def test_a_part_searched_later_keeps_its_silk_the_silk_clearance_from_a_label():
    import dataclasses
    from placemat.settings import Settings
    from placemat.values import Box
    fps = [footprint("J1", 10, 10, w=8, h=4, inst="j1", nets=("A", "B")),
           footprint("R1", 40, 10, w=2, h=1, inst="r1", nets=("A", "C"),
                     silk_boxes=[(39.0, 9.2, 41.0, 9.3)])]            # a silk line 0.2 mm north of its body
    g = board_geometry(fps, width=60, height=60, silk_clearance=0.2)
    b = Board(g, edge_margin=1.0, settings=dataclasses.replace(Settings(), place_envelope="physical"))
    b.place(Part("j1"), at=Location(20, 20))
    b.label(Part("j1"), "GND", side=Edge.SOUTH)
    b.place(Part("r1"), at=Near(Location(20, 24.2), radius=3))       # its silk would lie on the label's lower edge
    plan = b.resolve()
    (t,) = labels(plan)
    silk = Box.union([s.box for s in plan.occupancy.items["R1"].shapes if s.kind == "silk"])
    gap = max(t.box.left - silk.right, silk.left - t.box.right, t.box.top - silk.bottom, silk.top - t.box.bottom)
    assert gap >= 0.2 - 1e-9, (t.box, silk)


@pytest.mark.parametrize("side", [Edge.NORTH, Edge.SOUTH, Edge.EAST, Edge.WEST])
def test_a_label_up_the_page_is_boxed_where_it_reads(side):
    """At rotation 90 the text's length runs up the page and its height
    across it: the box that finds what the label sits on, and reserves it,
    stands off the side asked, centred on the item, as long as the text."""
    b = make_board()
    b.place(Part("j1"), at=Location(20, 20))
    b.label(Part("j1"), "RESET", side=side, gap=0.5, size=0.8, thickness=0.15, rotation=90)
    plan = b.resolve()
    (t,) = labels(plan)
    reach = plan.occupancy.items["J1"].reach
    length, height = 5 * 0.8 * 0.914 + 0.15, 0.8 + 0.15
    assert t.box.width == pytest.approx(height) and t.box.height == pytest.approx(length)
    if side is Edge.NORTH:
        assert t.box.bottom == pytest.approx(reach.top - 0.5) and t.box.center.x == pytest.approx(reach.center.x)
    elif side is Edge.SOUTH:
        assert t.box.top == pytest.approx(reach.bottom + 0.5) and t.box.center.x == pytest.approx(reach.center.x)
    elif side is Edge.EAST:
        assert t.box.left == pytest.approx(reach.right + 0.5) and t.box.center.y == pytest.approx(reach.center.y)
    else:
        assert t.box.right == pytest.approx(reach.left - 0.5) and t.box.center.y == pytest.approx(reach.center.y)


def _coin_board(cx, cy):
    """J1 at (20, 32), and M1: a part that draws neither silk nor fab, its
    courtyard a disc of radius 5, claimed as the part itself."""
    import dataclasses
    import math
    from placemat.settings import Settings
    from placemat.values import Box
    disc = tuple((cx + 5 * math.cos(k * math.pi / 16), cy + 5 * math.sin(k * math.pi / 16)) for k in range(32))
    m1 = dataclasses.replace(footprint("M1", cx, cy, w=10, h=10, inst="m1", nets=("A", "B")),
                             courtyard_poly=disc, courtyard_box=Box.of_points(disc))
    fps = [footprint("J1", 20, 32, w=8, h=4, inst="j1", nets=("A", "B")), m1]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0,
              settings=dataclasses.replace(Settings(), place_envelope="physical"))
    b.place(Part("j1"), at=Location(20, 32))
    b.label(Part("j1"), "MOTOR", side=Edge.NORTH, gap=2.0)       # the text's box: x 17.6 to 22.4, y 26.9 to 28
    return b.resolve()


def test_a_label_in_the_corner_of_a_round_parts_box_does_not_sit_on_it():
    """What a label sits on is judged by the other part's shapes, not the
    box round them: the disc's box covers the label's corner, the disc
    does not."""
    plan = _coin_board(26, 23)
    assert not [f for f in plan.findings if "sits on" in f and "M1" in f], list(plan.findings)


def test_a_label_inside_a_claimed_courtyard_sits_on_its_part():
    plan = _coin_board(25, 24)
    assert [f for f in plan.findings if "sits on" in f and "M1" in f], list(plan.findings)
