"""An item with one axis pinned slides along its line. With parts it
connects to already placed, it starts from the point on the line nearest
what it connects to; with none, it shares the line evenly as before."""
from placemat.layout import Board
from placemat.values import Centre, Location, Part
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("J1", 45, 10, inst="east", nets=("A", "X")),        # pad 1 on A at x 43.6
           footprint("J2", 12, 10, inst="west", nets=("B", "Y")),        # pad 1 on B at x 10.6
           footprint("R1", 70, 70, w=2, h=1, inst="ra", nets=("A", "P")),
           footprint("R2", 70, 75, w=2, h=1, inst="rb", nets=("B", "Q"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("east"), at=Location(45, 10))
    b.place(Part("west"), at=Location(12, 10))
    return b


def test_items_on_a_line_start_across_from_what_they_connect_to():
    b = _board()
    b.place(Part("ra"), at=Centre(None, 30))
    b.place(Part("rb"), at=Centre(None, 30))
    plan = b.resolve()
    assert abs(plan.box("ra").center.x - 43.6) < 1.5
    assert abs(plan.box("rb").center.x - 10.6) < 1.5
    assert plan.box("ra").center.y == 30 and plan.box("rb").center.y == 30


def test_items_with_nothing_placed_to_pull_them_share_the_line_evenly():
    fps = [footprint("R1", 70, 70, w=2, h=1, inst="ra", nets=("A", "P")),
           footprint("R2", 70, 75, w=2, h=1, inst="rb", nets=("B", "Q"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("ra"), at=Centre(None, 30))
    b.place(Part("rb"), at=Centre(None, 30))
    plan = b.resolve()
    xs = sorted([plan.box("ra").center.x, plan.box("rb").center.x])
    assert abs(xs[0] - 20.0) < 1.0 and abs(xs[1] - 40.0) < 1.0     # thirds of the keep-in, 1 .. 59
