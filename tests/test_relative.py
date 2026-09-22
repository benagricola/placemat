"""Positions said in terms of other things: a part at the midpoint of two
pads, a row centred on a pad pair or butted before or after another row,
a row that ends at a pad. No number a pad already knows is typed."""
import pytest

from placemat.layout import Board
from placemat.values import Freedom, OnEdge, Cell, Centre, Edge, Location, Mid, Part, PadRef, Priority, X, Y
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
    b.place(Part("j1"), at=OnEdge(Edge.NORTH, along=20.0), rotation=0)
    b.place(Part("c1"), at=Centre(X(Mid(PadRef(Part("j1"), "A"), PadRef(Part("j1"), "B"))), Y(PadRef(Part("j1"), "A"), 6.0)),
            rotation=90)
    plan = b.resolve()
    pa, pb = plan.occupancy.pad_location("J1", "1"), plan.occupancy.pad_location("J1", "2")
    assert plan.box("c1").center.x == pytest.approx((pa.x + pb.x) / 2)
    assert plan.box("c1").center.y == pytest.approx(pa.y + 6.0)


def test_a_row_may_be_centred_on_a_reference_and_another_butted_before_it():
    b = make_board()
    front = b.row([Part("j1")], Edge.NORTH, gap=1.0, start=26.0, rotation=0)
    pa, pb = PadRef(Part("j1"), "A"), PadRef(Part("j1"), "B")
    pair = b.row([Part("r1"), Part("r2")], Edge.NORTH, gap=1.0, rotation=0, behind=front, centre=X(Mid(pa, pb)))
    b.row([Part("h1")], Edge.NORTH, gap=1.0, rotation=0, before=pair)
    plan = b.resolve()
    ja, jb = plan.occupancy.pad_location("J1", "1"), plan.occupancy.pad_location("J1", "2")
    r1, r2, h1 = plan.box("r1"), plan.box("r2"), plan.box("h1")
    assert (r1.right + r2.left) / 2 == pytest.approx((ja.x + jb.x) / 2)      # the gap between them is under the midpoint
    assert h1.right == pytest.approx(r1.left - 1.2)                            # butted before, one gap away, claims touching the gap   # a row spaces by what parts claim: the courtyard excess (0.1 a side in these fixtures) is in every gap


def test_a_row_may_end_at_a_reference():
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH, along=40.0), rotation=0)
    b.row([Part("r1"), Part("r2")], Edge.NORTH, gap=1.0, rotation=0,
          end=X(PadRef(Part("j1"), "A"), -2.0))
    plan = b.resolve()
    ja = plan.occupancy.pad_location("J1", "1")
    assert plan.box("r2").right == pytest.approx(ja.x - 2.1)   # a row spaces by what parts claim: the courtyard excess (0.1 a side in these fixtures) is in every gap


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
    b.place(Part("u9"), priority=Priority.DEFAULT)           # 30 x 30 on a 40 board with u1 in the corner: nowhere fits (not critical, by the script)
    b.place(Part("r1"))                                      # wired to u1 and u9: seeds toward u1 only
    plan = b.resolve()
    assert "UNPLACED" in plan.step("u9").note and plan.placement("u9") is None
    assert "seeded on B" in plan.step("r1").note and plan.box("r1").center.distance(Location(10, 10)) < 8


def test_a_part_or_cell_may_be_a_reference_meaning_its_body_centre():
    """Aligning two parts on their centres, or standing one a distance
    from another, needs no pad: X(Part) and Y(Part) are the placed
    body's centre, so a second switch sits exactly beside the first."""
    fps = [footprint("SW1", 5, 5, w=5, h=3, inst="sw1", nets=("A", "B")),
           footprint("SW2", 30, 30, w=5, h=3, inst="sw2", nets=("C", "D")),
           footprint("U1", 40, 40, w=6, h=2, cell="pd", inst="pd.u", nets=("E", "F"))]
    b = Board(board_geometry(fps, cells=["pd"], width=60, height=60), edge_margin=1.0)
    b.place(Part("sw1"), at=Location(20, 20))
    b.place(Part("sw2"), at=Centre(X(Part("sw1"), 8.6), Y(Part("sw1"))))
    b.place(Cell("pd"), at=Centre(X(Part("sw2")), Y(Part("sw2"), 6.0)))
    plan = b.resolve()
    sw1, sw2, pd = plan.box("sw1"), plan.box("sw2"), plan.box("pd")
    assert sw2.center.y == pytest.approx(sw1.center.y) and sw2.center.x == pytest.approx(sw1.center.x + 8.6)
    assert pd.center.x == pytest.approx(sw2.center.x) and pd.center.y == pytest.approx(sw2.center.y + 6.0)
    assert plan.steps[0].item == "sw1" and [s.item for s in plan.steps[:3]] == ["sw1", "sw2", "pd"]     # each waits for its referent


