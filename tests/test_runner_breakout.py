"""End to end on a scratch copy of the Breakout: generate the board with the
pcb toolchain, run a script, write, check, record."""
import json
from pathlib import Path
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
# TOP clears the two parts this script does not place - trunk_led_ra and
# term_far_jumper, which the generator leaves at y 34.8..40.6 in the east
# column's lane. A part nobody places stays where it was put, and a cell
# dropped on top of one is a real collision.
EDGE, INNER, GAP, TOP = 3.0, 2.0, 3.0, 44.0
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


def test_a_run_records_itself_as_the_best_of_its_family(scratch_ecosystem):
    """A real run, not a synthetic record: the first run of these parts is
    their best, and best.json names it under its family."""
    from placemat.report import RunRecord, best_for, family_of
    runs = scratch_ecosystem / "breakout/.placemat/runs"
    rec = RunRecord.load(runs / "first" / "run.json")
    best = best_for(runs / "best.json", family_of(rec))
    assert best is not None and best.run_id == rec.run_id


def test_a_second_run_reuses_the_generation_and_reports_no_movement(scratch_ecosystem):
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    rec = run(script, label="second", render=False)
    assert rec.generated is False                 # restored from the cache, not regenerated
    assert "same inputs" in rec.impact_text and rec.record.run_id in rec.impact_text
    a = (scratch_ecosystem / "breakout/.placemat/runs/first/layout.kicad_pcb").read_bytes()   # via the label alias
    b = (scratch_ecosystem / "breakout/layout/Breakout/layout.kicad_pcb").read_bytes()
    assert a == b


def test_the_cli_runs_and_prints_a_one_line_verdict(scratch_ecosystem):
    # the module's earlier runs leave a best behind; this run coming out a
    # hair worse by run-to-run noise would exit 1 by the regression gate,
    # which is not what this test is about
    (scratch_ecosystem / "breakout" / ".placemat" / "runs" / "best.json").unlink(missing_ok=True)
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


def test_a_required_item_that_cannot_place_fails_the_run_but_writes_the_board_as_it_stood(scratch_ecosystem):
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    original = script.read_text()
    script.write_text(original.replace(
        'board.place(Cell("power_drop%d" % d), at=Centre(EDGE + PD_DEPTH / 2, y0 + PD_ALONG / 2), rotation=270)',
        'board.place(Cell("power_drop%d" % d), at=Centre(EDGE + PD_DEPTH / 2, y0 + PD_ALONG / 2), rotation=270) if d else None')
        + '\nfrom placemat import Near\n'
          'board.place(Cell("power_drop0"), at=Near(Location(8, 8), radius=0.4), required=True)   # on MH1: nowhere to go\n')
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


def test_a_run_explores_accepts_and_the_next_run_holds_the_lock(scratch_ecosystem):
    """--explore on a real run: the search is recorded in metrics.explore,
    --accept writes the lock beside the script, and a plain run after it
    holds what was accepted."""
    from placemat.explore import ExploreOptions
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    script.write_text(SCRIPT + 'board.place(Part("trunk_led_ra"))\n')
    try:
        rec = run(script, label="explored", render=False, drc=False,
                  explore=ExploreOptions(seconds=6, jobs=2, accept=True))
        data = json.loads((scratch_ecosystem / "breakout/.placemat/runs/explored/run.json").read_text())
        ex = data["metrics"]["explore"]
        assert ex["focus"] == ["trunk_led_ra"] and ex["tried"] >= 1
        lock = scratch_ecosystem / "breakout" / "Breakout_layout.lock.json"
        if ex["accepted"]:
            assert lock.exists()
            again = run(script, label="held", render=False, drc=False)
            steps = json.loads((scratch_ecosystem / "breakout/.placemat/runs/held/run.json").read_text())["steps"]
            assert any("held by lock" in s["note"] for s in steps if s["item"] == "trunk_led_ra")
        else:
            assert not lock.exists()
    finally:
        script.write_text(SCRIPT)
        lock = scratch_ecosystem / "breakout" / "Breakout_layout.lock.json"
        if lock.exists():
            lock.unlink()


def test_a_script_that_fails_leaves_the_board_as_the_last_run_wrote_it(scratch_ecosystem):
    """A failed script used to leave the fresh, unplaced generation in the
    layout folder in place of the last good board."""
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    pcb = scratch_ecosystem / "breakout/layout/Breakout/layout.kicad_pcb"
    good = run(script, label="good", render=False, drc=False)
    assert good.status == "ok" and not (good.run_dir / "before").exists()
    before = pcb.read_bytes()
    original = script.read_text()
    script.write_text(original + '\nraise RuntimeError("broken on purpose")\n')
    try:
        rec = run(script, label="broken", render=False, drc=False)
    finally:
        script.write_text(original)
    assert rec.status == "failed" and rec.record.failure["kind"] == "script"
    assert pcb.read_bytes() == before


def test_lock_current_holds_the_placement_the_board_stands_in(scratch_ecosystem):
    """A run, then `placemat lock --current`: the next run holds every
    searched item where the board stood."""
    from placemat import cli, lock
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    script.write_text(SCRIPT + 'board.place(Part("trunk_led_ra"))\nboard.place(Part("term_far_jumper"))\n')
    path = lock.path_for(script)
    try:
        first = run(script, label="to-lock", render=False, drc=False)
        assert cli.main(["lock", str(script), "--current"]) == 0
        keys = {e.key for e in lock.read(path)}
        assert {"trunk_led_ra", "term_far_jumper"} <= keys
        again = run(script, label="locked", render=False, drc=False)
        steps = json.loads((scratch_ecosystem / "breakout/.placemat/runs/locked/run.json").read_text())["steps"]
        for key in ("trunk_led_ra", "term_far_jumper"):
            assert any("held by lock" in s["note"] for s in steps if s["item"] == key)
        assert again.record.placements["trunk_led_ra"] == first.record.placements["trunk_led_ra"]
    finally:
        script.write_text(SCRIPT)
        path.unlink(missing_ok=True)


