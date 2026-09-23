"""Pocket scan: where a cell or part with nothing placed to pull it could go
at all, found by scanning the free board for rectangles its envelope fits."""
from placemat.occupancy import Occupancy
from placemat.placer import pockets
from placemat.placement import Placement
from placemat.values import CopperLayer, Face, Location
from placemat.layout import Board
from placemat.values import Cell, Part
from tests.fixtures import board_geometry, footprint


def test_pockets_are_free_rectangles_the_envelope_fits_in():
    # a 40 x 40 board with a 20 x 40 wall of parts down the middle: two 10-wide strips remain
    fps = [footprint("W%d" % i, 20, 5 + 10 * i, w=20, h=10, inst="w%d" % i, excess=0.0) for i in range(4)]
    fps.append(footprint("R1", 5, 5, w=6, h=3, inst="r1"))
    occ = Occupancy(board_geometry(fps, width=40, height=40), edge_margin=0.0)
    found = pockets(occ, width=6.0, height=3.0, face=Face.FRONT, step=1.0)
    assert found
    for p in found:
        assert p.box.width >= 6.0 and p.box.height >= 3.0
        assert p.box.right <= 10.0 + 1e-9 or p.box.left >= 30.0 - 1e-9       # only the two side strips
    assert found[0].box.area >= found[-1].box.area                            # biggest first


def test_a_cell_with_no_placed_partner_lands_in_a_pocket_and_says_so():
    fps = [footprint("W%d" % i, 20, 5 + 10 * i, w=20, h=10, inst="w%d" % i, nets=("X%d" % i, "Y%d" % i), excess=0.0)
           for i in range(4)]
    fps += [footprint("U1", 60, 60, w=4, h=2, cell="c", inst="c.u", nets=("A", "B")),
            footprint("R1", 60, 63, w=4, h=2, cell="c", inst="c.r", nets=("B", "C"))]
    b = Board(board_geometry(fps, cells=["c"], width=40, height=40), edge_margin=0.0)
    for i in range(4):
        b.place(Part("w%d" % i), at=Location(20, 5 + 10 * i))
    b.place(Cell("c"))                       # nothing it connects to is placed: no seed
    plan = b.resolve()
    box = plan.box("c")
    assert box.right <= 10.0 + 1e-6 or box.left >= 30.0 - 1e-6
    assert "pocket" in plan.step("c").note
    assert not plan.findings


