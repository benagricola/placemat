"""The studio shows a cell's arrangement: the step note's choice and each arrangement tried, the module run's list of
arrangements, the placements a run and an explore record."""
import json

from tests.test_studio_page import needs_node, run_page

NOTE = {"kind": "arrangement", "id": "c_in.east", "score": 41.2, "cost": 0.0, "default_score": 44.9,
        "tried": [{"id": "default", "score": 44.9, "legal": True}, {"id": "c_in.east", "score": 41.2, "legal": True}],
        "text": "arrangement c_in.east: 41.20 and 0.00 for it against 44.90 as the default module stands"}


def _in_page(tmp_path, code, before=""):
    """`code` run in the page's own scope (its functions are not globals of the harness), filling `o`; `o` as a dict."""
    return run_page(tmp_path, before + "Object.assign(out, ev(%s));\n" % json.dumps("(() => { const o = {};\n" + code + "\nreturn o; })()"))


def _parts(tmp_path, *notes, unplaced="null"):
    return _in_page(tmp_path, r"""
const np = noteParts(%s, %s);
o.arr = np.arrangement;
o.rows = noteRows(np).filter(r => r[1] != null && r[1] !== "").map(r => r[0]);
o.html = noteRows(np).map(r => r.join(" ")).join("|");
o.summary = stepSummary({why: ""}, null, np);
""" % (json.dumps(list(notes)), unplaced))


@needs_node
def test_the_step_card_reads_the_arrangement_note(tmp_path):
    out = _parts(tmp_path, NOTE)
    assert out["arr"]["id"] == "c_in.east" and [(t["id"], t["legal"]) for t in out["arr"]["tried"]] == [("default", True), ("c_in.east", True)]
    assert out["rows"] == ["arrangement", "default", "c_in.east"] and out["summary"] == "arrangement c_in.east"
    assert not any("(" in r for r in out["rows"])                           # no bracketed explanation in a label
    assert '<span class="chip net">c_in.east</span>' in out["html"]
    assert "default 44.90 legal" in out["html"] and "c_in.east 41.20 legal, taken" in out["html"]


@needs_node
def test_a_note_with_no_arrangement_changes_nothing(tmp_path):
    out = _in_page(tmp_path, r"""
const np = noteParts([{kind: "rank", rank: 1, of: 2, area_mm2: 3, area_ord: 1, pins: 4, pins_ord: 1}], null);
o.arr = np.arrangement || null;
o.rows = noteRows(np).map(r => r[0]);
""")
    assert out["arr"] is None and "arrangement" not in out["rows"]


@needs_node
def test_a_pruned_arrangement_reads_as_beaten_and_an_untried_default_is_not_named(tmp_path):
    note = {"kind": "arrangement", "id": "c_in.east", "score": 41.2, "cost": 0.0,
            "tried": [{"id": "c_in.east", "score": 41.2, "legal": True}, {"id": "mirrored", "score": None, "legal": True, "beaten": True},
                      {"id": "c_in.west", "score": None, "legal": False}],
            "text": "arrangement c_in.east: 41.20 and 0.00 for it, the lowest of it and mirrored"}
    out = _parts(tmp_path, note)
    assert out["rows"] == ["arrangement", "c_in.east", "mirrored", "c_in.west"]
    rows = out["html"].split("|")
    assert rows[2].startswith("mirrored <span title=") and rows[2].endswith(">legal, beaten</span>") and "c_in.west no legal spot" in rows
    assert "default" not in out["html"]


@needs_node
def test_a_note_that_names_none_says_no_arrangement_stood(tmp_path):
    note = {"kind": "arrangement", "tried": [{"id": "default", "score": None, "legal": False}, {"id": "c_in.east", "score": None, "legal": False}],
            "text": "no arrangement has a legal spot: tried default and c_in.east"}
    out = _parts(tmp_path, note)
    assert out["arr"]["id"] is None
    assert out["html"].startswith("arrangement none has a legal spot|")
    assert "taken" not in out["html"] and "chip" not in out["html"]
    assert out["summary"] == "no arrangement has a legal spot"


@needs_node
def test_an_arrangement_the_margin_held_back_is_said_as_the_engine_says_it(tmp_path):
    text = "arrangement default: 44.90 and 0.00 for it; c_in.east 4.15 mm better, within the 4.50 mm margin; the default stands"
    note = {"kind": "arrangement", "id": "default", "score": 44.9, "cost": 0.0, "default_score": 44.9,
            "within": {"id": "c_in.east", "by": 4.15, "margin": 4.5},
            "tried": [{"id": "default", "score": 44.9, "legal": True}, {"id": "c_in.east", "score": 40.75, "legal": True}], "text": text}
    out = _parts(tmp_path, note)
    assert ("why " + text) in out["html"].split("|")
    assert "default 44.90 legal, taken" in out["html"]


