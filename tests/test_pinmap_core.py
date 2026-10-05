"""The pin map study's core, through its one entry point (pinmap_core.study_group): the score of the present map, a
first map by minimum-cost matching, then moves, swaps and group moves under the constraints, per pose; deterministic;
stopped by its clock with the best found. Each test runs on every core in CORES: the native one (skipped when the
native module is not in use) and, from the Python twin's task on, the twin."""
from dataclasses import replace

import pytest

from placemat.pinmap_core import native_core, params_of, poses_of, problem_of, search, study_group
from placemat.pinmap_input import build, placed_from_geometry
from tests.fixtures import board_geometry, footprint, track
from tests.pinmap_boards import input_of, point_pad, quad, quad_footprint, reversed_four, settings

CORES = ["native", "python"]


@pytest.fixture(params=CORES)
def native(request):
    if request.param == "native" and native_core() is None:
        pytest.skip("the native module is not in use")
    return request.param == "native"


def run(inp, native, s=None, refs=("U1",), budget_steps=None, guard_ms=None):
    return study_group(inp, refs, s or settings(), budget_steps=budget_steps, guard_ms=guard_ms, native=native)


def best(g):
    return min(g.results, key=lambda r: r.breakdown.total)


def pin(result, net, ref="U1"):
    return dict(result.assign[net])[ref]


def test_four_nets_in_reverse_order_cross_six_times_and_are_uncrossed_at_the_present_rotation(native):
    inp, _ = input_of(*reversed_four())
    g = run(inp, native, settings(pins_rotations=(0.0,)))
    r = g.results[0]
    assert (g.present.among, g.present.against, g.present.weighted) == (6, 0, 6.0)
    assert r.breakdown.among == 0 and [pin(r, n) for n in "ABCD"] == ["4", "3", "2", "1"]
    s = settings()
    assert r.breakdown.total == pytest.approx(s.pins_length_weight * r.breakdown.length_mm
                                              + s.pins_bend_weight * r.breakdown.bend_deg)


def test_each_constraint_holds_fixed_allow_deny_and_a_group_kept_whole_and_in_order(native):
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C", "D", "E", ""]},
                    {"Pm.PinPool": "1-6", "Pm.PinFixed": "1", "Pm.PinAllow": "B:2,3", "Pm.PinDeny": "C:3",
                     "Pm.PinGroup": "bus!:4-5"})
    for i, net in enumerate(["A", "B", "C", "D", "E"]):
        pads += point_pad("T%d" % i, net, 20, 12.5 - i)                 # every target in reverse order
    inp, _ = input_of(pads, {"U1": u1})
    g = run(inp, native, settings(pins_rotations=(0.0,)))
    r = g.results[0]
    assert pin(r, "A") == "1" and pin(r, "B") in ("2", "3") and pin(r, "C") != "3"
    d, e = int(pin(r, "D")), int(pin(r, "E"))
    assert e == d + 1                                                   # the group moved whole, in its order
    assert r.breakdown.total < g.present.total


def test_a_net_whose_target_is_behind_the_part_is_moved_to_the_side_that_faces_it(native):
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""], "W": ["", ""]}, {"Pm.PinPool": "1-4"})
    pads += point_pad("T1", "A", 0, 10)
    inp, _ = input_of(pads, {"U1": u1})
    g = run(inp, native, settings(pins_rotations=(0.0,)))
    assert pin(g.results[0], "A") in ("3", "4")
    assert g.present.length_mm > g.results[0].breakdown.length_mm + 4.0     # the way round the body is gone
    (before,) = g.present_paths["A"]
    assert len(before) == 4                                             # exit, two corners, target


def test_a_net_of_several_pads_is_scored_on_its_tree_with_the_studied_pin_at_its_exit(native):
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""]}, {"Pm.PinPool": "1-2"})
    pads += point_pad("T1", "A", 20, 9.5) + point_pad("T2", "A", 30, 9.5)
    inp, _ = input_of(pads, {"U1": u1})
    g = run(inp, native, settings(pins_rotations=(0.0,)))
    assert sorted(tuple(sorted(p)) for p in g.present_paths["A"]) == [((12.75, 9.5), (20.0, 9.5)), ((20.0, 9.5), (30.0, 9.5))]
    assert g.present.length_mm == pytest.approx(17.25) and g.present.bend_deg == 0.0


