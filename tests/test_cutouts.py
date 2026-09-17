"""A hole in a board, whatever shape the board is.

A slot for a cable, a window, a bore: the path is declared the same way on
a rectangle, a disc and a shaped board, the keep-in refuses a part over it
in the same words, and Edge.Cuts gets the real arcs.
"""
import math

import pytest

from placemat.cutouts import Circle, Cutouts, Path, Slot
from placemat.layout import Board, PlacementCollision
from placemat.outline import Outline
from placemat.values import (Along, Box, Centre, Cutout, Disc, Edge, Fraction, Location, OnBore,
                             OnEdge, OnRim, Part, Polar, X, Y)
from tests.fixtures import board_geometry, footprint

# 17 mm tip to tip, 3 mm across, centred at (20, 28): its top face sits at
# y = 26.5 and its straight sides run x = 11.5 .. 28.5.
SLOT_SHAPE = Slot(17.0, 3.0)
SLOT = SLOT_SHAPE.path_at(Location(20.0, 28.0))
SLOT_AREA = 14.0 * 3.0 + math.pi * 1.5 ** 2

# each way of saying "a 40 mm board", with the area it has before the slot
DECLARE = [
    ("a rectangle", lambda b, holes: b.size(width=40.0, height=40.0, holes=holes), 1600.0),
    ("a disc", lambda b, holes: b.disc(diameter=40.0, holes=holes), math.pi * 400.0),
    ("a shaped board", lambda b, holes: b.outline([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)], holes=holes), 1600.0),
]


def make_board(*insts, margin=0.5, keep_going=False):
    fps = [footprint(i.upper(), 50.0, 3.0 + n * 6.0, w=4.0, h=4.0, inst=i, nets=("M", "GND"))
           for n, i in enumerate(insts)]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=margin, keep_going=keep_going)


def place_at(declare, y):
    """Put a 4 mm part with its centre at (20, y) and say what happened."""
    b = make_board("u1")
    declare(b, [SLOT])
    b.place(Part("u1"), at=Location(20.0, y))
    try:
        b.resolve()
        return None
    except PlacementCollision as e:
        return str(e).strip().splitlines()[-1].split(": ", 1)[1]


# ----------------------------------------------------------------- shapes
def test_a_slot_is_measured_tip_to_tip():
    """What callipers measure: a 13 mm slot is 13 mm end to end, not a
    13 mm centre line."""
    s = Slot(13.0, 3.0)
    assert s.area == pytest.approx(10.0 * 3.0 + math.pi * 1.5 ** 2, rel=0.005)
    path = s.path_at(Location(20.0, 20.0))
    xs = [p[0] for p in Cutouts([path]).loops[0]]
    assert max(xs) - min(xs) == pytest.approx(13.0, abs=0.02)


def test_a_slot_as_wide_as_it_is_long_is_a_circle():
    assert Cutouts([Slot(6.0, 6.0).path_at(Location(0.0, 0.0))]).area == \
        pytest.approx(math.pi * 9.0, rel=0.01)


def test_a_slot_narrower_than_it_is_wide_is_refused():
    with pytest.raises(ValueError, match="tip to tip"):
        Slot(2.0, 3.0)
    with pytest.raises(ValueError, match="positive"):
        Slot(10.0, 0.0)


def test_a_shape_is_placed_about_its_box_centre():
    for shape in (Slot(13.0, 3.0), Circle(8.0),
                  Path([(100.0, 100.0), (110.0, 100.0), (110.0, 104.0), (100.0, 104.0)])):
        loop = Cutouts([shape.path_at(Location(20.0, 30.0))]).loops[0]
        xs, ys = [p[0] for p in loop], [p[1] for p in loop]
        assert (min(xs) + max(xs)) / 2.0 == pytest.approx(20.0, abs=0.02)
        assert (min(ys) + max(ys)) / 2.0 == pytest.approx(30.0, abs=0.02)


