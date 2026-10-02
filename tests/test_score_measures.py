"""The run score prices what the placement search prices, at the search's weights: carried vias giving
way, pushes and back-face spots. Severity is a display concern and never feeds the score."""
import dataclasses

import pytest

from placemat import score
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Face, Location, Near, Part, PadRef
from tests.fixtures import board_geometry, footprint

CFG = Settings()


def M(**kw):
    base = {"unplaced": {}, "drc": 0, "link_excess": 0.0, "findings": {}, "crossings": {"signal": 0, "plane": 0},
            "airwire_mm": 0.0}
    base.update(kw)
    return base


# ------------------------------------------------------------ terms from measures
def test_the_new_terms_are_priced_at_the_searchs_weights_and_an_old_record_reads_as_zero():
    cfg = dataclasses.replace(CFG, score_push=7.0, score_back_face=3.0)
    t = score.terms(M(giveway=2.5, pushes=0.4, back_face=2), cfg)
    assert t["giveway"] == pytest.approx(2.5)               # the actions' own costs are already weighed
    assert t["push"] == pytest.approx(7.0 * 0.4)
    assert t["back_face"] == pytest.approx(3.0 * 2)
    old = score.terms(M(), cfg)
    assert old["giveway"] == old["push"] == old["back_face"] == 0.0
    assert {"giveway", "push", "back_face"} <= set(score.TERMS)
    assert score.total(M(giveway=2.5), cfg) == pytest.approx(2.5)


def test_a_finding_severity_does_not_move_the_measures():
    from placemat.findings import Finding
    b = _either_board(Face.EITHER)
    plan = b.resolve()
    before = score.plan_measures(b, plan)
    for f in plan.findings:
        f.severity = "critical"
    assert score.plan_measures(b, plan) == before
    assert Finding("copper", "x", "notice").kind == Finding("copper", "x", "critical").kind


# ------------------------------------------------------------ give way
def _giveway_board(**kw):
    from tests.test_vias_give_way import _moving_board
    return _moving_board((39.1, 42.2), True, (19.5, 23.0), **kw)


def test_a_via_given_way_is_measured_at_its_actions_costs():
    b = _giveway_board()
    plan = b.resolve()
    assert plan.given_way
    m = score.plan_measures(b, plan)
    assert m["giveway"] == pytest.approx(sum(a.cost for a in plan.given_way)) and m["giveway"] > 0
    assert score.terms(m, CFG)["giveway"] == pytest.approx(m["giveway"])


def test_a_via_moved_costs_its_setting_in_the_measure():
    b = _giveway_board(settings=Settings(score_via_move=9.0))
    plan = b.resolve()
    assert "move" in {a.kind for a in plan.given_way}
    assert score.plan_measures(b, plan)["giveway"] == pytest.approx(sum(a.cost for a in plan.given_way))
    assert any(a.cost == pytest.approx(9.0) for a in plan.given_way)


def test_a_field_relay_records_its_cost_once_across_its_steps():
    from tests.test_via_field_relay import FIELD, NO_LEAVE, TOP_ROW, _board
    b = _board(FIELD, [TOP_ROW], settings=NO_LEAVE)
    plan = b.resolve()
    steps = [a for a in plan.given_way if a.kind.startswith("relay")]
    assert len(steps) == 3
    # the search: score_via_relay once and score_via_relay_moved for each via moved (plus gap and pitch terms)
    s = b.settings
    assert sum(a.cost for a in steps) == pytest.approx(s.score_via_relay + 3 * s.score_via_relay_moved)
    assert score.plan_measures(b, plan)["giveway"] == pytest.approx(sum(a.cost for a in plan.given_way))


# ------------------------------------------------------------ pushes
def _push_board():
    fps = [footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND")),
           footprint("J1", 55, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("m1"), at=Location(10, 30))
    b.place(Part("j1"), at=Location(55, 30))
    b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"))
    b.place(Part("u2"), radius=25.0, step=1.0)
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(2.0, 3.2), limit=0.3)
    return b


