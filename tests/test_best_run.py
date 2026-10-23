"""A run is kept as the best one only when it is better, and better is a
ruling rather than a feeling. Pure: no KiCad, no board."""
from placemat import report, score
from placemat.report import RunRecord

ITEMS = ("mcu", "buck5", "j_usb", "c_bulk")


def _rec(run_id="a1", placed=4, drc=9, findings=15, airwire=5790.0, items=ITEMS,
         landed=None, status="ok", unplaced=None, crossings=0):
    landed = items if landed is None else landed
    unplaced = max(0, len(items) - placed) if unplaced is None else unplaced
    measures = {"v": score.MEASURES_VERSION, "unplaced": {"default": unplaced} if unplaced else {}, "drc": drc, "link_excess": 0.0,
                "findings": {"label": findings} if findings else {}, "airwire_mm": airwire,
                "crossings": {"plain+plain": crossings, "plane": 0}}
    return RunRecord(run_id=run_id, board="b", status=status,
                     placements={i: {"x": 0, "y": 0} for i in landed},
                     steps=[{"item": i} for i in items],
                     metrics={"placed": placed, "drc_real": {"clearance": drc} if drc else {},
                              "findings": findings, "airwire_mm": airwire, "measures": measures})


def test_completeness_outweighs_everything_else_at_the_default_weights():
    """A run at drc 6 that placed 29 of 101
    items: fewer parts is less copper is fewer violations. Ranking on DRC
    alone crowns a board that was barely laid out."""
    whole = _rec(placed=101, unplaced=0, drc=12, findings=12, airwire=5083)
    part = _rec(placed=29, unplaced=72, drc=6, findings=3, airwire=11050)
    assert report.is_better(whole, part) and not report.is_better(part, whole)


def test_a_drc_error_is_counted_before_the_run_score_not_weighed_in_it():
    """D13: a DRC error makes a board unbuildable, so it is counted in the validity tier before the run score: one
    more violation is worse however much shorter the wire, one fewer better however much longer."""
    base = _rec(drc=12, findings=12, airwire=5083)
    assert not report.is_better(_rec(drc=13, findings=12, airwire=4783), base)
    assert report.is_better(_rec(drc=11, findings=12, airwire=6083), base)
    said = report.regression(_rec(drc=13, findings=12, airwire=4783), _rec(run_id="b7", drc=12, airwire=5083))
    assert said and "drc_new 13 (best 12)" in said and "b7" in said


def test_an_invalid_run_never_replaces_a_valid_best(tmp_path):
    """D12: a run with a DRC error does not take the place of a clean one, however short its wire."""
    path = tmp_path / "best.json"
    report.update_best(path, _rec(run_id="clean", drc=0, airwire=5000))
    assert report.update_best(path, _rec(run_id="dirty", drc=1, airwire=100)) is False
    assert report.best_for(path, report.family_of(_rec())).run_id == "clean"


def test_a_routed_run_is_ranked_by_closure_before_the_score():
    def routed(clean, airwire, phases=()):
        r = _rec(drc=0, airwire=airwire)
        r.metrics["closure_clean"] = clean
        r.metrics["route"] = {"phases": [{"final_closure_clean": c} for c in phases]}
        return r
    assert report.is_better(routed(0.95, 6000), routed(0.9, 5000))
    assert report.is_better(routed(0.9, 6000, (1.0, 0.8)), routed(0.95, 5000, (0.9, 1.0)))
    said = report.regression(routed(0.9, 5000), routed(0.95, 6000))
    assert said and "clean closure 0.9" in said


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
    failed = _rec(run_id="short", placed=3, landed=ITEMS[1:])        # otherwise the same run
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


def test_against_best_reports_nothing_for_the_first_run_and_records_it(tmp_path):
    path = tmp_path / "best.json"
    said, prior = report.against_best(path, _rec(run_id="a1"))
    assert said is None and prior is None
    assert report.best_for(path, report.family_of(_rec())).run_id == "a1"


def test_against_best_names_a_regression_and_keeps_the_old_best(tmp_path):
    path = tmp_path / "best.json"
    report.against_best(path, _rec(run_id="good", airwire=4936))
    said, prior = report.against_best(path, _rec(run_id="bad", airwire=5402))
    assert prior.run_id == "good" and "airwire" in said
    assert report.best_for(path, report.family_of(_rec())).run_id == "good"