def test_a_rotated_slot_runs_on_its_bearing():
    """rotation is a bearing: 90 turns the slot's length to run north-south."""
    loop = Cutouts([Slot(13.0, 3.0).path_at(Location(20.0, 20.0), 90.0)]).loops[0]
    xs, ys = [p[0] for p in loop], [p[1] for p in loop]
    assert max(ys) - min(ys) == pytest.approx(13.0, abs=0.02)
    assert max(xs) - min(xs) == pytest.approx(3.0, abs=0.02)


def test_a_circle_takes_no_rotation():
    with pytest.raises(ValueError, match="no direction"):
        Circle(8.0).path_at(Location(0.0, 0.0), 45.0)


def test_a_shape_knows_its_box_before_it_is_flattened():
    assert Slot(13.0, 3.0).box_at(Location(20.0, 20.0), 0.0) == \
        pytest.approx((13.5, 18.5, 26.5, 21.5), abs=0.02)


# --------------------------------------------------- a cutout declared
def test_a_named_cutout_is_declared_with_a_shape_and_a_place():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Slot(17.0, 3.0), "ffc", at=Location(20.0, 28.0),
                         why="the cable passes through here")])
    plan = b.resolve()
    assert plan.cutouts.area == pytest.approx(SLOT_SHAPE.area, rel=0.005)


def test_a_cutout_needs_a_name_and_a_place():
    with pytest.raises(ValueError, match="name"):
        Cutout(Slot(10.0, 3.0), "", at=Location(0.0, 0.0))
    with pytest.raises(ValueError, match="at="):
        Cutout(Slot(10.0, 3.0), "ffc")


def test_two_cutouts_may_not_share_a_name():
    b = make_board()
    with pytest.raises(ValueError, match="already a cutout named"):
        b.size(width=40.0, height=40.0,
               holes=[Cutout(Circle(3.0), "vent", at=Location(10.0, 10.0), why="a"),
                      Cutout(Circle(3.0), "vent", at=Location(30.0, 10.0), why="b")])


def test_a_raw_path_and_a_named_cutout_live_side_by_side():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[SLOT, Cutout(Circle(4.0), "vent", at=Location(10.0, 10.0), why="a")])
    plan = b.resolve()
    assert plan.cutouts.area == pytest.approx(SLOT_SHAPE.area + math.pi * 4.0, rel=0.01)


# ------------------------------------------------ a cutout with a freedom
def test_a_cutout_with_one_freedom_slides_to_where_there_is_room():
    b = make_board("u1")
    b.size(width=40.0, height=40.0, web=1.0,
           holes=[Cutout(Circle(6.0), "vent", at=Centre(None, 20.0), why="airflow")])
    b.place(Part("u1"), at=Location(20.0, 20.0))
    plan = b.resolve()
    got = plan.cutouts_placed["vent"].centre
    assert not plan.findings, plan.findings
    assert got.y == pytest.approx(20.0)
    assert not plan.box("u1").overlaps(                             # it moved clear of the part
        Box(got.x - 3.0, got.y - 3.0, got.x + 3.0, got.y + 3.0))


def test_a_cutout_with_nowhere_legal_says_so():
    b = make_board()
    b.size(width=10.0, height=10.0, web=2.0,
           holes=[Cutout(Circle(9.0), "vent", at=Centre(None, 5.0), why="airflow")])
    with pytest.raises(PlacementCollision, match="vent"):
        b.resolve()


def test_a_slot_on_a_ring_runs_tangentially_unless_told():
    b = make_board()
    b.disc(diameter=40.0, web=1.0,
           holes=[Cutout(Slot(10.0, 2.0), "vent", at=Polar(14.0, Fraction(0.5)), why="airflow")])
    plan = b.resolve()
    placed = plan.cutouts_placed["vent"]
    assert not plan.findings, plan.findings
    assert placed.centre.y == pytest.approx(34.0, abs=0.05)         # due south of a centre at (20, 20)
    loop = Cutouts([list(placed.path)]).loops[0]                    # and running ACROSS the radius
    xs, ys = [p[0] for p in loop], [p[1] for p in loop]
    assert max(xs) - min(xs) == pytest.approx(10.0, abs=0.05)
    assert max(ys) - min(ys) == pytest.approx(2.0, abs=0.05)


