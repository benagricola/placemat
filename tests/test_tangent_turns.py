"""Turns.TANGENT / Tangent(...) and a radial band, Polar((r_min, r_max), None, about=): a searched
item whose turn at each spot is taken from the spot's bearing about a centre. Pure: synthetic boards."""
import math
import time

import pytest

from placemat import placer
from placemat.cutouts import Circle, Path
from placemat.layout import Board
from placemat.placer import scan
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import (Bearing, Cell, Cutout, Edge, Face, Location, Near, Part, Pin, Polar, Tangent, Turns)
from tests.fixtures import board_geometry, footprint

C = 26.5                                  # the disc's centre, both axes
R = 26.5
BAND = (12.0, 19.0)


def _cell(k, link=None):
    """Cell `c<k>`: a 6 x 2 member `w` (pads at its ends, along its local X) and a marker `m` 2.5 mm out
    along its local +Y, which is the side that faces out unless the cell declares another."""
    nets = ("L%d" % k, "M%d" % k) if link is None else (link, "M%d" % k)
    return [footprint("W%d" % k, 70.0, 10.0 + 8 * k, w=6, h=2, inst="c%d.w" % k, nets=nets, cell="c%d" % k),
            footprint("K%d" % k, 70.0, 12.5 + 8 * k, w=1, h=1, inst="c%d.m" % k, nets=("N%d" % k, "O%d" % k),
                      cell="c%d" % k)]


def _board(n=3, how="disc", settings=None, faces=None, extra=(), link=None):
    fps = [fp for k in range(n) for fp in _cell(k, link)] + list(extra)
    geom = board_geometry(fps, cells=["c%d" % k for k in range(n)], width=80, height=80, faces=faces)
    b = Board(geom, edge_margin=0.4, keep_going=True, **({"settings": settings} if settings else {}))
    if how == "disc":
        b.disc(2 * R)
    else:
        b.outline(_disc_with_an_arm())
    return b


def _disc_with_an_arm():
    a0 = math.asin(4.0 / R)
    pts = [(C + R * math.cos(t), C + R * math.sin(t))
           for t in (a0 + k * math.radians(3.0) for k in range(int((2 * math.pi - 2 * a0) / math.radians(3.0)) + 1))]
    pts.append((C + R * math.cos(2 * math.pi - a0), C - 4.0))
    pts += [(C + 29.5, C - 4.0), (C + 29.5, C + 4.0)]
    return pts


CENTRE = Location(C, C)


def _bearing_of(point, centre=CENTRE):
    return math.degrees(math.atan2(point.x - centre.x, centre.y - point.y)) % 360.0