@needs_node
def test_a_default_with_no_legal_spot_carries_the_engines_reason(tmp_path):
    text = "arrangement c_in.east: the default module has no legal spot (overlap x3)"
    note = {"kind": "arrangement", "id": "c_in.east", "default_blame": [{"form": "counts", "counts": [["overlap", 3]]}],
            "tried": [{"id": "default", "score": None, "legal": False}, {"id": "c_in.east", "score": None, "legal": True}], "text": text}
    out = _parts(tmp_path, note)
    assert ("why " + text) in out["html"].split("|") and "default no legal spot" in out["html"]


@needs_node
def test_a_bearing_left_unplaced_says_how_many_arrangements_it_tried(tmp_path):
    out = _in_page(tmp_path, r"""
const f = {kind: "unplaced", cause: "unplaced.bearing", facts: {item: "mod", turns: 4, arrangements: 2, counts: [["overlap", 8]]}, text: ""};
o.rows = unplacedRows(unplacedParts([], f)).map(r => r.join(" "));
""")
    assert "bearings 4 tried" in out["rows"] and "arrangements 2 tried" in out["rows"]


@needs_node
def test_the_part_card_shows_the_arrangement_a_cell_took(tmp_path):
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD);
finish(1, ["mod"]);
ev('plan().items.find(i => i.key === "mod").arrangement = "c_in.east"');
ev('selectItem("mod")'); flush();
out.card = els["#card"].innerHTML;
""")
    assert '<span class="kk">arrangement</span><span class="sep">: </span><span class="kvv"><span class="chip net">c_in.east</span>' in out["card"]


@needs_node
def test_the_run_detail_lists_the_modules_arrangements(tmp_path):
    out = _in_page(tmp_path, r"""
o.html = runDetail({drc: {}, severities: {}, timing: {}, verdicts: [], failure: null,
  arrangements: [{id: "default", offered: true, refused: 0}, {id: "mirrored", offered: false, refused: 2},
                 {id: "c_in.same", offered: false, refused: 0, duplicate_of: "default"}]});
o.none = runDetail({drc: {}, severities: {}, timing: {}, verdicts: [], failure: null});
""")
    h = out["html"]
    assert "Arrangements" in h and "Arrangements" not in out["none"]
    assert '<span class="chip good">default</span> offered' in h
    assert '<span class="chip warn">mirrored</span> refused 2' in h                      # a refusal is a warning: yellow, never red
    assert '<span class="chip notice">c_in.same</span> same as default' in h                # a notice: blue, not grey
    assert "chip bad" not in h


def test_a_run_summary_lists_the_arrangements_and_its_document_their_placements(tmp_path):
    from placemat.report import RunRecord
    from placemat.studio import Studio
    rec = RunRecord(run_id="r1", board="b", status="ok")
    rec.placements = {"mod": {"x": 1.0, "y": 2.0, "rotation": 90.0, "face": "front", "arrangement": "c_in.east"},
                      "R1": {"x": 3.0, "y": 4.0, "rotation": 0.0, "face": "front"}}
    rec.arrangements = [{"id": "default", "choices": {}, "offered": True},
                        {"id": "mirrored", "choices": {}, "offered": False, "refused": [{"form": "drc"}, {"form": "verdict"}]},
                        {"id": "c_in.same", "choices": {}, "offered": False, "duplicate_of": "default"}]
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    rec.save(run / "run.json")
    s = Studio.__new__(Studio)
    s._run_cache, s.cfg = {}, None
    s.runs_dir = lambda: tmp_path / "runs"
    assert s.run_summary(run / "run.json")["arrangements"] == [
        {"id": "default", "offered": True, "refused": 0}, {"id": "mirrored", "offered": False, "refused": 2},
        {"id": "c_in.same", "offered": False, "refused": 0, "duplicate_of": "default"}]
    items = {i["key"]: i for i in s.run_doc("r1")["items"]}
    assert items["mod"]["arrangement"] == "c_in.east" and "arrangement" not in items["R1"]


def test_an_explore_records_each_placements_arrangement():
    from placemat import explore
    from placemat.layout import Board
    from placemat.values import Cell, Location
    from tests.arrangement_support import with_arrangement
    b = Board(with_arrangement(), edge_margin=0.0, keep_going=True)
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.east")
    pl = explore._placements(b.resolve(), ["mod"])["mod"]
    assert len(pl) == 5 and pl[4] == "c_in.east"


def test_a_past_explore_does_not_move_an_item_whose_arrangement_changed():
    from placemat import explore_view
    from tests.test_studio_explore_view import _fp
    doc = {"items": [_fp("a", "U1", [[3, 2], [4, 2]]), _fp("b", "U2", [[6, 2], [7, 2]])]}
    out, moved = explore_view.move_items(doc, {"a": ([2, 2, 0, "front", ""], [10, 10, 0, "front", "c_in.east"]),
                                               "b": ([6, 2, 0, "front", "c_in.east"], [9, 2, 0, "front", "c_in.east"])}, thickness=1.6)
    assert moved == ["b"] and out["items"][0] == doc["items"][0]
    _, old = explore_view.move_items(doc, {"a": ([2, 2, 0, "front"], [10, 10, 0, "front"])}, thickness=1.6)    # a record from before arrangements
    assert old == ["a"]


@needs_node
def test_the_explore_panel_says_when_a_variant_changed_an_arrangement(tmp_path):
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD);
send("step", {id: 1, item: item("mod", 5)});
finish(1, ["mod"]);
ev('xvStart("record", "x", {focus: ["mod"], plain: {mod: [5, 0, 0, "front", ""]}, baseline: 10, order: ["mod"]})');
ev('xvAdd({seed: 3, score: 9, placements: {mod: [5, 0, 0, "front", "c_in.east"]}, t: 1}, true)');
ev('S.xv.drawn = S.xv.variants[1]');
out.html = ev("exploreHTML()");
""")
    assert "<b>mod</b>0 mm, arrangement default -&gt; c_in.east" in out["html"]


