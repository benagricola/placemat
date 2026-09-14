"""End to end on a scratch copy of the Breakout: generate the board with the
pcb toolchain, run a script, write, check, record."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from placemat.runner import run
from tests.conftest import ECOSYSTEM, needs_kicad

needs_pcb = pytest.mark.skipif(shutil.which("pcb") is None, reason="pcb toolchain not on PATH")
pytestmark = [needs_kicad, needs_pcb, pytest.mark.skipif(not (ECOSYSTEM / "breakout").exists(), reason="no ecosystem")]

SCRIPT = '''
from placemat import board, Part, Cell, Centre, Location, Edge, Net, CopperLayer, OnEdge

# module extents, measured off the generated cells (unrotated: along = width)
PD_ALONG, PD_DEPTH = board.extent(Cell("power_drop0")).width, board.extent(Cell("power_drop0")).height
BD_ALONG, BD_DEPTH = board.extent(Cell("bus_drop0")).width, board.extent(Cell("bus_drop0")).height
EDGE, INNER, GAP, TOP = 3.0, 2.0, 3.0, 35.0
STATION = PD_ALONG + INNER + BD_ALONG
W = 140.0
H = TOP + 3 * STATION + 2 * GAP + 30.0
board.size(width=W, height=H, chamfer=2.0)
board.place(Part("trunk_pwr"), at=OnEdge(Edge.NORTH, along=W / 2 - 14.0), rotation=180)
board.place(Part("trunk_sig"), at=OnEdge(Edge.NORTH, along=W / 2 + 14.0), rotation=180)
for d in range(3):
    y0 = TOP + d * (STATION + GAP)
    board.place(Cell("power_drop%d" % d), at=Centre(EDGE + PD_DEPTH / 2, y0 + PD_ALONG / 2), rotation=270)
    board.place(Cell("bus_drop%d" % d), at=Centre(W - EDGE - BD_DEPTH / 2, y0 + BD_ALONG / 2), rotation=90)
board.place(Part("mh1"), at=Location(8, 8)); board.place(Part("mh2"), at=Location(W - 8, 8))
board.place(Part("mh3"), at=Location(8, H - 8)); board.place(Part("mh4"), at=Location(W - 8, H - 8))
'''


@pytest.fixture(scope="module")
def scratch_ecosystem(tmp_path_factory):
    root = tmp_path_factory.mktemp("eco")
    for name in ("pcb.toml", "fab-profile.json"):
        shutil.copy(ECOSYSTEM / name, root / name)
    # pcb resolves symlinks and then refuses a part "outside the workspace", so
    # the part library is hard-linked into the scratch workspace (a copy when
    # /tmp is another filesystem)
    def link_or_copy(src, dst, *, follow_symlinks=True):
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    shutil.copytree(ECOSYSTEM / "parts", root / "parts", copy_function=link_or_copy)
    shutil.copytree(ECOSYSTEM / "modules", root / "modules", copy_function=link_or_copy,
                    ignore=shutil.ignore_patterns("__pycache__"))
    def skip(d, names):        # the board's own generated output and the old script; module fragments stay
        out = {n for n in names if n in ("__pycache__", ".placemat", "Breakout_layout.py")}
        if d == str(ECOSYSTEM / "breakout"):
            out.add("layout")
        return out
    shutil.copytree(ECOSYSTEM / "breakout", root / "breakout", ignore=skip)
    (root / "breakout" / "Breakout_layout.py").write_text(SCRIPT)
    return root


def test_a_run_generates_places_writes_and_records(scratch_ecosystem):
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    rec = run(script, label="first", render=False)
    assert rec.status == "ok"
    assert (scratch_ecosystem / "breakout/layout/Breakout/layout.kicad_pcb").exists()
    out = scratch_ecosystem / "breakout/.placemat/runs/first"
    data = json.loads((out / "run.json").read_text())
    assert data["board"] == "Breakout" and data["status"] == "ok"
    assert set(data["placements"]) >= {"trunk_pwr", "trunk_sig", "power_drop0", "bus_drop2", "mh1"}
    assert data["metrics"]["drc_real"] == {}
    assert data["metrics"]["unconnected"] > 0            # nothing routed yet
    assert (out / "generate.log").exists() and (out / "script.log").exists()
    assert "steps" in data and any(s["item"] == "trunk_pwr" for s in data["steps"])


def test_a_second_run_reuses_the_generation_and_reports_no_movement(scratch_ecosystem):
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    rec = run(script, label="second", render=False)
    assert rec.generated is False                 # restored from the cache, not regenerated
    assert "same inputs" in rec.impact_text and rec.record.run_id in rec.impact_text
    a = (scratch_ecosystem / "breakout/.placemat/runs/first/layout.kicad_pcb").read_bytes()   # via the label alias
    b = (scratch_ecosystem / "breakout/layout/Breakout/layout.kicad_pcb").read_bytes()
    assert a == b


def test_the_cli_runs_and_prints_a_one_line_verdict(scratch_ecosystem):
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    proc = subprocess.run([sys.executable, "-m", "placemat", "run", str(script), "--label", "cli", "--no-render"],
                          capture_output=True, text=True, cwd=str(scratch_ecosystem), timeout=600)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    assert "(label cli)" in proc.stdout and "DRC" in proc.stdout


def test_runs_are_named_by_hash_and_labels_are_aliases(scratch_ecosystem):
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    rec = run(script, render=False, drc=False)
    assert len(rec.record.run_id) == 8
    runs = scratch_ecosystem / "breakout/.placemat/runs"
    assert (runs / rec.record.run_id / "run.json").exists()
    again = run(script, render=False, drc=False, label="same-inputs")
    assert again.record.run_id == rec.record.run_id            # same inputs, same id
    assert (runs / "same-inputs").is_symlink() and (runs / "same-inputs").resolve() == (runs / rec.record.run_id).resolve()
    from placemat.report import RunRecord, resolve_run
    assert resolve_run(runs, "same-inputs") == runs / rec.record.run_id
    assert resolve_run(runs, rec.record.run_id[:6]) == runs / rec.record.run_id   # a unique prefix is enough


def test_a_critical_item_that_cannot_place_fails_the_run_but_writes_the_board_as_it_stood(scratch_ecosystem):
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    original = script.read_text()
    script.write_text(original.replace(
        'board.place(Cell("power_drop%d" % d), at=Centre(EDGE + PD_DEPTH / 2, y0 + PD_ALONG / 2), rotation=270)',
        'board.place(Cell("power_drop%d" % d), at=Centre(EDGE + PD_DEPTH / 2, y0 + PD_ALONG / 2), rotation=270) if d else None')
        + '\nfrom placemat import Near, Priority\n'
          'board.place(Cell("power_drop0"), at=Near(Location(8, 8), radius=0.4), priority=Priority.HIGH)   # on MH1: nowhere to go\n')
    try:
        rec = run(script, label="critical", render=False)
    finally:
        script.write_text(original)
    assert rec.status == "failed" and rec.record.failure["kind"] == "placement"
    assert "power_drop0" in rec.record.failure["message"]
    assert (scratch_ecosystem / "breakout/.placemat/runs/critical/layout.kicad_pcb").exists()   # the board as it stood


def test_a_plan_reports_its_extent_and_how_much_of_it_is_empty():
    """A module run says how big the cell is and how much of that is
    air, so a fat cell shows in the log."""
    from placemat.report import extent_of
    from placemat.layout import Board
    from placemat.values import Location, Part
    from tests.fixtures import board_geometry, footprint
    fps = [footprint("R1", 5, 5, w=2, h=1, inst="r1"), footprint("R2", 5, 5, w=2, h=1, inst="r2")]
    b = Board(board_geometry(fps, width=50, height=50), edge_margin=0.0)
    b.place(Part("r1"), at=Location(10, 10))
    b.place(Part("r2"), at=Location(18, 10))                     # 2 x 1 parts, 8 apart: a 10 x 1 extent, 60% empty
    ext = extent_of(b.resolve())
    assert ext.width == pytest.approx(10.2) and ext.height == pytest.approx(1.2)      # courtyards: the excess is part of what is claimed
    assert ext.empty == pytest.approx(1 - 2 * (2.2 * 1.2) / (10.2 * 1.2))
