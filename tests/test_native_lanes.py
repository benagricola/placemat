"""An escape's layout asks the board whether a lane's track or a via's site meets anything placed, thousands of times; the
native module answers from a grid of the board's pads and copper (native/src/lanes.rs). For tracks and vias of every
angle and size over parts, tracks, vias, pours, holes, a net tie and a rule area that forbids vias, the answer is the one
`Occupancy.copper_conflicts` and `Board._via_site_why` give, on the board itself and on the view a candidate makes of it.

The native module lays the escape out too (native/src/lane_layout.rs), when the search prices a candidate by the lanes it
blocks. For every kind of escape (a row turned across, at a corner, not at all, with vias that jog, pairs, a part turned
45, a pin drawn as two lands) on the board as it stands and with a part in each of many places, it lays out the lanes
Layouter.lay_out does, to the last bit, finds the same of them blocked, and asks about the same places.
`PLACEMAT_LANE_FUZZ=N` runs N random declarations in place of the default 48."""
import dataclasses
import math
import os
import random

import pytest

from placemat import layout
from placemat.copper import Pour, Track, Via
from placemat.layout import Board, _CopperContext, _LaneEnv
from placemat.occupancy import Occupancy, ban_shape, hole_shape
from placemat.placement import Placement
from placemat.score_delta import Delta
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Face, Location, Part
from tests.conftest import needs_native, parity
from tests.fixtures import board_geometry, footprint, pad
from tests.test_pad_on_pad_edge import _part, _tie

pytestmark = needs_native

F, B = CopperLayer.F, CopperLayer.B


def _track(net, a, b, width=0.2, layer=F):
    return layout._shape_of(Track(net, layer, width, Location(*a), Location(*b)))


def _via(net, at, drill=0.3, size=0.6):
    return [layout._shape_of(Via(net, Location(*at), drill, size)), hole_shape("", Location(*at), drill, net)]


def _pour(net, points, layer=F):
    return layout._shape_of(Pour(net, layer, tuple(points), 0.2))


def _scene(seed):
    """A board of parts (one turned), a net tie, and copper of every kind between them, as an occupancy."""
    rnd = random.Random(seed)
    tie = _tie("NT", ("A", "B"))
    parts = [footprint("P1", 20.0, 14.0, w=3.0, h=1.0, nets=("A", "C")),
             footprint("P2", 26.0, 19.0, w=3.0, h=1.0, nets=("B", "D"), rotation=30.0),
             footprint("P3", 14.0, 22.0, w=2.0, h=1.0, nets=("C", "D"), through=True),
             footprint("P4", 24.0, 26.0, w=2.0, h=1.0, nets=("A", "D"), face=Face.BACK)]
    fps = [tie] + parts
    occ = Occupancy(board_geometry(fps, width=40, height=40, extra_nets=("E",)), edge_margin=1.0,
                    settings=dataclasses.replace(Settings(), place_envelope="courtyard"))
    for fp in fps:
        occ.commit(fp, Placement(Location(20.25, 20.0), 0.0, Face.FRONT) if fp is tie
                   else Placement(fp.location, fp.rotation, fp.face))
    copper = []
    for k in range(14):
        x, y = rnd.uniform(10, 30), rnd.uniform(10, 30)
        a = rnd.uniform(0, 2 * math.pi)
        ln = rnd.uniform(0.3, 3.0)
        copper.append(_track("ABCDE"[k % 5], (x, y), (x + ln * math.cos(a), y + ln * math.sin(a)),
                             width=rnd.choice([0.1, 0.2, 0.4]), layer=rnd.choice([F, F, B])))
    for k in range(8):
        copper += _via("ABCDE"[k % 5], (rnd.uniform(10, 30), rnd.uniform(10, 30)), drill=0.3, size=rnd.choice([0.6, 0.8]))
    copper.append(_pour("E", [(12, 12), (16, 12), (16, 15), (12, 15)]))
    copper.append(ban_shape("via exclusion", ((17, 22), (20, 22), (20, 25), (17, 25)), None, ("A",)))
    occ.add_copper(copper)
    return occ