def test_no_pocket_is_a_finding_not_a_crash():
    fps = [footprint("W1", 20, 20, w=40, h=40, inst="w1", excess=0.0),
           footprint("R1", 100, 100, w=6, h=3, inst="r1", nets=("Q", "Z"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.0)
    b.place(Part("w1"), at=Location(20, 20))
    b.place(Part("r1"))
    plan = b.resolve()
    assert any("r1" in f and "pocket" in f for f in plan.findings)


def test_a_through_via_of_another_cell_takes_space_from_a_pocket_on_both_faces():
    """A front cell's ground vias come through the board; the pocket under
    them on the back is not free, so the report must not promise it."""
    from placemat.occupancy import Occupancy
    from placemat.placer import pockets
    from placemat.values import Face
    from tests.fixtures import board_geometry, footprint
    from placemat.board_geometry import CopperItem
    from placemat.values import Box
    from tests.fixtures import rect
    outline = rect(25, 25, 0.6, 0.6)
    via = CopperItem("via", "GND", frozenset([CopperLayer.F, CopperLayer.B]), (outline,), Box.of_points(outline), owner="mcu")
    g = board_geometry([footprint("U1", 10, 10, w=4, h=2, cell="mcu", inst="mcu.u")], cells=["mcu"], copper=[via], width=50, height=50)
    occ = Occupancy(g, edge_margin=1.0, board_box=g.outline_box)
    back = pockets(occ, 30.0, 30.0, Face.BACK, step=0.5, limit=1)
    assert back == []                                          # the via splits the 48 x 48 free square
    front_small = pockets(occ, 20.0, 20.0, Face.BACK, step=0.5, limit=1)
    b = front_small[0].box
    assert front_small and not (b.left < 25 < b.right and b.top < 25 < b.bottom)      # the pocket goes round the via


def test_a_search_that_no_pocket_can_satisfy_is_not_run():
    """A scan cannot find what pockets rule out: an item bigger than every
    free rectangle on its face is reported unplaced at once, with the
    reason, instead of trying thousands of candidates."""
    from placemat.values import Priority
    fps = [footprint("W1", 25, 25, w=30, h=30, inst="w1", nets=("A", "B")),
           footprint("B1", 5, 5, w=15, h=15, inst="b1", nets=("A", "C"))]
    b = Board(board_geometry(fps, width=50, height=50), edge_margin=1.0, keep_going=True)
    b.place(Part("w1"), at=Location(25, 25))
    b.place(Part("b1"), priority=Priority.DEFAULT)
    plan = b.resolve()
    note = plan.step("b1").note
    assert "UNPLACED" in note and "no pocket fits" in note and "15.0 x 15.0" in note
    assert not any("no legal location within" in f for f in plan.findings)


def test_a_part_not_yet_placed_blocks_no_pocket():
    """The generator leaves every part somewhere; one the script has not
    placed yet is pending, not an obstacle, so a pocket may lie under it."""
    from placemat.occupancy import Occupancy
    from placemat.placer import pockets
    from placemat.values import Face
    fps = [footprint("BIG", 30, 10, w=58, h=18, inst="big", nets=("D", "E"))]
    g = board_geometry(fps, width=60, height=20)
    occ = Occupancy(g, 0.5, board_box=g.outline_box)
    occ.pending |= {"BIG"}
    assert pockets(occ, 6.0, 6.0, Face.FRONT)


def test_a_part_not_yet_placed_conflicts_with_no_copper_and_covers_no_board():
    from placemat.occupancy import Occupancy, Shape
    from placemat.geometry import box_polygon
    from placemat.values import Box, Face
    fps = [footprint("BIG", 30, 10, w=58, h=18, inst="big", nets=("D", "E"))]
    g = board_geometry(fps, width=60, height=20)
    occ = Occupancy(g, 0.5, board_box=g.outline_box)
    track = Shape("", "copper", frozenset([Face.FRONT]), frozenset([CopperLayer.F]), "X",
                  box_polygon(Box(0, 9.9, 60, 10.1)), Box(0, 9.9, 60, 10.1))
    before = occ.free_area(Face.FRONT)
    assert occ.copper_conflicts(track)
    occ.pending |= {"BIG"}
    assert occ.copper_conflicts(track) == []
    assert occ.free_area(Face.FRONT) > before


def _tee():
    """A 20 x 20 board whose free room is a T: a 20 x 3 bar along the top and
    a 4-wide stem down the middle, the stem the bigger rectangle."""
    fps = [footprint("L1", 4, 11.5, w=8, h=17, inst="l1", excess=0.0),       # x 0..8, y 3..20
           footprint("R1", 16, 11.5, w=8, h=17, inst="r1", excess=0.0),      # x 12..20, y 3..20
           footprint("Q1", 60, 60, w=9.6, h=2.4, inst="q1", excess=0.0)]
    occ = Occupancy(board_geometry(fps, width=20, height=20), edge_margin=0.0)
    for fp in fps[:2]:
        occ.commit(fp, Placement(fp.location, 0.0, Face.FRONT))
    return occ


def test_a_pocket_is_found_where_the_item_fits_though_a_bigger_one_does_not():
    occ = _tee()
    found = pockets(occ, width=10.0, height=2.5, face=Face.FRONT, step=0.5)
    assert found and found[0].box.width >= 10.0 and found[0].box.height >= 2.5
    assert found[0].box.bottom <= 3.0 + 1e-9                                    # the bar, not the stem
    assert pockets(occ, width=5.0, height=5.0, face=Face.FRONT, step=0.5) == []


def test_a_gap_off_the_grid_is_not_lost_to_rounding():
    """Walls at 5.25 and 8.25 leave exactly 3 mm; rounding each wall out to the
    0.5 mm grid left 2.5, and the check before a search called a 3 mm part
    hopeless. That check rounds toward room."""
    fps = [footprint("W1", 2.625, 10, w=5.25, h=20, inst="w1", excess=0.0),
           footprint("W2", 14.125, 10, w=11.75, h=20, inst="w2", excess=0.0)]
    occ = Occupancy(board_geometry(fps, width=20, height=20), edge_margin=0.0)
    for fp in fps:
        occ.commit(fp, Placement(fp.location, 0.0, Face.FRONT))
    assert pockets(occ, width=3.0, height=3.0, face=Face.FRONT, step=0.5, covered=True)


def test_an_item_that_fits_the_smaller_room_is_placed_there():
    fps = [footprint("L1", 4, 11.5, w=8, h=17, inst="l1", excess=0.0),
           footprint("R1", 16, 11.5, w=8, h=17, inst="r1", excess=0.0),
           footprint("Q1", 60, 60, w=9.6, h=2.4, inst="q1", nets=("P", "Z"), excess=0.0)]
    b = Board(board_geometry(fps, width=20, height=20), edge_margin=0.0)
    b.place(Part("l1"), at=Location(4, 11.5))
    b.place(Part("r1"), at=Location(16, 11.5))
    b.place(Part("q1"), rotation=0)
    plan = b.resolve()
    assert plan.placement("q1") is not None, plan.step("q1").note
