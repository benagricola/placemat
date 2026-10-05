"""The pin map study's finding: a `pins.remap` notice when a map saves `pins.gain_min` of the present total, its facts
as data and its sentence rendered from them; a `setup.pins` warning for an entry the study ran without; the suggestion
that carries the map and the turn and writes nothing; and a study reused when what it reads has not changed."""
import json

import pytest

from placemat import suggestions as sg
from placemat.findings import FindingCause as C, FindingKind
from placemat.pinmap import study_findings
from tests.pinmap_boards import complete, point_pad, quad, reversed_four, settings


def study(pads, parts, s=None, copper=frozenset(), cache=None):
    return study_findings(pads, complete(pads, parts), {}, frozenset(), {}, {}, s or settings(), copper, cache)


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
    assert f.facts["routed"] == ["A"] and f.endswith("; 1 of the nets it moves has copper now: A")


def test_a_study_past_its_wall_clock_guard_is_a_warning_with_no_map_and_is_not_kept(tmp_path):
    cache = tmp_path / "pinmap.json"
    found, _ = study(*reversed_four(), settings(pins_rotations=(0.0,), pins_guard_ms=0.001, pins_budget_steps=500),
                     cache=cache)
    (f,) = found
    assert (f.cause, f.severity, f.facts["code"]) == (C.SETUP_PINS, "warning", "study_slow")
    assert (f.facts["guard_ms"], f.facts["steps"], f.facts["budget_steps"]) == (0.001, 0, 500)
    assert f == ("U1: the pin map study ran past its wall-clock guard, pins.guard_ms of 0.001 ms, after 0 of its 500 "
                 "steps; it gives no map, since one cut short by the time is not the study's answer")
    _, again = study(*reversed_four(), settings(pins_rotations=(0.0,)), cache=cache)
    assert again["reused"] is False


def test_a_spent_budget_is_said_in_steps():
    found, _ = study(*reversed_four(), settings(pins_rotations=(0.0,), pins_budget_steps=30))
    (f,) = found
    assert (f.facts["budget_out"], f.facts["steps"], f.facts["budget_steps"]) == (True, 30, 30)
    assert f.endswith("; the study stopped at its budget of 30 steps after 1 of 1 poses")


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


def test_a_present_map_that_breaks_a_rule_is_named_in_the_facts_and_is_a_setup_warning():
    found, _ = study(*reversed_four({"Pm.PinPool": "1-4", "Pm.PinDeny": "A:1"}), settings(pins_rotations=(0.0,)))
    (warn,) = [f for f in found if f.cause is C.SETUP_PINS]
    (f,) = [f for f in found if f.cause is C.PINS_REMAP]
    assert warn == "U1: net A stands on pin 1, against its Pm.PinDeny; the capture breaks its own rule"
    assert f.facts["present_breaks"] == [{"ref": "U1", "net": "A", "pin": "1", "rule": "Pm.PinDeny"}]
    assert f.facts["rotations"][0]["breaks"] == []