def _off(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _tangent_error(plan, k, centre=CENTRE):
    """Degrees between the long side of cell `k`'s member and the tangent at the cell's bearing."""
    p1, p2 = plan.occupancy.pad_location("W%d" % k, "1"), plan.occupancy.pad_location("W%d" % k, "2")
    along = math.degrees(math.atan2(p2.x - p1.x, p1.y - p2.y)) % 180.0           # the long side's bearing
    tangent = (_bearing_of(plan.box("c%d" % k).center, centre) + 90.0) % 180.0
    return _off(along * 2, tangent * 2) / 2.0


def _outward(plan, k):
    """Whether cell `k`'s marker lies further from the centre than its member: the +Y side faces out."""
    m, w = plan.occupancy.items["K%d" % k].body.center, plan.occupancy.items["W%d" % k].body.center
    return m.distance(CENTRE) > w.distance(CENTRE)


def _placed(plan, n):
    assert not [f for f in plan.findings if "unplaced" in f.kind], plan.findings
    return [k for k in range(n) if plan.placement("c%d" % k) is not None]


# ------------------------------------------------------------------ in a band, on a disc

@pytest.mark.parametrize("how", ["disc", "outline"])
def test_a_cell_in_a_band_lies_tangent_at_its_bearing_with_its_outward_side_out(how):
    b = _board(3, how)
    for k in range(3):
        b.place(Cell("c%d" % k), at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT)
    plan = b.resolve()
    assert _placed(plan, 3) == [0, 1, 2]
    for k in range(3):
        assert _tangent_error(plan, k) <= 6.0, (k, _tangent_error(plan, k))       # half the default 10 degree bin
        assert _outward(plan, k), k
        assert BAND[0] - 0.01 <= plan.box("c%d" % k).center.distance(CENTRE) <= BAND[1] + 0.01


def test_a_cell_in_a_band_of_an_outline_is_turned_about_about_not_the_boxs_centre():
    b = _board(3, "outline")
    assert abs(b.centre.x - C) > 1.0                      # the arm puts the box's centre off the disc's
    for k in range(3):
        b.place(Cell("c%d" % k), at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT)
    plan = b.resolve()
    assert all(_tangent_error(plan, k, CENTRE) <= 6.0 for k in range(3))
    assert any(_tangent_error(plan, k, b.centre) > 6.0 for k in range(3))     # not tangent about the wrong centre


def test_items_with_nothing_to_seed_them_share_the_turn():
    b = _board(3)
    for k in range(3):
        b.place(Cell("c%d" % k), at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT)
    plan = b.resolve()
    bearings = sorted(_bearing_of(plan.box("c%d" % k).center) for k in range(3))
    gaps = [(bearings[(i + 1) % 3] - bearings[i]) % 360.0 for i in range(3)]
    assert all(abs(g - 120.0) < 30.0 for g in gaps), bearings


def test_a_declared_outward_side_is_the_one_turned_out():
    """The cell's marker is local +Y; declared outward = east, the east side faces out instead."""
    faces = {"c0": {"outward": Edge.EAST.value}}
    b = _board(1, faces=faces)
    b.place(Cell("c0"), at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT)
    plan = b.resolve()
    assert _placed(plan, 1) == [0]
    p1, p2 = plan.occupancy.pad_location("W0", "1"), plan.occupancy.pad_location("W0", "2")
    # pad 2 is at local east: it is the further out one now, and the member's long side is radial
    assert p2.distance(CENTRE) > p1.distance(CENTRE) + 3.0


def test_a_back_face_cell_is_turned_out_too():
    b = _board(1)
    b.place(Cell("c0"), at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT, face=Face.BACK)
    plan = b.resolve()
    assert _placed(plan, 1) == [0]
    assert _outward(plan, 0)
    assert _tangent_error(plan, 0) <= 6.0


def test_quarters_add_the_two_quarter_turns():
    b = _board(1)
    b.place(Cell("c0"), at=Polar(BAND, None, about=CENTRE), rotations=Tangent(quarters=True))
    t = b._intents[-1].tangent
    assert t.quarters and t.about is None
    from placemat.placer import BearingTurns
    bt = BearingTurns(CENTRE, lambda bearing: (180.0 - bearing) % 360.0, 10.0, quarters=True)
    at = bt.at(C, C - 15.0)                               # due north of the centre: bearing 0
    assert len(at) == 4 and at[0] == 175.0 and set(at) == {175.0, 265.0, 85.0, 355.0}     # the bin 0 to 10 turns as its middle, 5
    assert bt.at(C, C + 15.0)[0] == 355.0                 # due south, 180 to 190: turned out as 185 is


def test_tangent_about_a_value_agrees_with_the_polars_about():
    a = _board(1, "outline")
    a.place(Cell("c0"), at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT)
    b = _board(1, "outline")
    b.place(Cell("c0"), at=Polar(BAND, None, about=CENTRE), rotations=Tangent(about=CENTRE))
    pa, pb = a.resolve(), b.resolve()
    assert pa.placement("c0") == pb.placement("c0")


def test_the_bin_is_a_setting():
    wide = _board(1, settings=Settings(place_tangent_bin=90.0))
    wide.place(Cell("c0"), at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT)
    plan = wide.resolve()
    assert _tangent_error(plan, 0) <= 50.0
    fine = _board(1, settings=Settings(place_tangent_bin=2.0))
    fine.place(Cell("c0"), at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT)
    assert _tangent_error(fine.resolve(), 0) <= 2.0


@pytest.mark.parametrize("bad", [0.0, -5.0, 361.0])
def test_a_bin_that_cannot_cut_the_circle_is_refused(bad):
    from placemat.placer import BearingTurns
    with pytest.raises(ValueError, match="tangent_bin"):
        BearingTurns(CENTRE, lambda bearing: bearing, bad)


def test_a_bin_that_does_not_divide_the_circle_is_rounded_to_one_that_does():
    from placemat.placer import BearingTurns
    bt = BearingTurns(CENTRE, lambda bearing: bearing, 7.0)
    assert bt.n == 51 and bt.width == pytest.approx(360.0 / 51)         # round(360 / 7) equal bins


# ------------------------------------------------------------------ the band

def test_a_band_keeps_the_item_inboard_of_a_rim_keepout():
    """A keepout ring over the outer 2.5 mm and a link to a part beyond it: the band holds the cell short."""
    ring = [(C + r * math.cos(t), C + r * math.sin(t)) for r in (R - 0.1,) for t in
            (math.radians(a) for a in range(0, 358, 2))]
    inner = [(C + (R - 2.6) * math.cos(t), C + (R - 2.6) * math.sin(t)) for t in
             (math.radians(a) for a in range(356, -1, -2))]
    anchor = footprint("A1", C + 20.0, C, w=2, h=1, inst="a1", nets=("L0", "GND"))
    b = _board(1, extra=[anchor], link="L0")
    b.place(Part("a1"), at=Location(C + 20.0, C))
    b.keepout(Path(ring + inner), "seal", at=CENTRE, why="the seal rim")
    b.place(Cell("c0"), at=Polar((10.0, 21.0), None, about=CENTRE), rotations=Turns.TANGENT)
    plan = b.resolve()
    assert _placed(plan, 1) == [0]
    reach = plan.box("c0")
    assert max(math.hypot(x - C, y - C) for x in (reach.left, reach.right) for y in (reach.top, reach.bottom)) < R - 2.5
    assert plan.box("c0").center.distance(CENTRE) <= 22.0


def test_a_spoke_segment_slides_within_its_range():
    b = _board(1)
    b.place(Cell("c0"), at=Polar((8.0, 14.0), 90.0, about=CENTRE))
    plan = b.resolve()
    c = plan.box("c0").center
    assert _off(_bearing_of(c), 90.0) < 1.0
    assert 8.0 - 0.01 <= c.distance(CENTRE) <= 14.0 + 0.01


@pytest.mark.parametrize("radius", [(5.0, 5.0), (9.0, 4.0), (-1.0, 4.0), (1.0, 2.0, 3.0), ("a", "b")])
def test_a_bad_radius_range_is_refused(radius):
    with pytest.raises((ValueError, TypeError)):
        Polar(radius, None)


def test_a_radius_range_with_a_bearing_of_two_points_is_refused():
    b = _board(1)
    with pytest.raises(TypeError, match="radius"):
        b.place(Cell("c0"), at=Polar((5.0, 9.0), Bearing(Part("c0.w"), Part("c0.m"))))


def test_a_radius_range_is_not_a_cutouts_place():
    with pytest.raises((ValueError, TypeError), match="band|range|radius"):
        b = _board(1)
        b.cutout(Cutout(Circle(2.0), "hole", at=Polar((5.0, 9.0), 30.0))) if hasattr(b, "cutout") else \
            b.disc(40.0, holes=[Cutout(Circle(2.0), "hole", at=Polar((5.0, 9.0), 30.0))])
        b.resolve()


# ------------------------------------------------------------------ other searched places

def test_a_seeded_cell_is_turned_to_its_bearing_about_the_board_centre():
    anchor = footprint("A1", C + 14.0, C - 6.0, w=2, h=1, inst="a1", nets=("L0", "GND"))
    b = _board(1, extra=[anchor], link="L0")
    b.place(Part("a1"), at=Location(C + 14.0, C - 6.0))
    b.place(Cell("c0"), rotations=Turns.TANGENT)
    plan = b.resolve()
    assert _placed(plan, 1) == [0]
    assert _tangent_error(plan, 0) <= 6.0                 # a link may favour the half turn, so not asked outward


def test_a_near_hint_takes_tangent_turns():
    b = _board(1)
    b.place(Cell("c0"), at=Near(Location(C + 10.0, C + 8.0), radius=3.0), rotations=Turns.TANGENT)
    plan = b.resolve()
    assert _placed(plan, 1) == [0]
    assert _tangent_error(plan, 0) <= 6.0 and _outward(plan, 0)


def test_a_part_in_a_band_is_turned_too():
    fps = [footprint("R1", 70.0, 10.0, w=4, h=1.5, inst="r1", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=80, height=80), edge_margin=0.4, keep_going=True)
    b.disc(2 * R)
    b.place(Part("r1"), at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT)
    plan = b.resolve()
    c = plan.box("r1").center
    p1, p2 = plan.occupancy.pad_location("R1", "1"), plan.occupancy.pad_location("R1", "2")
    along = math.degrees(math.atan2(p2.x - p1.x, p1.y - p2.y)) % 180.0
    assert _off(along * 2, ((_bearing_of(c) + 90.0) % 180.0) * 2) / 2.0 <= 6.0


# ------------------------------------------------------------------ refusals

@pytest.mark.parametrize("at", [
    Location(C + 10.0, C), Pin(Part("c0.w"), C + 10.0, C), Polar(14.0, 30.0, about=CENTRE),
    Polar(14.0, None, about=CENTRE), Polar(None, 30.0, about=CENTRE), Polar((8.0, 14.0), 30.0, about=CENTRE)])
def test_tangent_turns_are_refused_where_the_spot_is_not_searched(at):
    b = _board(1)
    with pytest.raises((ValueError, TypeError), match="tangent|Tangent"):
        b.place(Cell("c0"), at=at, rotations=Turns.TANGENT)


def test_tangent_turns_are_refused_with_a_declared_rotation_and_on_a_block_and_on_the_rim():
    from placemat.values import OnEdge, OnRim
    b = _board(1)
    with pytest.raises(ValueError, match="rotation"):
        b.place(Cell("c0"), at=Polar(BAND, None, about=CENTRE), rotation=90, rotations=Turns.TANGENT)
    with pytest.raises((ValueError, TypeError), match="tangent|Tangent"):
        b.place(Cell("c0"), at=OnEdge(b.edge(facing=Edge.NORTH)), rotations=Turns.TANGENT)
    with pytest.raises((ValueError, TypeError), match="tangent|Tangent"):
        b.place(Cell("c0"), at=OnRim(30.0), rotations=Turns.TANGENT)


# ------------------------------------------------------------------ the scan

def _scan_board():
    b = _board(1)
    b.place(Cell("c0"), at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT)
    return b


def test_native_and_python_sweeps_choose_the_same_spot_and_try_the_same_candidates(monkeypatch):
    if not placer.NATIVE_SWEEP:
        pytest.skip("no native sweep")
    results = []
    for native in (True, False):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", native)
        b = _board(2)
        for k in range(2):
            b.place(Cell("c%d" % k), at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT)
        plan = b.resolve()
        results.append([(plan.placement("c%d" % k), [s.note for s in plan.steps if s.item == "c%d" % k])
                        for k in range(2)])
    assert results[0] == results[1]


def test_a_tangent_scan_judges_half_the_candidates_of_a_four_turn_scan(monkeypatch):
    import dataclasses
    b = _scan_board()
    plan = b.resolve()
    occ = plan.occupancy
    monkeypatch.setattr(occ, "settings", dataclasses.replace(occ.settings, place_coarse_from=1e9))   # one pass over the grid
    item = b._intents[-1].item
    from placemat.placer import BearingTurns
    bt = BearingTurns(CENTRE, lambda bearing: (180.0 - bearing) % 360.0, 10.0)
    hint = Placement(Location(C, C - 15.0), 0.0, Face.FRONT)
    ring = lambda x, y: BAND[0] <= math.hypot(x - C, y - C) <= BAND[1]
    pull = lambda p: abs(p.location.x - C) * 0.01 + abs(p.location.y - C) * 0.013       # a score, so no early stop
    tangent = scan(occ, item, hint, 12.0, 0.5, None, 0.2, score=pull, turns_at=bt, within=ring)
    four = scan(occ, item, hint, 12.0, 0.5, (0, 90, 180, 270), 0.2, score=pull, within=ring)
    assert tangent.chosen is not None and four.chosen is not None
    assert tangent.tried * 2 == four.tried


def test_a_spots_turns_are_the_ones_of_its_bin():
    from placemat.placer import BearingTurns
    bt = BearingTurns(CENTRE, lambda bearing: (180.0 - bearing) % 360.0, 10.0)
    assert len(bt.turns) == 36                                   # one per bin; the half turn is another bin's outward turn
    for bearing in (0.0, 4.9, 5.1, 90.0, 123.0, 359.0):
        x, y = C + 10.0 * math.sin(math.radians(bearing)), C - 10.0 * math.cos(math.radians(bearing))
        first, half = bt.at(x, y)
        assert _off((180.0 - first) % 360.0, bearing) <= 5.0 + 1e-6      # outward side within half a bin of the bearing
        assert _off(first, half) == pytest.approx(180.0)
    assert bt.at(C, C)[0] == bt.at(C, C - 1.0)[0]                # the centre itself reads as bearing 0


def test_the_outward_turn_is_preferred_to_the_half_turn_when_both_cost_the_same():
    from placemat.placer import BearingTurns
    bt = BearingTurns(CENTRE, lambda bearing: (180.0 - bearing) % 360.0, 10.0, quarters=True)
    x, y = C + 10.0, C
    first = bt.at(x, y)[0]
    assert bt.tie(Placement(Location(x, y), first, Face.FRONT)) < bt.tie(
        Placement(Location(x, y), (first + 180.0) % 360.0, Face.FRONT))


def test_timing_against_the_four_turn_search():
    """Reported, not bounded tightly: a band cell's scan against the same cell on the four right angles."""
    times = {}
    for label, kw in (("tangent", {"rotations": Turns.TANGENT}), ("four", {"rotations": (0, 90, 180, 270)})):
        b = _board(3)
        for k in range(3):
            b.place(Cell("c%d" % k), at=Polar(BAND, None, about=CENTRE), **kw)
        t0 = time.perf_counter()
        plan = b.resolve()
        times[label] = time.perf_counter() - t0
        assert _placed(plan, 3) == [0, 1, 2]
    print("tangent %.2fs, four turns %.2fs" % (times["tangent"], times["four"]))
    assert times["tangent"] < 6.0 * times["four"] + 2.0


# ------------------------------------------------------------------ Face.EITHER

def _either_board(n=1, front_blocked=False, faces=None, **kw):
    from placemat.values import CopperLayer
    b = _board(n, faces=faces, **kw)
    if front_blocked:
        b.keepout(Circle(60.0), "front only", at=CENTRE, excludes=("parts",), layers=(CopperLayer.F,),
                  why="kept off the front")
    return b


def _either(b, n=1):
    for k in range(n):
        b.place(Cell("c%d" % k), face=Face.EITHER, at=Polar(BAND, None, about=CENTRE),
                rotations=Tangent(about=CENTRE, quarters=True))
    return b.resolve()


def test_either_with_tangent_turns_lies_tangent_and_outward_on_the_front():
    plan = _either(_either_board(3), 3)
    assert _placed(plan, 3) == [0, 1, 2]
    for k in range(3):
        assert plan.placement("c%d" % k).face is Face.FRONT
        assert _tangent_error(plan, k) <= 6.0 and _outward(plan, k)


def test_either_with_tangent_turns_forced_to_the_back_lies_tangent_and_outward_as_seen_from_the_front():
    pinned = _either_board(1, front_blocked=True)
    pinned.place(Cell("c0"), face=Face.FRONT, at=Polar(BAND, None, about=CENTRE), rotations=Turns.TANGENT)
    assert pinned.resolve().placement("c0") is None
    plan = _either(_either_board(3, front_blocked=True), 3)
    assert _placed(plan, 3) == [0, 1, 2]
    for k in range(3):
        assert plan.placement("c%d" % k).face is Face.BACK
        assert _tangent_error(plan, k) <= 6.0 and _outward(plan, k), k
        assert BAND[0] - 0.01 <= plan.box("c%d" % k).center.distance(CENTRE) <= BAND[1] + 0.01


def test_either_on_the_back_turns_a_declared_east_side_out():
    """Mirrored, the declared east side is on the west until turned: the back's turn is not the front's."""
    plan = _either(_either_board(1, front_blocked=True, faces={"c0": {"outward": Edge.EAST.value}}))
    assert plan.placement("c0").face is Face.BACK
    p1, p2 = plan.occupancy.pad_location("W0", "1"), plan.occupancy.pad_location("W0", "2")
    assert p2.distance(CENTRE) > p1.distance(CENTRE) + 3.0


def test_either_with_tangent_turns_native_and_python_agree(monkeypatch):
    if not placer.NATIVE_SWEEP:
        pytest.skip("no native sweep")
    out = []
    for native in (True, False):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", native)
        plan = _either(_either_board(2, front_blocked=True), 2)
        out.append([(plan.placement("c%d" % k), [s.note for s in plan.steps if s.item == "c%d" % k])
                    for k in range(2)])
    assert out[0] == out[1]


def test_either_with_tangent_turns_replays_the_face_and_the_turn():
    first = _either(_either_board(2, front_blocked=True), 2)
    again = _either_board(2, front_blocked=True)
    for k in range(2):
        again.place(Cell("c%d" % k), face=Face.EITHER, at=Polar(BAND, None, about=CENTRE),
                    rotations=Tangent(about=CENTRE, quarters=True))
    again = again.resolve(reuse=first.reuse)
    assert again.reuse["reused"] == len(first.reuse["steps"])
    for k in range(2):
        assert again.placement("c%d" % k) == first.placement("c%d" % k)
        assert again.placement("c%d" % k).face is Face.BACK


def test_either_with_a_band_from_the_centre_out_and_tangent_turns():
    b = _either_board(2)
    for k in range(2):
        b.place(Cell("c%d" % k), face=Face.EITHER, at=Polar((0.0, R - 3.0), None, about=CENTRE),
                rotations=Tangent(about=CENTRE, quarters=True))
    plan = b.resolve()
    assert _placed(plan, 2) == [0, 1]