def test_an_identical_rerun_is_neither_better_nor_worse(tmp_path):
    path = tmp_path / "best.json"
    report.against_best(path, _rec(run_id="a1"))
    said, prior = report.against_best(path, _rec(run_id="a1"))
    assert said is None and prior.run_id == "a1"


def test_a_run_that_regressed_exits_one(monkeypatch, tmp_path):
    """The user's ruling: a regression is a finding AND a non-zero exit, so it
    cannot pass unnoticed in a loop."""
    from placemat import cli, runner
    rec = _rec(run_id="bad")
    for regressed, want in (("airwire 5402 against 4936 in the best run (good)", 1), (None, 0)):
        result = runner.RunResult(rec, tmp_path, False, regressed=regressed)
        monkeypatch.setattr(runner, "run", lambda *a, _r=result, **k: _r)
        assert cli.main(["run", str(tmp_path / "x_layout.py")]) == want


def test_any_airwire_change_counts_unless_a_band_is_set():
    """A run's airwires are the same for the same board (kicad/airwires.py), so by default a difference of a few
    millimetres is a real one; a board that sets `best.airwire_noise` ties within that band."""
    import dataclasses
    from placemat.settings import Settings
    best = _rec(run_id="b1", airwire=2870.88)
    now = _rec(run_id="b1", airwire=2873.11)
    assert report.is_better(best, now) and not report.is_better(now, best)
    banded = dataclasses.replace(Settings(), best_airwire_noise=0.01)
    assert report.regression(now, best, banded) is None
    assert not report.is_better(now, best, banded) and not report.is_better(best, now, banded)


def test_an_airwire_change_beyond_the_noise_still_counts():
    best = _rec(airwire=5083.0)
    assert report.regression(_rec(airwire=5402.0), best)          # 6% worse
    assert report.is_better(_rec(airwire=4936.0), best)           # 3% better


def test_the_noise_band_is_a_setting():
    from placemat.settings import Settings
    assert Settings().best_airwire_noise == 0.0
    import dataclasses
    wide = report.regression(_rec(airwire=5402.0), _rec(airwire=5083.0),
                             dataclasses.replace(Settings(), best_airwire_noise=0.10))
    assert wide is None


def test_the_docs_say_a_regression_exits_one():
    from pathlib import Path
    api = " ".join(Path("skills/placemat/references/api.md").read_text().split())
    assert "best.json" in api
    assert "`placemat run` exits 1" in api
    assert "## To 0.15" in Path("skills/placemat/references/migration.md").read_text()


def _unmeasured(run_id="nodrc"):
    """A run made with --no-drc: it placed, but measured neither DRC nor airwire."""
    return RunRecord(run_id=run_id, board="b", status="ok",
                     placements={i: {"x": 0, "y": 0} for i in ITEMS},
                     steps=[{"item": i} for i in ITEMS],
                     metrics={"placed": 4, "findings": 15})


def test_a_run_that_measured_nothing_is_never_the_best(tmp_path):
    """A run without DRC has no airwire and no violations, and reading a
    missing number as zero made it the best possible run: every real run
    after it then "regressed" against airwire 0."""
    path = tmp_path / "best.json"
    assert report.update_best(path, _unmeasured()) is False
    assert report.best_for(path, report.family_of(_unmeasured())) is None


def test_a_run_that_measured_nothing_is_not_judged(tmp_path):
    path = tmp_path / "best.json"
    report.update_best(path, _rec(run_id="good"))
    said, prior = report.against_best(path, _unmeasured())
    assert said is None
    assert report.best_for(path, report.family_of(_rec())).run_id == "good"
    assert not report.comparable(_unmeasured()) and report.comparable(_rec())


def test_a_fully_connected_board_with_no_airwire_is_still_comparable():
    """Zero airwire after DRC is a real measurement - everything is joined -
    and must not be confused with a run that never measured."""
    done = _rec(airwire=0.0, drc=0)
    assert report.comparable(done)
    assert report.is_better(done, _rec(airwire=100.0, drc=0))


def test_an_unmeasured_best_already_on_disk_gives_way_to_a_measured_run(tmp_path):
    """0.15.0 could store a --no-drc run as the best. A measured run must not
    be judged against its missing numbers; it takes the place."""
    import json
    from dataclasses import asdict
    path = tmp_path / "best.json"
    path.write_text(json.dumps({report.family_of(_unmeasured()): asdict(_unmeasured())}))
    said, prior = report.against_best(path, _rec(run_id="real"))
    assert said is None
    assert report.best_for(path, report.family_of(_rec())).run_id == "real"
