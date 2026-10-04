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
    assert f.facts["arrangements"] == ["c_in.east"] and f.facts["kept"] == "unplaced"
    assert plan.placement("mod") is None                # the default's scan gave up at its coarse pass, before any spot
    assert "arrangements not reached: c_in.east" in str(f)


# ------------------------------------------------------------------ fix round 1


def _consistent(note):
    """The note's numbers are those the choice compared: the winner's row is the lowest scored one (the first of equals),
    its score and cost add to that row's, and the default's score is the default row's."""
    rows = {t["id"]: t for t in note["tried"]}
    won = rows[note["id"]]
    assert won["score"] == pytest.approx(note["score"] + note["cost"])
    scored = [t for t in note["tried"] if t["score"] is not None]
    assert won["score"] == min(t["score"] for t in scored)
    assert next(t for t in scored if t["score"] == won["score"])["id"] == note["id"]
    if "default_score" in note:
        assert rows["default"]["score"] == pytest.approx(note["default_score"])
    assert not [t for t in note["tried"] if t["score"] is not None and t["score"] >= 1e5]


@pytest.mark.parametrize("partner", [(50.0, 42.0), (60.0, 30.0), (18.0, 30.0), (40.0, 52.0)])
def test_an_either_face_cell_notes_each_arrangements_total_with_the_back_face_cost(partner):
    from placemat.values import Face
    cost = dataclasses.replace(Settings(), score_back_face=2.0)
    b = board(partner, cost)
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR), face=Face.EITHER)
    plan = b.resolve()
    note = next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")
    _consistent(note)


def test_the_reviewers_case_the_default_on_the_back_is_noted_with_the_back_face_cost():
    from placemat.values import Face
    b = board((50.0, 42.0), dataclasses.replace(Settings(), score_back_face=2.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR), face=Face.EITHER)
    plan = b.resolve()
    note = next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")
    alone = board((50.0, 42.0), dataclasses.replace(Settings(), score_back_face=2.0))
    alone.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR), face=Face.EITHER, arrangements=("default",))
    default = alone.resolve().placement("mod")
    if default.face is Face.BACK:                       # the default stood on the back: its noted score carries the 2.0
        assert note["default_score"] >= 2.0
    if note["id"] != "default":
        assert note["score"] + note["cost"] < note["default_score"]
    else:
        assert all(t["score"] is None or t["score"] >= note["score"] for t in note["tried"])


def test_an_arrangement_whose_front_is_pruned_and_whose_back_wins_is_noted_by_the_backs_total(monkeypatch):
    from placemat import layout, step_text
    from placemat.values import Face
    real = layout.scan

    def pruned_front(occ, item, hint, *a, **k):
        r = real(occ, item, hint, *a, **k)
        if getattr(item, "arrangement", "") == "c_in.east" and r.chosen is not None:
            r.score = r.score + layout.PRUNED if hint.face is Face.FRONT else 1.0     # the front cut by the floor, the back cheap
        return r
    monkeypatch.setattr(layout, "scan", pruned_front)
    b = board((60.0, 30.0), dataclasses.replace(Settings(), score_back_face=2.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR), face=Face.EITHER)
    plan = b.resolve()
    p = plan.placement("mod")
    assert p.arrangement == "c_in.east" and p.face is Face.BACK
    notes = {n["kind"]: n for n in plan.step("mod").notes}
    assert notes["back_face"] == {"kind": "back_face", "back": 1.0, "cost": 2.0, "front_beaten": True}
    assert "1000" not in step_text.render(notes["back_face"])
    _consistent(notes["arrangement"])
    assert next(t for t in notes["arrangement"]["tried"] if t["id"] == "c_in.east")["score"] == pytest.approx(3.0)


def test_a_row_cut_by_the_bound_while_its_vias_gave_way_is_beaten_not_without_room():
    from placemat.layout import _Tried
    from placemat.placer import ScanResult
    from placemat.placement import Placement
    from placemat.values import Face
    b = board((60.0, 30.0))
    hint = Placement(Location(40.0, 30.0), 0.0, Face.FRONT)
    i = types_intent(b)
    won = ScanResult(hint, hint, 10)
    won.score = 5.0
    default = _Tried(i, hint, 8.0, won, None, None, object())
    east = _Tried(b._arranged(i, "c_in.east"), hint, 8.0, ScanResult(None, hint, 10, bound=3), None, None, object())
    note = b._arrangement_note("", default, [("", default), ("c_in.east", east)], 0.0)
    assert note["tried"][1] == {"id": "c_in.east", "score": None, "legal": True, "beaten": True}