def test_a_cutout_may_slide_round_a_ring():
    b = make_board()
    b.disc(diameter=40.0, web=1.0,
           holes=[Cutout(Circle(4.0), "vent", at=Polar(14.0, None), why="airflow")])
    plan = b.resolve()
    got = plan.cutouts_placed["vent"].centre
    assert not plan.findings, plan.findings
    assert got.distance(b.centre) == pytest.approx(14.0, abs=0.1)


# ------------------------------------------- a cutout placed by reference
def test_a_cutout_is_placed_relative_to_the_part_it_serves():
    """Move the connector and the slot moves with it: the script says what
    the hole is for, not where it is."""
    for y in (12.0, 24.0):
        b = make_board("u1")
        b.size(width=40.0, height=40.0,
               holes=[Cutout(Slot(17.0, 3.0), "ffc",
                             at=Centre(X(Part("u1")), Y(Part("u1"), 6.0)), why="the cable")])
        b.place(Part("u1"), at=Location(20.0, y))
        plan = b.resolve()
        assert plan.cutouts_placed["ffc"].centre.y == pytest.approx(y + 6.0, abs=0.05)
        assert plan.cutouts_placed["ffc"].centre.x == pytest.approx(20.0, abs=0.05)


def test_a_part_placed_against_a_cutout_waits_for_it():
    b = make_board("u1", "d1")
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Slot(17.0, 3.0), "ffc",
                         at=Centre(X(Part("u1")), Y(Part("u1"), 6.0)), why="the cable")])
    b.place(Part("u1"), at=Location(20.0, 12.0))
    b.place(Part("d1"), at=OnEdge(b.cutout("ffc").edge(side=Edge.SOUTH), along=Along.MID))
    plan = b.resolve()
    assert plan.box("d1").top > plan.cutouts_placed["ffc"].centre.y


def test_a_cutout_may_not_be_placed_against_a_searched_part():
    b = make_board("u1")
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Circle(4.0), "vent", at=Centre(X(Part("u1")), Y(Part("u1"), 8.0)), why="a")])
    b.place(Part("u1"))                                      # searched: no position yet
    with pytest.raises(ValueError, match="only FIXED and EDGE"):
        b.resolve()


def test_a_cutout_that_would_break_the_web_is_refused():
    b = make_board()
    b.size(width=40.0, height=40.0, web=2.0,
           holes=[Cutout(Circle(4.0), "vent", at=Location(2.5, 20.0), why="a")])
    with pytest.raises(PlacementCollision, match="web"):
        b.resolve()


def test_a_cutout_may_not_be_milled_through_a_part():
    b = make_board("u1")
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Circle(6.0), "vent", at=Location(20.0, 20.0), why="a")])
    b.place(Part("u1"), at=Location(20.0, 20.0))
    with pytest.raises(PlacementCollision, match="u1"):
        b.resolve()


def test_a_cutout_that_touches_the_outline_is_a_notch_not_a_hole():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Circle(6.0), "notch", at=Location(1.0, 20.0), why="a")])
    with pytest.raises(PlacementCollision, match="notch"):
        b.resolve()


# ------------------------------------------------------ the web check
def test_a_cutout_too_near_the_edge_is_a_finding():
    b = make_board(keep_going=True)
    b.size(width=40.0, height=40.0, web=1.5,
           holes=[Cutout(Circle(4.0), "vent", at=Location(2.5, 20.0), why="a")])
    plan = b.resolve()
    assert any("web" in f and "vent" in f for f in plan.findings), plan.findings


def test_a_cutout_with_room_round_it_is_not():
    b = make_board()
    b.size(width=40.0, height=40.0, web=1.5,
           holes=[Cutout(Circle(4.0), "vent", at=Location(20.0, 20.0), why="a")])
    assert not b.resolve().findings


