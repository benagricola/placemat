import dataclasses

import pytest

from placemat import arrangement_note as N
from placemat.arranged_geometry import attach
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Cell, Location, Near, Part
from tests.arrangement_support import OBSTACLE, east_doc, stamped_geometry, with_arrangement

NEAR = dict(radius=8.0, step=0.5)


def board(partner=None, settings=None, doc=None, obstacle=None, geometry=None):
    g = geometry or with_arrangement(stamped_geometry(partner=partner, obstacle=obstacle), doc)
    b = Board(g, edge_margin=0.0, keep_going=True, settings=settings or Settings())
    b.rect(width=80, height=60)
    if obstacle is not None:
        b.place(Part("obst"), at=Location(obstacle[0], obstacle[1]))
    if partner is not None:
        b.place(Part("r8"), at=Location(*partner))
    return b


def run(partner, settings=None, doc=None, **place):
    b = board(partner, settings, doc)
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR), **place)
    return b.resolve()


def test_with_links_that_favour_the_east_side_the_cell_takes_the_arrangement():
    plan = run((60.0, 30.0))
    assert plan.placement("mod").arrangement == "c_in.east"
    note = next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")
    assert note["id"] == "c_in.east" and note["score"] < note["default_score"]
    assert [t["id"] for t in note["tried"]] == ["default", "c_in.east"] and all(t["legal"] for t in note["tried"])


def test_with_the_default_at_least_as_good_the_cell_stays_default():
    assert run((18.0, 30.0)).placement("mod").arrangement == ""             # the pull is west: the module's own layout has VIN west


def test_with_no_pulls_the_cell_takes_the_default_and_scans_nothing_else():
    plan = run(None)
    assert plan.placement("mod").arrangement == ""
    assert not [n for n in plan.step("mod").notes if n["kind"] == "arrangement"]       # one scan: nothing to tell


def test_the_cost_flips_a_close_call():
    big = dataclasses.replace(Settings(), score_arrangement=1000.0)
    assert run((60.0, 30.0), big).placement("mod").arrangement == ""


def two_arrangements(partner=(60.0, 30.0)):
    g = stamped_geometry(partner=partner)
    texts = N.encode(east_doc("c_in.b", 2), 4000) + N.encode(east_doc("c_in.a", 1), 4000)
    return dataclasses.replace(g, cells={**g.cells, "mod": attach(g.cells["mod"], texts, frozenset(g.nets), g.layers)})


def test_a_tie_goes_to_the_arrangement_declared_first():
    b = board(partner=(60.0, 30.0), geometry=two_arrangements())
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    assert b.resolve().placement("mod").arrangement == "c_in.a"             # two that score alike: the one the module declared first


def test_the_first_arrangement_with_a_legal_spot_is_taken_when_the_default_has_none():
    b = board(obstacle=OBSTACLE)
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), radius=0.0, step=0.5))
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.east"
    note = next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")
    assert note["tried"][0] == {"id": "default", "score": None, "legal": False} and "default_blame" in note
    assert next(t for t in note["tried"] if t["id"] == "c_in.east")["legal"] is True


def test_a_pinned_arrangement_restricts_the_search_and_several_try_in_order():
    for ids, want in ((("default",), ""), (("c_in.east", "default"), "c_in.east"), (("default", "c_in.east"), "c_in.east")):
        assert run((60.0, 30.0), arrangements=ids).placement("mod").arrangement == want


def test_the_native_and_the_python_sweep_choose_the_same_arrangement(monkeypatch):
    from placemat import placer
    from placemat.geometry import native_status
    if not native_status().in_use:
        pytest.skip("the native module is not in use")
    a = run((60.0, 30.0)).placement("mod")
    monkeypatch.setattr(placer, "NATIVE_SWEEP", False)
    assert run((60.0, 30.0)).placement("mod") == a


def test_each_arrangement_has_its_own_scan_budget_and_a_cut_is_reported_if_any_scan_was_cut():
    tiny = dataclasses.replace(Settings(), place_step_budget=40)
    plan = run((60.0, 30.0), tiny)
    (f,) = [f for f in plan.findings if f.cause == "setup.step_budget"]
    assert f.facts["limit"] == 40 and f.facts["item"] == "mod"


