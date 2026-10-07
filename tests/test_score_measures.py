"""The run score prices what the placement search prices, at the search's weights: carried vias giving
way, pushes and back-face spots. Severity is a display concern and never feeds the score."""
import dataclasses

import pytest

from placemat import score
from placemat.findings import FindingCause as C
from tests.finding_samples import finding
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Face, Location, Near, Part, PadRef
from tests.fixtures import board_geometry, footprint

CFG = Settings()


def M(**kw):
    base = {"unplaced": {}, "drc": 0, "link_excess": 0.0, "findings": {}, "crossings": {"plain+plain": 0, "plane": 0},
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
    from placemat.findings import FindingCause as C
    b = _either_board(Face.EITHER)
    plan = b.resolve()
    before = score.plan_measures(b, plan)
    for f in plan.findings:
        f.severity = "critical"
    assert score.plan_measures(b, plan) == before
    assert finding(C.COPPER_STITCH, "notice").kind == finding(C.COPPER_STITCH, "critical").kind


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
    occ = plan.occupancy
    distance = occ.geometry_of("M1").reference.location.distance(occ.geometry_of("U2").body.center)
    want = 3.2 * (2.0 / distance) ** 3 / 0.3
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
    ctx.note(C.COPPER_NOT_DRAWN, {"variant": "plane_outside", "net": "GND"})
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


# ------------------------------------------------------------ airwire on signal nets, links, area (step 2)
def _pad_distance(plan, a, b):
    pa, pb = plan.occupancy.pad_anchor(*a), plan.occupancy.pad_anchor(*b)
    return ((pa.x - pb.x) ** 2 + (pa.y - pb.y) ** 2) ** 0.5


def _two_part_board(**kw):
    fps = [footprint("U1", 10, 10, w=6, h=2, inst="u1", nets=("VIN", "GND")),
           footprint("C1", 30, 30, inst="c1", nets=("VIN", "GND"))]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, **kw)


def test_the_airwire_is_the_signal_nets_alone_and_an_impedance_net_counts_thrice():
    import dataclasses
    from placemat.board_geometry import NetClass
    from placemat.values import CopperLayer, Net
    b = _two_part_board()
    b.plane(Net("GND"), [CopperLayer.B])
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("c1"), at=Location(30, 30))
    plan = b.resolve()
    d = _pad_distance(plan, ("U1", "1"), ("C1", "1"))
    m = score.plan_measures(b, plan)
    assert m["airwire_mm"] == pytest.approx(d, abs=1e-2)         # GND, a plane's, leaves the airwire
    classes = dict(b.geometry.netclasses)
    classes["VIN"] = NetClass("SE50", 0.1, 0.2, 0.6, 0.3, tuning_profile="SE50")
    b2 = _two_part_board()
    b2.geometry = dataclasses.replace(b2.geometry, netclasses=classes)
    b2.plane(Net("GND"), [CopperLayer.B])
    b2.place(Part("u1"), at=Location(10, 10))
    b2.place(Part("c1"), at=Location(30, 30))
    m2 = score.plan_measures(b2, b2.resolve())
    assert m2["airwire_mm"] == pytest.approx(d, abs=1e-2) and m2["airwire_impedance_mm"] == pytest.approx(d, abs=1e-2)
    assert score.terms(m2, b2.settings)["airwire"] == pytest.approx(d * b2.settings.score_impedance, abs=1e-2)


def test_a_declared_link_is_measured_at_its_weight_times_the_pads_distance():
    from placemat.values import LinkWeight
    b = _two_part_board()
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("c1"), at=Location(30, 30))
    b.link(PadRef(Part("c1"), 1), PadRef(Part("u1"), 1), weight=LinkWeight.SHORT)
    plan = b.resolve()
    d = _pad_distance(plan, ("U1", "1"), ("C1", "1"))
    m = score.plan_measures(b, plan)
    assert m["link_mm"] == pytest.approx(8 * d, abs=1e-2)
    assert m["v"] == score.MEASURES_VERSION and m["area_mm2"] == 0.0
    assert "rudy_steps" in m


def test_a_fitted_frames_area_counts_on_the_axes_it_fits():
    from placemat.values import Axis
    for fit, declared in ((True, {}), (Axis.X, {"height": 40.0}), (Axis.Y, {"width": 50.0})):
        b = _two_part_board()
        b.rect(fit=fit, **declared)
        b.place(Part("u1"), at=Location(10, 10))
        b.place(Part("c1"), at=Location(30, 30))
        plan = b.resolve()
        o = plan.outline
        want = {True: (o.right - o.left) * (o.bottom - o.top),
                Axis.X: (o.right - o.left) * 40.0, Axis.Y: 50.0 * (o.bottom - o.top)}[fit]
        assert plan.fitted_axes == {True: (True, True), Axis.X: (True, False), Axis.Y: (False, True)}[fit]
        assert score.plan_measures(b, plan)["area_mm2"] == pytest.approx(want, abs=1e-3)
    fixed = _two_part_board()
    fixed.place(Part("u1"), at=Location(10, 10))
    plan = fixed.resolve()
    assert plan.fitted_axes == (False, False)


def test_whole_prices_the_incremental_terms_of_the_board_as_it_stands():
    from placemat.values import LinkWeight
    b = _two_part_board()
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("c1"), at=Location(30, 30))
    b.link(PadRef(Part("c1"), 1), PadRef(Part("u1"), 1), weight=LinkWeight.SHORT)
    plan = b.resolve()
    w = score.whole(b, plan.occupancy, plan)
    t = score.terms(score.plan_measures(b, plan), b.settings)
    for k, v in w.items():
        assert v == pytest.approx(t[k]), k
    assert {"airwire", "crossings", "link", "link_over", "push", "congestion", "area"} <= set(w)