def test_a_diagonal_turn_wins_on_the_bend_when_it_is_listed_and_is_not_reported_when_it_is_not(native):
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""]}, {"Pm.PinPool": "1-2"})
    pads += point_pad("T1", "A", 22, -2)
    inp, _ = input_of(pads, {"U1": u1})
    eighths = run(inp, native, settings(pins_rotations=tuple(range(0, 360, 45))))
    b = best(eighths)
    assert b.poses == (("U1", 45.0, False),) and b.breakdown.bend_deg < 5.0
    quarters = run(inp, native)
    assert {p[1] for r in quarters.results for p in r.poses} == {0.0, 90.0, 180.0, 270.0}


def test_the_other_face_is_studied_only_when_asked_and_the_part_may_stand_there(native):
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""]}, {"Pm.PinPool": "1-2"}, may_flip=True)
    pads += point_pad("T1", "A", 22, 10)
    inp, _ = input_of(pads, {"U1": u1})
    assert poses_of(inp.parts[0], settings()) == [(0.0, False), (90.0, False), (180.0, False), (270.0, False)]
    assert (90.0, True) in poses_of(inp.parts[0], settings(pins_faces=True))
    g = run(inp, native, settings(pins_faces=True))
    assert g.of == 8 and any(p[2] for r in g.results for p in r.poses)


def test_the_present_pose_comes_first_and_each_turn_is_studied_once_however_the_turns_are_written():
    inp, _ = input_of(*reversed_four())
    assert poses_of(inp.parts[0], settings(pins_rotations=(360, -90, 90.0, 90))) == [(0.0, False), (270.0, False), (90.0, False)]


def test_the_same_board_gives_the_same_maps_and_totals(native):
    inp, _ = input_of(*reversed_four())
    a, b = run(inp, native), run(inp, native)
    assert [(r.poses, r.breakdown, r.assign) for r in a.results] == [(r.poses, r.breakdown, r.assign) for r in b.results]


def test_a_budget_of_no_steps_gives_no_first_map_and_one_spent_later_keeps_the_best_found(native):
    inp, _ = input_of(*reversed_four())
    s = settings(pins_anneal_moves=500, pins_seeds=4)                   # 2000 steps a pose
    g = run(inp, native, s, budget_steps=0)
    assert (g.first_map, g.budget_out, g.results, g.steps) == (False, True, (), 0)
    g = run(inp, native, s, budget_steps=2500)                          # spent in the second pose
    assert g.first_map and g.budget_out and len(g.results) == g.searched == 2 and g.of == 4 and g.steps == 2500


def test_a_study_inside_its_budget_takes_a_step_for_each_move_of_each_search(native):
    inp, _ = input_of(*reversed_four())
    g = run(inp, native, settings(pins_anneal_moves=70, pins_seeds=3))
    assert not g.budget_out and g.searched == g.of == 4 and g.steps == 4 * 3 * 70 and not g.slow


def test_the_python_core_gives_the_same_best_map_however_slow_its_clock(monkeypatch):
    # every read of the time a second after the last: a run that stopped at a time would stop at its first look
    from placemat import pinmap_twin
    inp, _ = input_of(*reversed_four())
    s = settings(pins_budget_steps=150, pins_guard_ms=0.0)              # spent part way through the second pose
    key = lambda g: (g.budget_out, g.steps, [(r.poses, r.breakdown, r.assign) for r in g.results])
    want = run(inp, False, s)
    now = [0.0]

    def slow():
        now[0] += 1.0
        return now[0]
    monkeypatch.setattr(pinmap_twin.time, "perf_counter", slow)
    a, b = run(inp, False, s), run(inp, False, s)
    assert key(a) == key(b) == key(want)
    assert want.budget_out and want.steps == 150 and len(want.results) == 2