def _probes(seed, n, around=(9, 31, 9, 31)):
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        net = rnd.choice("ABCDEF")
        at = Location(rnd.uniform(around[0], around[1]), rnd.uniform(around[2], around[3]))
        if rnd.random() < 0.5:
            a = rnd.choice([0.0, math.pi / 4, math.pi / 2, rnd.uniform(0, 2 * math.pi)])
            ln = rnd.choice([0.0, 0.5, 2.0])
            out.append(Track(net, rnd.choice([F, F, B]), rnd.choice([0.1, 0.2, 0.3]), at,
                             Location(round(at.x + ln * math.cos(a), 6), round(at.y + ln * math.sin(a), 6))))
        else:
            out.append(Via(net, at, 0.3, rnd.choice([0.5, 0.6, 0.8])))
    return out


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_probe_meets_what_copper_conflicts_says_it_meets(seed):
    occ = _scene(seed)
    view = occ.lane_view()
    assert view is not None
    seen = {True: 0, False: 0}
    for op in _probes(seed, 400):
        shape = layout._shape_of(op)
        want = not occ.copper_conflicts(shape)
        seen[want] += 1
        assert view.copper_free(shape) == want, op
    assert seen[True] > 20 and seen[False] > 20, seen


def test_a_probe_on_a_net_tie_is_excused_as_python_excuses_it(monkeypatch):
    from collections import Counter
    excused = Counter()
    real = Occupancy._net_tie_exclusion

    def spy(self, *a, **kw):
        r = real(self, *a, **kw)
        excused[bool(r)] += 1
        return r
    monkeypatch.setattr(Occupancy, "_net_tie_exclusion", spy)
    occ = _scene(6)
    view = occ.lane_view()
    seen = Counter()
    for op in _probes(6, 1500, around=(19.0, 21.5, 19.2, 20.8)):
        shape = layout._shape_of(op)
        want = not occ.copper_conflicts(shape)
        seen[want] += 1
        assert view.copper_free(shape) == want, op
    assert excused[True] > 20 and excused[False] > 20, excused
    assert seen[True] > 20 and seen[False] > 20, seen


def test_a_probe_asked_while_the_board_is_held_gets_the_same_answer():
    occ = _scene(4)
    view = occ.lane_view()
    with occ.held():
        for op in _probes(4, 100):
            shape = layout._shape_of(op)
            assert view.copper_free(shape) == (not occ.copper_conflicts(shape)), op


@pytest.mark.parametrize("seed", [1, 2])
def test_a_via_site_is_free_where_via_site_why_finds_nothing(seed):
    occ = _scene(seed)
    board = Board(occ.geometry, edge_margin=1.0, keep_going=True)
    ctx = _CopperContext(board, occ)
    decl = type("Decl", (), {"ref": "ZZ"})()
    env = _LaneEnv(board, occ, decl, {}, Face.FRONT, context=ctx)
    assert env._native() is not None
    rnd = random.Random(seed)
    seen = {True: 0, False: 0}
    for _ in range(500):
        net = rnd.choice("ABCDEF")
        at = Location(rnd.uniform(5, 35), rnd.uniform(5, 35))
        size, drill = rnd.choice([(0.45, 0.2), (0.6, 0.3), (0.8, 0.4)])
        want = env.via_site(at, net, size, drill) is None
        seen[want] += 1
        assert env.via_free(at, net, size, drill) == want, (net, at, size)
    assert seen[True] > 20 and seen[False] > 20, seen


