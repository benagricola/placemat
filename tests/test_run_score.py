"""The run score: one number in millimetres of wire, each thing that can go
wrong counted and weighted by a setting, lower better. Runs, explore
variants and the bench are judged by it."""
import dataclasses

import pytest

from placemat import score
from placemat.settings import Settings
from placemat.values import LinkWeight, Location, PadRef, Part, Priority
from tests.fixtures import board_geometry, footprint

CFG = Settings()


def M(**kw):
    base = {"unplaced": {}, "drc": 0, "link_excess": 0.0, "findings": {}, "crossings": {"signal": 0, "plane": 0},
            "airwire_mm": 0.0}
    base.update(kw)
    return base


def test_each_term_is_its_measure_times_its_weight():
    cfg = dataclasses.replace(CFG, score_crossing=2.0)
    t = score.terms(M(unplaced={"default": 1, "high": 1, "low": 2}, drc=3, link_excess=0.5,
                      findings={"fixed": 1, "copper": 2, "label": 1, "setup": 4, "escape_walled": 1},
                      crossings={"signal": 10, "plane": 6}, airwire_mm=123.0), cfg)
    assert t["unplaced"] == pytest.approx(cfg.score_unplaced * (1 * 1 + 1 * 2 + 2 * 0.5))
    assert t["drc"] == 3 * cfg.score_drc
    assert t["link_over"] == pytest.approx(0.5 * cfg.score_link_over)
    assert t["fixed"] == cfg.score_fixed and t["copper"] == 2 * cfg.score_copper and t["label"] == cfg.score_label
    assert t["setup"] == 0.0                                    # the same every run: weighs nothing by default
    assert t["escape_walled"] == cfg.score_escape_walled
    assert t["crossings"] == pytest.approx(2.0 * (10 + 6 * cfg.score_crossing_plane))
    assert t["airwire"] == 123.0
    assert score.total(M(drc=1, airwire_mm=10.0), cfg) == pytest.approx(cfg.score_drc + 10.0)


def test_the_defaults_rank_an_unplaced_part_above_a_walled_pad_above_a_closed_escape_above_a_crossed_one():
    assert CFG.score_unplaced > CFG.score_escape_walled > CFG.score_escape_closed > CFG.score_escape_crossed > 0
    assert CFG.score_priority_high == 2.0 and CFG.score_priority_default == 1.0 and CFG.score_priority_low == 0.5


def test_runs_within_the_noise_band_tie_and_the_deciding_term_is_named():
    a = M(airwire_mm=1000.0)
    b = M(airwire_mm=1005.0)                                    # within 1% of airwire
    assert score.compare(a, b, CFG)[0] == 0
    c = M(airwire_mm=1000.0, findings={"label": 1})
    sign, term = score.compare(c, a, CFG)
    assert sign == 1 and term == "label"
    sign, term = score.compare(a, c, CFG)
    assert sign == -1 and term == "label"


def test_a_changed_weight_reranks_two_recorded_runs_without_running_either():
    fewer_crossings = M(crossings={"signal": 10, "plane": 0}, airwire_mm=1000.0)
    shorter_wire = M(crossings={"signal": 30, "plane": 0}, airwire_mm=960.0)
    light = dataclasses.replace(CFG, score_crossing=1.0)
    heavy = dataclasses.replace(CFG, score_crossing=5.0)
    assert score.compare(shorter_wire, fewer_crossings, light)[0] == -1
    assert score.compare(shorter_wire, fewer_crossings, heavy)[0] == 1


def _board():
    fps = [footprint("U1", 10, 10, w=6, h=2, inst="u1", nets=("VIN", "OUT")),
           footprint("C1", 40, 40, inst="c1", nets=("VIN", "GND")),
           footprint("R1", 40, 45, inst="r1", nets=("OUT", "GND"))]
    from placemat.layout import Board
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True)


def test_a_plan_is_measured_an_unplaced_part_once_by_its_priority_and_a_link_by_how_far_over():
    from placemat.values import Near
    b = _board()
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("c1"), at=Location(30, 30))
    b.link(PadRef(Part("c1"), "VIN"), PadRef(Part("u1"), "VIN"), weight=LinkWeight.SHORT, limit_mm=2.0)
    b.place(Part("r1"), at=Near(Location(10, 10), radius=0.5), priority=Priority.HIGH)     # no room there
    plan = b.resolve()
    m = score.plan_measures(b, plan)
    assert m["unplaced"] == {"high": 1}
    assert "unplaced" not in m["findings"] and "link_over" not in m["findings"]
    link = next(l for l in plan.links if l.limit_mm)
    assert m["link_excess"] == pytest.approx((link.achieved_mm - 2.0) * int(LinkWeight.SHORT))
    t = score.terms(m, CFG)
    assert t["unplaced"] == pytest.approx(CFG.score_unplaced * CFG.score_priority_high)


def test_a_plan_measures_its_own_crossings_with_plane_nets_apart():
    from placemat.values import CopperLayer, Net
    fps = [footprint("A1", 10, 10, inst="a1", nets=("S1", "GND")), footprint("A2", 20, 20, inst="a2", nets=("GND", "S1")),
           footprint("B1", 10, 20, inst="b1", nets=("S2", "S3")), footprint("B2", 20, 10, inst="b2", nets=("S3", "S2"))]
    from placemat.layout import Board
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.plane(Net("GND"), [CopperLayer.B])
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    m = score.plan_measures(b, b.resolve())
    assert m["crossings"]["signal"] >= 1                     # S1 (a1-a2) crosses S2/S3 (b1-b2) on the diagonals
    assert m["crossings"]["plane"] >= 1                      # GND (a1-a2) crosses them too, counted apart
    assert m["airwire_mm"] > 0


def test_an_old_record_without_the_measures_is_no_best():
    from placemat.report import RunRecord, comparable
    old = RunRecord.of({"run_id": "x", "board": "b", "status": "ok", "metrics": {"placed": 3, "drc_real": {}, "findings": 0,
                                                                   "airwire_mm": 10.0}})
    assert not comparable(old)
