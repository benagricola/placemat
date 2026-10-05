"""The pin map study's finding: a `pins.remap` notice when a map saves `pins.gain_min` of the present total, its facts
as data and its sentence rendered from them; a `setup.pins` warning for an entry the study ran without; the suggestion
that carries the map and the turn and writes nothing; and a study reused when what it reads has not changed."""
import json

import pytest

from placemat import suggestions as sg
from placemat.findings import FindingCause as C, FindingKind
from placemat.pinmap import study_findings
from tests.pinmap_boards import complete, point_pad, quad, reversed_four, settings


def study(pads, parts, s=None, copper=frozenset(), cache=None, step_ms=0.0):
    return study_findings(pads, complete(pads, parts), {}, frozenset(), {}, {}, s or settings(), copper, cache, step_ms)


def test_a_better_map_is_a_notice_with_its_facts_and_its_sentence():
    found, record = study(*reversed_four(), settings(pins_rotations=(0.0,)))
    (f,) = found
    assert f.cause is C.PINS_REMAP and f.kind is FindingKind.PINS and f.severity == "notice"
    assert f == "U1: a pin map with 6 fewer weighted crossings exists at its present rotation"
    facts = json.loads(json.dumps(f.facts))
    assert facts["present"]["among"] == 6 and facts["rotations"][0]["among"] == 0 and facts["best"] == 0
    assert [(m["net"], m["from"]["pin"], m["to"]["pin"]) for m in facts["rotations"][0]["map"]] == [
        ("A", "1", "4"), ("B", "2", "3"), ("C", "3", "2"), ("D", "4", "1")]
    assert {w["net"] for w in facts["before"]} == {"A", "B", "C", "D"} and facts["rotations"][0]["paths"]
    assert record == {"seconds": record["seconds"], "reused": False, "groups": 1, "parts": 1}


def facing_away():
    """U1 with A and B on its west side, north to south, and their targets east of it in the same order: turned half
    round, its pins face them, A and B crossing until they trade pins."""
    pads, u1 = quad("U1", 10, 10, {"W": ["A", "B", ""]}, {"Pm.PinPool": "1-3"})
    for i, net in enumerate(["A", "B"]):
        pads += point_pad("T%d" % i, net, 25, 9.5 + i)
    return pads, {"U1": u1}


def test_a_better_pose_is_named_with_what_it_saves_beside_the_present_one():
    (f,) = study(*facing_away())[0]
    assert f.startswith("U1: a pin map with ") and " exists at its present rotation; at 180 degrees, " in f
    assert f.facts["rotations"][f.facts["best"]]["turns"] == [
        {"ref": "U1", "turn_deg": 180.0, "rotation_deg": 180.0, "face": "front", "flip": False}]


def test_a_map_saving_less_than_the_gain_min_is_no_finding():
    found, _ = study(*reversed_four(), settings(pins_rotations=(0.0,), pins_gain_min=0.99))
    assert found == []


def test_an_entry_the_study_runs_without_is_a_setup_warning():
    found, _ = study(*reversed_four({"Pm.PinPool": "1-4, 9"}), settings(pins_rotations=(0.0,)))
    pins = [f for f in found if f.cause is C.SETUP_PINS]
    assert [str(f) for f in pins] == ["U1: Pm.PinPool names pin 9, which U1 does not have; the study runs without it"]
    assert pins[0].severity == "warning"


def test_the_moved_nets_with_copper_now_are_named():
    (f,) = study(*reversed_four(), settings(pins_rotations=(0.0,)), copper=frozenset({"A", "Z"}))[0]
    assert f.facts["routed"] == ["A"] and f.endswith("; 1 of the nets it moves have copper now: A")


def test_a_budget_too_short_for_a_first_map_says_so():
    found, _ = study(*reversed_four(), settings(pins_budget_ms=50), step_ms=100.0)        # out at the first question
    (f,) = found
    assert f == "U1: the pin map study ran out of its 50 ms before a first map; pins.budget_ms sets it"
    assert sg.suggest(f.cause, f.facts) == []


def test_the_suggestion_carries_the_map_and_the_turn_and_writes_nothing(tmp_path):
    (f,) = study(*facing_away())[0]
    best, present = sg.suggest(f.cause, f.facts)
    assert (best.lever, best.how, best.edits) == ("pins", "advice", ())
    assert best.text == "Move 2 nets of U1 to the pins in the map, a capture change, and turn U1 to 180 degrees"
    assert best.advice["turns"][0]["rotation_deg"] == 180.0
    assert [(m["net"], m["from"]["pin"], m["to"]["pin"]) for m in best.advice["map"]] == [("A", "1", "2"), ("B", "2", "1")]
    assert present.advice["rotation"] == 0 and "turn" not in present.text
    assert sg.Suggestion.from_json(best.to_json()) == best

    class _Board:
        script_file = ""
        settings = settings()
    f.suggestions = ()
    sg.bind([f], _Board())
    assert [s.id for s in f.suggestions] == ["s1a", "s1b"]
    with pytest.raises(sg.EditRefused, match="advice"):
        sg.apply_suggestion(f.suggestions, "s1a", root=tmp_path)


