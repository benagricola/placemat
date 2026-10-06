"""A route with nothing left for the main pass (every net excluded, as on a
module whose nets all have pours) records a route of zero connections rather
than calling the router, which refuses a net list that matches nothing (KRT
route.py: "No nets matched the given patterns!", exit 1). A router that fails
is a RouterFailed carrying its exit code and log, and a run whose route fails
records the failure instead of staying "running"."""
import json
import shutil

import pytest

from tests.test_route_resume import rig  # noqa: F401  (the stand-in router)


def _all_nets(pcb):
    from placemat.kicad.read import read_board
    return {n for n in read_board(str(pcb)).nets if n}


def test_with_every_net_excluded_the_router_is_not_called_and_the_route_closes_zero_of_zero(rig):  # noqa: F811
    report = rig.route(islands={}, exclude_nets=_all_nets(rig.pcb))
    assert rig.calls() == []
    assert (report.open_before, report.open_after, report.closure, report.closure_clean) == (0, 0, 1.0, 1.0)
    assert report.routed_pcb.exists()
    assert json.loads((rig.work / "route.json").read_text())["closure"] == 1.0


def test_a_router_that_fails_raises_router_failed_with_its_exit_code_and_log(rig, monkeypatch):  # noqa: F811
    from placemat.kicad.route import RouterFailed
    monkeypatch.setenv("FAKE_ROUTER_MAIN", "fail")
    with pytest.raises(RouterFailed) as e:
        rig.route(islands={})
    assert e.value.exit_code == 3 and e.value.log == rig.work / "router.log"
    assert e.value.what == "router exited 3 without a routed board"


def _run_with_route(tmp_path, monkeypatch, fail):
    from placemat import runner
    import placemat.kicad.route as route_mod
    from tests import real_modules as rm
    script = rm.stage(tmp_path, "usb5v")

    def restore(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        shutil.copytree(runner.cached_generation(src), src.layout_dir)
        return False
    monkeypatch.setattr(runner, "generate", restore)
    monkeypatch.setattr(route_mod, "route_board", lambda *a, **kw: fail())
    try:
        return runner.run(script, render=False, quiet=True, route=True)
    finally:
        from placemat import console
        console.configure(quiet=False)


def test_a_route_that_raises_fails_the_run_and_its_record_says_so(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")

    def fail():
        raise RuntimeError("something in the route broke")
    result = _run_with_route(tmp_path, monkeypatch, fail)
    assert result.status == "failed"
    assert result.record.failure["kind"] == "route"
    assert "RuntimeError: something in the route broke" in result.record.failure["error"]
    saved = json.loads((result.run_dir / "run.json").read_text())
    assert saved["status"] == "failed" and saved["failure"]["kind"] == "route"


def test_a_router_failure_in_a_run_records_its_exit_code_and_log(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    from placemat.kicad.route import RouterFailed
    log = tmp_path / "router.log"

    def fail():
        raise RouterFailed("router exited 1 without a routed board", 1, log, "No nets matched the given patterns!")
    result = _run_with_route(tmp_path, monkeypatch, fail)
    failure = result.record.failure
    assert result.status == "failed" and failure["kind"] == "route"
    assert (failure["error"], failure["exit_code"], failure["log"]) == ("router exited 1 without a routed board", 1, str(log))
    assert failure["tail"] == "No nets matched the given patterns!"


def test_the_main_pass_matches_what_the_routers_wildcard_and_exclusions_match():
    from placemat.kicad.route import main_pass_nets
    nets = {"", "GND", "/Sub/GND", "/GND_A", "SIG", "unconnected-(U1-Pad3)", "Unconnected-x"}
    assert main_pass_nets(nets, {"GND"}) == {"/GND_A", "SIG"}
    assert main_pass_nets(nets, {"/Sub/GND", "SIG"}) == {"GND", "/GND_A"}
    assert main_pass_nets(nets, {"GND", "/GND_A", "SIG"}) == set()