def test_a_candidate_view_is_asked_as_the_board_it_is():
    from tests.escape_fixtures import PD_NETS, board_with, qfn, small_part
    b = board_with([qfn(nets=PD_NETS), small_part("R1", "r1", ("VOUT", "SENSE"), cx=50.0, cy=50.0),
                    small_part("R2", "r2", ("SENSE", "PGOOD"), cx=40.0, cy=50.0)], keep_going=True, nets=("E",))
    for inst, at in (("pd", (30, 30)), ("r1", (50, 50)), ("r2", (40, 50))):
        b.place(Part(inst), at=Location(*at))
    plan = b.resolve()
    occ = plan.occupancy
    rnd = random.Random(5)
    occ.add_copper([_track("E", (26, 28), (34, 27), 0.2), _track("SENSE", (36, 33), (36, 38), 0.3)]
                   + _via("E", (31, 25)) + _via("VOUT", (24, 31)))
    item = b.geometry.footprint("R1")
    occ.lift({"R1"})
    delta = Delta(b, occ, item, plan.links, plan=plan)
    probes = [dataclasses.replace(op, net=op.net) for op in _probes(5, 300)]
    for _ in range(10):
        at = Placement(Location(rnd.uniform(24, 38), rnd.uniform(23, 37)), rnd.choice([0.0, 90.0]), Face.FRONT)
        view, geometries, copper = delta._view(at)
        native = view.lane_view()
        assert native is not None
        for op in probes:
            op = _moved(op, 20.0, 20.0)
            shape = layout._shape_of(op)
            assert native.copper_free(shape) == (not view.copper_conflicts(shape)), (at, op)


def test_a_via_site_on_a_candidate_view_is_judged_against_the_holes_it_moves():
    from tests.escape_fixtures import board_with
    th = dataclasses.replace(footprint("T1", 50.0, 50.0, w=3.0, h=1.0, nets=("VOUT", "SENSE"), through=True),
                             npth=((Location(50.0, 51.5), 0.8),))
    fixed = dataclasses.replace(footprint("T2", 36.0, 33.0, w=3.0, h=1.0, nets=("A", "B"), through=True),
                                npth=((Location(36.0, 34.4), 0.7),))
    b = board_with([qfn(nets=PD_NETS), th, fixed], keep_going=True)
    for inst, at in (("pd", (30, 30)), ("t1", (50, 50)), ("t2", (36, 33))):
        b.place(Part(inst), at=Location(*at))
    plan = b.resolve()
    occ = plan.occupancy
    occ.add_copper(_via("E", (33.0, 29.0)))
    item = b.geometry.footprint("T1")
    occ.lift({"T1"})
    delta = Delta(b, occ, item, plan.links, plan=plan)
    rnd = random.Random(3)
    seen = {True: 0, False: 0}
    for _ in range(12):
        at = Placement(Location(rnd.uniform(26, 38), rnd.uniform(26, 38)), rnd.choice([0.0, 90.0]), Face.FRONT)
        view, _, _ = delta._view(at)
        ctx = _CopperContext(b, view)
        env = _LaneEnv(b, view, type("Decl", (), {"ref": "ZZ"})(), {}, Face.FRONT, context=ctx)
        assert env._native() is not None
        for _ in range(60):
            where = Location(at.location.x + rnd.uniform(-3, 3), at.location.y + rnd.uniform(-3, 3))
            size, drill = rnd.choice([(0.45, 0.2), (0.6, 0.3), (0.8, 0.4)])
            want = env.via_site(where, "E", size, drill) is None
            seen[want] += 1
            assert env.via_free(where, "E", size, drill) == want, (at, where, size)
    assert seen[True] > 20 and seen[False] > 20, seen


def _moved(op, dx, dy):
    if isinstance(op, Track):
        return dataclasses.replace(op, start=Location(op.start.x + dx, op.start.y + dy),
                                   end=Location(op.end.x + dx, op.end.y + dy))
    return dataclasses.replace(op, at=Location(op.at.x + dx, op.at.y + dy))


# ------------------------------------------------------------------ a whole layout
from placemat.lanes import EscapeError, Layouter
from placemat.values import Corner, Edge, Net
from tests.escape_fixtures import PD_NETS, bypass_135, board_with, fan_board, one_pad, qfn, qfn56, small_part, CLEAR56, TRACK56