def test_a_cell_that_changed_arrangement_is_a_difference():
    from placemat.studio_diff import diff_plans
    cell = {"key": "mod", "at": [1.0, 2.0], "rotation": 0.0, "face": "front"}
    a, b = {"items": [cell]}, {"items": [dict(cell, arrangement="c_in.east")]}
    d = diff_plans(a, b, partial=True)
    (m,) = d["moved"]
    assert m["rearranged"] and not m["turned"] and m["distance"] == 0.0 and m["to"]["arrangement"] == "c_in.east"
    assert "arrangement" not in m["from"] and not d["empty"]
    assert diff_plans(b, b, partial=True)["moved"] == [] and diff_plans(a, a, partial=True)["empty"]


@needs_node
def test_the_compare_says_a_cell_changed_arrangement(tmp_path):
    out = run_page(tmp_path, r"""
hello(); started(1); send("board", BOARD); finish(1, ["mod"]);
ev('setCompare({a: "run r1", b: 1, diff: {moved: [{key: "mod", from: {at: [1, 2], rotation: 0, face: "front"}, to: {at: [1, 2], rotation: 0, face: "front", arrangement: "c_in.east"}, distance: 0, turned: false, flipped: false, rearranged: true}], added: [], removed: [], copper: {added: [], removed: []}, links: [], findings: {gained: [], lost: []}, score: null, congestion: null, empty: false}, files: {}, trace: {items: {}, lines: {}}, run: "r1"})');
ev('goTab("compare"); renderCompare()'); flush();
out.html = els["#tab-compare"].innerHTML;
""")
    assert "0 mm, arrangement default to c_in.east" in out["html"]


@needs_node
def test_the_run_detail_says_a_combination_was_excluded(tmp_path):
    out = _in_page(tmp_path, r"""
o.html = runDetail({drc: {}, severities: {}, timing: {}, verdicts: [], failure: null,
  arrangements: [{id: "default", offered: true, refused: 0},
                 {id: "pair.upright+caps_upright", offered: false, refused: 0, excluded: true}]});
""")
    h = out["html"]
    assert '<span class="chip notice">pair.upright+caps_upright</span> excluded' in h      # a notice, never red or grey
    assert "chip bad" not in h and "refused 0" not in h


def test_a_run_summary_marks_an_excluded_combination(tmp_path):
    from placemat.report import RunRecord
    from placemat.studio import Studio
    rec = RunRecord(run_id="r1", board="b", status="ok")
    rec.arrangements = [{"id": "default", "choices": {}, "offered": True},
                        {"id": "pair.upright+caps_upright", "choices": {"pair": "upright", "caps_upright": "caps_upright"},
                         "offered": False, "excluded": {"why": "both stand", "by": ["pair.upright", "caps_upright"]}}]
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    rec.save(run / "run.json")
    s = Studio.__new__(Studio)
    s._run_cache, s.cfg = {}, None
    s.runs_dir = lambda: tmp_path / "runs"
    assert s.run_summary(run / "run.json")["arrangements"] == [
        {"id": "default", "offered": True, "refused": 0},
        {"id": "pair.upright+caps_upright", "offered": False, "refused": 0, "excluded": True}]
