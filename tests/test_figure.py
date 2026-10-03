"""A datasheet figure's frame: its points and a keepout's path share one
frame, and a script that never names a figure is not changed by it."""
import pytest

from placemat import reuse
from placemat.copper import Track, Via
from placemat.cutouts import Path
from placemat.layout import Board
from placemat.values import (CopperLayer, Face, Location, Mid, Net, PadRef, Part, Pin, Polar,
                             Turned, X, Y)
from tests.fixtures import board_geometry, footprint

WHY = "ant datasheet p7, recommended layout"
SHAPE = [(0.0, 0.0), (6.0, 0.0), (6.0, 2.5), (2.0, 4.0)]
ANCHOR = (1.0, 0.5)


def make_board():
    fps = [footprint("U1", 30.0, 30.0, w=6.0, h=3.0, inst="ant", nets=("SIG", "GND")),
           footprint("R1", 10.0, 10.0, inst="r1", nets=("SIG", "GND"))]
    return Board(board_geometry(fps, width=80, height=80), edge_margin=1.0)


def vias_of(plan):
    return [o for o in plan.copper if isinstance(o, Via)]


def test_a_figure_at_a_pad_is_the_pad_plus_the_point():
    b = make_board()
    b.place(Part("ant"), at=Location(30.0, 30.0))
    fig = b.figure(at=PadRef(Part("ant"), 1), why=WHY)
    b.via(Net("SIG"), at=fig.point(1.5, 2.0), why="p7")
    plan = b.resolve()
    pad = (27.6, 30.0)
    assert vias_of(plan)[0].at.x == pytest.approx(pad[0] + 1.5)
    assert vias_of(plan)[0].at.y == pytest.approx(pad[1] + 2.0)


def test_a_figure_anchor_is_the_point_that_lands_on_at():
    b = make_board()
    b.place(Part("ant"), at=Location(30.0, 30.0))
    fig = b.figure(at=Location(40.0, 20.0), anchor=(2.0, 3.0), why=WHY)
    b.via(Net("SIG"), at=fig.point(2.0, 3.0), why="p7")
    b.via(Net("SIG"), at=fig.point(5.0, 3.0), why="p7")
    plan = b.resolve()
    assert [(v.at.x, v.at.y) for v in vias_of(plan)] == [pytest.approx((40.0, 20.0)), pytest.approx((43.0, 20.0))]


def _old_and_new(degrees, face, mid=True):
    """The same figure placed both ways: a Path keepout with anchor= the old
    way, a keepout with frame=, and vias at each of the path's points."""
    b = make_board()
    b.place(Part("ant"), at=Location(30.0, 30.0), rotation=degrees, face=face)
    at = Mid(PadRef(Part("ant"), 1), PadRef(Part("ant"), 2)) if mid else PadRef(Part("ant"), 1)
    turn = Turned(Part("ant"), 90)
    b.keepout(Path(SHAPE, anchor=ANCHOR), "old", at=at, rotation=turn, excludes=("fill",), why="old")
    fig = b.figure(at=at, rotation=turn, anchor=ANCHOR, why=WHY)
    b.keepout(Path(SHAPE), "new", frame=fig, excludes=("fill",), why="new")
    for x, y in SHAPE:
        b.via(Net("SIG"), at=fig.point(x, y), why="p7")
    return b.resolve()


@pytest.mark.parametrize("degrees", [0, 90, 180])
@pytest.mark.parametrize("face", [Face.FRONT, Face.BACK])
@pytest.mark.parametrize("mid", [True, False])
def test_points_and_frame_keepout_match_a_path_keepout_placed_the_old_way(degrees, face, mid):
    plan = _old_and_new(degrees, face, mid)
    old, new = plan.keepouts["old"], plan.keepouts["new"]
    assert tuple(new.poly) == tuple(old.poly)
    assert new.centre == old.centre and new.rotation == pytest.approx(old.rotation)
    corners = [(v.at.x, v.at.y) for v in vias_of(plan)]
    assert len(corners) == len(SHAPE)
    for c in corners:
        assert any(c == pytest.approx(p, abs=1e-5) for p in old.poly), (c, old.poly)


def test_a_turned_figure_is_not_the_unturned_one():
    a, b = _old_and_new(0, Face.FRONT), _old_and_new(90, Face.FRONT)
    assert [v.at for v in vias_of(a)] != [v.at for v in vias_of(b)]


def test_frame_keepout_gives_the_polygon_of_the_anchor_form():
    for rot in (0.0, 30.0, Turned(Part("ant"), 180)):
        b = make_board()
        b.place(Part("ant"), at=Location(30.0, 30.0), rotation=90)
        at = Location(40.0, 40.0)
        b.keepout(Path(SHAPE, anchor=ANCHOR), "old", at=at, rotation=rot, excludes=("fill",), why="old")
        b.keepout(Path(SHAPE), "new", frame=b.figure(at=at, rotation=rot, anchor=ANCHOR, why=WHY),
                  excludes=("fill",), why="new")
        plan = b.resolve()
        assert tuple(plan.keepouts["new"].poly) == tuple(plan.keepouts["old"].poly)


