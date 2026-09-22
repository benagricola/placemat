"""The placer decides the order things go down in, never the script: FIXED,
EDGE, then every searched item in one queue - a cell, a block and a loose
part together - by what each needs, the room it takes and the links pulling
it. Every choice carries the sentence that made it."""
import pytest

from placemat.layout import Board
from placemat.values import Near, OnEdge, Cell, Edge, LinkWeight, Location, Part, PadRef
from tests.fixtures import board_geometry, footprint


def make_board():
    fps = [footprint("J1", 5, 5, w=8, h=3, inst="j1", nets=("A", "GND")),
           footprint("U1", 40, 40, w=12, h=8, cell="big", inst="big.u", nets=("A", "B")),
           footprint("C1", 40, 46, w=3, h=1.5, cell="big", inst="big.c", nets=("B", "GND")),
           footprint("U2", 70, 70, w=4, h=3, cell="small", inst="small.u", nets=("B", "C")),
           footprint("U3", 80, 80, w=10, h=2, cell="strip", inst="strip.u", nets=("C", "D")),
           footprint("R1", 90, 90, inst="r1", nets=("D", "GND")),
           footprint("R2", 90, 95, inst="r2", nets=("A", "GND")),
           footprint("MH", 2, 2, w=2, h=2, inst="mh", nets=("GND", "GND"))]
    return Board(board_geometry(fps, cells=["big", "small", "strip"], width=100, height=100), edge_margin=1.0)


def order_of(plan):
    return [s.item for s in plan.steps if s.kind != "part" or s.placement is not None or "UNPLACED" in s.note]


def test_firm_first_then_searched_by_what_they_need_whatever_the_file_order():
    b = make_board()
    b.place(Part("r1"))                                                  # loose
    b.place(Cell("small"))                                               # cell
    b.place(Part("j1"), at=OnEdge(Edge.NORTH, along=50.0))      # edge
    b.place(Part("mh"), at=Location(3, 3))                               # fixed
    b.place(Cell("big"))
    order = order_of(b.resolve())
    assert order[0] == "mh" and order[1] == "j1"                          # FIXED then EDGE, as declared
    assert order.index("big") < order.index("r1")                         # then what needs the most room
    assert order.index("big") < order.index("small")


def test_among_cells_the_largest_goes_first_and_the_choice_is_explained():
    b = make_board()
    b.place(Cell("small"))
    b.place(Cell("strip"))
    b.place(Cell("big"))
    plan = b.resolve()
    cells = [s for s in plan.steps if s.kind == "cell"]
    assert [s.item for s in cells][0] == "big"
    # the sentence that chose it: the rank, and the two measurements behind it
    assert "rank 1/" in cells[0].note and "mm2" in cells[0].note and "pins" in cells[0].note


def test_pull_decides_between_items_the_rank_cannot_separate():
    """Pull is the tie-break, not the lead. Two identical parts score the same
    to the last bit, so the one wired to something already placed goes first;
    a part the rank CAN separate is not reordered by pull."""
    fps = [footprint("J1", 5, 5, w=8, h=3, inst="j1", nets=("A", "GND")),
           footprint("R1", 40, 40, w=2, h=1, inst="r1", nets=("A", "GND")),    # wired to J1
           footprint("R2", 60, 60, w=2, h=1, inst="r2", nets=("X", "GND")),    # identical, wired to nothing placed
           footprint("U1", 80, 80, w=12, h=8, inst="u1", nets=("X", "Y"))]     # far bigger, wired to nothing placed
    b = Board(board_geometry(fps, width=100, height=100), edge_margin=1.0)
    b.place(Part("j1"), at=Location(10, 10))
    b.place(Part("r2"))
    b.place(Part("r1"))
    b.place(Part("u1"))
    order = order_of(b.resolve())
    assert order.index("u1") < order.index("r1")       # the rank leads: pull does not lift a passive over it
    assert order.index("r1") < order.index("r2")       # and decides between the two that tie


def test_loose_parts_go_down_heaviest_link_first():
    b = make_board()
    b.place(Part("j1"), at=Location(10, 10))
    b.place(Part("r1"))
    b.place(Part("r2"))
    b.link(PadRef(Part("r2"), "A"), PadRef(Part("j1"), "A"), weight=LinkWeight.SHORT, limit_mm=3.0)
    order = order_of(b.resolve())
    assert order.index("r2") < order.index("r1")


def test_the_order_is_the_same_whatever_the_declaration_order():
    def run(seq):
        b = make_board()
        b.place(Part("j1"), at=Location(10, 10))
        for name in seq:
            b.place(Cell(name))
        return order_of(b.resolve())
    assert run(("small", "strip", "big")) == run(("big", "small", "strip")) == run(("strip", "big", "small"))


def test_a_high_priority_cell_goes_before_the_others_whatever_pulls_them():
    """MCU, driver, bridge: the script says which searched items matter,
    with a priority, never by where the line sits in the file."""
    from placemat.values import Priority
    b = make_board()
    b.place(Part("j1"), at=Location(10, 10))          # net A pulls the big cell
    b.place(Cell("strip"))                            # nets C, D: nothing pulls it
    b.place(Cell("small"))                            # pulled by nothing placed
    b.place(Cell("big"))
    order = order_of(b.resolve())
    assert order.index("big") < order.index("strip")   # by pull: the default order
    b = make_board()
    b.place(Part("j1"), at=Location(10, 10))
    b.place(Cell("big"))
    b.place(Cell("small"))
    b.place(Cell("strip"), priority=Priority.HIGH)    # declared last, placed first
    order = order_of(b.resolve())
    assert order.index("strip") < order.index("big") < order.index("small")


