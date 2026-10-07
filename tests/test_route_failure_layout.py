"""A route that fails after a good placement keeps the placed, unrouted board in the layout folder, says so, and
keeps the route's work for the rerun; a failure before the board is written puts the folder back as the last run
left it."""
import shutil
from pathlib import Path

import pytest

from placemat.project import find_board


@pytest.fixture
def staged(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    from placemat import runner
    from placemat.console import configure, console as sink
    from tests import real_modules as rm
    script = rm.stage(tmp_path, "usb5v")
    src = find_board(script)
    src.layout_dir.mkdir(parents=True, exist_ok=True)
    (src.layout_dir / "earlier.txt").write_text("the folder as the last run left it\n")

    def cached(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        shutil.copytree(runner.cached_generation(src), src.layout_dir)
        return False
    monkeypatch.setattr(runner, "generate", cached)
    said = []
    real = sink.say
    monkeypatch.setattr(sink, "say", lambda stage, message="", **kw: (said.append((stage, message)),
                                                                       real(stage, message, **kw))[1])

    class Staged:
        pass
    s = Staged()
    s.src, s.said = src, said

    def run():
        try:
            return runner.run(script, render=False, quiet=True, route=True)
        finally:
            configure(quiet=False)
    s.run = run
    return s


def _failing(monkeypatch, exc, seen):
    """route_board stood in for: it records the board it was given and whether its work folder held an earlier
    route's work, leaves work of its own, and raises `exc`."""
    import placemat.kicad.route as route_mod

    def route(pcb, work, *a, **kw):
        seen.append({"placed": Path(pcb).read_bytes(), "kept_before": (Path(work) / "kept.txt").exists()})
        Path(work).mkdir(parents=True, exist_ok=True)
        (Path(work) / "kept.txt").write_text("a phase this route finished\n")
        raise exc
    monkeypatch.setattr(route_mod, "route_board", route)


def _router_failed():
    from placemat.kicad.route import RouterFailed
    return RouterFailed("the router exited 3 routing phase signals", 3, "router.log", "tail")


def _refused():
    from placemat.kicad.route import RouteRefused
    return RouteRefused("no_phases")


@pytest.mark.parametrize("exc", [_router_failed, _refused])
def test_a_failed_route_keeps_the_placed_board_and_says_so(staged, monkeypatch, exc):
    seen = []
    _failing(monkeypatch, exc(), seen)
    result = staged.run()
    assert result.status == "failed" and result.record.failure["kind"] == "route"
    assert result.record.failure["layout"] == "placed_unrouted"
    assert staged.src.pcb.read_bytes() == seen[0]["placed"]
    assert not (staged.src.layout_dir / "earlier.txt").exists()
    assert any(stage == "fail" and "holds the placed board, unrouted" in text for stage, text in staged.said)


def test_a_rerun_after_a_failed_route_finds_its_work(staged, monkeypatch):
    seen = []
    _failing(monkeypatch, _router_failed(), seen)
    staged.run()
    staged.run()
    assert [s["kept_before"] for s in seen] == [False, True]


def test_a_failure_before_the_board_is_written_still_restores_the_folder(staged, monkeypatch):
    from placemat import runner

    def broken(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        src.layout_dir.mkdir(parents=True)
        raise runner.RunFailure("generation", "Schematic generation failed", {"exit_code": 1})
    monkeypatch.setattr(runner, "generate", broken)
    result = staged.run()
    assert result.status == "failed" and result.record.failure["layout"] == "restored"
    assert (staged.src.layout_dir / "earlier.txt").exists()


def _record(src):
    import json
    runs = [p for p in (src.board_dir / ".placemat" / "runs").glob("*/run.json") if not p.parent.name.startswith(".")]
    return json.loads(max(runs, key=lambda p: p.stat().st_mtime).read_text())


def test_a_stop_during_the_route_keeps_the_placed_board_and_the_rerun_resumes(staged, monkeypatch):
    import signal
    from placemat import stop
    seen = []
    _failing(monkeypatch, stop.Stopped(signal.SIGTERM), seen)
    with pytest.raises(stop.Stopped):
        staged.run()
    rec = _record(staged.src)
    assert rec["status"] == "stopped" and rec["failure"]["stage"] == "route"
    assert rec["failure"]["layout"] == "placed_unrouted"
    assert staged.src.pcb.read_bytes() == seen[0]["placed"]
    assert not (staged.src.layout_dir / "earlier.txt").exists()
    assert any("holds the placed board, unrouted" in text for _, text in staged.said)
    with pytest.raises(stop.Stopped):
        staged.run()
    assert [s["kept_before"] for s in seen] == [False, True]


def test_a_stop_before_the_route_still_restores_the_folder(staged, monkeypatch):
    import signal
    from placemat import runner, stop

    def stopped(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        src.layout_dir.mkdir(parents=True)
        raise stop.Stopped(signal.SIGTERM)
    monkeypatch.setattr(runner, "generate", stopped)
    with pytest.raises(stop.Stopped):
        staged.run()
    assert (staged.src.layout_dir / "earlier.txt").exists()