def test_a_second_study_of_the_same_board_is_reused_and_a_changed_setting_is_not(tmp_path):
    cache = tmp_path / "pinmap" / "layout.json"
    s = settings(pins_rotations=(0.0,))
    first, r1 = study(*reversed_four(), s, cache=cache)
    again, r2 = study(*reversed_four(), s, cache=cache)
    assert (r1["reused"], r2["reused"]) == (False, True) and [str(f) for f in again] == [str(f) for f in first]
    assert again[0].facts == first[0].facts
    _, r3 = study(*reversed_four(), settings(pins_rotations=(0.0,), pins_seeds=2), cache=cache)
    assert r3["reused"] is False


def test_a_net_on_two_pins_of_the_part_stays_and_is_not_in_the_map():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "TIED", "TIED", "B"]}, {"Pm.PinPool": "1-4"})
    pads += point_pad("T1", "B", 20, 8.5) + point_pad("T2", "A", 20, 11.5) + point_pad("T3", "TIED", 20, 10)
    (f,) = study(pads, {"U1": u1}, settings(pins_rotations=(0.0,)))[0]
    assert {m["net"] for r in f.facts["rotations"] for m in r["map"]} <= {"A", "B"}


def test_a_part_at_45_degrees_with_its_pins_under_its_body_is_studied_and_its_poses_named_from_where_it_stands():
    from placemat.pinmap_input import PlacedPart
    from placemat.values import Box
    from tests.pinmap_boards import pad
    pads = [pad("U1", n, net, 10 + dx, 10 + dy) for n, (net, dx, dy) in
            enumerate([("A", -1, -1), ("B", 1, -1), ("", -1, 1), ("", 1, 1)], 1)]
    pads += point_pad("T1", "A", 25, 9) + point_pad("T2", "B", 0, 9)
    u1 = PlacedPart("U1", Box(7, 7, 13, 13), 45.0, "front", False, {"Pm.PinPool": "1-4"})
    (f,) = study(pads, {"U1": u1})[0]
    assert [t["rotation_deg"] for r in f.facts["rotations"] for t in r["turns"]] == [45.0, 135.0, 225.0, 315.0]
    assert f.facts["rotations"][0]["total"] < f.facts["present"]["total"]


def through_resistors():
    """U1 with A-D on its east side, north to south, each through a series resistor in the same order to a far net,
    and the far nets' test points due east in the opposite order: crossed only when the resistors are followed."""
    from tests.pinmap_boards import two_pad
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C", "D"]}, {"Pm.PinPool": "1-4"})
    for i, net in enumerate(["A", "B", "C", "D"]):
        pads += two_pad("R%d" % (i + 1), net, net + "_FAR", 14, 8.5 + i)
    for i, net in enumerate(["D", "C", "B", "A"]):
        pads += point_pad("TP%d" % (i + 1), net + "_FAR", 22, 8.5 + i)
    return pads, {"U1": u1}


def test_series_parts_are_followed_only_when_their_prefix_is_in_the_setting():
    found, _ = study(*through_resistors(), settings(pins_rotations=(0.0,)))
    assert [f.cause for f in found] == [C.PINS_REMAP]
    found, _ = study(*through_resistors(), settings(pins_rotations=(0.0,), pins_follow_prefixes=("FB",)))
    assert found == []


def test_a_present_map_that_breaks_a_rule_is_named_in_the_facts():
    found, _ = study(*reversed_four({"Pm.PinPool": "1-4", "Pm.PinDeny": "A:1"}), settings(pins_rotations=(0.0,)))
    (f,) = found
    assert f.facts["present_breaks"] == [{"ref": "U1", "net": "A", "pin": "1", "rule": "Pm.PinDeny"}]
    assert f.facts["rotations"][0]["breaks"] == [] and f.endswith("; the present map has A on pin 1, against Pm.PinDeny")


def test_a_pose_whose_best_is_the_present_map_carries_the_rule_it_breaks():
    """The core may keep the present map at the present pose without checking it against the rules: that row says so."""
    from dataclasses import replace
    from placemat.pinmap import group_facts
    from placemat.pinmap_core import Breakdown, study as core_study
    from tests.pinmap_boards import input_of
    s = settings(pins_rotations=(0.0,))
    inp, _ = input_of(*reversed_four({"Pm.PinPool": "1-4", "Pm.PinAllow": "A:2-4"}))
    (g,) = core_study(inp, s)
    kept = replace(g.results[0], breakdown=Breakdown(1.0, 0, 0, 0.0, 0.0, 0.0), assign=g.present_assign)
    facts = group_facts(inp, replace(g, results=(kept,)), frozenset(), s)
    assert facts["present_breaks"] == [{"ref": "U1", "net": "A", "pin": "1", "rule": "Pm.PinAllow"}]
    assert facts["rotations"][0]["breaks"] == facts["present_breaks"] and facts["rotations"][0]["map"] == []


def test_a_net_held_off_its_only_legal_pin_names_the_net_that_holds_it():
    found, _ = study(*reversed_four({"Pm.PinPool": "1-4", "Pm.PinFixed": "4", "Pm.PinAllow": "A:4"}),
                     settings(pins_rotations=(0.0,)))
    assert "U1: net A may take only pin 4, which net D holds; U1 is not studied" in found