def test_a_study_past_its_wall_clock_guard_gives_no_map(native):
    inp, _ = input_of(*reversed_four())
    g = run(inp, native, settings(), guard_ms=1e-9)
    assert g.slow and g.results == () and g.searched == 0
    assert not run(inp, native, settings(), guard_ms=0.0).slow          # 0 is off


def test_a_routed_board_scores_as_the_same_board_without_its_copper(native):
    fps = [quad_footprint("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"}),
           footprint("R1", 20, 10.5, w=2, h=1, inst="r1", nets=("A", "N1")),
           footprint("R2", 20, 9.5, w=2, h=1, inst="r2", nets=("B", "N2"))]
    a1, r1 = fps[0].pads[0].airwire_end, fps[1].pads[0].airwire_end
    routed = board_geometry(fps, copper=[track("A", a1.x, a1.y, r1.x, r1.y)], width=40, height=40)
    bare = board_geometry(fps, width=40, height=40)
    present = []
    for g in (routed, bare):
        inp, _ = build(*placed_from_geometry(g)[:2], {}, frozenset(), {}, g.netclasses)
        present.append(run(inp, native, settings(pins_rotations=(0.0,))).present)
    assert present[0] == present[1] and present[0].among == 1           # A still has its airwire, and it crosses B's


def test_the_core_takes_the_study_as_plain_arrays():
    inp, _ = input_of(*reversed_four({"Pm.PinPool": "1-4", "Pm.PinGroup": "ab!:1-2"}))
    pb = problem_of(inp, 0.5)
    assert pb.parts == [("U1", 10.0, 10.0, 2.25, 2.25)] and [p[0] for p in pb.pins[0]] == ["1", "2", "3", "4"]
    assert pb.nets == [("A", 0), ("B", 0), ("C", 0), ("D", 0)] and pb.ends == [[(0, 0)], [(0, 1)], [(0, 2)], [(0, 3)]]
    assert pb.movable == [(0, 0, [0, 1, 2, 3], 0), (1, 0, [0, 1, 2, 3], 0), (2, 0, [0, 1, 2, 3], -1), (3, 0, [0, 1, 2, 3], -1)]
    assert pb.groups == [(0, [0, 1], [[0, 1], [1, 2], [2, 3]])]
    assert pb.fixed[0] == [(20.0, 11.5, "TP4", "1")] and pb.wires == []


def test_a_group_a_rule_holds_part_of_may_stay_where_it_stands(native):
    # the bus is 2-4 with its middle net held on 3 by its allow rule, so of the runs of free pins only 4-6 would hold
    # the bus: its present place is a window of its own, first, and every net already faces its target
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "D", "E", "F", "", ""]},
                    {"Pm.PinPool": "1-6", "Pm.PinAllow": "E:3", "Pm.PinGroup": "bus!:2-4"})
    for i, net in enumerate(["A", "D", "E", "F"]):
        pads += point_pad("T%d" % i, net, 20, 7.5 + i)
    inp, _ = input_of(pads, {"U1": u1})
    pb = problem_of(inp, 0.5)
    assert pb.groups[0][2] == [[1, 2, 3], [3, 4, 5]]
    g = run(inp, native, settings(pins_rotations=(0.0,)))
    r = g.results[0]
    assert (pin(r, "D"), pin(r, "E"), pin(r, "F")) == ("2", "3", "4")
    assert r.breakdown.total == pytest.approx(g.present.total)


def test_at_the_present_pose_the_best_is_never_worse_than_the_present_map(native):
    # the bus case above: one seed of 100 moves from the first map ends on the 4-6 window, worse than where it stands
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "D", "E", "F", "", ""]},
                    {"Pm.PinPool": "1-6", "Pm.PinAllow": "E:3", "Pm.PinGroup": "bus!:2-4"})
    for i, net in enumerate(["A", "D", "E", "F"]):
        pads += point_pad("T%d" % i, net, 20, 7.5 + i)
    inp, _ = input_of(pads, {"U1": u1})
    g = run(inp, native, settings(pins_rotations=(0.0,), pins_anneal_moves=100, pins_seeds=1))
    r = g.results[0]
    assert [pin(r, n) for n in "ADEF"] == ["1", "2", "3", "4"]
    assert r.breakdown.total == g.present.total