def test_a_push_is_measured_as_the_search_priced_it_the_whole_value_over_its_limit():
    """The search adds score_push * value / limit for every push, not only the excess over the limit."""
    b = _push_board()
    plan = b.resolve()
    assert plan.pushes
    m = score.plan_measures(b, plan)
    want = sum(p.achieved_value / p.limit for p in plan.pushes)
    assert want > 0 and m["pushes"] == pytest.approx(want, rel=1e-4)
    assert score.terms(m, CFG)["push"] == pytest.approx(CFG.score_push * want, rel=1e-4)


# ------------------------------------------------------------ back face
def _either_board(face):
    fps = [footprint("B1", 20, 20, w=30, h=30, inst="b1", nets=("N", "M")),
           footprint("R1", 5, 5, inst="r1", nets=("X", "Y"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5, keep_going=True)
    b.place(Part("b1"), at=Location(20, 20))
    b.place(Part("r1"), at=Near(Location(20, 20), radius=3.0), face=face)
    return b


def test_an_item_a_face_either_search_put_on_the_back_is_counted_and_priced_at_score_back_face():
    b = _either_board(Face.EITHER)
    plan = b.resolve()
    assert plan.placement("r1").face is Face.BACK
    assert next(s for s in plan.steps if s.item == "r1").back_face
    m = score.plan_measures(b, plan)
    assert m["back_face"] == 1
    assert score.terms(m, CFG)["back_face"] == CFG.score_back_face


def test_an_item_put_on_the_back_by_its_declaration_is_not_counted():
    fps = [footprint("R1", 5, 5, inst="r1", nets=("X", "Y"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.place(Part("r1"), at=Location(20, 20), face=Face.BACK)
    plan = b.resolve()
    assert plan.placement("r1").face is Face.BACK
    assert score.plan_measures(b, plan)["back_face"] == 0


def test_a_step_keeps_its_back_face_flag_through_the_reuse_record():
    from placemat import reuse
    plan = _either_board(Face.EITHER).resolve()
    step = next(s for s in plan.steps if s.item == "r1")
    assert reuse.step_from_json(reuse.step_to_json(step)).back_face
    old = reuse.step_to_json(step)
    del old["back_face"]
    assert not reuse.step_from_json(old).back_face


# ------------------------------------------------------------ batch notes carry their own kind
def test_a_note_a_copper_plan_raises_is_a_finding_of_its_own_kind(monkeypatch):
    """A declaration that cannot be drawn is a copper finding; a pour that needs KiCad where it is absent
    is a setup one: each is counted under its own score term."""
    from placemat.kicad import polyops
    from tests.test_pour_reach import _node
    monkeypatch.setattr(polyops, "available", lambda: False)
    plan = _node(reach=0.4).resolve()
    said = [f for f in plan.findings if "reach= needs KiCad" in f]
    assert len(said) == 1 and said[0].kind == "setup"
    assert said[0].severity == "warning"


def test_a_copper_plans_notes_take_only_findings():
    from placemat.layout import _CopperContext
    ctx = _CopperContext(None, None)
    with pytest.raises(TypeError):
        ctx.notes.append("a bare sentence has no kind")
    ctx.note("a declaration not drawn")
    assert [(f.kind, f.severity) for f in ctx.notes] == [("copper", "warning")]


# ------------------------------------------------------------ a real fixture
def test_a_real_module_resolves_and_records_the_new_measures(tmp_path):
    from tests import real_modules as rm
    from tests.conftest import _has_pcbnew
    if not _has_pcbnew():
        pytest.skip("pcbnew not importable")
    result, _, _ = rm.run(tmp_path, "usbtcpc")
    assert result.status == "ok", result.record.failure
    m = result.record.metrics["measures"]
    assert m["giveway"] >= 0 and m["pushes"] >= 0 and m["back_face"] >= 0
    assert {"giveway", "push", "back_face"} <= set(score.terms(m, CFG))
    copper = [f for f in result.record.findings if getattr(f, "kind", "") == "copper"]
    assert m["findings"].get("copper", 0) == len(copper)