def test_a_part_may_be_placed_by_where_one_of_its_pads_lands():
    from placemat.values import Pin
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH, along=20.0), rotation=0)
    b.place(Part("r1"), at=Pin("A", X(PadRef(Part("j1"), "A")), Y(PadRef(Part("j1"), "A"), 6.0)), rotation=90)
    plan = b.resolve()
    ja = plan.occupancy.pad_location("J1", "1")
    ra = plan.occupancy.pad_location("R1", "1")
    assert (ra.x, ra.y) == pytest.approx((ja.x, ja.y + 6.0))          # R1's A pad sits on the point, at that rotation
    assert plan.step("r1").freedom is Freedom.FIXED


def test_a_location_may_be_said_in_references_too():
    b = make_board()
    b.place(Part("j1"), at=OnEdge(Edge.NORTH, along=20.0), rotation=0)
    b.place(Part("r1"), at=Location(X(PadRef(Part("j1"), "A")), Y(PadRef(Part("j1"), "A"), 6.0)), rotation=0)
    plan = b.resolve()
    ja = plan.occupancy.pad_location("J1", "1")
    assert plan.placement("r1").location == Location(ja.x, ja.y + 6.0)    # the origin lands on the referenced point


def four_pad_part():
    """A part with two pads on one net, as a module with several supply pins
    has: pads 1 and 3 are V3V3, pads 2 and 4 are GND."""
    from placemat.board_geometry import Box, Footprint
    from placemat.values import Face
    from tests.fixtures import pad
    body = Box(20.0, 20.0, 28.0, 26.0)
    pads = (pad("U9", "u9", 1, "V3V3", 21.0, 21.0), pad("U9", "u9", 2, "GND", 27.0, 21.0),
            pad("U9", "u9", 3, "V3V3", 21.0, 25.0), pad("U9", "u9", 4, "GND", 27.0, 25.0))
    return Footprint("U9", "u9", None, "U9", Location(24.0, 23.0), 0.0, Face.FRONT,
                     body, body.inflate(0.1), body, pads)


def test_a_net_names_the_same_pad_wherever_it_is_used():
    """A net key on a part carrying several pads of that net picks the first,
    and every path picks the SAME one: the pad a script measures an offset
    off is the pad a Pin puts on the point, or the offset is measured off one
    pad and applied through another."""
    from placemat.values import Pin
    fps = [four_pad_part(), footprint("C9", 5, 5, w=2, h=1.2, inst="c9", nets=("V3V3", "GND"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    first = b.part("u9").pad("V3V3")
    assert first.number == "1"                                        # the first of the two, in pad order
    assert b._pad_ref(PadRef(Part("u9"), "V3V3"))[1] == first.number   # a reference resolves to it too
    b.place(Part("u9"), at=Pin("V3V3", 30.0, 40.0), rotation=0)
    plan = b.resolve()
    assert plan.occupancy.pad_location("U9", "1") == Location(30.0, 40.0)   # that pad, exactly on the point
    assert "V3V3 is 2 pads on U9" in plan.step("u9").note                   # and it says which it took


def test_a_net_that_names_one_pad_says_nothing_extra():
    from placemat.values import Pin
    b = make_board()
    b.place(Part("j1"), at=Pin("A", 20.0, 20.0), rotation=0)
    assert b.resolve().step("j1").note == ""