def _grounded(rotation=0.0):
    """U1 with A on its east pin, its target far west, and a plane net on its north pin whose other pad is far west
    and a little north."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A"], "N": ["GND"]}, {"Pm.PinPool": "1"}, rotation=rotation)
    pads += point_pad("T1", "A", -20, 10) + point_pad("J1", "GND", -20, 9)
    return input_of(pads, {"U1": u1}, quiet={"GND"})[0]


def test_a_plane_nets_airwires_on_a_studied_part_turn_with_it(native):
    # turned half round, A leaves west along y = 10 and the plane's pin, now south, has its airwire cross it; where the
    # pin stood its airwire stays north of A's
    s = settings(pins_rotations=(0.0, 180.0), score_crossing_plane=1.0)
    turned = next(r for r in run(_grounded(), native, s).results if r.poses == (("U1", 180.0, False),))
    laid = run(_grounded(rotation=180.0), native, settings(pins_rotations=(0.0,), score_crossing_plane=1.0))
    assert turned.breakdown.against == laid.present.against == 1
    assert turned.breakdown.length_mm == pytest.approx(laid.present.length_mm)
    assert run(_grounded(), native, settings(pins_rotations=(0.0, 180.0))).results[1].breakdown.against == 0


def test_a_pin_normal_off_the_axes_is_refused(native):
    inp, _ = input_of(*reversed_four())
    pb = problem_of(inp, 0.5)
    pins = [[(n, x, y, 0.6, 0.8) for n, x, y, _, _ in pb.pins[0]]]
    with pytest.raises(ValueError, match="not one of the four axis directions"):
        search(replace(pb, pins=pins), [0], [[(0, 0.0, False)]], params_of(settings(), ("U1",)), native)


def test_a_groups_tallies_count_only_its_own_nets_and_their_crossings(native):
    s = settings(pins_rotations=(0.0,))
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"})
    pads += point_pad("T1", "A", 20, 10.5) + point_pad("T2", "B", 20, 9.5)
    alone = run(input_of(pads, {"U1": u1})[0], native, s)
    p2, u2 = quad("U2", 50, 10, {"E": ["C", "D", "E", "F"]}, {"Pm.PinPool": "1-4"})
    for i, n in enumerate("CDEF"):
        p2 += point_pad("S%d" % i, n, 60, 11.5 - i)
    beside = run(input_of(pads + p2, {"U1": u1, "U2": u2})[0], native, s)
    assert beside.present == alone.present and alone.present.among == 1
    assert beside.results[0].breakdown == alone.results[0].breakdown


def test_a_net_never_takes_the_pin_of_a_groups_empty_slot(native):
    # the bus is 1-3 with no net on 2, and S's target faces pin 2: S stays off it
    pads, u1 = quad("U1", 10, 10, {"E": ["D", "", "F", "S"]}, {"Pm.PinPool": "1-4", "Pm.PinGroup": "bus!:1-3"})
    pads += point_pad("T1", "D", 20, 8.5) + point_pad("T2", "S", 14, 9.5) + point_pad("T3", "F", 20, 10.5)
    inp, _ = input_of(pads, {"U1": u1})
    r = run(inp, native, settings(pins_rotations=(0.0,))).results[0]
    d, f, s = int(pin(r, "D")), int(pin(r, "F")), int(pin(r, "S"))
    assert f == d + 2 and s != d + 1


def test_an_index_out_of_range_is_refused(native):
    inp, _ = input_of(*reversed_four())
    pb = problem_of(inp, 0.5)
    for bad in (replace(pb, ends=[[(0, 9)]] + pb.ends[1:]), replace(pb, movable=[(7, 0, [0], -1)]),
                replace(pb, groups=[(0, [5], [[0]])]), replace(pb, fixed=[[]] * 4, joined=[[(0, 1)]] + pb.joined[1:])):
        with pytest.raises(ValueError, match="out of range"):
            search(bad, [0], [[(0, 0.0, False)]], params_of(settings(), ("U1",)), native)
    with pytest.raises(ValueError, match="out of range"):
        search(pb, [3], [[(0, 0.0, False)]], params_of(settings(), ("U1",)), native)


def test_at_a_diagonal_pose_the_airwires_leave_and_go_round_the_turned_courtyard_not_its_bounding_box(native):
    # U1 4 mm square (courtyard 2.25 mm each way from its centre), A on its east pin and B on its west pin, both
    # targets far out on its north-east diagonal. Turned 45 degrees, A faces its target; B goes round the turned body.
    pads, u1 = quad("U1", 10, 10, {"E": ["A"], "W": ["B"]}, {"Pm.PinPool": "1-2"})
    pads += point_pad("TA", "A", 30, -10) + point_pad("TB", "B", 31, -9)
    inp, _ = input_of(pads, {"U1": u1})
    g = run(inp, native, settings(pins_rotations=(0.0, 45.0)))
    turned = next(r for r in g.results if r.poses == (("U1", 45.0, False),))
    a = turned.paths["A"][0]
    exit_a = a[0] if a[0] != (30.0, -10.0) else a[-1]
    # the exit is pins.exit_mm past the turned courtyard's side, 2.75 mm from the centre on the diagonal; past the
    # bounding box of the turned courtyard it would be 2.25 * 2 ** 0.5 + 0.5 = 3.68 mm
    assert ((exit_a[0] - 10) ** 2 + (exit_a[1] - 10) ** 2) ** 0.5 == pytest.approx(2.75, abs=1e-6)
    assert exit_a[0] - 10 == pytest.approx(10 - exit_a[1], abs=1e-6)              # north-east, on the diagonal
    assert len(a) == 2                                                              # straight out to its target
    b = turned.paths["B"][0]
    corners = [p for p in b if p not in (b[0], b[-1])]
    # the turned body's corners, grown by the exit margin, lie on the axes through its centre, 2.75 * 2 ** 0.5 out
    assert corners
    for x, y in corners:
        assert ((x - 10) ** 2 + (y - 10) ** 2) ** 0.5 == pytest.approx(2.75 * 2 ** 0.5, abs=1e-6)
        assert min(abs(x - 10), abs(y - 10)) == pytest.approx(0.0, abs=1e-6)


def _diagonal(rotation, may_flip=False):
    """U1 laid at `rotation`, A on its east pin and B on its west pin (as it is laid), their targets far out on the
    board's north-east and south-west diagonals."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A"], "W": ["B"]}, {"Pm.PinPool": "1-2"}, rotation=rotation, may_flip=may_flip)
    pads += point_pad("TA", "A", 30, -10) + point_pad("TB", "B", -10, 30)
    return input_of(pads, {"U1": u1})[0]