# ------------------------------------------------------------------ the default among those tried, or not


def test_the_default_score_is_the_defaults_when_it_was_tried_later():
    plan = run((60.0, 30.0), arrangements=("c_in.east", "default"))
    note = next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")
    assert [t["id"] for t in note["tried"]] == ["c_in.east", "default"]
    default = next(t for t in note["tried"] if t["id"] == "default")
    assert note["default_score"] == default["score"] and note["score"] < note["default_score"]


def test_with_no_default_tried_the_note_has_no_default_score_and_its_text_names_no_default():
    b = board(partner=(60.0, 30.0), geometry=two_arrangements())
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR), arrangements=("c_in.b", "c_in.a"))
    step = b.resolve().step("mod")
    note = next(n for n in step.notes if n["kind"] == "arrangement")
    assert note["id"] in ("c_in.a", "c_in.b") and "default_score" not in note and "default_blame" not in note
    assert "default" not in [t["id"] for t in note["tried"]]
    from placemat import step_text
    assert "default" not in step_text.render(note)


# ------------------------------------------------------------------ refusals and time


def test_an_unplaced_cell_says_which_arrangement_each_refusal_came_from():
    from placemat import step_text
    b = board(obstacle=OBSTACLE)
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), radius=0.0, step=0.5), arrangements=("default",))
    plan = b.resolve()
    assert plan.placement("mod") is None
    reasons = plan.step("mod").unplaced
    assert reasons and not [r for r in reasons if "arrangement" in r]       # the default's refusals carry no arrangement
    tagged = dict(reasons[0], arrangement="c_in.east")
    text = step_text.unplaced_text([tagged])
    assert text.startswith("as c_in.east: ") and text[len("as c_in.east: "):] == step_text.unplaced_text([reasons[0]])


def test_a_step_limit_finding_names_the_arrangements_not_reached():
    from placemat import finding_text
    from placemat.findings import FindingCause as C
    facts = {"item": "mod", "elapsed_s": 3.0, "limit_s": 2.0, "pass": "coarse", "within": None, "stage": "coarse",
             "firm_pass": None, "kept": "best_so_far"}
    plain = finding_text.render(C.TIME_STEP_LIMIT, facts)
    said = finding_text.render(C.TIME_STEP_LIMIT, dict(facts, arrangements=["c_in.east", "default"]))
    assert said == plain + "; arrangements not reached: c_in.east, default"


def test_a_default_that_stands_is_said_as_the_lowest_of_those_tried():
    from placemat import step_text
    note = next(n for n in run((18.0, 30.0)).step("mod").notes if n["kind"] == "arrangement")
    beaten = next(t for t in note["tried"] if t["id"] == "c_in.east")
    assert note["id"] == "default" and beaten == {"id": "c_in.east", "score": None, "legal": True, "beaten": True}
    assert step_text.render(note) == "arrangement default: %.2f and 0.00 for it, the lowest of it and c_in.east" % note["score"]


def test_a_step_out_of_time_after_the_default_names_the_arrangements_it_did_not_reach(monkeypatch):
    import time

    from placemat import layout, timecap
    from placemat.board_geometry import CellGeom
    real = layout.scan

    def slow(occ, item, *a, **k):
        if isinstance(item, CellGeom) and item.name == "mod" and not item.arrangement:
            time.sleep(0.6)                     # the default's scan crosses the limit; its next pass gives up
        return real(occ, item, *a, **k)
    monkeypatch.setattr(layout, "scan", slow)
    timecap.configure(step_limit=0.3)
    timecap.arm(Settings())
    try:
        plan = run((60.0, 30.0))
    finally:
        timecap.reset()
    (f,) = [f for f in plan.findings if f.cause == "time.step_limit" and f.facts["item"] == "mod"]
    assert f.facts["arrangements"] == ["c_in.east"]
    assert plan.placement("mod") is None or plan.placement("mod").arrangement == ""
    assert "arrangements not reached: c_in.east" in str(f)
