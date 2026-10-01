"""A firm placement whose reference is a searched item rides it: at each
candidate the reference is tried at, the rider is placed where its relation
gives and must be legal there, and the two commit together. Pure: synthetic
boards."""
import dataclasses

import pytest

from placemat.layout import Board, CriticalUnplaced
from placemat.settings import Settings
from placemat.values import Beside, Cell, CellPadRef, Edge, Location, OnEdge, PadRef, Pin, Part, Turned, X, Y
from tests.fixtures import board_geometry, footprint


def _fps(extra=()):
    return [footprint("J1", 5, 20, w=2, h=2, inst="j1", nets=("VIN", "GND")),
            footprint("U1", 30, 20, w=8, h=3, inst="u1", nets=("VIN", "OUT")),
            footprint("C1", 50, 50, w=2, h=1, inst="c1", nets=("VIN", "GND")),
            footprint("C2", 52, 52, w=2, h=1, inst="c2", nets=("GND", "OUT"))] + list(extra)


def _board(extra=(), width=60.0, height=60.0, **kw):
    b = Board(board_geometry(_fps(extra), width=width, height=height), edge_margin=0.5, **kw)
    b.place(Part("j1"), at=Location(5, 20))
    return b


def _pin_c1(b, dy=-2.5):
    """c1's pad 1 a fixed distance north of the searched part's pad 1."""
    b.place(Part("c1"), at=Pin(1, X(PadRef(Part("u1"), 1)), Y(PadRef(Part("u1"), 1), dy)))


def _pad(plan, ref, number):
    return plan.occupancy.pad_location(ref, str(number))


def _placing(plan) -> list:
    """The findings that say an item was not placed, or placed where it is
    not legal."""
    return [f for f in plan.findings if f.kind in ("fixed", "unplaced")]


def _near(a, b):
    return abs(a.x - b.x) < 1e-6 and abs(a.y - b.y) < 1e-6


def test_a_pin_rider_lands_at_its_offset_from_the_searched_parts_pad():
    b = _board()
    b.place(Part("u1"))
    _pin_c1(b)
    plan = b.resolve()
    assert plan.placement("u1") is not None and plan.placement("c1") is not None
    want = _pad(plan, "U1", 1).offset(0.0, -2.5)
    assert _near(_pad(plan, "C1", 1), want)
    assert "rides u1" in plan.step("c1").note
    assert not _placing(plan)


def test_a_rider_is_where_the_same_relation_puts_it_off_a_fixed_part():
    """The rider lands exactly where the same declaration would put it were
    the reference fixed at the spot the search chose."""
    b = _board()
    b.place(Part("u1"))
    b.place(Part("c1"), at=Beside(Part("u1"), Edge.EAST))
    searched = b.resolve()
    b2 = _board()
    b2.place(Part("u1"), at=searched.placement("u1").location, rotation=searched.placement("u1").rotation)
    b2.place(Part("c1"), at=Beside(Part("u1"), Edge.EAST))
    fixed = b2.resolve()
    assert searched.placement("c1") == fixed.placement("c1")
    assert "rides u1" in searched.step("c1").note


def test_a_rider_turns_with_its_reference_under_rotations():
    """A board too narrow for the part at 0 takes it at 90; a rider said in
    the part's own frame (Turned, PadRef.local) turns with it."""
    b = _board(width=7.0, height=60.0)
    b.place(Part("u1"), rotations=(0, 90))
    local = PadRef(Part("u1"), 1).local(0.0, -2.5)
    b.place(Part("c1"), at=Pin(1, X(local), Y(local)), rotation=Turned(Part("u1")))
    plan = b.resolve()
    u1 = plan.placement("u1")
    assert u1 is not None and u1.rotation == 90.0
    c1 = plan.placement("c1")
    assert c1 is not None and c1.rotation == 90.0
    # the part's own north (-y) at 90 counter-clockwise on screen is screen west (-x)
    assert _near(_pad(plan, "C1", 1), _pad(plan, "U1", 1).offset(-2.5, 0.0))
    assert not _placing(plan)


def test_a_candidate_counts_only_where_the_rider_is_legal():
    """A part fixed where the rider would land beside the reference's best
    spot: the reference moves to a spot where the rider fits."""
    alone = _board()
    alone.place(Part("u1"))
    best = alone.resolve()
    rider_at = _pad(best, "U1", 1).offset(0.0, -2.5)
    blocker = footprint("R9", 55, 5, w=3, h=3, inst="r9", nets=("X", "Y"))
    b = _board(extra=[blocker])
    b.place(Part("r9"), at=Location(rider_at.x, rider_at.y))
    b.place(Part("u1"))
    _pin_c1(b)
    plan = b.resolve()
    assert plan.placement("u1") is not None and plan.placement("u1") != best.placement("u1")
    assert _near(_pad(plan, "C1", 1), _pad(plan, "U1", 1).offset(0.0, -2.5))
    assert not _placing(plan)
    assert not plan.box("c1").overlaps(plan.box("r9"))