def test_a_part_laid_at_45_degrees_is_studied_in_its_own_frame_its_body_the_turned_courtyard(native):
    inp = _diagonal(45.0)
    (part,) = inp.parts
    # the courtyard is 4.5 mm square: the box round it turned 45 degrees is 6.36 mm, the body stays 4.5
    assert part.frame == 45.0 and (part.hw, part.hh) == (pytest.approx(2.25), pytest.approx(2.25))
    assert inp.parts[0].pin("1").nx == 1.0 and inp.parts[0].pin("2").nx == -1.0
    g = run(inp, native, settings(pins_rotations=(0.0,)))
    (a,) = g.present_paths["A"]
    exit_a = a[0] if a[0] != (30.0, -10.0) else a[-1]
    assert ((exit_a[0] - 10) ** 2 + (exit_a[1] - 10) ** 2) ** 0.5 == pytest.approx(2.75, abs=1e-6)
    assert len(a) == 2 and g.present.bend_deg < 1.0                      # both pins face their targets
    assert pin(g.results[0], "A") == "1"


def test_a_part_laid_at_45_degrees_scores_as_one_laid_square_and_studied_at_45(native):
    laid = run(_diagonal(45.0), native, settings(pins_rotations=(0.0, 90.0)))
    turned = run(_diagonal(0.0), native, settings(pins_rotations=(45.0, 135.0)))
    for k in (0, 1):
        a = laid.results[k].breakdown
        b = turned.results[k + 1].breakdown
        assert (a.against, a.among) == (b.against, b.among)
        assert a.total == pytest.approx(b.total, abs=1e-6) and a.length_mm == pytest.approx(b.length_mm, abs=1e-6)
    assert laid.present.total == pytest.approx(turned.results[1].breakdown.total, abs=1e-6)