def test_a_board_resolved_twice_keeps_no_stale_link_length():
    from placemat.values import LinkWeight
    b = _two_part_board(keep_going=True)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("c1"), at=Location(30, 30))
    b.link(PadRef(Part("c1"), 1), PadRef(Part("u1"), 1), weight=LinkWeight.SHORT)
    b.resolve()
    b._links[0].b = ("NOPE", 1)             # one end no longer on the board
    plan = b.resolve()
    assert plan.links[0].achieved_mm is None
    assert score.plan_measures(b, plan)["link_mm"] == 0.0


@pytest.mark.parametrize('moving', ['M1', 'U2'])
def test_whole_push_tracks_either_endpoint_and_forgets_lifted_pairs(moving):
    b = _push_board()
    plan = b.resolve()
    occ = plan.occupancy
    before = score.whole(b, occ, plan)['push']
    for push in plan.pushes:
        push.achieved_value = 999999.0  # presentation facts never drive live geometry
    assert score.whole(b, occ, plan)['push'] == before
    item = next(item for item in plan._items.values() if getattr(item, 'ref', None) == moving)
    occ.lift([moving])
    assert score.whole(b, occ, plan)['push'] == 0
    original = next(step.placement for step in plan.steps if plan._items.get(step.item) is item)
    occ.commit(item, dataclasses.replace(original, location=Location(original.location.x + 0.000123, original.location.y)))
    distance = occ.geometry_of('M1').reference.location.distance(occ.geometry_of('U2').body.center)
    assert score.whole(b, occ, plan)['push'] == pytest.approx(b.settings.score_push * 3.2 * (2.0 / distance) ** 3 / 0.3)
    assert score.whole(b, occ, plan)['push'] != before


def test_whole_ignores_stale_link_and_fit_facts_and_keeps_small_geometry_changes():
    from placemat.values import LinkWeight
    b = _two_part_board()
    b.rect(fit=True)
    b.place(Part('u1'), at=Location(10, 10))
    b.place(Part('c1'), at=Location(30, 30))
    b.link(PadRef(Part('c1'), 1), PadRef(Part('u1'), 1), weight=LinkWeight.SHORT)
    plan = b.resolve()
    occ = plan.occupancy
    before = score.whole(b, occ, plan)
    plan.links[0].achieved_mm = 999999.0
    assert score.whole(b, occ, plan) == before
    item = plan._items['c1']
    occ.lift(['C1'])
    lifted = score.whole(b, occ, plan)
    assert lifted['link'] == 0 and lifted['area'] < before['area']
    original = plan.placement('c1')
    occ.commit(item, dataclasses.replace(original, location=Location(30.000123, 30)))
    after = score.whole(b, occ, plan)
    assert after['area'] > before['area']
    assert 0 < after['airwire'] - before['airwire'] < 0.001
    assert after['link'] > before['link']


@pytest.mark.parametrize('moving', ['M1', 'U1'])
def test_annotation_pushes_follow_live_emission_and_sense_points(moving):
    fps = [footprint('M1', 10, 10, inst='m1', fields={'Pm.Emits': 'heat:1C@1mm^1', 'Pm.EmitsAt': '2,0'}),
           footprint('U1', 30, 10, inst='u1', fields={'Pm.Limit': 'heat:1C'})]
    b = Board(board_geometry(fps, width=60, height=60))
    b.place(Part('m1'), at=Location(10, 10))
    b.place(Part('u1'), at=Location(30, 10))
    plan = b.resolve()
    occ = plan.occupancy
    assert score.whole(b, occ, plan)['push'] == pytest.approx(b.settings.score_push / 18.0)
    item = plan._items[moving.lower()]
    original = plan.placement(moving.lower())
    occ.lift([moving])
    assert score.whole(b, occ, plan)['push'] == 0.0
    occ.commit(item, dataclasses.replace(original, location=Location(original.location.x + 1, 10)))
    expected_distance = 17.0 if moving == 'M1' else 19.0
    assert score.whole(b, occ, plan)['push'] == pytest.approx(b.settings.score_push / expected_distance)



def test_live_fit_area_includes_committed_candidate_before_step_facts_are_updated():
    b = _two_part_board()
    b.rect(fit=True)
    b.place(Part('u1'), at=Location(10, 10))
    b.place(Part('c1'), at=Location(30, 30))
    plan = b.resolve()
    occ = plan.occupancy
    area = score.whole(b, occ, plan)['area']
    step = next(s for s in plan.steps if s.item == 'c1')
    placement = step.placement
    step.placement = None
    occ.lift(['C1'])
    assert score.whole(b, occ, plan)['area'] < area
    occ.commit(plan._items['c1'], placement)
    assert score.whole(b, occ, plan)['area'] == area
    occ.lift(['C1'])
    occ.unlift(['C1'])
    assert score.whole(b, occ, plan)['area'] == area



def test_live_declared_push_exists_before_the_step_records_its_achieved_value():
    b = _push_board()
    plan = b.resolve()
    before = score.whole(b, plan.occupancy, plan)['push']
    plan.pushes.clear()
    assert score.whole(b, plan.occupancy, plan)['push'] == before
