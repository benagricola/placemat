"""A firm item (a decided place: Beside, Pin, Centre on both axes) said in terms of a searched item is placed right
after what it needs, in the search; a searched item that needs one waits for it. Pure: synthetic boards."""
import pytest

from placemat.layout import Board
from placemat.values import Beside, Cell, Edge, Location, Mid, Near, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board(extra=(), **kw):
    fps = [footprint("U1", 30, 20, w=8, h=3, inst="u1", nets=("VIN", "OUT")),
           footprint("J1", 5, 20, w=2, h=2, inst="j1", nets=("VIN", "GND")),
           footprint("C1", 50, 50, w=2, h=1, inst="c1", nets=("VIN", "GND")),
           footprint("C2", 52, 52, w=2, h=1, inst="c2", nets=("GND", "OUT")),
           footprint("C3", 54, 54, w=2, h=1, inst="c3", nets=("GND", "OUT")),
           footprint("A1", 0, 0, w=4, h=2, inst="src.a1", nets=("P", "Q"), cell="src"),
           footprint("A2", 10, 0, w=4, h=2, inst="src.a2", nets=("R", "S"), cell="src"),
           footprint("B1", 0, 0, w=4, h=2, inst="dst.b1", nets=("T", "U"), cell="dst"),
           footprint("B2", 10, 0, w=4, h=2, inst="dst.b2", nets=("V", "W"), cell="dst")] + list(extra)
    b = Board(board_geometry(fps, cells=["src", "dst"], width=100, height=100), edge_margin=0.5, **kw)
    b.place(Part("j1"), at=Location(5, 20))
    return b


def _pad(plan, ref, number):
    return plan.occupancy.pad_location(ref, str(number))


def _order(plan):
    return [s.item for s in plan.steps]


def test_a_beside_part_aligned_on_a_searched_parts_pad_lands_aligned_after_it():
    b = _board()
    b.place(Part("u1"))
    b.place(Part("c1"), at=Beside(Part("j1"), Edge.EAST, align=PadRef(Part("u1"), 1)))
    plan = b.resolve()
    assert plan.placement("u1") is not None and plan.placement("c1") is not None
    assert _order(plan).index("u1") < _order(plan).index("c1")
    assert _pad(plan, "C1", 1).y == pytest.approx(_pad(plan, "U1", 1).y)


def test_a_beside_cell_aligned_on_a_searched_cells_pads_centres_on_them():
    b = _board()
    b.place(Cell("src"))
    b.place(Cell("dst"), at=Beside(Part("j1"), Edge.SOUTH,
                                   align=Mid(PadRef(Part("src.a1"), 1), PadRef(Part("src.a2"), 1))))
    plan = b.resolve()
    assert _order(plan).index("src") < _order(plan).index("dst")
    mid = (_pad(plan, "A1", 1).x + _pad(plan, "A2", 1).x) / 2.0
    assert plan.box("dst").center.x == pytest.approx(mid)


def test_a_chain_of_two_deferred_items_follows_the_searched_one():
    b = _board()
    b.place(Part("c2"), at=Beside(Part("c1"), Edge.EAST, align=PadRef(Part("c1"), 2)))    # declared before what it needs
    b.place(Part("c1"), at=Beside(Part("j1"), Edge.EAST, align=PadRef(Part("u1"), 1)))
    b.place(Part("u1"))
    plan = b.resolve()
    order = _order(plan)
    assert order.index("u1") < order.index("c1") < order.index("c2")
    assert _pad(plan, "C1", 1).y == pytest.approx(_pad(plan, "U1", 1).y)
    assert plan.placement("c2") is not None


def test_a_searched_item_waits_for_a_deferred_one_it_needs():
    b = _board()
    b.place(Part("u1"))
    b.place(Part("c1"), at=Beside(Part("j1"), Edge.EAST, align=PadRef(Part("u1"), 1)))
    b.place(Part("c3"), at=Near(PadRef(Part("c1"), 1)))
    plan = b.resolve()
    order = _order(plan)
    assert order.index("u1") < order.index("c1") < order.index("c3")
    assert all(plan.placement(k) is not None for k in ("u1", "c1", "c3"))


def test_a_need_that_is_never_placed_is_refused_naming_it():
    b = _board()
    b.place(Part("c1"), at=Beside(Part("j1"), Edge.EAST, align=PadRef(Part("u1"), 1)))      # u1 is never placed
    with pytest.raises(ValueError, match=r"c1 is placed relative to U1, which is never placed"):
        b.resolve()


def test_a_deferred_item_that_collides_is_a_finding_as_a_firm_one_is():
    def run(by):
        b = _board(extra=[footprint("K1", 25, 20, w=14, h=30, inst="blk", nets=("GND", "Z"))], keep_going=True)
        b.place(Part("blk"), at=Location(14, 20))               # fills the east side of j1
        b.place(Part("u1"))
        b.place(Part("c1"), at=Beside(Part("j1"), Edge.EAST, align=PadRef(Part(by), 1)))
        return b.resolve()
    firm, late = run("j1"), run("u1")
    said = lambda plan: sorted((f.cause.value if hasattr(f.cause, "value") else str(f.cause)) for f in plan.findings
                               if str(getattr(f, "cause", "")).startswith("C.FIXED") or "fixed" in str(f.cause))
    assert said(firm) and said(firm) == said(late)


def test_a_deferred_item_is_a_step_that_replays_and_searches_again_when_changed():
    def board(by):
        b = _board()
        b.place(Part("u1"))
        b.place(Part("c1" if by == 1 else "c2"), at=Beside(Part("j1"), Edge.EAST, align=PadRef(Part("u1"), by)))
        return b
    first = board(1).resolve()
    again = board(1).resolve(reuse=first.reuse)
    assert again.reuse["reused"] == len(first.reuse["steps"]) > 0
    assert again.placement("c1") == first.placement("c1")
    changed = board(2).resolve(reuse=first.reuse)
    assert changed.reuse["reused"] < len(changed.reuse["steps"])
    assert changed.placement("c2") is not None
