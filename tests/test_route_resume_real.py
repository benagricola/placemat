"""A run's route on a real module (tests/real_modules.py) with the real
router: a rerun of the same inputs takes the stages the first finished
instead of routing again, and gets the same route."""
import shutil
from pathlib import Path

import pytest

pytest.importorskip("pcbnew")

from placemat.kicad.route import ROUTER_DEFAULT
from placemat.kicad.route_state import RouteState
from tests import real_modules as rm

if not (Path(ROUTER_DEFAULT) / ".venv/bin/python").exists():
    pytest.skip("KiCadRoutingTools not at %s" % ROUTER_DEFAULT, allow_module_level=True)


@pytest.fixture(autouse=True)
def _console_loud():
    """A run sets the console's quiet flag for the process: put it back for the tests that read the console."""
    yield
    from placemat import console
    console.configure(quiet=False)


def _run(script, monkeypatch, **kw):
    from placemat import runner

    def restore(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        shutil.copytree(runner.cached_generation(src), src.layout_dir)
        return False
    monkeypatch.setattr(runner, "generate", restore)
    return runner.run(script, render=False, quiet=True, route=True, keep_going=True, **kw)


def test_a_rerun_takes_the_stages_the_first_run_finished_and_gets_the_same_route(tmp_path, monkeypatch):
    script = rm.stage(tmp_path, "usb5v")
    (tmp_path / "board" / "placemat.toml").write_text('[route]\nislands = ["GND"]\n')      # two stages: islands, main
    first = _run(script, monkeypatch)
    assert first.status == "ok", first.record.failure
    route = first.record.metrics["route"]
    assert route["resumed"] == []
    work = first.run_dir / "route"
    assert RouteState(work).finished == ["islands", "main"]

    again = _run(script, monkeypatch)
    assert again.status == "ok" and again.run_dir == first.run_dir
    again_route = again.record.metrics["route"]
    assert again_route["resumed"] == ["islands", "main"]
    for k in ("closure", "closure_clean", "open_after", "islands", "shorted", "violations"):
        assert again_route[k] == route[k], k

    fresh = _run(script, monkeypatch, resume=False)
    assert fresh.record.metrics["route"]["resumed"] == []
    assert fresh.record.metrics["route"]["closure"] == route["closure"]
