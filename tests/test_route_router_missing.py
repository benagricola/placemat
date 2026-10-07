"""A route with no router named ([route] router_dir, $KRT_DIR) refuses, naming both, as data with --json."""
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import needs_kicad

pytestmark = needs_kicad

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _route(pcb, *flags):
    env = {k: v for k, v in os.environ.items() if k != "KRT_DIR"}
    env["PYTHONPATH"] = SRC
    return subprocess.run([sys.executable, "-m", "placemat", "route", str(pcb), "--out", str(pcb.parent / "work"), *flags],
                          capture_output=True, text=True, env=env, cwd=str(pcb.parent))


def test_a_route_with_no_router_named_refuses_and_says_where_to_name_one(tmp_path):
    import pcbnew
    pcb = tmp_path / "b.kicad_pcb"
    pcbnew.CreateEmptyBoard().Save(str(pcb))
    (tmp_path / "placemat.toml").write_text('[[route.phase]]\nname = "signals"\n')     # a route needs a phase first
    said = _route(pcb)
    assert said.returncode == 2
    assert "[route] router_dir" in said.stdout + said.stderr and "$KRT_DIR" in said.stdout + said.stderr
    data = _route(pcb, "--json")
    assert data.returncode == 2
    assert json.loads(data.stdout) == {"code": "router_unset", "setting": "[route] router_dir", "env": "KRT_DIR"}
