"""`Pm.PinGroup` groups, soft by default and hard on request: a soft group's nets move one by one, each under its own
rules, and the study adds `pins.group_weight` times the group's spread (how far its neighbouring nets' pads stand apart
beyond the part's pin pitch) to its total; a hard group (`name!:pins`) moves as one block, in order, to a run of
consecutive pool entries, as every group did before. Each pose's facts carry the groups where they landed."""
import itertools
import json
from pathlib import Path
import struct

import pytest

from placemat.findings import FindingCause as C
from placemat.pinmap import study_findings
from placemat.pinmap_core import native_core, params_of, poses_of, problem_of, search, study_group
from placemat.pinmap_rules import Problem, read_rules
from tests.pinmap_boards import complete, input_of, point_pad, quad, settings

CORES = ["native", "python"]


@pytest.fixture(params=CORES)
def native(request):
    if request.param == "native" and native_core() is None:
        pytest.skip("the native module is not in use")
    return request.param == "native"


def run(inp, native, s=None):
    return study_group(inp, ("U1",), s or settings(pins_rotations=(0.0,)), native=native)


def pin(result, net, ref="U1"):
    return dict(result.assign[net])[ref]


PADS = [(str(n), "N%d" % n) for n in range(1, 9)]


def test_a_group_named_with_a_bang_is_hard_and_one_without_is_soft():
    rules, problems = read_rules("U1", {"Pm.PinPool": "1-8", "Pm.PinGroup": "lcd:1-4; pio0!:5-6"}, PADS, {})
    assert problems == []
    assert rules.groups == (("lcd", ("1", "2", "3", "4"), False), ("pio0", ("5", "6"), True))


def test_a_name_is_read_as_written_but_for_one_bang_and_a_double_bang_is_a_problem():
    rules, problems = read_rules("U1", {"Pm.PinPool": "1-8", "Pm.PinGroup": "spi(a):1-2; bus-:3-4; pio0!!:5-6; !:7-8"},
                                 PADS, {})
    assert rules.groups == (("spi(a)", ("1", "2"), False), ("bus-", ("3", "4"), False))
    assert problems == [Problem("U1", "Pm.PinGroup", "pio0!!:5-6", "bad_marker", "!!"),
                        Problem("U1", "Pm.PinGroup", "!:7-8", "unreadable", "!:7-8")]


def test_two_groups_of_one_name_are_a_problem_naming_both_and_the_second_is_left_out():
    rules, problems = read_rules("U1", {"Pm.PinPool": "1-8", "Pm.PinGroup": "lcd:1-2; lcd!:5-6"}, PADS, {})
    assert rules.groups == (("lcd", ("1", "2"), False),)
    assert problems == [Problem("U1", "Pm.PinGroup", "lcd:1-2; lcd!:5-6", "same_name", "lcd")]
    from placemat.findings import Finding
    assert str(Finding(C.SETUP_PINS, problems[0].facts())) == (
        "U1: Pm.PinGroup entries lcd:1-2; lcd!:5-6 name two groups lcd; the study runs without the second")