def test_a_rider_on_an_edge_part_slides_it_along_the_edge():
    blocker = footprint("R9", 55, 5, w=3, h=3, inst="r9", nets=("X", "Y"))
    alone = _board()
    alone.place(Part("u1"), at=OnEdge(Edge.SOUTH))
    best = alone.resolve()
    rider_at = _pad(best, "U1", 1).offset(0.0, -2.5)
    b = _board(extra=[blocker])
    b.place(Part("r9"), at=Location(rider_at.x, rider_at.y))
    b.place(Part("u1"), at=OnEdge(Edge.SOUTH))
    _pin_c1(b)
    plan = b.resolve()
    assert plan.placement("u1") is not None and plan.placement("u1") != best.placement("u1")
    assert _near(_pad(plan, "C1", 1), _pad(plan, "U1", 1).offset(0.0, -2.5))
    assert not _placing(plan)


@pytest.mark.parametrize("seeded", [True, False])
def test_a_rider_that_fits_nowhere_fails_its_reference_and_is_named(seeded):
    """Off the board at every candidate: the reference finds no place, the
    finding names the rider and why, and neither is committed."""
    small = dict(width=24.0, height=24.0)             # the whole board is searched: kept small
    b = _board(**small) if seeded else Board(board_geometry(_fps(), **small), edge_margin=0.5)
    b.place(Part("u1"))
    _pin_c1(b, dy=-100.0)
    plan = b.resolve()
    assert plan.placement("u1") is None and plan.placement("c1") is None
    said = [f for f in plan.findings if f.startswith("u1:")]
    assert said and "rider c1: " in said[0] and "board edge" in said[0], plan.findings
    assert "rides u1" in plan.step("c1").note
    assert plan.occupancy.items["C1"].reference.location == Location(50, 50)       # never committed


def test_a_rider_that_overlaps_its_reference_fails_it():
    b = _board()
    b.place(Part("u1"))
    b.place(Part("c1"), at=Pin(1, X(PadRef(Part("u1"), 1)), Y(PadRef(Part("u1"), 1))))
    plan = b.resolve()
    assert plan.placement("u1") is None
    said = [f for f in plan.findings if f.startswith("u1:")]
    assert said and "rider c1: C1 courtyard overlaps U1 courtyard" in said[0], plan.findings


def test_a_required_rider_that_fits_nowhere_stops_the_run():
    b = _board()
    b.place(Part("u1"))
    b.place(Part("c1"), at=Pin(1, X(PadRef(Part("u1"), 1)), Y(PadRef(Part("u1"), 1))), required=True)
    with pytest.raises(CriticalUnplaced, match="c1"):
        b.resolve()


def test_a_rider_of_a_rider_chains():
    b = _board()
    b.place(Part("u1"))
    _pin_c1(b)
    b.place(Part("c2"), at=Pin(1, X(PadRef(Part("c1"), 2), 1.5), Y(PadRef(Part("c1"), 2))))
    plan = b.resolve()
    assert plan.placement("c2") is not None
    assert _near(_pad(plan, "C2", 1), _pad(plan, "C1", 2).offset(1.5, 0.0))
    assert _near(_pad(plan, "C1", 1), _pad(plan, "U1", 1).offset(0.0, -2.5))
    assert "rides c1" in plan.step("c2").note
    assert not _placing(plan)


def test_a_relation_to_a_third_searched_part_is_still_refused():
    """A Beside whose align pad is on another searched part: that pad has no
    position until its own part lands."""
    extra = [footprint("U2", 40, 40, w=4, h=2, inst="u2", nets=("GND", "Z"))]
    b = _board(extra=extra)
    b.place(Part("u1"))
    b.place(Part("u2"))
    b.place(Part("c1"), at=Beside(Part("u1"), Edge.EAST, align=PadRef(Part("u2"), 1)))
    with pytest.raises(ValueError, match="only FIXED and EDGE"):
        b.resolve()


def test_a_relation_beside_a_fixed_part_aligned_on_a_searched_pad_is_refused():
    b = _board()
    b.place(Part("u1"))
    b.place(Part("c1"), at=Beside(Part("j1"), Edge.EAST, align=PadRef(Part("u1"), 1)))
    with pytest.raises(ValueError, match="only FIXED and EDGE"):
        b.resolve()