def test_a_present_map_that_breaks_a_rule_is_reported_when_no_remap_is():
    """A and B leave in the order their targets lie, so no map saves anything, and A stands on a pin its rule bars."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "", ""]}, {"Pm.PinPool": "1-4", "Pm.PinAllow": "A:2-4"})
    pads += point_pad("T1", "A", 20, 8.5) + point_pad("T2", "B", 20, 9.5)
    found, _ = study(pads, {"U1": u1}, settings(pins_rotations=(0.0,)))
    assert [f.cause for f in found] == [C.SETUP_PINS]
    assert found[0].facts["code"] == "present_breaks" and (found[0].facts["pin"], found[0].facts["rule"]) == ("1", "Pm.PinAllow")
    assert found[0] == "U1: net A stands on pin 1, against its Pm.PinAllow; the capture breaks its own rule"


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


def test_a_saving_exactly_at_the_gain_min_is_reported():
    from dataclasses import replace
    from placemat.pinmap import group_facts
    from placemat.pinmap_core import Breakdown, study as core_study
    from tests.pinmap_boards import input_of
    s = settings(pins_rotations=(0.0,), pins_gain_min=0.25)
    inp, _ = input_of(*reversed_four())
    (g,) = core_study(inp, s)
    g = replace(g, present=Breakdown(8.0, 0, 0, 0.0, 0.0, 0.0),
                results=(replace(g.results[0], breakdown=Breakdown(6.0, 0, 0, 0.0, 0.0, 0.0)),))
    assert group_facts(inp, g, frozenset(), s) is not None
    assert group_facts(inp, g, frozenset(), replace(s, pins_gain_min=0.2501)) is None


@pytest.mark.parametrize("kept", ["{not json", '{"version": 0, "digest": "x", "findings": []}'])
def test_a_cache_that_cannot_be_read_or_is_of_another_version_is_studied_again(tmp_path, kept):
    from placemat import pinmap
    cache = tmp_path / "pinmap.json"
    s = settings(pins_rotations=(0.0,))
    first, _ = study(*reversed_four(), s, cache=cache)
    doc = json.loads(cache.read_text())
    if kept.startswith("{\"version"):
        doc["version"] = pinmap.CACHE_VERSION + 1
        cache.write_text(json.dumps(doc))
    else:
        cache.write_text(kept)
    again, record = study(*reversed_four(), s, cache=cache)
    assert record["reused"] is False and [str(f) for f in again] == [str(f) for f in first]
    assert json.loads(cache.read_text())["version"] == pinmap.CACHE_VERSION


def test_a_cache_that_cannot_be_written_leaves_the_findings(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    found, record = study(*reversed_four(), settings(pins_rotations=(0.0,)), cache=blocker / "pinmap.json")
    assert [f.cause for f in found] == [C.PINS_REMAP] and record["reused"] is False


def test_settings_the_study_does_not_read_keep_the_cache():
    from placemat.pinmap import digest
    from tests.pinmap_boards import input_of
    inp, problems = input_of(*reversed_four())
    s = settings()
    d = digest(inp, problems, frozenset(), s)
    assert digest(inp, problems, frozenset(), settings(pins_explore_top=7, pins_probe_budget_steps=9000)) == d
    assert digest(inp, problems, frozenset(), settings(pins_seeds=3)) != d
    assert digest(inp, problems, frozenset(), settings(pins_budget_steps=77)) != d
    assert digest(inp, problems, frozenset(), settings(pins_guard_ms=77.0)) != d


def test_a_pose_on_the_other_face_is_named_as_placemat_flips_a_part_standing_at_90_degrees():
    """The rotation reported for a flipped pose, and the advice's turn, are the ones whose declaration
    (geometry.pose_transform from where the part stands) puts the pads where the study scored them."""
    from placemat.geometry import pose_transform
    from placemat.pinmap_geom import Pose
    from placemat.placement import Placement
    from placemat.values import Face, Location
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C", "D"]}, {"Pm.PinPool": "1-4"}, rotation=90.0, may_flip=True)
    for i, net in enumerate(["D", "C", "B", "A"]):
        pads += point_pad("TP%d" % (i + 1), net, 8.5 + i, 0)
    (f,) = study(pads, {"U1": u1}, settings(pins_faces=True))[0]
    present = Placement(Location(10, 10), 90.0, Face.FRONT)
    mine = [p for p in pads if p.ref == "U1"]

    def declared(turn):
        """The back-face rotation whose declaration puts U1's pads where the flipped pose `turn` has them."""
        studied = Pose(10, 10, turn, True)
        want = [studied.to_board(p.anchor.x - 10, p.anchor.y - 10) for p in mine]
        for r in (0.0, 90.0, 180.0, 270.0):
            moved = pose_transform(present, Placement(Location(10, 10), r, Face.BACK))
            if all(moved.apply((p.anchor.x, p.anchor.y)) == pytest.approx(w, abs=1e-6) for p, w in zip(mine, want)):
                return r
        raise AssertionError("no declared rotation gives the studied pads")

    flipped = [i for i, r in enumerate(f.facts["rotations"]) if r["turns"][0]["flip"]]
    assert len(flipped) == 4
    for i in flipped:
        (t,) = f.facts["rotations"][i]["turns"]
        assert (t["face"], t["rotation_deg"]) == ("back", declared(t["turn_deg"]))
        advice = sg.pin_advice(f.facts, i)
        assert advice["turns"] == [t]
        assert "urn U1 to %g degrees on the back" % t["rotation_deg"] in sg.pin_advice_text(advice)