def _signature(laid):
    """A Python layout as the native one reports it: per lane (in order) its points, tracks, via, and whether it is blocked."""
    return [(n, [(p.x, p.y) for p in laid.lanes[n].points],
             [(t.start.x, t.start.y, t.end.x, t.end.y) for t in laid.lanes[n].tracks],
             (laid.lanes[n].via.at.x, laid.lanes[n].via.at.y) if laid.lanes[n].via else None, bool(laid.lanes[n].blocked))
            for n in laid.order]


def _both(board, occ, decl, placement=None, context=None):
    """(Python's layout, the native one, the boxes each asked about) of an escape on `occ`; a layout that cannot be laid
    out is "refused"."""
    pads, axis, lands, face = board._escape_parts(occ, decl, placement)
    mine = []
    for native in (False, True):
        asked = []
        env = _LaneEnv(board, occ, decl, pads, face, context=context, asked=asked)
        layouter = Layouter(decl, pads, axis, env, lands)
        if native:
            laid = env.lay_out(layouter, True)
            assert laid is not None, "the native module laid nothing out"
            got = "refused" if laid[0] else [(n, pts, [a + b for a, b in tracks], via, blocked)
                                             for n, pts, tracks, via, blocked in laid[3]]
        else:
            env._lane_view = None
            try:
                got = _signature(layouter.lay_out())
            except EscapeError:
                got = "refused"
        boxes = set()
        for a in asked:
            boxes.update(a.boxes() if not isinstance(a, Box) else [(a.left, a.top, a.right, a.bottom)])
        mine.append((got, sorted(boxes)))
    return mine


def _same(a, b, why):
    assert a[0] == b[0], why
    assert a[1] == b[1], why + " (the places asked about)"


def _fan(turned, extra=(), **kw):
    """The QFN-56 (turned 45 or not) with a pad part to move about, as a board and the part; `extra` parts are placed
    where they are drawn."""
    cap = dataclasses.replace(one_pad("C1", "c1", "GND", 20.0, 20.0, other=("BYP", 0.9, 0.0)),
                              npth=((Location(20.0, 21.2), 0.5),))
    peg = dataclasses.replace(one_pad("P1", "p1", "PEG", 22.6, 31.4), npth=((Location(23.3, 31.9), 0.6),))
    extra = (peg, *extra)
    if turned:
        b = board_with([qfn56(), cap, *extra], track=TRACK56, clearance=CLEAR56, keep_going=True, **kw)
        b.place(Part("mcu"), at=Location(30, 30), rotation=45)
    else:
        b = fan_board([cap, *extra], keep_going=True, **kw)
    b.place(Part("c1"), at=Location(20.0, 20.0))
    for fp in extra:
        b.place(Part(fp.inst), at=fp.location)
    return b, cap


