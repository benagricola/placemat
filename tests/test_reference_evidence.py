"""A route of a board that already has DRC errors is a completed route, judged on the errors it adds."""
import json
import subprocess

import pytest

from fixtures.reference import fetch, place_ref, prepare, route_ref

VERSIONS = {"placemat": "p", "krt": "k", "pcb": "z"}
BOARD = fetch.Board(name="x", repo="github:o/r", commit="0" * 40, files={}, board="x.kicad_pcb",
                    licence="MIT", tests=("a",), phases=(), fixed=(), human_track_mm=0.2, kicad5=False)
INVALID = {"valid": False, "closure_clean": 1.0, "open_before": 4, "open_after": 0, "seconds": 8.0,
           "invalid_reason": "the input board has DRC errors"}


def routed(work, rc, report):
    """A stand-in for the route process: writes `report` as route.json (unless None) and exits `rc`."""
    def run(cmd, **kwargs):
        if report is not None:
            (work / "route.json").write_text(report if isinstance(report, str) else json.dumps(report))
        return subprocess.CompletedProcess(cmd, rc, "out", "err")
    return run


def test_exit_1_with_a_fresh_invalid_report_is_a_completed_route(tmp_path, monkeypatch):
    work = tmp_path / "route"
    monkeypatch.setattr(route_ref, "run_owned", routed(work, 1, INVALID))
    assert route_ref._route(tmp_path / "input.kicad_pcb", work, None) == INVALID
    facts = json.loads((work / "process.json").read_text())
    assert facts["returncode"] == 1 and (work / "stdout.log").read_text() == "out"


@pytest.mark.parametrize("rc,report", [
    (1, None),                                  # no fresh report
    (1, "not JSON"),
    (1, dict(INVALID, error="router crashed")),
    (1, dict(INVALID, valid=True)),             # a valid route exits 0, so this one failed after its report
    (2, INVALID),
])
def test_other_failed_routes_raise(tmp_path, monkeypatch, rc, report):
    work = tmp_path / "route"
    work.mkdir()
    (work / "route.json").write_text(json.dumps(INVALID))   # a stale report from an earlier run
    monkeypatch.setattr(route_ref, "run_owned", routed(work, rc, report))
    with pytest.raises((RuntimeError, ValueError)):
        route_ref._route(tmp_path / "input.kicad_pcb", work, None)


def test_an_invalid_input_board_passes_on_clean_closure_and_nothing_new():
    template = route_ref.AResult("x", "class", 0.0, 0, [], [], 0, 0.0, 0, 0.0, False, 0.0, VERSIONS)
    assert route_ref.judge({"valid": False, "closure_clean": 1.0}, [], template).passed


def test_a_failed_row_records_new_drc_as_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(route_ref, "_krt_version", lambda path: "k")
    result = route_ref.failed(BOARD, "class", RuntimeError("not run"), VERSIONS, prepare.HumanCopper(0, 0), tmp_path / "input")
    assert result.new_violations is None
    text = route_ref.line(result, route_ref.Comparison("worse", []))
    assert "FAILED RuntimeError" in text and "new DRC 0" not in text


def test_an_open_board_on_an_invalid_input_is_a_route_not_a_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace
    folder = tmp_path / "x"
    folder.mkdir()
    (folder / "x_layout.py").write_text("# controlled input\n")
    pcb = tmp_path / "routed.kicad_pcb"
    pcb.write_text("")
    (tmp_path / "drc_after.json").write_text(json.dumps({"violations": []}))
    monkeypatch.setattr(place_ref, "generation_inputs", lambda path: "inputs")
    monkeypatch.setattr(place_ref.lint, "lint", lambda *args: SimpleNamespace(problems=[]))
    monkeypatch.setattr(place_ref, "krt_version", lambda path: "k")
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder, *, script: 1.0)
    monkeypatch.setattr(prepare, "measure", lambda path: (None, prepare.HumanCopper(12, 67.5)))
    route = dict(INVALID, closure_clean=0.75, open_after=1, routed_pcb=str(pcb))
    monkeypatch.setattr(place_ref, "placemat_run", lambda script, extra: (
        {"status": "ok", "metrics": {"route": route}}, 12.0))
    prepared = prepare.Prepared(tmp_path / "ref", tmp_path / "input", [], 2, prepare.HumanCopper(2, 3))
    result = place_ref.run_b(BOARD, folder, tmp_path / "work", prepared=prepared, versions=VERSIONS)
    assert result.failure == "" and (result.closure_clean, result.open, result.vias) == (0.75, 1, 12)
    assert result.new_violations == []