def test_no_web_declared_is_no_web_check():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Circle(4.0), "vent", at=Location(2.1, 20.0), why="a")])
    assert not b.resolve().findings
    assert b.web == 0.0


def test_two_cutouts_too_near_each_other_is_a_finding():
    b = make_board(keep_going=True)
    b.size(width=40.0, height=40.0, web=2.0,
           holes=[Cutout(Circle(4.0), "a", at=Location(18.0, 20.0), why="x"),
                  Cutout(Circle(4.0), "b", at=Location(23.0, 20.0), why="y")])
    plan = b.resolve()
    assert any("web" in f for f in plan.findings), plan.findings


# ------------------------------------------ placing against a cutout
def _with_slot():
    b = make_board("u1")
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Slot(17.0, 3.0), "ffc", at=Location(20.0, 28.0), why="the cable")])
    return b


def test_a_part_sits_against_the_side_of_a_cutout_it_was_given():
    """side=NORTH is the hole's northern boundary, so the part sits above
    the slot, held off it by the keep-in, turned to face down into it."""
    b = _with_slot()
    run = b.cutout("ffc").edge(side=Edge.NORTH)
    assert run.facing == pytest.approx(180.0, abs=1.0)        # the item faces south, into the hole
    b.place(Part("u1"), at=OnEdge(run, along=Along.MID))
    plan = b.resolve()
    assert plan.box("u1").bottom == pytest.approx(26.5 - 0.5, abs=0.05)
    assert plan.box("u1").center.x == pytest.approx(20.0, abs=0.2)
    # the same turn the board's own south-facing edge gives: outward side pointing south
    assert plan.placements["u1"].rotation == pytest.approx(0.0, abs=1.0)


def test_the_two_sides_of_a_slot_are_opposite_stretches():
    b = _with_slot()
    north, south = b.cutout("ffc").edge(side=Edge.NORTH), b.cutout("ffc").edge(side=Edge.SOUTH)
    assert north.at(north.length / 2.0)[0].y == pytest.approx(26.5, abs=0.02)
    assert south.at(south.length / 2.0)[0].y == pytest.approx(29.5, abs=0.02)


def test_a_cutout_takes_side_and_refuses_facing():
    b = _with_slot()
    with pytest.raises(TypeError, match="side="):
        b.cutout("ffc").edge(facing=Edge.NORTH)


def test_a_cutout_that_was_never_declared_says_which_there_are():
    b = _with_slot()
    with pytest.raises(ValueError, match="ffc"):
        b.cutout("usb")


def test_a_raw_path_board_says_only_a_named_cutout_can_be_referred_to():
    b = make_board()
    b.size(width=40.0, height=40.0, holes=[SLOT])
    with pytest.raises(ValueError, match="named Cutout"):
        b.cutout("ffc")


def test_the_boards_own_edge_never_returns_a_cutouts():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Slot(17.0, 3.0), "ffc", at=Location(20.0, 28.0), why="a"),
                  Cutout(Circle(4.0), "vent", at=Location(10.0, 10.0), why="b")])
    for facing in (Edge.NORTH, Edge.SOUTH, Edge.EAST, Edge.WEST):
        (run,) = b.edges(facing)
        assert run.length == pytest.approx(40.0)


def test_each_cutout_offers_only_its_own_edges():
    b = make_board()
    b.size(width=40.0, height=40.0,
           holes=[Cutout(Slot(17.0, 3.0), "ffc", at=Location(20.0, 28.0), why="a"),
                  Cutout(Circle(8.0), "vent", at=Location(10.0, 10.0), why="b")])
    assert b.cutout("vent").edge(side=Edge.NORTH).length < math.pi * 8.0
    assert b.cutout("ffc").centre.y == pytest.approx(28.0, abs=0.02)