def _scenes():
    """(a board with its escape declared and a pad part to move, where to look for trouble), by name."""
    out = []

    def add(name, make, window):
        out.append(pytest.param(make, window, id=name))
    window_west = (21.5, 27.5, 26.0, 36.0)
    for turn_name, turn in (("edge", Edge.NORTH), ("corner", Corner.NW), ("none", None)):
        for vias in ((), (46,), (45, 47)):
            if turn is None and vias:
                continue

            def make(turn=turn, vias=vias):
                b, cap = _fan(False)
                b.escape(Part("mcu"), [44, 45, 46, 47], turn=turn, vias=list(vias), why="west fan")
                return b, cap
            add("west-%s-%d" % (turn_name, len(vias)), make, window_west)

    def pairs():
        b, cap = _fan(False)
        b.escape(Part("mcu"), [44, 45, 46, 47], turn=Corner.NW, pairs=[(45, 46)], why="a pair")
        return b, cap
    add("west-pair", pairs, window_west)

    def sized():
        b, cap = _fan(False)
        b.escape(Part("mcu"), [45, 46], turn=Corner.SW, depth=0.7, run=1.2, chamfer=0.0, why="deep and square")
        return b, cap
    add("west-depth", sized, window_west)

    def wide():
        b, cap = _fan(False)
        b.escape(Part("mcu"), [44, 45, 46], turn=Edge.NORTH, vias=[45], widths={45: 0.25}, why="a wide lane")
        return b, cap
    add("west-width", wide, window_west)

    def tied():
        tie = dataclasses.replace(_tie("NT", ("N45", "N46")), location=Location(23.4, 28.0))
        b, cap = _fan(False, extra=(tie,))
        b.escape(Part("mcu"), [44, 45, 46, 47], turn=Corner.NW, vias=[45], why="beside a net tie")
        return b, cap
    add("west-tie", tied, (22.0, 26.5, 26.0, 33.0))

    def deep():
        b, cap = _fan(True)
        b.escape(Part("mcu"), [5, 6, 7], turn=Edge.SOUTH, depth=0.6, vias=[6], why="a part turned 45, a set depth")
        return b, cap
    add("turned-depth", deep, (28.0, 36.0, 28.0, 40.0))

    def corner_pin():
        from tests.test_escape_corner_pin import corner_qfn
        cap = one_pad("C1", "c1", "GND", 20.0, 20.0, other=("BYP", 0.9, 0.0))
        b = board_with([corner_qfn(), cap], keep_going=True)
        b.place(Part("pd"), at=Location(30, 30))
        b.place(Part("c1"), at=Location(20.0, 20.0))
        b.escape(Part("pd"), [24, 23, 22], turn=Edge.NORTH, vias=[23], why="a pin drawn as two lands")
        return b, cap
    add("corner-pin", corner_pin, (31.5, 38.0, 22.0, 29.0))

    def south():
        b, cap = _fan(False, via_size=0.45, via_drill=0.20)
        b.escape(Part("mcu"), [9, 10], vias=[9, 10], why="the south pins")
        return b, cap
    add("south-jog", south, (27.5, 33.0, 34.0, 40.0))
    for turn_name, turn in (("edge", Edge.SOUTH), ("corner", Corner.NE), ("corner-sw", Corner.SW)):
        for vias in ((), (6,)):
            def turned(turn=turn, vias=vias):
                b, cap = _fan(True)
                b.escape(Part("mcu"), [5, 6, 7], turn=turn, vias=list(vias), why="a part turned 45")
                return b, cap
            add("turned-%s-%d" % (turn_name, len(vias)), turned, (28.0, 36.0, 28.0, 40.0))

    def turned_none():
        b, cap = _fan(True)
        b.escape(Part("mcu"), [5, 6, 7], vias=[6], why="a part turned 45, straight")
        return b, cap
    add("turned-none", turned_none, (28.0, 36.0, 28.0, 40.0))
    return out


def _litter(occ, rnd, window):
    """Copper of every kind in the window, as a routed board has."""
    left, right, top, bottom = window
    shapes = []
    for k in range(10):
        x, y = rnd.uniform(left, right), rnd.uniform(top, bottom)
        a = rnd.uniform(0, 2 * math.pi)
        shapes.append(_track("ABCDE"[k % 5], (x, y), (x + 1.2 * math.cos(a), y + 1.2 * math.sin(a)), width=0.16,
                             layer=rnd.choice([F, F, B])))
    for k in range(4):
        shapes += _via("ABCDE"[k % 5], (rnd.uniform(left, right), rnd.uniform(top, bottom)), drill=0.2, size=0.45)
    if rnd.random() < 0.5:
        x, y = rnd.uniform(left, right), rnd.uniform(top, bottom)
        shapes.append(ban_shape("via exclusion", ((x, y), (x + 1.5, y), (x + 1.5, y + 1.5), (x, y + 1.5)), None, ("N45",)))
    occ.add_copper(shapes)


