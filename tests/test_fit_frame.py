"""A fragment's frame sized to what is placed in it. Pure: synthetic boards."""
import pytest

from placemat.layout import Board
from placemat.values import Edge, Location, OnEdge, Part, PadRef, Pin, X, Y
from tests.fixtures import board_geometry, footprint


def _board(**kw):
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("C1", 30, 30, w=2, h=1, inst="c1", nets=("A", "GND")),
           footprint("R1", 34, 34, w=2, h=1, inst="r1", nets=("B", "GND"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=0.5)
    b.size(fit=True, draw=False, **kw)
    return b


def test_fit_is_for_a_fragments_frame_only():
    b = Board(board_geometry([footprint("U1", 20, 20, inst="u1")], width=60, height=60))
    with pytest.raises(ValueError, match="fit"):
        b.size(fit=True, draw=True)


def test_what_needs_the_frame_is_refused_on_a_fit_board():
    b = _board()
    for ask in (lambda: b.width, lambda: b.height, lambda: b.centre,
                lambda: b.place(Part("c1"), at=OnEdge(Edge.NORTH)),
                lambda: b.row([Part("c1"), Part("r1")], Edge.SOUTH),
                lambda: b.edge(Edge.NORTH)):
        with pytest.raises(ValueError, match="fit"):
            ask()


def test_a_searched_part_goes_round_the_decided_content():
    b = _board()
    b.place(Part("u1"), at=Location(0, 0))
    b.place(Part("c1"))
    plan = b.resolve()
    p = plan.placement("c1")
    assert p is not None and p.location.distance(Location(0, 0)) < b.settings.place_fit_room + 5


def test_with_nothing_decided_the_first_part_is_at_the_origin():
    b = _board()
    b.place(Part("u1"))
    plan = b.resolve()
    assert plan.placement("u1").location.distance(Location(0, 0)) < 1e-6


from placemat.copper import Zone
from placemat.values import CopperLayer, Net


def _pinned(b):
    b.place(Part("u1"), at=Location(0, 0))
    b.place(Part("c1"), at=Pin(1, X(PadRef(Part("u1"), 1), -3.0), Y(PadRef(Part("u1"), 1))))
    return b


def test_the_frame_is_the_content_plus_the_margin():
    b = _pinned(_board(margin=0.5))
    plan = b.resolve()
    content = b._placed_box(plan.occupancy, plan)
    assert plan.outline == content.inflate(0.5)
    assert plan.outline.left < 0          # c1 sits west of u1: the frame is not at the origin


def test_a_plane_is_inset_from_the_fitted_frame_and_does_not_size_it():
    b = _pinned(_board(margin=0.5))
    b.plane(Net("GND"), layers=(CopperLayer.B,))
    plan = b.resolve()
    (z,) = [c for c in plan.copper if isinstance(c, Zone)]
    xs, ys = [p[0] for p in z.points], [p[1] for p in z.points]
    inset = b.settings.copper_plane_inset
    assert abs(min(xs) - (plan.outline.left + inset)) < 1e-6
    assert abs(max(ys) - (plan.outline.bottom - inset)) < 1e-6


def test_a_plane_with_its_own_outline_keeps_it():
    b = _pinned(_board())
    pts = [Location(-1, -1), Location(1, -1), Location(1, 1), Location(-1, 1)]
    b.plane(Net("GND"), layers=(CopperLayer.B,), outline=pts)
    (z,) = [c for c in b.resolve().copper if isinstance(c, Zone)]
    assert set(z.points) == {(-1, -1), (1, -1), (1, 1), (-1, 1)}


def test_an_unchanged_fit_script_replays_to_the_same_frame():
    first = _pinned(_board()).resolve()
    again = _pinned(_board()).resolve(reuse=first.reuse)
    assert again.reuse["reused"] > 0 and again.outline == first.outline


def _big(*extra):
    fps = [footprint("U1", 20, 20, w=2, h=1, inst="u1", nets=("A", "B")),
           footprint("J1", 40, 40, w=30, h=4, inst="j1", nets=("A", "GND")),
           footprint("M1", 10, 50, w=24, h=12, inst="m1", nets=("B", "GND"))] + list(extra)
    b = Board(board_geometry(fps, width=80, height=80), edge_margin=0.5)
    b.size(fit=True, draw=False)
    return b


def test_a_large_searched_part_finds_room_and_the_frame_grows_round_it():
    b = _big()
    b.place(Part("u1"), at=Location(0, 0))
    b.place(Part("j1"))
    b.place(Part("m1"))
    plan = b.resolve()
    for key in ("j1", "m1"):
        assert plan.placement(key) is not None, plan.step(key).note
        assert plan.outline.contains(plan.occupancy.body_box(plan._items[key], plan.placement(key)))


def test_a_large_part_with_nothing_decided_finds_room():
    b = _big()
    b.place(Part("m1"))
    assert b.resolve().placement("m1") is not None


def test_a_keepout_at_a_place_works_on_a_fit_board_and_one_with_a_freedom_is_refused():
    from placemat.cutouts import Circle
    b = _pinned(_board())
    b.keepout(Circle(2.0), "clear", at=Location(8, 0), why="a clear area beside the part")
    assert b.resolve().placement("u1") is not None
    b = _pinned(_board())
    with pytest.raises(ValueError, match="fit"):
        b.keepout(Circle(2.0), "slides", at=Location(8, None), why="slides along the frame")


def test_a_cells_own_copper_counts_toward_the_frame():
    from placemat.board_geometry import CopperItem
    from placemat.values import Box, Cell, CopperLayer
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="mod.u1", cell="mod", nets=("A", "B"))]
    track = ((19.0, 20.0), (21.0, 20.0), (21.0, 29.0), (19.0, 29.0))
    copper = [CopperItem("track", "A", frozenset([CopperLayer.F]), (track,), Box(19.0, 20.0, 21.0, 29.0), "mod")]
    b = Board(board_geometry(fps, cells=["mod"], copper=copper, width=60, height=60), edge_margin=0.5)
    b.size(fit=True, draw=False, margin=0.0)
    b.place(Cell("mod"), at=Location(20, 24.5))
    plan = b.resolve()
    assert plan.outline.bottom - plan.outline.top >= 9.0 - 1e-6