# --------------------------------------------------- runs off a cutout
def test_a_hole_is_walked_so_its_normals_point_into_it():
    """An item against a slot's northern boundary faces south, into the
    slot: the same turn OnBore makes at a bore."""
    o = Outline.of([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)], holes=[SLOT])
    (run,) = o.runs(Edge.SOUTH, within=20.0, loop=1)
    point, out = run.at(run.length / 2.0)
    assert point.y == pytest.approx(26.5, abs=0.02)      # the slot's TOP edge
    assert out == pytest.approx(180.0, abs=1.0)          # facing down, into the slot


def test_the_board_is_still_loop_zero():
    o = Outline.of([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)], holes=[SLOT])
    (north,) = o.runs(Edge.NORTH)
    assert north.length == pytest.approx(40.0) and north.at(0.0)[0].y == 0.0
    assert o.runs(Edge.NORTH) == o.runs(Edge.NORTH, loop=0)


def test_a_loop_that_is_not_there_is_refused():
    o = Outline.of([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)], holes=[SLOT])
    with pytest.raises(ValueError, match="1 cutout"):
        o.runs(Edge.NORTH, loop=2)


# -------------------------------------------------------------- the web
def test_the_gap_between_two_loops_is_their_shortest_distance():
    from placemat.cutouts import loop_gap
    inner = Cutouts([Circle(10.0).path_at(Location(20.0, 20.0))]).loops[0]
    outer = Cutouts([Path([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)])
                     .path_at(Location(20.0, 20.0))]).loops[0]
    assert loop_gap(inner, outer) == pytest.approx(15.0, abs=0.02)   # 20 to the wall, less the 5 radius


def test_two_loops_that_cross_have_no_gap():
    from placemat.cutouts import loop_gap
    a = Cutouts([Circle(10.0).path_at(Location(20.0, 20.0))]).loops[0]
    b = Cutouts([Circle(10.0).path_at(Location(24.0, 20.0))]).loops[0]
    assert loop_gap(a, b) == 0.0


def test_the_web_is_the_narrowest_gap_to_anything():
    board = Cutouts([Path([(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)])
                     .path_at(Location(20.0, 20.0))]).loops[0]
    holes = Cutouts([Circle(6.0).path_at(Location(20.0, 20.0)),       # 17 from the wall
                     Circle(4.0).path_at(Location(4.0, 20.0))])       # 2 from the wall
    web, which = holes.web_against([board])
    assert web == pytest.approx(2.0, abs=0.02) and which == 1


# ------------------------------------------------- the same on every board
@pytest.mark.parametrize("name,declare,area", DECLARE, ids=[d[0] for d in DECLARE])
def test_a_part_over_a_cutout_is_refused_whatever_the_board_is(name, declare, area):
    assert place_at(declare, 28.0) == "body box 18.00,26.00..22.00,30.00 is inside a cutout"


@pytest.mark.parametrize("name,declare,area", DECLARE, ids=[d[0] for d in DECLARE])
def test_a_cutout_holds_a_part_off_by_the_keep_in(name, declare, area):
    """The slot's top face is at 26.5 and the keep-in is 0.5, so a part whose
    body reaches 26.0 is the last one that fits."""
    assert place_at(declare, 23.9) is None                      # body to 25.9: 0.6 mm clear
    assert place_at(declare, 24.1) == "body box 18.00,22.10..22.00,26.10 is past the cutout's keep-in (0.50 mm)"


@pytest.mark.parametrize("name,declare,area", DECLARE, ids=[d[0] for d in DECLARE])
def test_a_cutout_is_board_a_part_cannot_use(name, declare, area):
    b = make_board()
    declare(b, [SLOT])
    plan = b.resolve()
    assert plan.occupancy.free_area(None) / 2.0 == pytest.approx(area - SLOT_AREA, rel=0.005)


# ------------------------------------------------------------ a round board
def test_a_disc_keeps_its_round_verbs_with_a_slot_in_it():
    """The cutout is an extra thing the board holds, not a different kind of
    board: the rim, the bore and the ring all still answer."""
    b = make_board("u1", "d1")
    b.disc(diameter=40.0, hole=6.0, holes=[SLOT])
    b.place(Part("u1"), at=OnRim(Edge.NORTH))
    b.place(Part("d1"), at=OnBore(Edge.WEST))
    plan = b.resolve()
    assert not plan.findings
    assert b.radius == 20.0 and b.bore == 3.0
    assert plan.box("u1").center.y < 5.0                        # up at the rim
    assert plan.shape.area == pytest.approx(math.pi * (400.0 - 9.0) - SLOT_AREA, rel=0.005)


