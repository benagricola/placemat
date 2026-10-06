"""A real explore with --route-top (the UsbC fixture module, as a real `placemat run`, the real router): its best two
variants are written and quick-routed in their own folders, and run.json, the explore record and the console carry each
one's closure."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pcbnew")

from placemat.kicad.route import ROUTER_DEFAULT
from tests.test_stop_run import ROOT, _only_run, _searched_module

if not (Path(ROUTER_DEFAULT) / ".venv/bin/python").exists():
    pytest.skip("KiCadRoutingTools not at %s" % ROUTER_DEFAULT, allow_module_level=True)


def test_a_real_explore_routes_its_best_two_variants_and_records_their_closure(tmp_path):
    mod, script, src = _searched_module(tmp_path)
    done = subprocess.run([sys.executable, "-m", "placemat", "run", str(script), "--no-render", "--keep-going", "--explore", "8",
                           "--jobs", "1", "--route-top", "2", "--accept"], cwd=ROOT, capture_output=True, text=True, timeout=900)
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    doc, run_dir = _only_run(src)
    ex = doc["metrics"]["explore"]
    routes = ex["routes"]
    assert len(routes) == 2 and [r["seed"] for r in routes] == [row for row in _ranked(ex)][:2], routes
    for r in routes:
        assert "error" not in r, r
        assert 0.0 <= r["closure_clean"] <= 1.0 and 0.0 <= r["closure"] <= 1.0 and r["open_before"] > 0 and r["seconds"] > 0
        d = Path(r["dir"])
        assert d.parent == run_dir / "explore" and (d / "layout.kicad_pcb").exists()
        assert json.loads((d / "route" / "route.json").read_text())["closure_clean"] == r["closure_clean"]
    taken = ex["taken_seed"]
    assert taken == max(routes, key=lambda r: r["closure_clean"])["seed"]
    assert sum(1 for line in out.splitlines() if "  route, seed " in line) == 2, out
    assert "routes: 2 variants quick-routed in " in out and "taken by closure: seed %d" % taken in out, out
    record = json.loads(Path(ex["record"]).read_text())
    assert record["routes"] == routes and record["taken_seed"] == taken
    assert ex["accepted"] == (taken != 0)


def _ranked(ex):
    """The seeds of the explore's variants by run score, the best first, as the explore ranked them (seed 0 the plain
    placement), from its curve."""
    return [c["seed"] for c in sorted(ex["curve"], key=lambda c: (c["score"], c["seed"]))]
