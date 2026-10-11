"""Local reference fixtures preserve observed evidence and unrelated result keys."""
import contextlib
import json

import pytest

from fixtures.reference import route_ref


def result(**changes):
    values = dict(fixture="wall", phases=[], widths_failed=1, drc_new=0, vias=0,
                  track_mm=24.0, passed=True, seconds=1.0,
                  versions={"placemat": "a", "krt": "b", "pcb": "c"})
    return route_ref.FResult(**dict(values, **changes))


def test_local_result_comparison_keeps_version_and_failure_changes():
    old = route_ref.asdict(result())
    assert route_ref.compare_local(old, result(), set()).status == "same"
    different = result(versions={"placemat": "new", "krt": "b", "pcb": "c"})
    compared = route_ref.compare_local(old, different, set())
    assert (compared.status, compared.value, compared.differ) == ("not comparable", "same", ["placemat"])
    assert route_ref.compare_local(old, different, {"placemat"}).status == "same"
    assert route_ref.compare_local(old, result(passed=False, failure="RouterMissing"), set()).status == "changed"


def test_local_save_preserves_board_module_and_other_fixture_results(tmp_path):
    path = tmp_path / "results.json"
    original = {"a": {"board": {}}, "b": {"board": {}}, "modules": {}, "fixtures": {"other": {"passed": True}}}
    path.write_text(json.dumps(original))
    route_ref.save_local(path, [result()])
    got = json.loads(path.read_text())
    assert got == dict(original, fixtures={"other": {"passed": True}, "wall": route_ref.asdict(result())})


def test_local_route_retains_deduplicated_blocker_evidence_and_final_widths(tmp_path, monkeypatch):
    monkeypatch.setattr(route_ref, "_krt_version", lambda path: "router")
    opened = {"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "J2", "pad": "1"},
              "outcome": "failed", "evidence": {"diagnosis": "blocked", "blocked_by": [
                  {"ref": "U1"}, {"ref": "U1"}, {"net": "N1"}]}}
    report = {"phases": [{"name": "legs", "asked": 1, "joined": 0, "closure_clean": 0.0,
                          "final_closure_clean": 0.0, "open": [opened]}], "widths_failed": 1, "drc_new": 0}
    monkeypatch.setattr(route_ref, "_route", lambda *args, **kwargs: report)
    got = route_ref.run_local("obstructed-route", tmp_path, {"placemat": "p", "pcb": "z"})
    assert got.passed and got.widths_failed == 1 and got.versions["krt"] == "router"
    assert json.loads((tmp_path / "local_result.json").read_text()) == route_ref.asdict(got)
    assert got.phases[0]["open"][0]["blockers"] == ["U1", "N1 copper"]
    assert got.phases[0]["final_closure_clean"] == 0.0


def test_router_resolution_failure_is_recorded_not_raised(tmp_path, monkeypatch):
    def missing(path):
        raise RuntimeError("missing router")
    monkeypatch.setattr(route_ref, "_krt_version", missing)
    got = route_ref.run_local("obstructed-route", tmp_path, {"placemat": "p"})
    assert not got.passed and got.failure == "RuntimeError" and got.versions["krt"] == "unknown"
    assert json.loads((tmp_path / "local_result.json").read_text()) == route_ref.asdict(got)