def test_a_plane_declared_before_the_fit_size_follows_the_frame():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=0.5)
    b.plane(Net("GND"), layers=(CopperLayer.B,))
    b.size(fit=True, draw=False)
    b.place(Part("u1"), at=Location(0, 0))
    plan = b.resolve()
    (z,) = [c for c in plan.copper if isinstance(c, Zone)]
    assert min(p[0] for p in z.points) >= plan.outline.left


def test_a_sized_frame_after_fit_is_a_sized_frame():
    b = _board()
    b.size(30, 20)
    assert b.width == 30


def test_fit_needs_no_draw_and_a_negative_margin_is_refused():
    fps = [footprint("U1", 20, 20, inst="u1")]
    b = Board(board_geometry(fps, width=60, height=60))
    b.size(fit=True)
    with pytest.raises(ValueError, match="margin"):
        Board(board_geometry(fps, width=60, height=60)).size(fit=True, margin=-1.0)


def test_an_unreserved_label_counts_toward_the_frame():
    b = _pinned(_board(margin=0.0))
    b.label(Part("u1"), "LONG LABEL TEXT", side="N", size=2.0, reserve=False)
    plan = b.resolve()
    texts = [c for c in plan.copper if type(c).__name__ == "Text"]
    assert texts and all(plan.outline.contains(t.box) for t in texts)


def test_edges_and_centroid_name_fit_on_a_fit_board():
    b = _board()
    for ask in (lambda: b.edges(Edge.NORTH), lambda: b.centroid):
        with pytest.raises(ValueError, match="fit"):
            ask()