@pytest.mark.parametrize("seed", [1, pytest.param(2, marks=parity), pytest.param(3, marks=parity)])
@pytest.mark.parametrize("make,window", _scenes())
def test_a_native_layout_is_the_layout_python_makes(make, window, seed):
    rnd = random.Random(seed)
    b, cap = make()
    try:
        plan = b.resolve()
    except EscapeError:
        pytest.skip("the escape does not resolve with nothing beside it")
    occ = plan.occupancy
    decl = b._escapes[0]
    item = b.geometry.footprint("C1")
    occ.lift({"C1"})
    if seed > 1:
        _litter(occ, rnd, window)
    delta = Delta(b, occ, item, plan.links, plan=plan)
    left, right, top, bottom = window
    _same(*_both(b, occ, decl), "the board as it stands")
    refused = blocked = 0
    for k in range(30):
        at = Placement(Location(rnd.uniform(left, right), rnd.uniform(top, bottom)), rnd.choice([0.0, 90.0]), Face.FRONT)
        view, _, _ = delta._view(at)
        mine = _both(b, view, decl, context=_CopperContext(b, view))
        _same(*mine, "a pad part at %r" % (at,))
        refused += mine[0][0] == "refused"
        blocked += mine[0][0] != "refused" and any(lane[4] for lane in mine[0][0])
    assert refused + blocked > 0 or seed > 1, "no candidate blocked or refused the escape: the scene tests nothing"


@pytest.mark.parametrize("turned", [False, True])
def test_the_lanes_blocked_at_a_placement_of_the_part_are_counted_as_python_counts_them(turned, monkeypatch):
    from types import SimpleNamespace
    b, cap = _fan(turned)
    b.escape(Part("mcu"), [5, 6, 7] if turned else [44, 45, 46], turn=Edge.SOUTH if turned else Edge.NORTH,
             vias=[6] if turned else [45], why="the part is the candidate")
    b.settings = dataclasses.replace(b.settings, score_escape_lane=1.0)
    plan = b.resolve()
    occ = plan.occupancy
    mcu = b.geometry.footprint("mcu")
    occ.lift({"U1"})
    price = b._lane_pricer(occ, plan, SimpleNamespace(kind="part", item=mcu))

    def prices():
        rnd = random.Random(7)
        return [price(Placement(Location(rnd.uniform(26, 34), rnd.uniform(26, 34)), rnd.choice([0.0, 45.0, 90.0]),
                                Face.FRONT)) for _ in range(25)]
    laid = []
    real = _LaneEnv.lay_out
    monkeypatch.setattr(_LaneEnv, "lay_out", lambda self, *a, **k: laid.append(real(self, *a, **k)) or laid[-1])
    native = prices()
    assert len(laid) > 5 and all(got is not None for got in laid)
    monkeypatch.setattr(Occupancy, "lane_view", lambda self: None)
    assert native == prices()
    assert len(set(native)) > 1, native


ROWS = {"south": range(1, 15), "east": range(15, 29), "north": range(29, 43), "west": range(43, 57)}