def test_frame_is_refused_with_at_or_rotation():
    b = make_board()
    fig = b.figure(at=Location(40.0, 40.0), why=WHY)
    with pytest.raises(ValueError, match="frame="):
        b.keepout(Path(SHAPE), "k", frame=fig, at=Location(1.0, 1.0), why="x")
    with pytest.raises(ValueError, match="frame="):
        b.keepout(Path(SHAPE), "k", frame=fig, rotation=90.0, why="x")
    with pytest.raises(ValueError, match="anchor"):
        b.keepout(Path(SHAPE, anchor=(0.0, 0.0)), "k", frame=fig, why="x")


def test_a_figure_without_a_why_is_refused():
    b = make_board()
    for why in ("", "  "):
        with pytest.raises(ValueError, match="datasheet"):
            b.figure(at=Location(1.0, 1.0), why=why)
    with pytest.raises(ValueError, match="why="):
        b.figure(at=Location(1.0, 1.0))


def test_a_figure_point_is_a_pin_target():
    b = make_board()
    b.place(Part("ant"), at=Location(30.0, 30.0))
    fig = b.figure(at=PadRef(Part("ant"), 1), why=WHY)
    b.place(Part("r1"), at=Pin(1, fig.point(-4.0, 6.0)), rotation=0, why="p7")
    plan = b.resolve()
    r1 = plan.box("r1")                 # pad 1 is 1.4 west of the part's centre, and lands on (23.6, 36)
    assert (r1.center.x, r1.center.y) == pytest.approx((25.0, 36.0))


def test_pin_axes_take_a_figure_point_through_x_and_y():
    b = make_board()
    b.place(Part("ant"), at=Location(30.0, 30.0))
    fig = b.figure(at=PadRef(Part("ant"), 1), why=WHY)
    b.place(Part("r1"), at=Pin(1, X(fig.point(-4.0, 0.0)), Y(fig.point(0.0, 6.0))), rotation=0, why="p7")
    plan = b.resolve()
    assert plan.box("r1").center.y > 30.0


def test_a_figure_point_is_a_track_point_and_a_polar_centre():
    b = make_board()
    b.place(Part("ant"), at=Location(30.0, 30.0))
    fig = b.figure(at=Location(40.0, 50.0), why=WHY)
    b.track(Net("SIG"), [fig.point(0.0, 0.0), fig.point(5.0, 0.0)], layer=CopperLayer.F, width=0.3, why="p7")
    b.via(Net("SIG"), at=Polar(angle=90, radius=3.0, about=fig.point(1.0, 1.0)), why="p7")
    plan = b.resolve()
    t = [o for o in plan.copper if isinstance(o, Track)][0]
    assert (t.start.x, t.start.y, t.end.x, t.end.y) == pytest.approx((40.0, 50.0, 45.0, 50.0))
    v = vias_of(plan)[0]
    assert (v.at.x, v.at.y) == pytest.approx((44.0, 51.0))


def test_a_figure_point_is_the_end_of_a_mid():
    b = make_board()
    b.place(Part("ant"), at=Location(30.0, 30.0))
    fig = b.figure(at=Location(40.0, 50.0), why=WHY)
    b.via(Net("SIG"), at=Mid(fig.point(0.0, 0.0), fig.point(4.0, 2.0)), why="p7")
    assert (vias_of(b.resolve())[0].at.x, vias_of(b.resolve())[0].at.y) == pytest.approx((42.0, 51.0))


def test_a_figure_places_nothing_and_leaves_a_script_without_one_digesting_as_before():
    b = make_board()
    b.place(Part("ant"), at=Location(30.0, 30.0))
    before = reuse.canonical(b.via(Net("SIG"), at=Location(25.0, 25.0), why="tap"))
    b2 = make_board()
    b2.place(Part("ant"), at=Location(30.0, 30.0))
    b2.figure(at=Location(1.0, 1.0), why=WHY)
    assert reuse.canonical(b2.via(Net("SIG"), at=Location(25.0, 25.0), why="tap")) == before
    assert not b2._keepouts
    k = b2.keepout(Path(SHAPE), "k", at=Location(40.0, 40.0), why="x")
    assert reuse.canonical(k) == (
        "KeepoutIntent(key='keepout k',keepout=Keepout(shape=Path(points=[[0.0,0.0],[6.0,0.0],[6.0,2.5],[2.0,4.0]],"
        "anchor=None),name='k',at=Location(x=40.0,y=40.0),rotation=None,excludes=['parts','fill','tracks','vias',"
        "'pads'],allow=[],layers=None,why='x'),why='x',index=1,needs={},freedom=<Freedom.FIXED: 'fixed'>)")
