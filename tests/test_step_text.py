"""A step's notes are records: JSON values, rendered by step_text and nowhere else."""
import json

from placemat import step_text
from placemat.step_text import record, render, render_all
from placemat.refusals import Code, Refusal


def test_a_note_is_a_record_of_json_values():
    n = record("moved_off_hint", mm=8.56, why=None)
    assert n == {"kind": "moved_off_hint", "mm": 8.56}
    assert json.loads(json.dumps(n)) == n


def test_the_rank_the_priority_and_required_are_one_clause():
    notes = [record("rank", rank=3, of=24, area_mm2=5.1, area_rank=3, pins=12, pins_rank=5),
             record("priority", source="script", value="high"), record("required"), record("seeded", nets=["VDD", "GND"])]
    assert render_all(notes) == "rank 3/24 (5.1 mm2, 3rd of 24; 12 pins, 5th) (script: high), required; seeded on VDD, GND"
    assert render_all([record("required"), record("lock_held")]) == "required; held by lock"


def test_an_unplaced_step_says_why_from_its_reasons():
    reason = Refusal(Code.EDGE, what="body", box=[0, 0, 1, 1], verdict="crosses", margin_mm=0.0).to_json()
    out = render_all([record("unplaced")], [reason, {"form": "no_pocket"}])
    assert out.startswith("UNPLACED: ") and out.endswith("; no pocket fits")
    assert render_all([record("unplaced")], []) == "UNPLACED"


def test_every_kind_renders_from_its_facts():
    where = {"form": "line", "axis": "x", "at_mm": 26.5}
    sample = {
        "next_largest": {"area_mm2": 12.0}, "one_freedom": {}, "room": {"form": "near", "spots": 12.6, "cut_mm2": 3.0, "level": 3, "pitch_mm": 1.0}, "waited_for": {"partner": "u2"}, "placed_before": {"other": "u2"},
        "no_faces_declared": {}, "seeded": {"nets": ["A"]}, "seeded_by_solve": {}, "pocket": {"w_mm": 1.0, "h_mm": 2.0, "at": [3.0, 4.0]},
        "pocket_other_face": {"face": "back", "wanted": "front"}, "back_face": {"back": 1.0, "cost": 2.0, "front": 3.0},
        "lookahead_dropped": {"partners": ["a", "b"]}, "solve_hint_dropped": {"radius_mm": 3.0}, "room_kept": {"for": ["x"]},
        "where": {"where": where}, "slid": {"mm": 0.5}, "stopped_short": {"mm": 1.0, "toward": "south"}, "moved_off_hint": {"mm": 2.0},
        "block": {"members": 3}, "member_of": {"block": "q"}, "anchor_of": {"block": "q"}, "pin_row_slide": {"mm": 1.0, "ref": "U1", "pin": "4"},
        "in_front_of": {"ref": "U1", "pins": ["5", "6"]}, "rides": {"of": "u1"}, "chose_pad": {"net": "GND", "count": 2, "ref": "U1", "pad": "3"},
        "lock_held": {}, "lock_drifted": {"mm": 1.0}, "lock_released": {"reason": {"form": "no_spot_round"}},
        "push": {"source": "L1", "value": 0.5, "at_mm": 3.0, "limit": 1.0},
        "exposure": {"quantity": "field", "sensitive": "U2", "total": 0.5, "unit": "uT", "limit": 1.0, "nearest": "L1", "at_mm": 2.0},
        "cleanup": {"swapped_with": ["b"], "moved_mm": 0.3}, "stamped_regions": {"area_mm2": 2.0}, "drops": {"mode": "half", "fields": []},
        "flip_via": {"net": "GND", "span": ["F.Cu", "In1.Cu"], "flipped": ["B.Cu", "In4.Cu"], "from_layer": "In1.Cu", "to_layer": "In4.Cu",
                     "why": {"form": "standing", "from": "own_plane", "to": "no_plane"}},
        "unplaced": {}, "cut": {"at": [1.0, 2.0], "turn": 90.0}, "kept_clear": {"at": [1.0, 2.0]}, "points_off_board": {"outside": 1, "of": 4},
        "ops": {"n": 2}, "in_pad_vias": {}, "lanes": {"n": 2, "pins": ["1", "2"]}, "lanes_blocked": {"n": 1},
        "fanout": {"sides": ["north"], "depth_mm": 1.0}, "faces": {"sides": {"outward": "north"}},
        "bridge": {"net": "A", "under": "B", "at": [1.0, 2.0], "why": "first_by_name"}, "label_at": {"side": "north", "item": "J1"},
        "label_off_board": {"was": "north", "fault": {"verdict": "outside", "margin_mm": 0.0}}, "sits_on": {"hits": ["R1"]},
        "reserved": {}, "label_moved": {"from": "north", "to": "east", "by": ["R1"]}, "turned": {"rot": 90, "of": 4, "cost": 1.5},
        "locked_order": {}, "explore_before": {"other": "u1"},
        "search_budget": {"judged": 5000, "share": 0.1, "limit": 5000},
    }
    missing = sorted(set(step_text.RENDER) - set(sample) - {"rank", "priority", "required", "seeded_no_spot", "took_pocket", "vias", "split",
                                                          "refused", "refused_count"})
    assert not missing, missing
    for kind, facts in sample.items():
        text = render(record(kind, **facts))
        assert isinstance(text, str) and text, kind
        json.dumps(record(kind, **facts))


def test_nothing_a_step_says_is_kept_as_a_sentence():
    """A step's notes are dicts; the sentence is `Step.note`, a property of them."""
    from placemat.layout import Step
    s = Step("a", "part", None, None, 0.0, (record("lock_held"), record("slid", mm=0.5, units="mm")))
    assert s.note == "held by lock; slid 0.50 mm from its slot"
    assert all(isinstance(n, dict) for n in s.notes)
    assert "note" not in {f.name for f in __import__("dataclasses").fields(Step)}


def test_nothing_reads_a_sentence_of_a_step_back_for_data():
    """The studio page reads a step's notes, and no layout code writes the text of a step's note."""
    from pathlib import Path
    import re
    import placemat
    src = Path(placemat.__file__).parent
    page = (src / "studio_page.html").read_text()
    for gone in ("joinVias", "splitTop(note", "/^UNPLACED", "rank (\\d+)\\/(\\d+)", "seeded on (", "from its slot(?:"):
        assert gone not in page, gone
    layout = (src / "layout.py").read_text()
    assert not re.search(r"\.note\s*(\+?=)[^=]", layout), "a step's note is its notes' rendering: add a note with step.say(kind, ...)"