def types_intent(b):
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    return next(i for i in b._placements() if i.key == "mod")


def test_a_required_cell_is_placed_when_only_an_arrangement_has_a_legal_spot():
    b = board(obstacle=OBSTACLE)
    b.keep_going = False
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), radius=0.0, step=0.5), required=True)
    assert b.resolve().placement("mod").arrangement == "c_in.east"


# A board walled off but for a hole north-east and the corner the partner stands in. The default (9.5 x 4 mm) fits neither; the
# arrangement c_in.north, c_in stood above u1 (6 x 6 mm), fits the hole.

def north_doc():
    from placemat.placement import Placement
    from placemat.values import Face
    from tests.arrangement_support import DEFAULT_C_IN, DEFAULT_U1
    north = Placement(Location(6.0, -0.2), 0.0, Face.FRONT)
    return N.document("c_in.north", {"c_in": "north"}, [("c_in", north, DEFAULT_C_IN), ("u1", DEFAULT_U1, DEFAULT_U1)], [], [],
                      order=1)


def walled(partner, hole_bottom):
    from tests.fixtures import board_geometry, footprint
    walls = [(43.15, 11.85, 73.7, 23.7), (3.0, 32.4, 6.0, 55.2), (32.0, 42.0, 51.4, 36.0), (73.15, 42.0, 13.7, 36.0),
             (62.0, (hole_bottom + 0.3 + 60.0) / 2, 8.0, 60.0 - hole_bottom - 0.3)]
    fps = [footprint("C1", 31.0, 13.0, w=3, h=1.6, nets=("mod.VIN", "mod.GND"), cell="mod", inst="mod.c_in"),
           footprint("U1", 36.0, 13.0, w=6, h=4, nets=("mod.VIN", "mod.OUT"), cell="mod", inst="mod.u1"),
           footprint("R8", partner[0], partner[1], w=3, h=1.6, nets=("mod.VIN", "GND"), inst="r8")]
    fps += [footprint("W%d" % k, x, y, w=w, h=h, nets=("GND", "GND"), inst="w%d" % k) for k, (x, y, w, h) in enumerate(walls)]
    g = board_geometry(fps, cells=["mod"], extra_nets=("mod.GND", "mod.OUT", "GND"), width=80, height=60)
    g = with_arrangement(g, north_doc())
    b = Board(g, edge_margin=0.0, keep_going=True, settings=Settings())
    b.rect(width=80, height=60)
    for k, (x, y, _, _) in enumerate(walls):
        b.place(Part("w%d" % k), at=Location(x, y))
    b.place(Part("r8"), at=Location(*partner))
    return b


def test_a_default_with_no_pocket_is_blamed_for_it_in_the_note():
    from placemat import step_text
    b = walled((62.0, 33.0), 35.3)
    b.place(Cell("mod"))
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.north"
    note = next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")
    assert note["tried"][0] == {"id": "default", "score": None, "legal": False}
    assert note["default_blame"] == [{"form": "pocket", "variant": "any_rotation", "w_mm": pytest.approx(9.5, abs=0.5),
                                      "h_mm": pytest.approx(4.0, abs=0.5), "face": "front"}]
    assert "no pocket fits" in step_text.render(note)


def test_the_lowest_of_list_names_only_arrangements_with_room():
    from placemat import step_text
    note = {"kind": "arrangement", "id": "c_in.a", "score": 3.0, "cost": 0.0,
            "tried": [{"id": "c_in.b", "score": None, "legal": False}, {"id": "c_in.a", "score": 3.0, "legal": True},
                      {"id": "c_in.c", "score": None, "legal": True, "beaten": True}]}
    assert step_text.render(note) == "arrangement c_in.a: 3.00 and 0.00 for it, the lowest of it and c_in.c"


def test_a_cell_whose_default_fits_no_pocket_takes_the_pocket_of_an_arrangement_that_fits_one():
    b = walled((2.0, 1.5), 32.3)
    b.place(Cell("mod"))
    plan = b.resolve()
    p = plan.placement("mod")
    assert p is not None and p.arrangement == "c_in.north"
    assert "mod" in plan.pocketed
    assert 57.7 < p.location.x < 66.3 and 23.7 < p.location.y < 32.3