def test_a_part_laid_at_45_degrees_and_flipped_mirrors_its_pads_as_they_stand(native):
    # flipping mirrors the pads where they stand, then turns them: laid at 45 and flipped at 90 is laid square and
    # flipped at 45
    s = settings(pins_rotations=(0.0, 45.0, 90.0), pins_faces=True)
    laid = run(_diagonal(45.0, may_flip=True), native, s)
    square = run(_diagonal(0.0, may_flip=True), native, s)
    a = next(r for r in laid.results if r.poses == (("U1", 90.0, True),)).breakdown
    b = next(r for r in square.results if r.poses == (("U1", 45.0, True),)).breakdown
    assert (a.against, a.among) == (b.against, b.among) and a.total == pytest.approx(b.total, abs=1e-6)


def test_a_study_past_its_guard_gives_no_problem_found_before_the_trip(monkeypatch):
    # the second pose's first map says a net has no pin; the guard trips before the third pose
    from placemat import pinmap_twin
    inp, _ = input_of(*reversed_four())
    real, calls, now = pinmap_twin.first_map, [], [0.0]

    def first_map(sc, group_parts, start):
        calls.append(1)
        got, problems = real(sc, group_parts, start)
        if len(calls) == 2:
            now[0] = 10.0
            problems = problems + [(0, 0)]
        return got, problems
    monkeypatch.setattr(pinmap_twin, "first_map", first_map)
    monkeypatch.setattr(pinmap_twin.time, "perf_counter", lambda: now[0])
    g = run(inp, False, settings(), guard_ms=1000.0)
    assert len(calls) == 2 and g.slow and g.results == () and g.problems == ()


def _barred(fields=None):
    """U1 with A and B on east pins 1 and 2, their targets due east of them, and an allow rule that bars both from
    where they stand: the present map is the cheapest there is, and breaks the rule."""
    f = {"Pm.PinPool": "1-6", "Pm.PinAllow": "A:5-6; B:5-6"}
    f.update(fields or {})
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "", "", "", ""]}, f)
    pads += point_pad("T1", "A", 20, 7.5) + point_pad("T2", "B", 20, 8.5)
    return input_of(pads, {"U1": u1})[0]


@pytest.mark.parametrize("group", ["", "disp:1-2", "disp!:1-2"])
def test_at_the_present_pose_the_best_obeys_an_allow_rule_the_present_map_breaks(native, group):
    # the present map scores lowest, but it is no candidate: the nets move onto the pins their rule allows; a soft or
    # hard group named by the barred pins moves with them
    inp = _barred({"Pm.PinGroup": group} if group else None)
    assert [b[:2] for b in inp.part("U1").slots.breaks] == [("A", "1"), ("B", "2")]
    g = run(inp, native, settings(pins_rotations=(0.0,), pins_gain_min=0.0))
    r = g.results[0]
    assert g.problems == ()
    assert {pin(r, "A"), pin(r, "B")} <= {"5", "6"}
    assert r.breakdown.total > g.present.total


def test_a_hard_group_with_no_window_its_nets_may_take_is_reported_not_kept(native):
    # A may take only 6 and B only 5, so the bus A, B has no run of pins in its order: no legal map
    inp = _barred({"Pm.PinAllow": "A:6; B:5", "Pm.PinGroup": "disp!:1-2"})
    pb = problem_of(inp, 0.5)
    assert pb.groups[0][2] == []
    g = run(inp, native, settings(pins_rotations=(0.0,), pins_gain_min=0.0))
    assert g.results == () and g.problems == (("U1", "A"),)
