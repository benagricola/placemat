"""The Python twin of the pin map study's core, its own parts: the random stream, the crossing weights, the background
grid, the matching, the incremental tally (a move priced as the whole total would price it), the order windows are
ranked in, the reserved empty slots, the index checks and the counted clock."""
from dataclasses import replace
import random

import pytest

from placemat.pinmap_core import Problem, params_of, problem_of
from placemat.pinmap_geom import Pose
from placemat import pinmap_twin
from placemat.pinmap_twin import (CELL_NM, Background, Clock, Scorer, SplitMix64, Tally, cells, crossing, hungarian,
                                  posed_wires, segments, total_order)
from placemat.ratsnest import _cross_nm
from tests.pinmap_boards import input_of, point_pad, quad, reversed_four, settings

W = (5.0, 3.0, 0.25, 0.25, 0.005, 1.0)      # pair, impedance, plane, length, bend, group


def test_the_random_stream_is_splitmix64():
    r = SplitMix64(1234567)
    assert (r.next(), r.next()) == (6457827717110365317, 3203168211198807973)
    assert 0 <= r.unit() < 1 and 0 <= r.below(7) < 7


def test_a_crossing_counts_one_more_for_a_pair_or_a_controlled_impedance_and_the_plane_weight_for_a_plane():
    assert crossing(W, 0, 0) == 1.0
    assert crossing(W, 0, 1) == 5.0 and crossing(W, 2, 0) == 3.0 and crossing(W, 1, 2) == 5.0
    assert crossing(W, 3, 1) == 0.25


def test_the_background_counts_the_wires_a_path_crosses_and_drops_a_weightless_plane():
    nm = lambda v: int(round(v * 1e6))
    wires = [(0, nm(5), 0, nm(5), nm(10)), (1, nm(7), 0, nm(7), nm(10)), (3, nm(8), 0, nm(8), nm(10))]
    segs = segments([((0.0, 5.0), (10.0, 5.0))])
    assert Background(wires, (5.0, 3.0, 0.0, 0.0, 0.0)).cross(0, segs) == (6.0, 2)
    assert Background(wires, (5.0, 3.0, 0.5, 0.0, 0.0)).cross(0, segs) == (6.5, 3)


def seg(ax, ay, bx, by):
    return (ax, ay, bx, by, min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def test_a_long_diagonal_is_filed_only_in_the_cells_it_passes_through():
    got = cells(seg(0, 0, 20_000_000, 20_000_000))
    assert len(got) <= 31 and all((k, k) in got for k in range(10))
    assert cells(seg(-1_000_000, 5_000_000, 9_000_000, 5_000_000)) == [(x, 2) for x in range(-1, 5)]


def test_the_grid_finds_every_crossing_a_full_scan_finds_and_adds_them_in_wire_order():
    w = (5.0, 3.0, 0.7, 0.25, 0.005, 1.0)
    r = SplitMix64(11)
    c = lambda lo, hi: lo + r.next() % (hi - lo)
    wires = []
    for k in range(300):
        ax, ay = c(-40_000_000, 40_000_000), c(-40_000_000, 40_000_000)
        ax = int(ax / CELL_NM) * CELL_NM if k % 10 == 0 else ax           # some on cell lines exactly, some long
        bx, by = (ax, ay + c(-30_000_000, 30_000_000)) if k % 5 == 0 else \
            (ax + c(-30_000_000, 30_000_000), int(ay / CELL_NM) * CELL_NM)
        wires.append((k % 4, ax, ay, bx, by))
    bg = Background(wires, w)
    for _ in range(200):
        ax, ay = c(-40_000_000, 40_000_000), c(-40_000_000, 40_000_000)
        s = seg(ax, ay, ax + c(-30_000_000, 30_000_000), ay + c(-30_000_000, 30_000_000))
        total, count = 0.0, 0
        for t in wires:
            if _cross_nm(s[0], s[1], s[2], s[3], t[1], t[2], t[3], t[4]):
                total += crossing(w, 1, t[0])
                count += 1
        assert bg.cross(1, [s]) == (total, count)


def test_the_inlined_crossing_test_is_the_ratsnests():
    # short segments on a small grid of whole nanometres: many touch, share an end or lie along each other
    r = random.Random(3)
    c = lambda: r.randint(0, 6) * 1000
    for _ in range(4000):
        s, t = seg(c(), c(), c(), c()), seg(c(), c(), c(), c())
        if t[6] < s[4] or s[6] < t[4] or t[7] < s[5] or s[7] < t[5]:
            continue
        assert pinmap_twin._crosses(s, t) == _cross_nm(*s[:4], *t[:4])


def test_the_matching_is_the_cheapest_and_refuses_what_cannot_be_matched():
    inf = float("inf")
    assert hungarian([[4, 1, 3], [2, 0, 5], [3, 2, 2]]) == [1, 0, 2]
    assert hungarian([[1, 2, 3], [1, 2, 3]]) == [0, 1]
    assert hungarian([[1, inf], [2, inf]]) is None
    assert hungarian([]) == []


def test_window_costs_are_ranked_in_the_total_order_and_a_nan_ranks_last_without_raising():
    nan, inf = float("nan"), float("inf")
    costs = [(3.0, 0), (nan, 1), (-0.0, 2), (0.0, 3), (inf, 4), (1.0, 5), (1.0, 6)]
    assert [wi for _, wi in sorted(costs, key=lambda t: (total_order(t[0]), t[1]))] == [2, 3, 5, 6, 0, 4, 1]


def test_a_move_is_priced_by_recounting_the_nets_it_touches_as_the_whole_total_would():
    # A, B and D a soft group round C, which an allow rule holds: a move of A, B or D re-prices the group's spread
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C"], "S": ["D", "E", ""], "W": ["F", "", ""]},
                    {"Pm.PinPool": "1-9", "Pm.PinAllow": "C:3", "Pm.PinGroup": "abcd:1-4"})
    rng = random.Random(1)
    for i, net in enumerate("ABCDEF"):
        pads += point_pad("T%d" % i, net, rng.uniform(0, 25), rng.uniform(0, 25))
    pads += point_pad("Q1", "X", 0, 0) + point_pad("Q2", "X", 25, 25)
    pb = problem_of(input_of(pads, {"U1": u1})[0], 0.5)
    assert pb.soft and len(pb.soft[0][2]) == 4
    sc = Scorer(pb, [Pose(10.0, 10.0)], W, Background(pb.wires, W), [0])
    tally = Tally(sc, [tuple(q for _, q in e) for e in pb.ends])
    spread = 0
    held = pb.nets.index(("C", 0))
    for _ in range(40):
        a, b = rng.sample([n for n in range(len(pb.nets)) if n != held], 2)
        change = {a: tally.assign[b], b: tally.assign[a]} if rng.random() < 0.5 else {a: (rng.randrange(9),)}
        d = tally.delta(change)
        after = list(tally.assign)
        for n, pins in change.items():
            after[n] = pins
        assert d == pytest.approx(sc.total(after)[0] - sc.total(tally.assign)[0], abs=1e-9)
        spread += sc.total(after)[8] != sc.total(tally.assign)[8]
        tally.apply(change, d)
    assert tally.value == pytest.approx(sc.total(tally.assign)[0], abs=1e-6)
    assert spread > 5


