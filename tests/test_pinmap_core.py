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

CORES = ["native"]


@pytest.fixture(params=CORES)
def native(request):
    if request.param == "native" and native_core() is None:
        pytest.skip("the native module is not in use")
    return request.param == "native"


def run(inp, native, s=None, refs=("U1",), step_ms=0.0, budget_ms=None):
    return study_group(inp, refs, s or settings(), step_ms=step_ms, budget_ms=budget_ms, native=native)


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
                     "Pm.PinGroup": "bus:4-5"})
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


def test_a_clock_out_before_the_first_map_says_so_and_one_out_later_keeps_the_best_found(native):
    inp, _ = input_of(*reversed_four())
    s = settings(pins_anneal_moves=500, pins_seeds=4)                   # 64 questions a pose: more than the budget
    g = run(inp, native, s, step_ms=1.0, budget_ms=0.5)                 # out at the first question
    assert (g.first_map, g.budget_out, g.results) == (False, True, ())
    g = run(inp, native, s, step_ms=1.0, budget_ms=40)                  # out after 40 questions
    assert g.first_map and g.budget_out and 1 <= len(g.results) < 4 and g.searched == len(g.results) and g.of == 4


def test_a_routed_board_scores_as_the_same_board_without_its_copper(native):
    fps = [quad_footprint("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"}),
           footprint("R1", 20, 10.5, w=2, h=1, inst="r1", nets=("A", "N1")),
           footprint("R2", 20, 9.5, w=2, h=1, inst="r2", nets=("B", "N2"))]
    a1, r1 = fps[0].pads[0].airwire_end, fps[1].pads[0].airwire_end
    routed = board_geometry(fps, copper=[track("A", a1.x, a1.y, r1.x, r1.y)], width=40, height=40)
    bare = board_geometry(fps, width=40, height=40)
    present = []
    for g in (routed, bare):
        inp, _ = build(*placed_from_geometry(g), {}, frozenset(), {}, g.netclasses)
        present.append(run(inp, native, settings(pins_rotations=(0.0,))).present)
    assert present[0] == present[1] and present[0].among == 1           # A still has its airwire, and it crosses B's


def test_the_core_takes_the_study_as_plain_arrays():
    inp, _ = input_of(*reversed_four({"Pm.PinPool": "1-4", "Pm.PinGroup": "ab:1-2"}))
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
                    {"Pm.PinPool": "1-6", "Pm.PinAllow": "E:3", "Pm.PinGroup": "bus:2-4"})
    for i, net in enumerate(["A", "D", "E", "F"]):
        pads += point_pad("T%d" % i, net, 20, 7.5 + i)
    inp, _ = input_of(pads, {"U1": u1})
    pb = problem_of(inp, 0.5)
    assert pb.groups[0][2] == [[1, 2, 3], [3, 4, 5]]
    g = run(inp, native, settings(pins_rotations=(0.0,)))
    r = g.results[0]
    assert (pin(r, "D"), pin(r, "E"), pin(r, "F")) == ("2", "3", "4")
    assert r.breakdown.total == pytest.approx(g.present.total)


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


def test_a_pin_normal_off_the_axes_is_refused():
    if native_core() is None:
        pytest.skip("the native module is not in use")
    inp, _ = input_of(*reversed_four())
    pb = problem_of(inp, 0.5)
    pins = [[(n, x, y, 0.6, 0.8) for n, x, y, _, _ in pb.pins[0]]]
    with pytest.raises(ValueError, match="not one of the four axis directions"):
        search(replace(pb, pins=pins), [0], [[(0, 0.0, False)]], params_of(settings(), ("U1",)))