def test_a_disc_with_the_same_cutouts_is_the_same_disc():
    a = Disc(Location(20.0, 20.0), 40.0, 6.0, holes=[SLOT])
    b = Disc(Location(20.0, 20.0), 40.0, 6.0, holes=[SLOT])
    assert a == b and hash(a) == hash(b)
    assert Disc(Location(20.0, 20.0), 40.0, 6.0) != a           # a solid one is not the same board


def test_a_disc_cutout_is_an_edge_the_runs_do_not_offer():
    """Runs come off the board's own outline, so a slot is not a stretch of
    edge to place along. The rim still is."""
    b = make_board()
    b.disc(diameter=40.0, holes=[SLOT])
    north = b.edge(facing=Edge.NORTH)
    assert north.length == pytest.approx(math.pi * 20.0 / 2.0, rel=0.02)


# ----------------------------------------- a round verb on a board with no rim
ROUND_VERBS = [
    ("OnRim", lambda b: b.place(Part("u1"), at=OnRim(Edge.EAST)), "OnEdge"),
    ("OnBore", lambda b: b.place(Part("u1"), at=OnBore(Edge.NORTH)), "OnEdge"),
    ("ring at the rim", lambda b: b.ring([Part("u1"), Part("d1")], radius=None), "radius"),
    ("board.radius", lambda b: b.radius, "board.box"),
    ("board.bore", lambda b: b.bore, "holes="),
]


@pytest.mark.parametrize("name,use,hint", ROUND_VERBS, ids=[v[0] for v in ROUND_VERBS])
def test_a_round_verb_on_a_shaped_board_says_what_to_use_instead(name, use, hint):
    """A script reaching for the rim of a board that has none is using the
    wrong verb, not finding a broken tool: it is told the one that does the
    same thing, never an attribute error from inside the placer."""
    b = make_board("u1", "d1")
    b.outline(Circle(40.0).path_at(Location(20.0, 20.0)), holes=[SLOT])
    with pytest.raises(ValueError) as e:
        use(b)
    assert "shaped board" in str(e.value) and hint in str(e.value)


def test_a_free_spoke_on_a_shaped_board_does_not_reach_for_a_bore():
    """Polar with only a bearing slides out along it. On a disc that starts
    at the bore; on a shaped board there is none to start from."""
    b = make_board("u1")
    b.outline(Circle(40.0).path_at(Location(20.0, 20.0)), holes=[SLOT])
    b.place(Part("u1"), at=Polar(None, Edge.EAST))
    plan = b.resolve()
    assert not plan.findings
    assert plan.box("u1").center.y == pytest.approx(20.0)       # out along the east spoke


# ---------------------------------------------------------------- the fab
def test_a_path_that_closes_on_itself_draws_no_leg_of_nothing():
    """A circle of arcs and a rounded slot both end where they started.
    Closing them again would put a zero-length segment on Edge.Cuts."""
    from placemat.cutouts import closes_itself
    assert closes_itself(Circle(10.0).path_at(Location(0.0, 0.0)))
    assert closes_itself(SLOT)
    assert not closes_itself([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])


def test_an_outline_still_carries_its_own_holes():
    """The shape a script declares owns its cutouts; nothing else has to
    know about them."""
    o = Outline.of(Circle(40.0).path_at(Location(20.0, 20.0)), holes=[SLOT])
    assert o.area == pytest.approx(math.pi * 400.0 - SLOT_AREA, rel=0.005)
    assert o.why_not(Box(18.0, 26.0, 22.0, 30.0), 0.5) == "inside a cutout"
    assert o.why_not(Box(18.0, 8.0, 22.0, 12.0), 0.5) is None
