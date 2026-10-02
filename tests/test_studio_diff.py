"""Comparing two plans (as JSON), two texts, and tracing one to the other."""
import copy

from placemat.layout import Board
from placemat.preview_json import declared_sites, plan_json
from placemat.studio_diff import (declaration_span, diff_plans, line_diff, trace, unified_diff,
                                  with_spans)
from placemat.values import CopperLayer, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _plan(u1_at=(30, 10), drop_r1=False, extra_track=False):
    fps = [footprint("J1", 3, 10, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("U1", 30, 10, w=6, h=6, inst="u1", nets=("A", "B")),
           footprint("R1", 40, 15, w=2, h=1, inst="r1", nets=("B", "C"))]
    b = Board(board_geometry(fps, width=60, height=20), edge_margin=0.5, keep_going=True)
    b.place(Part("j1"), at=Location(3, 10))
    b.place(Part("u1"), at=Location(*u1_at))
    if not drop_r1:
        b.place(Part("r1"), at=Location(40, 15))
    if extra_track:
        b.track(Net("A"), [PadRef(Part("j1"), 1), (6.0, 18.0)], layer=CopperLayer.F)
    plan = b.resolve()
    return plan_json(plan, declared_sites(b))


def test_nothing_changed_is_empty():
    d = diff_plans(_plan(), _plan())
    assert d["empty"] and d["moved"] == d["added"] == d["removed"] == []


def test_a_moved_item_has_both_places():
    d = diff_plans(_plan(), _plan(u1_at=(34, 10)))
    assert [m["key"] for m in d["moved"]] == ["u1"]
    m = d["moved"][0]
    assert m["from"]["at"] == [30.0, 10.0] and m["to"]["at"] == [34.0, 10.0]
    assert abs(m["distance"] - 4.0) < 1e-6 and not m["turned"] and not m["flipped"]
    assert not d["empty"] and d["added"] == [] and d["removed"] == []


def test_added_and_removed_items():
    a, b = _plan(), _plan(drop_r1=True)
    gone = diff_plans(a, b)
    assert [r["key"] for r in gone["removed"]] == ["r1"] and gone["added"] == []
    back = diff_plans(b, a)
    assert [r["key"] for r in back["added"]] == ["r1"] and back["removed"] == []
    assert gone["removed"][0]["at"] == [40.0, 15.0]


def test_turned_and_flipped_are_said():
    a = _plan()
    b = copy.deepcopy(a)
    u1 = next(i for i in b["items"] if i["key"] == "u1")
    u1["rotation"], u1["face"] = 90.0, "back"
    m = diff_plans(a, b)["moved"][0]
    assert m["turned"] and m["flipped"] and m["distance"] == 0.0


def test_copper_is_compared_as_it_is_drawn_in_each_state():
    d = diff_plans(_plan(), _plan(extra_track=True))
    assert {c["t"] for c in d["copper"]["added"]} == {"track"} and d["copper"]["removed"] == []
    back = diff_plans(_plan(extra_track=True), _plan())
    assert {c["t"] for c in back["copper"]["removed"]} == {"track"} and back["copper"]["added"] == []


def test_findings_gained_and_lost():
    a, b = _plan(), _plan()
    a["findings"] = [{"text": "u1 (fixed): x", "kind": "fixed", "at": None, "item": "u1"}]
    b["findings"] = [{"text": "r1 (fixed): y", "kind": "fixed", "at": None, "item": "r1"}]
    d = diff_plans(a, b)
    assert [f["text"] for f in d["findings"]["gained"]] == ["r1 (fixed): y"]
    assert [f["text"] for f in d["findings"]["lost"]] == ["u1 (fixed): x"]


def test_the_score_change_is_shown_when_both_have_one():
    a, b = _plan(), _plan()
    a["score"], b["score"] = {"total": 10.0, "terms": {"airwire": 10.0}}, {"total": 7.5, "terms": {"airwire": 7.5}}
    assert diff_plans(a, b)["score"] == {"a": 10.0, "b": 7.5, "delta": -2.5}
    a["score"] = None
    assert diff_plans(a, b)["score"] is None


def test_a_partial_set_of_placements_compares_only_what_it_holds():
    """An explore variant lists the items it varied: the rest are not removed."""
    full = _plan()
    variant = {"items": [{"key": "u1", "at": [34.0, 10.0], "rotation": 0.0, "face": "front"}]}
    d = diff_plans(full, variant, partial=True)
    assert [m["key"] for m in d["moved"]] == ["u1"] and d["removed"] == [] and d["added"] == []
    assert d["copper"] == {"added": [], "removed": []}


def test_it_reads_a_bare_placement_set():
    a = {"items": [{"key": "p", "at": [0, 0], "rotation": 0, "face": "front"}]}
    b = {"items": [{"key": "p", "at": [1, 0], "rotation": 0, "face": "front"}, {"key": "q", "at": [5, 5], "rotation": 0, "face": "back"}]}
    d = diff_plans(a, b)
    assert [m["key"] for m in d["moved"]] == ["p"] and [x["key"] for x in d["added"]] == ["q"]


OLD = "a = 1\nb = place(\n    x,\n    at=1)\nc = 3\n"
NEW = "a = 1\nb = place(\n    x,\n    at=2)\nc = 3\nd = 4\n"


def test_line_diff_numbers_both_sides_and_marks_changed_lines():
    d = line_diff(OLD, NEW)
    assert d["changed_new"] == [4, 6] and d["changed_old"] == [4]
    assert d["added"] == 2 and d["removed"] == 1
    rows = [r for h in d["hunks"] for r in h["lines"]]
    assert {"tag": "-", "old": 4, "new": None, "text": "    at=1)"} in rows
    assert {"tag": "+", "old": None, "new": 4, "text": "    at=2)"} in rows
    assert {"tag": " ", "old": 1, "new": 1, "text": "a = 1"} in rows


def test_line_diff_of_equal_texts_has_no_hunks():
    d = line_diff(OLD, OLD)
    assert d["hunks"] == [] and d["changed_new"] == [] and d["added"] == 0


def test_unified_diff_is_the_usual_text():
    text = unified_diff(OLD, NEW, "s.py")
    assert text.startswith("--- s.py\n+++ s.py\n") and "-    at=1)\n+    at=2)\n" in text


def test_a_declaration_is_its_statement_whatever_line_the_call_names():
    assert declaration_span(OLD, 3) == (2, 4)
    assert declaration_span(OLD, 2) == (2, 4)
    assert declaration_span(OLD, 5) == (5, 5)
    assert declaration_span("for i in x:\n    y(\n      i)\n", 1) == (1, 1)
    assert declaration_span("def f(:\n", 1) == (1, 1)


def test_a_changed_line_traces_to_the_item_it_moved_and_back():
    a, b = _plan(), _plan(u1_at=(34, 10))
    texts_a = {a["items"][0]["file"]: OLD}
    for doc, text in ((a, OLD), (b, NEW)):
        for item in doc["items"]:
            item["file"], item["line"] = "s.py", 3            # every item declared on the multi-line statement
    d = diff_plans(a, b)
    files = {"s.py": line_diff(OLD, NEW)}
    t = trace(d, with_spans(a, {"s.py": OLD}), with_spans(b, {"s.py": NEW}), files)
    assert t["items"]["u1"]["lines"] == {"new": [4], "old": [4]}
    assert t["lines"]["s.py"]["new"]["4"] == ["u1"] and t["knock_on"] == []


def test_a_moved_item_with_no_changed_line_is_knock_on():
    a, b = _plan(), _plan(u1_at=(34, 10))
    for doc in (a, b):
        for item in doc["items"]:
            item["file"], item["line"] = "s.py", 1
    t = trace(diff_plans(a, b), with_spans(a, {"s.py": OLD}), with_spans(b, {"s.py": NEW}), {"s.py": line_diff(OLD, NEW)})
    assert t["knock_on"] == ["u1"] and t["items"]["u1"]["lines"] == {"new": [], "old": []}


def test_with_spans_gives_every_item_its_statement():
    doc = _plan()
    for item in doc["items"]:
        item["file"], item["line"] = "s.py", 3
    spans = with_spans(doc, {"s.py": OLD})
    assert all(i["span"] == [2, 4] for i in spans["items"])
    assert "span" not in doc["items"][0]            # the original is left alone