def test_a_quiet_net_on_a_studied_part_turns_with_it_and_a_weightless_plane_is_left_out():
    inp, _ = input_of(*reversed_four())
    pb = problem_of(inp, 0.5)
    pins = [pb.pins[0] + [("5", -1.7, 0.0, -1.0, 0.0)]]
    pads = [(8.3, 10.0, "U1", "5", 0, 4), (8.3, 0.0, "J1", "1", -1, -1)]
    pb = replace(pb, pins=pins, posed=[(3, pads, [])])
    ends = lambda got: [{(s[0], s[1]), (s[2], s[3])} for _, s in got]
    w = (5.0, 3.0, 1.0, 0.25, 0.005, 1.0)
    assert ends(posed_wires(pb, [Pose(10.0, 10.0)], w)) == [{(8_300_000, 10_000_000), (8_300_000, 0)}]
    assert ends(posed_wires(pb, [Pose(10.0, 10.0, 180.0)], w)) == [{(11_700_000, 10_000_000), (8_300_000, 0)}]
    assert posed_wires(pb, [Pose(10.0, 10.0, 180.0)], (5.0, 3.0, 0.0, 0.25, 0.005, 1.0)) == []


def test_no_single_net_is_offered_the_pin_of_a_groups_empty_slot():
    # the bus is 1-3 with no net on 2: a single's moves never land on 2, however many are drawn
    pads, u1 = quad("U1", 10, 10, {"E": ["D", "", "F", "S", ""]}, {"Pm.PinPool": "1-5", "Pm.PinGroup": "bus!:1-3"})
    pads += point_pad("T1", "D", 20, 8.5) + point_pad("T2", "S", 14, 9.5) + point_pad("T3", "F", 20, 10.5)
    pb = problem_of(input_of(pads, {"U1": u1})[0], 0.5)
    present = [tuple(q for _, q in e) for e in pb.ends]
    st = pinmap_twin._State(pb, present)
    units = [u for u in pinmap_twin._units(pb, [0]) if u[0] == "m"]
    rng = SplitMix64(5)
    landed = set()
    for _ in range(200):
        got = pinmap_twin._propose(rng, st, pb, units)
        if got:
            landed |= set(got.values())
    assert 1 not in landed and landed


def test_an_index_out_of_range_or_a_normal_off_the_axes_is_refused():
    pb = problem_of(input_of(*reversed_four())[0], 0.5)
    pr = params_of(settings(), ("U1",))
    for bad in (replace(pb, ends=[[(0, 9)]] + pb.ends[1:]), replace(pb, movable=[(7, 0, [0], -1)]),
                replace(pb, groups=[(0, [5], [[0]])]), replace(pb, fixed=[[]] * 4, joined=[[(0, 1)]] + pb.joined[1:]),
                replace(pb, posed=[(3, [(0.0, 0.0, "U1", "9", 0, 9)], [])])):
        with pytest.raises(ValueError, match="out of range"):
            pinmap_twin.search(bad, [0], [[(0, 0.0, False)]], pr)
    with pytest.raises(ValueError, match="out of range"):
        pinmap_twin.search(pb, [3], [[(0, 0.0, False)]], pr)
    pins = [[(n, x, y, 0.6, 0.8) for n, x, y, _, _ in pb.pins[0]]]
    with pytest.raises(ValueError, match="not one of the four axis directions"):
        pinmap_twin.search(replace(pb, pins=pins), [0], [[(0, 0.0, False)]], pr)


def test_the_clock_counts_steps_to_its_budget_and_its_guard_reads_the_time(monkeypatch):
    c = Clock(3)
    assert [c.take() for _ in range(4)] == [True, True, True, False] and c.steps == 3
    now = [0.0]
    monkeypatch.setattr(pinmap_twin.time, "perf_counter", lambda: now[0])
    c, off = Clock(3, guard_ms=500.0), Clock(3)
    now[0] = 0.4
    assert not c.slow() and not off.slow()
    now[0] = 0.6
    assert c.slow() and not off.slow()
    assert isinstance(Problem([], [], [], [], [], [], [], [], [], 0.5), Problem)