def test_later_phase_break_is_recorded_and_compared_on_the_final_board(tmp_path, monkeypatch):
    monkeypatch.setattr(route_ref, "_krt_version", lambda path: "router")
    opened = {"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "J2", "pad": "1"}}
    phase = {"name": "legs", "asked": 1, "joined": 1, "closure_clean": 1.0, "open": [],
             "final_asked": 1, "final_joined": 0, "final_closure_clean": 0.0, "final_open": [opened]}
    monkeypatch.setattr(route_ref, "_route", lambda *args, **kwargs: {"phases": [phase], "drc_new": 0})
    got = route_ref.run_local("obstructed-route", tmp_path, {})
    assert got.passed and got.phases[0]["open"] == []
    assert got.phases[0]["final_asked"] == 1 and got.phases[0]["final_open"][0]["net"] == "VB"
    assert "legs final open VB" in route_ref.local_line(got, route_ref.Comparison("new", []))
    old = route_ref.asdict(got)
    old["phases"][0]["final_open"] = []
    assert route_ref.compare_local(old, got, set()).status == "changed"


def test_main_runs_only_the_named_local_fixture_under_the_shared_lock(tmp_path, monkeypatch, capsys):
    events = []
    @contextlib.contextmanager
    def locked():
        events.append("lock")
        yield
        events.append("unlock")
    monkeypatch.setattr(route_ref.lock, "realboard", locked)
    monkeypatch.setattr(route_ref, "LOCAL", {"wall": tmp_path})
    monkeypatch.setattr(route_ref, "current_versions", lambda: events.append("versions") or {})
    monkeypatch.setattr(route_ref, "run_local", lambda name, work, versions: events.append(name) or result())
    monkeypatch.setattr(route_ref, "_run_boards", lambda boards, *args: events.append(boards) or False)
    path = tmp_path / "results.json"
    assert route_ref.main(["wall", "--update", "--results", str(path)]) == 0
    assert events == ["lock", "versions", [], "wall", "unlock"]
    assert "wall" in json.loads(path.read_text())["fixtures"]
    assert "wall" in capsys.readouterr().out


def test_unknown_name_lists_boards_and_local_fixtures(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        route_ref.main(["absent", "--results", str(tmp_path / "results.json")])
    assert error.value.code == 2
    assert "obstructed-route" in capsys.readouterr().err


def test_local_search_protocol_is_explicit_and_does_not_change_parent_environment(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("KICAD_NET_RESCUE", "1")
    monkeypatch.setattr(route_ref, "_krt_version", lambda _: "router")
    seen = {}
    def route(*args, env):
        seen.update(env)
        return {"phases": [], "drc_new": 0}
    monkeypatch.setattr(route_ref, "_route", route)
    got = route_ref.run_local("obstructed-route", tmp_path, {})
    assert got.passed and got.protocol == {"KICAD_NET_RESCUE": "0"}
    assert seen["KICAD_NET_RESCUE"] == "0" and os.environ["KICAD_NET_RESCUE"] == "1"
    old = route_ref.asdict(got)
    old["protocol"] = {"KICAD_NET_RESCUE": "1"}
    assert route_ref.compare_local(old, got, set()).status == "changed"


@pytest.mark.parametrize("rc,fresh", [(3, False), (3, True), (0, False)])
def test_failed_route_cannot_reuse_stale_report(tmp_path, monkeypatch, rc, fresh):
    from types import SimpleNamespace
    work = tmp_path / "route"
    work.mkdir()
    report = work / "route.json"
    report.write_text('{"closure_clean": 1.0}')
    diagnostic = work / "route.log"
    diagnostic.write_text("prior diagnostic")
    def fail(*args, **kwargs):
        assert not report.exists()
        if fresh:
            report.write_text('{"error": "failed invocation"}')
        return SimpleNamespace(returncode=rc, communicate=lambda **_: ("", "failed"))
    monkeypatch.setattr(route_ref.subprocess, "Popen", fail)
    with pytest.raises(RuntimeError):
        route_ref._route(tmp_path / "board.kicad_pcb", work, None)
    assert report.exists() == fresh and diagnostic.read_text() == "prior diagnostic"


def test_local_provenance_write_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    (tmp_path / "local_result.json").mkdir()
    monkeypatch.setattr(route_ref, "_krt_version", lambda _: "router")
    monkeypatch.setattr(route_ref, "_route", lambda *args, **kwargs: {"phases": []})
    with pytest.raises(IsADirectoryError):
        route_ref.run_local("obstructed-route", tmp_path, {})


def test_reference_route_runs_in_its_own_session(tmp_path, monkeypatch):
    from types import SimpleNamespace
    seen = {}
    work = tmp_path / "route"
    work.mkdir()
    def run(*args, **kwargs):
        seen.update(kwargs)
        (work / "route.json").write_text('{"closure_clean": 0.5}')
        return SimpleNamespace(returncode=0, communicate=lambda **_: ("", ""))
    monkeypatch.setattr(route_ref.subprocess, "Popen", run)
    assert route_ref._route(tmp_path / "board.kicad_pcb", work, None, env={"A": "1"})["closure_clean"] == 0.5
    assert seen["env"] == {"A": "1"}
    assert seen["start_new_session"] is True


def test_reference_timeout_reaps_its_process_group(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    # the route's own child (the router) is in the route's process group
    candidate = "import time; time.sleep(100)"
    main = ("import os,subprocess,sys,time; "
            "p=subprocess.Popen([sys.executable,'-c',%r]); "
            "open(%r,'w').write(str(os.getpid())+' '+str(p.pid)); "
            "time.sleep(100)") % (candidate, str(tmp_path / "pids"))
    real = subprocess.Popen
    def run(cmd, **kwargs):
        return real([sys.executable, "-c", main], **kwargs)
    monkeypatch.setattr(route_ref.subprocess, "Popen", run)
    monkeypatch.setattr(route_ref, "ROUTE_TIMEOUT_S", 0.5)
    with pytest.raises(RuntimeError, match="timed out"):
        route_ref._route(tmp_path / "board.kicad_pcb", tmp_path / "route", None)
    parent, child = map(int, (tmp_path / "pids").read_text().split())
    for pid in (parent, child):
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_interrupted_reference_wait_reaps_owned_parent(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    real = subprocess.Popen
    seen = []
    def run(cmd, **kwargs):
        proc = real([sys.executable, "-c", "import time; time.sleep(100)"], **kwargs)
        seen.append(proc.pid)
        communicate = proc.communicate
        first = True
        def interrupted(**options):
            nonlocal first
            if first:
                first = False
                raise KeyboardInterrupt
            return communicate(**options)
        proc.communicate = interrupted
        return proc
    monkeypatch.setattr(route_ref.subprocess, "Popen", run)
    with pytest.raises(KeyboardInterrupt):
        route_ref._route(tmp_path / "board.kicad_pcb", tmp_path / "route", None)
    with pytest.raises(ProcessLookupError):
        os.kill(seen[0], 0)