def test_order_follows_what_an_item_needs_not_what_kind_it_is():
    """A connector can be the most important thing on a board. Nothing waits
    for a whole tier of cells and blocks just for being one part."""
    fps = [footprint("J9", 25, 45, w=20, h=6, inst="j_big", nets=("A", "GND")),
           footprint("U9", 10, 10, w=4, h=3, cell="small", inst="small.u", nets=("A", "B")),
           footprint("C9", 10, 14, w=3, h=1.5, cell="small", inst="small.c", nets=("B", "GND"))]
    b = Board(board_geometry(fps, cells=["small"], width=50, height=50), edge_margin=1.0)
    b.place(Cell("small"))
    b.place(Part("j_big"))
    plan = b.resolve()
    order = [s.item for s in plan.steps if s.item in ("j_big", "small")]
    assert order == ["j_big", "small"]
    assert plan.step("j_big").rank == 1 and plan.step("small").rank == 2


def test_a_decided_position_leaves_priority_nothing_to_order():
    """Priority says when a searched item goes down. An item whose position
    the script already decided is not searched at all, so a scheduling
    priority on it cannot mean anything, and saying one is a mistake worth
    a message: silently dropping either half would place the part somewhere
    the script never asked for."""
    from placemat.values import Along, Centre, OnEdge, Priority
    for at in (OnEdge(Edge.NORTH, along=Along.MID), Location(20, 20), Centre(20, 20)):
        b = make_board()
        with pytest.raises(ValueError, match="decided"):
            b.place(Part("j1"), at=at, priority=Priority.HIGH)


def test_a_decided_position_is_not_a_priority_a_script_can_name():
    """Whether a position is decided is derived from `at=`, so there is no
    priority to ask for: the enum holds only what a script may say."""
    from placemat.values import Freedom, Priority
    assert [p.value for p in Priority] == ["high", "default", "low"]
    assert not hasattr(Priority, "FIXED") and not hasattr(Priority, "EDGE")
    assert Freedom.FIXED.value == "fixed" and Freedom.EDGE.value == "edge"


def test_an_item_free_to_slide_along_an_edge_still_takes_a_priority():
    """One degree of freedom is still searched, so priority orders it: the
    connector goes down before the cells that would otherwise crowd it."""
    from placemat.values import Priority
    b = make_board()
    b.place(Cell("big"))
    b.place(Cell("strip"))
    b.place(Part("j1"), at=OnEdge(Edge.NORTH), priority=Priority.HIGH)
    plan = b.resolve()
    assert plan.findings == []
    assert plan.step("j1").priority is Priority.HIGH
    assert "along the north edge" in plan.step("j1").note
    order = order_of(plan)
    assert order.index("j1") < order.index("big") < order.index("strip")


def test_a_no_legal_location_finding_names_the_top_blocking_owners():
    fps = [footprint("BIG", 25, 25, w=22, h=22, inst="big", nets=("A", "B")),
           footprint("SMALL", 50, 50, w=6, h=6, inst="small", nets=("B", "C"))]
    b = Board(board_geometry(fps, width=50, height=50), edge_margin=1.0, keep_going=True)
    b.place(Part("big"), at=Location(25, 25))
    b.place(Part("small"), at=Near(Location(25, 25), radius=1.0, step=0.5))
    (finding,) = [f for f in b.resolve().findings if f.startswith("small")]
    assert "BIG" in finding and "front" in finding


def test_the_plan_counts_which_nets_seeded_which_items():
    """A board with no plane declared pulls every part sharing a net to one
    centroid. The counts say so without placemat deciding a threshold."""
    fps = [footprint("J1", 5, 5, w=6, h=3, inst="j1", nets=("BUS", "GND"))]
    fps += [footprint("C%d" % i, 20 + i * 3, 20, w=1, h=0.5, inst="c%d" % i, nets=("BUS", "GND"))
            for i in range(4)]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("j1"), at=Location(10, 10))
    for i in range(4):
        b.place(Part("c%d" % i))
    plan = b.resolve()
    assert plan.seeded_by_net["BUS"] == 4


def test_a_declared_plane_net_never_seeds_anything():
    from placemat.values import CopperLayer, Net
    fps = [footprint("J1", 5, 5, w=6, h=3, inst="j1", nets=("BUS", "GND"))]
    fps += [footprint("C%d" % i, 20 + i * 3, 20, w=1, h=0.5, inst="c%d" % i, nets=("BUS", "GND"))
            for i in range(4)]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.size(width=60, height=60)
    b.plane(Net("GND"), layers=(CopperLayer.B,))
    b.place(Part("j1"), at=Location(10, 10))
    for i in range(4):
        b.place(Part("c%d" % i))
    plan = b.resolve()
    assert "GND" not in plan.seeded_by_net and plan.seeded_by_net["BUS"] == 4
