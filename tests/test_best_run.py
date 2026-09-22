"""A run is kept as the best one only when it is better, and better is a
ruling rather than a feeling. Pure: no KiCad, no board."""
from placemat import report
from placemat.report import RunRecord

ITEMS = ("mcu", "buck5", "j_usb", "c_bulk")


def _rec(run_id="a1", placed=4, drc=9, findings=15, airwire=5790.0, items=ITEMS,
         landed=None, status="ok"):
    landed = items if landed is None else landed
    return RunRecord(run_id=run_id, board="middleweight", status=status,
                     placements={i: {"x": 0, "y": 0} for i in landed},
                     steps=[{"item": i} for i in items],
                     metrics={"placed": placed, "drc_real": {"clearance": drc} if drc else {},
                              "findings": findings, "airwire_mm": airwire})


def test_the_objective_puts_completeness_before_everything():
    """The middleweight ledger holds a run at drc 6 that placed 29 of 101
    items: fewer parts is less copper is fewer violations. Ranking on DRC
    alone crowns a board that was barely laid out."""
    whole = _rec(placed=101, drc=12, findings=12, airwire=5083)
    part = _rec(placed=29, drc=6, findings=3, airwire=11050)
    assert report.objective(whole.metrics) < report.objective(part.metrics)


def test_among_equally_complete_runs_drc_leads_then_findings_then_wire():
    base = _rec(drc=12, findings=12, airwire=5083)
    for other in (_rec(drc=13, findings=1, airwire=1.0),
                  _rec(drc=12, findings=13, airwire=1.0),
                  _rec(drc=12, findings=12, airwire=5084)):
        assert report.objective(base.metrics) < report.objective(other.metrics)


def test_a_run_that_improves_wire_without_regressing_drc_is_better():
    assert report.is_better(_rec(drc=13, findings=16, airwire=4936),
                            _rec(drc=13, findings=16, airwire=5089))


def test_a_run_with_more_drc_is_never_better_however_short_its_wire():
    assert not report.is_better(_rec(drc=1193, findings=84, airwire=2102),
                                _rec(drc=9, findings=15, airwire=5790))


def test_a_regression_names_the_metric_that_regressed():
    said = report.regression(_rec(airwire=5402), _rec(run_id="b7", airwire=4936))
    assert said and "airwire" in said and "4936" in said and "5402" in said and "b7" in said


def test_a_run_that_is_better_reports_no_regression():
    assert report.regression(_rec(airwire=4000), _rec(airwire=5000)) is None


def test_a_family_is_what_the_script_asked_for_not_what_landed():
    """When `mcu` fails to place it drops out of `placements` but keeps its
    step. Keying on what landed would put that run in a family of its own,
    where nothing is compared against it - the one run the gate is for."""
    asked = _rec(items=ITEMS)
    failed = _rec(items=ITEMS, landed=ITEMS[1:], placed=3)
    assert report.family_of(asked) == report.family_of(failed)
    assert report.family_of(_rec(items=ITEMS + ("r_extra",))) != report.family_of(asked)


def test_the_family_does_not_depend_on_the_order_things_were_placed():
    assert report.family_of(_rec(items=ITEMS)) == report.family_of(_rec(items=tuple(reversed(ITEMS))))


def test_a_run_that_failed_to_place_a_part_regresses_against_its_family(tmp_path):
    path = tmp_path / "best.json"
    report.update_best(path, _rec(run_id="whole", placed=4))
    failed = _rec(run_id="short", placed=3, landed=ITEMS[1:], drc=0, airwire=1.0)
    best = report.best_for(path, report.family_of(failed))
    assert best.run_id == "whole"
    said = report.regression(failed, best)
    assert said and "placed" in said


def test_the_first_run_of_a_family_is_its_best(tmp_path):
    path = tmp_path / "best.json"
    now = _rec(run_id="a1")
    assert report.update_best(path, now) is True
    assert report.best_for(path, report.family_of(now)).run_id == "a1"


def test_a_redesign_starts_its_own_family(tmp_path):
    path = tmp_path / "best.json"
    old = _rec(run_id="old", items=ITEMS)
    new = _rec(run_id="new", items=ITEMS + ("r_extra",), drc=40)
    report.update_best(path, old)
    assert report.update_best(path, new) is True          # nothing to lose to
    assert report.best_for(path, report.family_of(old)).run_id == "old"
    assert report.best_for(path, report.family_of(new)).run_id == "new"


def test_a_worse_run_does_not_replace_the_best(tmp_path):
    path = tmp_path / "best.json"
    report.update_best(path, _rec(run_id="good", airwire=4936))
    assert report.update_best(path, _rec(run_id="bad", airwire=5402)) is False
    assert report.best_for(path, report.family_of(_rec())).run_id == "good"


def test_a_failed_run_is_never_the_best(tmp_path):
    path = tmp_path / "best.json"
    assert report.update_best(path, _rec(run_id="broke", status="failed")) is False
    assert report.best_for(path, report.family_of(_rec())) is None


def test_the_best_file_survives_a_record_it_cannot_read(tmp_path):
    path = tmp_path / "best.json"
    path.write_text("{ not json at all")
    assert report.best_for(path, report.family_of(_rec())) is None
    assert report.update_best(path, _rec(run_id="a1")) is True


def test_a_record_written_by_a_later_version_still_loads():
    doc = {"run_id": "z9", "board": "b", "status": "ok", "a_field_from_the_future": 1}
    assert RunRecord.of(doc).run_id == "z9"
