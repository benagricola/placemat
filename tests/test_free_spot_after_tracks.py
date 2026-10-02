"""A FreeSpot via is planned after the tracks declared before it, as a track that waits for a searched part is
(layout.py `_copper_after`): the track has no way round a via that was decided before it was drawn."""
from placemat.layout import Board
from placemat.values import CopperLayer, FreeSpot, Location, Net, Part, PadRef
from tests.fixtures import board_geometry, footprint


def _board(via_first=False):
    u = footprint("U1", 20, 20, w=3, h=1, inst="u", nets=("A", "G"))
    c = footprint("C1", 30, 30, w=3, h=1, inst="c", nets=("A", "B"))
    b = Board(board_geometry([u, c], width=40, height=40, extra_nets=["G"]), edge_margin=0.5, keep_going=True)
    b.place(Part("u"), at=Location(20, 20))
    b.place(Part("c"))
    spot = lambda: b.via(Net("G"), FreeSpot(near=PadRef(Part("u"), 2), radius=1.5), drill=0.2, size=0.45)
    if via_first:
        v = spot()
    t = b.track(Net("A"), [PadRef(Part("u"), 1), PadRef(Part("c"), 1)], layer=CopperLayer.F)
    if not via_first:
        v = spot()
    return b, t, v


def test_a_via_declared_after_a_searched_track_waits_for_it():
    b, t, v = _board()
    b._derive_copper_freedom()
    assert not v.freedom.decided, "planned with the track, not before the search"
    assert t.index in b._copper_after[v.index]


def test_a_via_declared_before_the_track_is_planned_as_it_was():
    b, t, v = _board(via_first=True)
    b._derive_copper_freedom()
    assert v.freedom.decided