def bus_board(group, fence=0) -> tuple:
    """(pads, parts): U1, 6 mm square, with a bus A-D on its east pins 1-4 (north to south) and four free pins 5-8 on
    its south side (west to east); A-D's targets due east of their pins. With `fence` > 0, D's target is far south
    instead, and that many board airwires lie across the way to it from pin 4, but not from the south pins."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C", "D"], "S": ["", "", "", ""]},
                    {"Pm.PinPool": "1-8", "Pm.PinGroup": group}, body=6.0)
    for i, net in enumerate("ABC"):
        pads += point_pad("T%d" % i, net, 25, 8.5 + i)
    pads += point_pad("T3", "D", 12, 30) if fence else point_pad("T3", "D", 25, 11.5)
    for k in range(fence):
        pads += point_pad("Q%da" % k, "X%d" % k, 12.6, 20 + k) + point_pad("Q%db" % k, "X%d" % k, 20, 20 + k)
    return pads, {"U1": u1}


def bus(group, fence=0):
    return input_of(*bus_board(group, fence))[0]


def landed(result, name):
    return next(g for g in result.groups if g.name == name)


def test_a_soft_group_whose_nets_gain_nothing_apart_stays_whole_and_costs_nothing(native):
    g = run(bus("bus:1-4"), native)
    r = g.results[0]
    assert [pin(r, n) for n in "ABCD"] == ["1", "2", "3", "4"]
    got = landed(r, "bus")
    assert (got.hard, got.spread_mm, got.cost, got.nets, got.pins) == (False, 0.0, 0.0, ("A", "B", "C", "D"),
                                                                       ("1", "2", "3", "4"))
    assert r.breakdown.spread_mm == 0.0 and g.present.spread_mm == 0.0


def test_a_soft_group_splits_three_and_one_when_that_saves_enough_crossings_the_fourth_on_the_nearest_pin(native):
    g = run(bus("bus:1-4", fence=4), native)
    r = g.results[0]
    # D leaves for pin 8, the south pin next to the east side; A-C close up behind it on 2-4, in order, which costs
    # them under 0.1 of airwire and turning and saves 0.8 mm of spread
    assert [pin(r, n) for n in "ABCD"] == ["2", "3", "4", "8"]
    assert g.present.against == 4 and r.breakdown.against == 0
    got = landed(r, "bus")
    # pin 4 (2.7, 1.5) to pin 8 (1.5, 2.7) in the part's frame: 1.697 mm, one 1 mm pitch allowed
    assert got.spread_mm == pytest.approx(2 ** 0.5 * 1.2 - 1.0, abs=1e-6) and not got.hard
    assert got.cost == pytest.approx(settings().pins_group_weight * got.spread_mm)
    assert r.breakdown.spread_mm == pytest.approx(got.spread_mm)
    assert r.breakdown.cohesion == pytest.approx(got.cost)
    assert got.nets == ("A", "B", "C", "D") and got.pins == ("2", "3", "4", "8")


def test_a_heavier_group_weight_keeps_the_soft_group_whole(native):
    r = run(bus("bus:1-4", fence=4), native, settings(pins_rotations=(0.0,), pins_group_weight=20.0)).results[0]
    assert [pin(r, n) for n in "ABCD"] == ["1", "2", "3", "4"]


def test_a_hard_group_moves_only_as_a_block_in_order(native):
    r = run(bus("bus!:1-4", fence=4), native).results[0]
    at = [int(pin(r, n)) for n in "ABCD"]
    assert at == list(range(at[0], at[0] + 4))
    got = landed(r, "bus")
    assert got.hard and got.cost == 0.0 and r.breakdown.spread_mm == 0.0


OLD = json.loads((Path(__file__).parent / "data" / "pinmap_0_99_16_search.json").read_text())


def hexed(x):
    if isinstance(x, float):
        return struct.pack("<d", x).hex()
    if isinstance(x, (list, tuple)):
        return [hexed(v) for v in x]
    return x


@pytest.mark.parametrize("case", sorted(OLD))
def test_a_board_with_no_soft_group_or_controlled_impedance_scores_to_the_bit_as_0_99_16_did(case, native):
    """0.99.16's core on these boards (tests/data, written by that release's Python twin; their groups marked hard
    here): every pose's map, airwires and tallies, the floats to the last bit. The tallies added since (the
    controlled impedance's length, the spread and the cohesion) are 0 on them and left out."""
    from tests import test_native_pinmap as cases
    make, refs = cases.CASES[case]
    inp = make()
    s = settings(pins_rotations=tuple(range(0, 360, 45)), pins_faces=True, score_crossing_plane=0.7)
    pb = problem_of(inp, s.pins_exit_mm)
    at = {p.ref: i for i, p in enumerate(inp.parts)}
    lists = [[(at[r], t, f) for t, f in poses_of(inp.part(r), s)] for r in refs]
    combos = [list(c) for c in itertools.islice(itertools.product(*lists), s.pins_joint_combinations)]
    base, paths, results, out, first, problems, _, _ = json.loads(json.dumps(
        search(pb, [at[r] for r in refs], combos, params_of(s, refs), native=native), default=list))
    assert all(v == 0 for t in [base] + [r[1] for r in results] for v in t[6:])
    got = [base[:6], paths, [[k, t[:6], a, p] for k, t, a, p in results], out, first, problems]
    assert hexed(got) == OLD[case]


def test_a_split_across_a_pin_outside_the_pool_costs_its_physical_distance(native):
    # pins 1-5 on the east side, 1 mm apart, pin 3 outside the pool: the group's run 1, 2, 4, 5 is consecutive in the
    # pool's listed order, but 2 to 4 is 2 mm, one pitch more than its neighbours
    for group, hard in (("bus:1-2, 4-5", False), ("bus!:1-2, 4-5", True)):
        pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "", "C", "D"]}, {"Pm.PinPool": "1-2, 4-5", "Pm.PinGroup": group},
                        body=6.0)
        for i, net in enumerate("AB CD"):
            if net != " ":
                pads += point_pad("T%d" % i, net, 25, 8 + i)
        g = run(input_of(pads, {"U1": u1})[0], native)
        got = landed(g.results[0], "bus")
        assert got.spread_mm == pytest.approx(1.0) and got.pins == ("1", "2", "4", "5")
        assert got.cost == (0.0 if hard else pytest.approx(settings().pins_group_weight))
        assert g.present.spread_mm == (0.0 if hard else pytest.approx(1.0))


def test_the_part_pitch_is_its_nearest_pad_spacing():
    inp = bus("bus:1-4")
    assert inp.parts[0].pitch == pytest.approx(1.0)


def test_each_poses_facts_carry_its_groups_and_the_sentence_says_a_soft_group_ends_split():
    pads, parts = bus_board("bus:1-4", fence=4)
    found, _ = study_findings(pads, complete(pads, parts), {}, frozenset(), {}, {}, settings(pins_rotations=(0.0,)))
    (f,) = [f for f in found if f.cause is C.PINS_REMAP]
    facts = json.loads(json.dumps(f.facts))
    (row,) = facts["rotations"][facts["best"]]["groups"]
    assert row["name"] == "bus" and row["hard"] is False and row["nets"] == ["A", "B", "C", "D"]
    assert row["pins"] == ["2", "3", "4", "8"] and row["spread_mm"] == pytest.approx(0.697, abs=1e-3)
    assert row["cost"] == pytest.approx(settings().pins_group_weight * row["spread_mm"], abs=1e-3)
    assert "group bus ends split, 0.7 mm beyond its pin pitch" in str(f)