def test_adopting_a_net_locks_the_searched_items_it_joins(scratch_ecosystem, tmp_path):
    """No router: the route's work folder is made by hand, its routed copy one
    track more on a net a searched part joins."""
    import shutil
    from types import SimpleNamespace
    import pcbnew
    from placemat import cli, lock, routes
    from placemat.kicad.read import read_board
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    script.write_text(SCRIPT + 'board.place(Part("trunk_led_ra"))\n')
    try:
        run(script, label="to-adopt", render=False, drc=False)
        pcb = scratch_ecosystem / "breakout/layout/Breakout/layout.kicad_pcb"
        g = read_board(pcb)
        led = next(fp for fp in g.footprints if fp.inst == "trunk_led_ra")
        pad = next(p for p in led.pads if p.net and any(q.net == p.net for fp in g.footprints if fp is not led
                                                         for q in fp.pads))
        other = next(q for fp in g.footprints if fp is not led for q in fp.pads if q.net == pad.net)
        work = tmp_path / "route"
        work.mkdir()
        shutil.copy(pcb, work / "in.kicad_pcb")
        routed = work / "routed.kicad_pcb"
        shutil.copy(pcb, routed)
        brd = pcbnew.LoadBoard(str(routed))
        t = pcbnew.PCB_TRACK(brd)
        t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(pad.box.center.x), pcbnew.FromMM(pad.box.center.y)))
        t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(other.box.center.x), pcbnew.FromMM(other.box.center.y)))
        t.SetWidth(pcbnew.FromMM(0.2))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(brd.FindNet(pad.net))
        brd.Add(t)
        brd.Save(str(routed))
        cli._adopt(script, [pad.net], SimpleNamespace(work=work, routed_pcb=routed, open_nets={}, shorted=[]))
        assert [e.net for e in routes.read(routes.path_for(script))] == [pad.net]
        assert "trunk_led_ra" in {e.key for e in lock.read(lock.path_for(script))}
    finally:
        script.write_text(SCRIPT)
        lock.path_for(script).unlink(missing_ok=True)
        routes.path_for(script).unlink(missing_ok=True)


def test_lock_current_on_a_board_run_with_keep_going_and_no_record(scratch_ecosystem):
    """A board written by a --keep-going run past a firm collision: with no
    replay record to say so, the lock resolves the same way, not refuses."""
    from placemat import cli, lock
    from placemat.report import latest_for
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    script.write_text(SCRIPT + 'board.place(Part("trunk_led_ra"))\n'
                      'board.place(Part("term_far_jumper"), at=Location(8, 8))   # on mh1: a firm collision\n')
    path = lock.path_for(script)
    try:
        run(script, label="kept-going", render=False, drc=False, keep_going=True)
        last = latest_for(scratch_ecosystem / "breakout/.placemat/runs", "Breakout")
        (Path(last.paths["run_dir"]) / "reuse.json").unlink()
        assert cli.main(["lock", str(script), "--current"]) == 0
        assert "trunk_led_ra" in {e.key for e in lock.read(path)}
    finally:
        script.write_text(SCRIPT)
        path.unlink(missing_ok=True)


def test_the_resolve_a_later_adoption_asks_sees_the_kept_routes(scratch_ecosystem, tmp_path):
    """A later route --adopt keeps the entries that held on the board it
    routed; it asks resolve_like_last_run which did, and that resolve must
    draw the routes file, or none held and every one was replaced."""
    import shutil
    from types import SimpleNamespace
    import pcbnew
    from placemat import cli, lock, routes
    from placemat.kicad.read import read_board
    from placemat.previewer import resolve_like_last_run
    script = scratch_ecosystem / "breakout" / "Breakout_layout.py"
    script.write_text(SCRIPT + 'board.place(Part("trunk_led_ra"))\n')
    try:
        run(script, label="to-adopt-2", render=False, drc=False)
        pcb = scratch_ecosystem / "breakout/layout/Breakout/layout.kicad_pcb"
        g = read_board(pcb)
        led = next(fp for fp in g.footprints if fp.inst == "trunk_led_ra")
        pad = next(p for p in led.pads if p.net and any(q.net == p.net for fp in g.footprints if fp is not led
                                                         for q in fp.pads))
        other = next(q for fp in g.footprints if fp is not led for q in fp.pads if q.net == pad.net)
        work = tmp_path / "route"
        work.mkdir()
        shutil.copy(pcb, work / "in.kicad_pcb")
        routed = work / "routed.kicad_pcb"
        shutil.copy(pcb, routed)
        brd = pcbnew.LoadBoard(str(routed))
        t = pcbnew.PCB_TRACK(brd)
        t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(pad.box.center.x), pcbnew.FromMM(pad.box.center.y)))
        t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(other.box.center.x), pcbnew.FromMM(other.box.center.y)))
        t.SetWidth(pcbnew.FromMM(0.2))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(brd.FindNet(pad.net))
        brd.Add(t)
        brd.Save(str(routed))
        cli._adopt(script, [pad.net], SimpleNamespace(work=work, routed_pcb=routed, open_nets={}, shorted=[]))
        run(script, label="adopted-2", render=False, drc=False)
        _, plan, _, _ = resolve_like_last_run(script)
        assert plan.adopted == {pad.net: "held"}
    finally:
        script.write_text(SCRIPT)
        lock.path_for(script).unlink(missing_ok=True)
        routes.path_for(script).unlink(missing_ok=True)
