"""Completed invalid copper retains measurements without certifying a board."""
import json
import subprocess

import pytest

from fixtures.reference import fetch, place_ref, prepare, route_ref

VERSIONS = {"placemat": "p", "krt": "k", "pcb": "z"}
BOARD = fetch.Board(name="x", repo="github:o/r", commit="0" * 40, files={}, board="x.kicad_pcb",
                    licence="MIT", tests=("a",), phases=(), fixed=(), human_track_mm=0.2, kicad5=False)


def completed_report(folder):
    folder.mkdir(parents=True, exist_ok=True)
    pcb = folder / "routed.kicad_pcb"
    pcb.write_text("controlled new copper")
    record = folder / "route_record.json"
    report = {"valid": False, "closure": 0.9, "closure_clean": 0.75, "open_before": 4, "open_after": 1,
              "seconds": 8.0, "vias": 12, "track_mm": 67.5, "drc_after": {"invalid_outline": 1},
              "violations": {}, "invalid_reason": "original outline invalid", "routed_pcb": str(pcb),
              "record": str(record), "phases": [{"name": "signals", "asked": 4, "final_asked": 4,
                  "final_joined": 1, "final_connected": 3, "final_width_known_under": 1, "final_width_unknown": 2}]}
    record.write_text(json.dumps({"complete": True, "report": report}))
    (folder / "route.json").write_text(json.dumps(report))
    return report


def test_failed_route_retains_verified_measurements_but_never_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(route_ref, "_krt_version", lambda path: "k")
    work = tmp_path / "route"
    def run(cmd, **kwargs):
        completed_report(work)
        return subprocess.CompletedProcess(cmd, 1, "", "invalid")
    monkeypatch.setattr(route_ref, "run_owned", run)
    with pytest.raises(route_ref.RouteFailure) as error:
        route_ref._route(tmp_path / "input.kicad_pcb", work, None)
    result = route_ref.failed(BOARD, "class", error.value, VERSIONS, prepare.HumanCopper(2, 3.0), tmp_path / "input.kicad_pcb")
    assert (result.closure_clean, result.open, result.vias, result.track_mm, result.seconds) == (0.75, 1, 12, 67.5, 8.0)
    assert not result.passed and result.failure == "RouteFailure"
    assert result.routing_evidence["measured"] and not result.routing_evidence["certified"]
    phase = result.routing_evidence["phases"][0]
    assert (phase["clean"], phase["connected"], phase["width_known_under"], phase["width_unknown"]) == (1, 3, 1, 2)
    assert result.routing_evidence["manufacturing"]["new"] is None


def test_uncorroborated_failure_has_no_measured_routing(tmp_path, monkeypatch):
    monkeypatch.setattr(route_ref, "_krt_version", lambda path: "k")
    result = route_ref.failed(BOARD, "class", route_ref.RouteFailure("failed", {"closure_clean": 0.75}),
                              VERSIONS, prepare.HumanCopper(0, 0), tmp_path / "input.kicad_pcb")
    assert not result.routing_evidence["measured"] and not result.passed


def test_explicitly_invalid_report_never_passes_at_complete_closure():
    template = route_ref.AResult("x", "class", 0.0, 0, [], [], 0, 0.0, 0, 0.0, False, 0.0, VERSIONS)
    assert not route_ref.judge({"valid": False, "closure_clean": 1.0}, [], template).passed


@pytest.mark.parametrize("completed", [False, True])
def test_rc1_placement_keeps_raw_diagnostic_but_measures_only_completed_artifacts(tmp_path, monkeypatch, completed):
    script = tmp_path / "Board_layout.py"
    script.write_text("# controlled input\n")
    def run(cmd, **kwargs):
        folder = tmp_path / ".placemat/runs/new"
        report = completed_report(folder / "route")
        if not completed:
            (folder / "route/route_record.json").write_text(json.dumps({"complete": False, "report": report}))
        (folder / "run.json").write_text(json.dumps({"status": "ok", "metrics": {"route": report}}))
        return subprocess.CompletedProcess(cmd, 1, "", "invalid")
    monkeypatch.setattr(route_ref, "run_owned", run)
    result, _ = place_ref.placemat_run(script)
    assert place_ref._failure(result)[0] == "exit 1"
    assert result["raw_record_diagnostic"]["metrics"]["route"]["closure_clean"] == 0.75
    assert bool(route_ref.verified_invalid_report(result.get("route_diagnostic", {}))) is completed


def test_historical_phase_without_separate_counts_stays_unknown():
    report = {"valid": False, "closure_clean": 0.75, "phases": [{"name": "signals", "asked": 4, "joined": 3}]}
    phase = route_ref.routing_evidence(report, status="completed_invalid")["phases"][0]
    assert phase["connected"] is None and phase["width_known_under"] is None and phase["width_unknown"] is None