def test_a_bad_marker_renders_as_a_setup_pins_sentence():
    from placemat.findings import Finding
    f = Finding(C.SETUP_PINS, Problem("U1", "Pm.PinGroup", "pio0!!:1-4", "bad_marker", "!!").facts())
    assert str(f) == ("U1: Pm.PinGroup entry pio0!!:1-4 marks its group with !!, and a single ! (hard) is the only "
                      "marker; the study runs without the group")


def gapped_bus():
    """A soft bus A, B, C, D on east pins 1, 2, 4 and 5, pin 3 free between them, of a pool 1-6; each net's target due
    east of its pin. Closing the gap gains only the group's cohesion."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "", "C", "D", ""]},
                    {"Pm.PinPool": "1-6", "Pm.PinGroup": "bus:1-2, 4-5"}, body=6.0)
    for i, net in ((0, "A"), (1, "B"), (3, "C"), (4, "D")):
        pads += point_pad("T%d" % i, net, 25, 7.5 + i)
    return pads, {"U1": u1}


def test_a_gain_from_cohesion_alone_is_named_and_no_saving_is_negative():
    pads, parts = gapped_bus()
    found, _ = study_findings(pads, complete(pads, parts), {}, frozenset(), {}, {}, settings(pins_rotations=(0.0,)))
    (f,) = [f for f in found if f.cause is C.PINS_REMAP]
    text = str(f)
    assert "group bus brought together" in text, text
    assert "-" not in text.split(":", 1)[1].split(";")[0], text
    assert "ends split" not in text


def test_a_spread_under_a_twentieth_of_a_mm_is_together_in_the_sentence():
    from placemat import finding_text as ft
    row = {"total": 1.0, "weighted": 0.0, "length_mm": 1.0, "bend_deg": 0.0, "cohesion": 0.0,
           "groups": [{"name": "bus", "hard": False, "spread_mm": 0.04, "cost": 0.16, "nets": [], "pins": []}]}
    assert ft.split_groups(row) == []
    row["groups"][0]["spread_mm"] = 0.06
    assert [g["name"] for g in ft.split_groups(row)] == ["bus"]


def test_the_first_map_starts_a_soft_group_on_the_window_nearest_its_held_member():
    # E is held on pin 4 by its allow rule; E, D, F a soft group, written in that order. Every target is due east of
    # pin 4, so the runs 2-3 and 5-6 for D and F cost the same to reach: only the spread against E, one pitch for 2-3
    # and none for 5-6, picks the run beside it
    from placemat import pinmap_twin
    from placemat.pinmap_geom import Pose
    pads, u1 = quad("U1", 10, 10, {"E": ["", "", "", "E", "", "", ""], "W": ["D", "F"]},
                    {"Pm.PinPool": "1-9", "Pm.PinAllow": "E:4", "Pm.PinGroup": "g:4, 8, 9"}, body=8.0)
    pads += point_pad("TD", "D", 30, 10) + point_pad("TF", "F", 30, 10) + point_pad("TE", "E", 30, 10)
    pb = problem_of(input_of(pads, {"U1": u1})[0], 0.5)
    w = (5.0, 3.0, 0.0, 0.25, 0.005, 4.0)
    sc = pinmap_twin.Scorer(pb, [Pose(10.0, 10.0)], w, pinmap_twin.Background(pb.wires, w), [0])
    start, _ = pinmap_twin.first_map(sc, [0], [tuple(q for _, q in e) for e in pb.ends])
    at = {pb.nets[n][0]: pb.pins[0][start[n][0]][0] for n in range(len(pb.nets))}
    assert (at["E"], at["D"], at["F"]) == ("4", "5", "6")


def test_both_cores_start_the_soft_group_beside_its_held_member():
    # the same board through each core in use, one move from the first map at most, which gains nothing: the first
    # map stands
    pads, u1 = quad("U1", 10, 10, {"E": ["", "", "", "E", "", "", ""], "W": ["D", "F"]},
                    {"Pm.PinPool": "1-9", "Pm.PinAllow": "E:4", "Pm.PinGroup": "g:4, 8, 9"}, body=8.0)
    pads += point_pad("TD", "D", 30, 10) + point_pad("TF", "F", 30, 10) + point_pad("TE", "E", 30, 10)
    inp = input_of(pads, {"U1": u1})[0]
    s = settings(pins_rotations=(0.0,), pins_anneal_moves=1, pins_anneal_start=0.0, pins_anneal_end=0.0)
    for native in [False] + ([True] if native_core() is not None else []):
        g = study_group(inp, ("U1",), s, native=native)
        r = g.results[0]
        assert (pin(r, "D"), pin(r, "F")) == ("5", "6"), native