def _random_scene(rnd):
    """A QFN-56 (turned 45 or not) with a random escape declared on one of its rows, and a pad part to move about: the board,
    or None where the declaration is refused or does not resolve."""
    turned = rnd.random() < 0.4
    via = rnd.choice([(0.45, 0.20), (0.5, 0.25), (0.6, 0.3)])
    cap = one_pad("C1", "c1", "GND", 20.0, 20.0, other=("BYP", 0.9, 0.0))
    kw = dict(track=TRACK56, clearance=CLEAR56, keep_going=True, via_size=via[0], via_drill=via[1])
    if turned:
        b = board_with([qfn56(), cap], **kw)
        b.place(Part("mcu"), at=Location(30, 30), rotation=45)
    else:
        b = board_with([qfn56(), cap], **kw)
        b.place(Part("mcu"), at=Location(30, 30))
    b.place(Part("c1"), at=Location(20.0, 20.0))
    row = list(ROWS[rnd.choice(sorted(ROWS))])
    n = rnd.randint(1, 5)
    first = rnd.randrange(0, len(row) - n + 1)
    pins = row[first:first + n]
    if rnd.random() < 0.5:
        pins = pins[::-1]
    opts = dict(turn=rnd.choice([None, Edge.NORTH, Edge.EAST, Edge.SOUTH, Edge.WEST, Corner.NE, Corner.NW, Corner.SE,
                                 Corner.SW]))
    if rnd.random() < 0.6:
        opts["vias"] = rnd.sample(pins, rnd.randint(1, len(pins)))
    if rnd.random() < 0.3:
        opts["depth"] = rnd.choice([0.3, 0.6, 1.0])
    if rnd.random() < 0.3:
        opts["run"] = rnd.choice([0.5, 1.0, 2.0])
    if rnd.random() < 0.3:
        opts["widths"] = {rnd.choice(pins): rnd.choice([0.1, 0.2, 0.3])}
    if rnd.random() < 0.3:
        opts["chamfer"] = rnd.choice([0.0, 0.1, 0.3])
    if len(pins) > 1 and opts["turn"] is not None and rnd.random() < 0.3:
        order = sorted(pins, key=lambda p: pins.index(p))
        k = rnd.randrange(len(order) - 1)
        opts["pairs"] = [(order[k], order[k + 1])]
    try:
        b.escape(Part("mcu"), pins, why="random", **opts)
        b.resolve()
    except (ValueError, EscapeError):
        return None
    return b, (turned, pins, opts)


@pytest.mark.parametrize("seed", range(int(os.environ.get("PLACEMAT_LANE_FUZZ", "48"))))
def test_a_native_layout_is_the_layout_python_makes_for_any_declaration(seed):
    rnd = random.Random(1000 + seed)
    made = _random_scene(rnd)
    if made is None:
        pytest.skip("the declaration is refused or does not resolve")
    b, what = made
    plan = b.resolve()
    occ = plan.occupancy
    decl = b._escapes[0]
    item = b.geometry.footprint("C1")
    occ.lift({"C1"})
    delta = Delta(b, occ, item, plan.links, plan=plan)
    _same(*_both(b, occ, decl), "the board as it stands %r" % (what,))
    for _ in range(12):
        at = Placement(Location(rnd.uniform(20.0, 40.0), rnd.uniform(20.0, 40.0)), rnd.choice([0.0, 90.0]), Face.FRONT)
        view, _, _ = delta._view(at)
        _same(*_both(b, view, decl, context=_CopperContext(b, view)), "a pad part at %r, %r" % (at.location, what))


def test_without_the_native_module_a_candidate_is_priced_as_with_it(monkeypatch):
    from placemat import geometry
    from types import SimpleNamespace
    b, cap = _fan(False)
    b.escape(Part("mcu"), [44, 45, 46, 47], turn=Corner.NW, vias=[45], why="west fan")
    b.settings = dataclasses.replace(b.settings, score_escape_lane=1.0)
    plan = b.resolve()
    occ = plan.occupancy
    item = b.geometry.footprint("C1")
    occ.lift({"C1"})
    rnd = random.Random(11)
    spots = [Placement(Location(rnd.uniform(21.5, 27.5), rnd.uniform(26.0, 36.0)), rnd.choice([0.0, 90.0]), Face.FRONT)
             for _ in range(30)]

    def counts():
        delta = Delta(b, occ, item, plan.links, plan=plan)
        return [b._lanes_blocked_each(delta._view(at)[0], plan) for at in spots]
    with_native = [{k: v[0] for k, v in each.items()} for each in counts()]
    monkeypatch.setattr(geometry, "_native", None)
    without = [{k: v[0] for k, v in each.items()} for each in counts()]
    assert with_native == without
    assert any(n for each in with_native for n in each.values())