def test_changed_output_revokes_diagnostic_measurements(tmp_path):
    folder = tmp_path / "route"
    report = completed_report(folder)
    receipt = route_ref._invalid_route_diagnostic(report, folder / "route.json", folder, {})
    assert route_ref.verified_invalid_report(receipt)
    (folder / "routed.kicad_pcb").write_text("changed after grading")
    assert route_ref.verified_invalid_report(receipt) is None


def test_known_inherited_and_new_errors_are_distinct(tmp_path, monkeypatch):
    work = tmp_path / "route"
    baseline = {"violations": [{"type": "clearance", "severity": "error", "items": [
        {"description": "Track [N]", "pos": {"x": 1, "y": 1}}]}]}
    (tmp_path / prepare.BASELINE).write_text(json.dumps(baseline))
    def run(cmd, **kwargs):
        completed_report(work)
        after = {"violations": baseline["violations"] + [{"type": "shorting_items", "severity": "error", "items": [
            {"description": "Track [M]", "pos": {"x": 4, "y": 4}}]}]}
        (work / "drc_after.json").write_text(json.dumps(after))
        return subprocess.CompletedProcess(cmd, 1, "", "invalid")
    monkeypatch.setattr(route_ref, "run_owned", run)
    monkeypatch.setattr(route_ref, "_krt_version", lambda path: "k")
    with pytest.raises(route_ref.RouteFailure) as error:
        route_ref._route(tmp_path / "input.kicad_pcb", work, None)
    result = route_ref.failed(BOARD, "class", error.value, VERSIONS, prepare.HumanCopper(0, 0), tmp_path / "input.kicad_pcb")
    errors = result.routing_evidence["manufacturing"]
    assert [v.type for v in errors["inherited"]] == ["clearance"]
    assert [v.type for v in errors["new"]] == ["shorting_items"]
    assert not result.passed
    assert "certification failed" in route_ref.line(result, route_ref.Comparison("worse", []))


def test_failed_certification_stays_held_when_measured_closure_improves():
    old = route_ref.AResult("x", "class", 0.9, 0, [], [], 0, 0.0, 0, 0.0, True, 0.0, VERSIONS)
    new = route_ref.AResult("x", "class", 1.0, 0, [], [], 0, 0.0, 0, 0.0, False, 0.0, VERSIONS,
                           failure="RouteFailure", routing_evidence={"measured": True})
    comparison = route_ref.compare(route_ref.asdict(old), new, {"placemat"})
    assert comparison.status == "worse" and route_ref.lower(comparison)
    assert route_ref.ratchet([new], [comparison], False) == ([], [new])


def test_unmeasured_failure_line_never_displays_zero_as_routing_closure(tmp_path, monkeypatch):
    monkeypatch.setattr(route_ref, "_krt_version", lambda path: "k")
    result = route_ref.failed(BOARD, "class", RuntimeError("not run"), VERSIONS, prepare.HumanCopper(0, 0), tmp_path / "input")
    text = route_ref.line(result, route_ref.Comparison("worse", []))
    assert "routing unmeasured" in text and "closure_clean 0" not in text


@pytest.mark.parametrize("key,value", [("vias", True), ("track_mm", float("nan")), ("phases", [True])])
def test_malformed_completed_measurements_are_not_verified(tmp_path, key, value):
    folder = tmp_path / "route"
    report = completed_report(folder)
    report[key] = value
    (folder / "route.json").write_text(json.dumps(report))
    (folder / "route_record.json").write_text(json.dumps({"complete": True, "report": report}))
    assert not route_ref._invalid_route_diagnostic(report, folder / "route.json", folder, {})


def test_board_collector_retains_completed_invalid_counts_and_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace
    folder = tmp_path / "x"
    folder.mkdir()
    (folder / "x_layout.py").write_text("# controlled input\n")
    monkeypatch.setattr(place_ref, "generation_inputs", lambda path: "inputs")
    monkeypatch.setattr(place_ref.lint, "lint", lambda *args: SimpleNamespace(problems=[]))
    monkeypatch.setattr(place_ref, "krt_version", lambda path: "k")
    def run(script, extra):
        route_dir = script.parent / ".placemat/runs/new/route"
        report = completed_report(route_dir)
        receipt = route_ref._invalid_route_diagnostic(report, route_dir / "route.json", route_dir, {})
        return {"status": "failed", "failure": {"kind": "exit 1", "message": "invalid"},
                "route_diagnostic": receipt}, 12.0
    monkeypatch.setattr(place_ref, "placemat_run", run)
    prepared = prepare.Prepared(tmp_path / "ref", tmp_path / "input", [], 2, prepare.HumanCopper(2, 3))
    result = place_ref.run_b(BOARD, folder, tmp_path / "work", prepared=prepared, versions=VERSIONS)
    assert (result.closure_clean, result.open, result.vias, result.track_mm) == (0.75, 1, 12, 67.5)
    assert result.failure == "exit 1" and not result.routing_evidence["certified"]
    assert result.routing_evidence["phases"][0]["connected"] == 3
    assert "certification failed" in place_ref.line_b(result, route_ref.Comparison("worse", []))