def test_riders_replay_and_a_changed_rider_searches_again():
    def board(dy):
        b = _board(settings=dataclasses.replace(Settings(), cleanup_enabled=False))
        b.place(Part("u1"))
        _pin_c1(b, dy=dy)
        return b
    first = board(-2.5).resolve()
    again = board(-2.5).resolve(reuse=first.reuse)
    assert again.reuse["first_change"] is None
    assert again.placement("c1") == first.placement("c1")
    assert again.occupancy.items["C1"].reference == first.occupancy.items["C1"].reference
    changed = board(-3.0).resolve(reuse=first.reuse)
    assert changed.reuse["first_change"] == "u1"
    assert _near(_pad(changed, "C1", 1), _pad(changed, "U1", 1).offset(0.0, -3.0))


def _cell_board():
    fps = [footprint("U1", 0, 0, w=4, h=2, inst="pd.u1", nets=("A", "B"), cell="pd"),
           footprint("C1", 0, 3, w=2, h=1, inst="pd.c1", nets=("C", "GND"), cell="pd"),
           footprint("R1", 40, 40, w=3, h=1.3, inst="r1", nets=("A", "GND")),
           footprint("J1", 5, 20, w=2, h=2, inst="j1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, cells=["pd"], width=60, height=60), edge_margin=0.5)
    b.place(Part("j1"), at=Location(5, 20))
    return b


def test_a_part_rides_a_searched_cell():
    b = _cell_board()
    b.place(Cell("pd"))
    b.place(Part("r1"), at=Pin(1, X(CellPadRef(Cell("pd"), net="B"), 3.0), Y(CellPadRef(Cell("pd"), net="B"))))
    plan = b.resolve()
    assert plan.placement("pd") is not None
    assert _near(_pad(plan, "R1", 1), _pad(plan, "U1", 2).offset(3.0, 0.0))
    assert "rides pd" in plan.step("r1").note
    assert not _placing(plan)


def test_a_cell_rides_a_searched_part():
    b = _cell_board()
    b.place(Part("r1"))
    b.place(Cell("pd"), at=Pin(CellPadRef(Cell("pd"), net="B"), X(PadRef(Part("r1"), 2), 6.0),
                               Y(PadRef(Part("r1"), 2))))
    plan = b.resolve()
    assert plan.placement("r1") is not None
    assert _near(_pad(plan, "U1", 2), _pad(plan, "R1", 2).offset(6.0, 0.0))
    assert "rides r1" in plan.step("pd").note
    assert not _placing(plan)


def test_a_row_of_a_searched_part_rides_it():
    """Each item of the row rides the part; the row's start is found again
    at each candidate, so it lands where the same row of the part fixed
    there would. A part fixed under the part's best spot moves it."""
    alone = _board()
    alone.place(Part("u1"))
    best = alone.resolve().box("u1")
    blocker = footprint("R9", 55, 5, w=3, h=3, inst="r9", nets=("X", "Y"))
    b = _board(extra=[blocker])
    b.place(Part("r9"), at=Location(best.center.x, best.bottom + 2.0))
    b.place(Part("u1"))
    b.row([Part("c1"), Part("c2")], Edge.SOUTH, of=Part("u1"), rotation=0)
    searched = b.resolve()
    assert searched.placement("u1") is not None and searched.box("u1") != best
    b2 = _board(extra=[blocker])
    b2.place(Part("r9"), at=Location(best.center.x, best.bottom + 2.0))
    b2.place(Part("u1"), at=searched.placement("u1").location, rotation=searched.placement("u1").rotation)
    b2.row([Part("c1"), Part("c2")], Edge.SOUTH, of=Part("u1"), rotation=0)
    fixed = b2.resolve()
    assert (searched.placement("c1"), searched.placement("c2")) == (fixed.placement("c1"), fixed.placement("c2"))
    assert "rides u1" in searched.step("c1").note and "rides u1" in searched.step("c2").note
    assert not _placing(searched)


def test_copper_at_a_riders_pad_waits_for_it():
    """A track to a rider's pad and a fixed part's is planned once the rider
    has landed, not where the generator left it."""
    from placemat.values import CopperLayer, Net
    b = _board()
    b.place(Part("u1"))
    _pin_c1(b)
    b.track(Net("VIN"), [PadRef(Part("c1"), 1), PadRef(Part("j1"), 1)], layer=CopperLayer.F)
    plan = b.resolve()
    tracks = [op for op in plan.copper if getattr(op, "net", None) == "VIN" and hasattr(op, "start")]
    assert tracks and _near(tracks[0].start, _pad(plan, "C1", 1))