@pytest.mark.parametrize("old_measured,new_measured", [(False, True), (True, False), (False, False)])
def test_failed_unmeasured_closure_sentinel_is_not_a_routing_comparison(old_measured, new_measured):
    old = route_ref.AResult("x", "class", 0.0, 0, [], [], 0, 0.0, 0, 0.0, False, 0.0, VERSIONS,
                           failure="failed", routing_evidence={"measured": old_measured})
    new = route_ref.AResult("x", "class", 0.75, 1, [], [], 12, 67.5, 0, 0.0, False, 8.0, VERSIONS,
                           failure="failed", routing_evidence={"measured": new_measured})
    comparison = route_ref.compare(route_ref.asdict(old), new, {"placemat"})
    assert (comparison.status, comparison.value) == ("not comparable", "")
    assert comparison.differ == ["routing measurements"]


@pytest.mark.parametrize("kind", ["a", "b"])
@pytest.mark.parametrize("old_measured,new_measured", [(False, True), (True, False), (False, False)])
def test_unresolved_failure_measurements_hold_existing_baseline_bytes(tmp_path, kind, old_measured, new_measured):
    if kind == "a":
        result = route_ref.AResult("x", "class", 0.75, 1, [], [], 12, 67.5, 0, 0.0, False, 8.0, VERSIONS,
                                  failure="failed", routing_evidence={"measured": new_measured})
        old = dict(route_ref.asdict(result), closure_clean=0.0, routing_evidence={"measured": old_measured})
        compare = route_ref.compare
        save = lambda path, rows: route_ref.save_results(path, rows)
        pins = {"a": {"x": {"class": old}}}
    else:
        result = place_ref.BResult("x", 0.75, 1, [], 12, 67.5, 0.0, 0, 0.0, None, 8.0, VERSIONS,
                                   failure="failed", routing_evidence={"measured": new_measured})
        old = dict(route_ref.asdict(result), closure_clean=0.0, routing_evidence={"measured": old_measured})
        compare = place_ref.compare_b
        save = lambda path, rows: place_ref.save_results(path, boards=rows)
        pins = {"b": {"x": old}}
    path = tmp_path / "results.json"
    path.write_text(json.dumps(pins, indent=2) + "\n")
    before = path.read_bytes()
    comparison = compare(old, result, {"placemat"})
    assert comparison.status == "not comparable" and comparison.value == ""
    assert route_ref.lower(comparison)
    accepted, held = route_ref.ratchet([result], [comparison], False)
    assert accepted == [] and held == [result]
    save(path, accepted)
    assert path.read_bytes() == before


@pytest.mark.parametrize("raw", ['{', '[]', '{"violations": [true]}', '{"violations": [{"type":3}]}'])
def test_malformed_diagnostic_drc_is_unknown(raw, tmp_path):
    path = tmp_path / "drc.json"
    path.write_text(raw)
    assert route_ref.diagnostic_violations(path) is None


def test_version_incomparability_alone_does_not_hold_identical_results():
    assert not route_ref.lower(route_ref.Comparison("not comparable", ["krt"], "same"))


@pytest.mark.parametrize("kind", ["a", "b"])
def test_reference_gate_reports_unresolved_and_leaves_baseline_bytes(kind, tmp_path, monkeypatch, capsys):
    import contextlib
    if kind == "a":
        result = route_ref.AResult("x", "class", 0.75, 1, [], [], 12, 67.5, 0, 0.0, False, 8.0, VERSIONS,
                                  failure="failed", routing_evidence={"measured": True})
        old = dict(route_ref.asdict(result), routing_evidence={"measured": False}, closure_clean=0.0)
        pins = {"a": {"x": {"class": old}}}
        module = route_ref
        monkeypatch.setattr(route_ref, "LOCAL", {})
    else:
        result = place_ref.BResult("x", 0.75, 1, [], 12, 67.5, 0.0, 0, 0.0, None, 8.0, VERSIONS,
                                   failure="failed", routing_evidence={"measured": True})
        old = dict(route_ref.asdict(result), routing_evidence={"measured": False}, closure_clean=0.0)
        pins = {"b": {"x": old}}
        module = place_ref
    path = tmp_path / "results.json"
    path.write_text(json.dumps(pins, indent=2) + "\n")
    original = path.read_bytes()
    monkeypatch.setattr(route_ref, "current_versions", lambda: VERSIONS)
    monkeypatch.setattr(module.fetch, "load_manifest", lambda: [])
    monkeypatch.setattr(module.lock, "realboard", contextlib.nullcontext)
    def run(chosen, root, recorded, versions, changing, results, comparisons, save):
        comparison = route_ref.Comparison("not comparable", ["routing measurements"])
        results.append(result)
        comparisons.append(comparison)
        save()
        return route_ref.lower(comparison)
    monkeypatch.setattr(module, "_run_boards", run)
    assert module.main(["--update", "--work", str(tmp_path / "work"), "--results", str(path)]) == 1
    assert path.read_bytes() == original
    output = capsys.readouterr().out
    assert "held back, unresolved routing measurements" in output
    assert "held back, worse" not in output
