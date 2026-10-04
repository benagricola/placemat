"""Time bounds on a command (timecap.py): `--max-time` stops through the stop machinery and the rerun resumes, `--step-warn` and
`--step-limit` bound one step. Synthetic boards with a deliberately slow step, and a real fixture module through `placemat preview`."""
import dataclasses
import json
import signal
import time

import pytest

from placemat import placer, reuse as reuse_mod, stop, timecap
from placemat.findings import FindingCause as C
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.settings import Settings
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint
from tests.test_reuse_replay import _board, _same


@pytest.fixture(autouse=True)
def _clean():
    yield
    timecap.reset()


def _slow_scan(monkeypatch, ref="R2", seconds=3.0):
    """The search of one part takes `seconds` before it starts."""
    from placemat import layout
    real = layout.scan

    def slow(occ, item, *a, **k):
        if getattr(item, "ref", None) == ref:
            time.sleep(seconds)
        return real(occ, item, *a, **k)
    monkeypatch.setattr(layout, "scan", slow)


def _slow_candidates(monkeypatch, ref="R2", each=0.005):
    """Every candidate spot of one part takes `each` seconds to judge (the pure-Python sweep), so its coarse pass is slow."""
    monkeypatch.setattr(placer, "NATIVE_SWEEP", False)
    real = Occupancy.legal_bucket

    def slow(self, item, *a, **k):
        if getattr(item, "ref", None) == ref:
            time.sleep(each)
        return real(self, item, *a, **k)
    monkeypatch.setattr(Occupancy, "legal_bucket", slow)


def _armed(**bounds):
    timecap.configure(**{k: v for k, v in bounds.items()})
    return timecap.arm(Settings())


def _times(plan, item="r2"):
    """The time findings of the slowed part: under a loaded machine an ordinary step can cross a bound too."""
    return [f for f in plan.findings if f.kind == "time" and f.facts.get("item") == item]


def test_a_step_past_its_warn_time_gets_a_finding_naming_the_item_its_seconds_and_the_pass(monkeypatch):
    _slow_scan(monkeypatch)
    _armed(step_warn=1.5)
    plan = _board().resolve()
    [f] = _times(plan)
    assert f.cause is C.TIME_STEP_SLOW and f.facts["item"] == "r2" and f.facts["elapsed_s"] >= 3.0
    assert f.facts["pass"] in ("scan", "coarse", "fine") and f.facts["warn_s"] == 1.5 and f.severity == "notice"
    assert "r2" in f and "--step-warn" in f
    plain = _board()
    timecap.reset()
    _same(plain.resolve(), dataclasses.replace(plan, findings=plan.findings.__class__(x for x in plan.findings if x.kind != "time")))


def test_a_warn_sends_a_live_event_while_the_step_is_still_running(monkeypatch):
    from placemat import channel
    sent = []
    monkeypatch.setattr(channel, "send", sent.append)
    _slow_scan(monkeypatch, seconds=3.0)
    _armed(step_warn=1.5)
    _board().resolve()
    [ev] = [e for e in sent if e["ev"] == "step_warn" and e.get("item") == "r2"]
    assert ev["item"] == "r2" and ev["bound_s"] == 1.5 and ev["elapsed_s"] >= 1.5 and ev["pass"] and "at" in ev


def test_a_step_past_its_limit_is_left_unplaced_with_a_finding_and_the_resolve_goes_on(monkeypatch):
    _slow_scan(monkeypatch)
    _armed(step_limit=1.5)
    plan = _board().resolve()
    [f] = _times(plan)
    assert f.cause is C.TIME_STEP_LIMIT and f.facts["item"] == "r2" and f.facts["kept"] == "unplaced" and f.severity == "critical"
    assert f.facts["limit_s"] == 1.5 and f.facts["elapsed_s"] >= 3.0 and f.facts["pass"] in ("scan", "coarse", "fine")
    step = next(s for s in plan.steps if s.item == "r2")
    assert step.placement is None and "UNPLACED: gave up" in step.note
    assert not [x for x in plan.findings if x.kind == "unplaced" and x.facts.get("item") == "r2"]      # not "no room"
    assert all(s.placement is not None for s in plan.steps if s.item in ("j1", "ldo", "cin", "r1", "r3"))   # the rest went on


def test_a_limit_inside_a_scored_scan_keeps_the_best_spot_found_so_far(monkeypatch):
    _slow_candidates(monkeypatch)
    _armed(step_limit=0.4)
    plan = _board(r2_radius=8.0).resolve()
    [f] = _times(plan)
    assert f.cause is C.TIME_STEP_LIMIT and f.facts["kept"] == "best_so_far" and f.severity == "warning"
    assert f.facts["pass"] in ("coarse", "refine", "give-way", "coarse (half stride)", "fine") and f.facts["elapsed_s"] >= 0.4
    assert next(s for s in plan.steps if s.item == "r2").placement is not None


def test_a_step_that_gave_up_is_searched_again_by_the_next_resolve(monkeypatch):
    _slow_scan(monkeypatch)
    _armed(step_limit=1.5)
    first = _board().resolve()
    timecap.reset()
    monkeypatch.undo()
    again = _board().resolve(reuse=first.reuse)
    fresh = _board().resolve()
    _same(fresh, again)
    assert 0 < again.reuse["reused"] < len(first.reuse["steps"]) and again.reuse["first_change"] == "r2"


def test_no_bound_changes_nothing():
    plain = _board().resolve()
    assert _armed() is None
    _same(plain, _board().resolve())


def test_the_bounds_are_the_flags_over_the_settings():
    cfg = dataclasses.replace(Settings(), run_max_time_s=60.0, run_step_warn_s=5.0)
    b = timecap.bounds_for(cfg, {"max_time_s": None, "step_warn_s": 0, "step_limit_s": 9})
    assert (b.max_time_s, b.step_warn_s, b.step_limit_s) == (60.0, 0.0, 9.0)
    assert Settings().run_max_time_s == 0 and Settings().run_step_warn_s == 0 and Settings().run_step_limit_s == 0


def test_the_cap_stops_through_the_stop_machinery_and_what_was_done_is_kept(monkeypatch, tmp_path):
    _slow_scan(monkeypatch, ref="r2" if False else "R3", seconds=30)            # the last searched step takes far longer than the cap
    previous = stop.install()
    try:
        timecap.configure(max_time=1.0)
        timecap.arm(Settings())
        partial = reuse_mod.PartialLog(tmp_path / "p.jsonl")
        t0 = time.time()
        with pytest.raises(stop.Stopped) as e:
            _board().resolve(partial=partial)
        assert time.time() - t0 < 10 and e.value.exit_code == 143
        rec = stop.record(e.value, command="preview")
    finally:
        stop.restore(previous)
    assert rec["kind"] == "stopped" and rec["cause"] == "max_time" and rec["limit_s"] == 1.0
    assert rec["steps_done"] >= 3 and rec["steps_of"] == 6
    assert rec["in_progress"]["item"] and rec["in_progress"]["pass"]
    assert rec["findings"]["count"] >= 0
    said = stop.line(dict(rec, stage="resolve"))
    assert "stopped at --max-time 1 s" in said and "steps done" in said and "in progress" in said and "run it again and it goes on" in said
    # the rerun replays what was finished and places as an uncapped run does
    kept = reuse_mod.read_partial(tmp_path / "p.jsonl")
    assert len(kept["steps"]) == rec["steps_done"]
    monkeypatch.undo()
    resumed = _board().resolve(reuse=kept)
    fresh = _board().resolve()
    _same(fresh, resumed)
    assert resumed.reuse["reused"] == rec["steps_done"]


def test_a_stop_by_a_person_is_not_a_cap():
    s = stop.Stopped(signal.SIGTERM)
    assert s.cause is None and s.label == "SIGTERM" and stop.cause_fields(s) == {}
    assert "max-time" not in stop.line(stop.record(s, command="run"))


def test_the_cap_is_lifted_once_the_placement_is_in_hand(monkeypatch):
    previous = stop.install()
    try:
        timecap.configure(max_time=0.6)
        clock = timecap.arm(Settings())
        timecap.placement_done()
        time.sleep(1.5)                                         # past the cap, with the stop handlers installed: nothing is raised
        assert clock.cap_lifted and not clock.cap_asked
    finally:
        stop.restore(previous)


def test_a_process_with_no_stop_handlers_is_never_stopped():
    stop.request("max_time", limit_s=1)                          # nothing installed: nothing happens (this test is still running)
    assert timecap.active() is None


def _fixture_script(tmp_path, monkeypatch, module="logicsupply"):
    pytest.importorskip("pcbnew")
    from tests import real_modules as rm
    return rm.stage(tmp_path, module)


def _preview(script, *flags):
    import sys
    from placemat import cli, console
    was = console.errors._stream
    console.errors._stream = sys.stderr             # the live lines go to stderr, which capsys has replaced since the import
    try:
        return cli.main(["preview", str(script), "--svg", *flags])
    finally:
        console.errors._stream = was
        console.configure(quiet=False)


def test_preview_max_time_stops_says_how_far_it_got_and_the_rerun_resumes(tmp_path, monkeypatch, capsys):
    script = _fixture_script(tmp_path, monkeypatch)
    from placemat import layout
    real = layout.Board._recorded_settle
    slow = {"on": True, "n": 0}

    def settle(self, *a, **k):
        slow["n"] += 1
        if slow["on"] and slow["n"] == 4:
            time.sleep(2.5)                 # the fourth searched or decided step takes far longer than the cap
        return real(self, *a, **k)
    monkeypatch.setattr(layout.Board, "_recorded_settle", settle)
    code = _preview(script, "--max-time", "1.5")
    out = capsys.readouterr()
    assert code == 143
    for stream in (out.out, out.err):
        assert "stopped at --max-time 1.5 s during resolve: 3 of" in stream and "c_bst in progress (" in stream, stream
        assert "run it again and it goes on from there" in stream
    views = script.parent / ".placemat" / "views" / "preview"
    kept = reuse_mod.read_partial(views / "reuse.partial.jsonl")
    assert kept is not None and kept["steps"]
    slow["on"] = False
    from placemat.previewer import preview, resolved
    resumed = preview(script, svg_only=True, quiet=True)
    assert not (views / "reuse.partial.jsonl").exists()
    assert resumed.reused.startswith("reused %d of" % len(kept["steps"])) and "interrupted preview" in resumed.reused, resumed.reused
    with resolved(script, tmp_path / "fresh", fresh=True, quiet=True) as r:            # an uncapped resolve from nothing
        assert [(s.item, s.placement, s.note) for s in r.plan.steps] == [(s.item, s.placement, s.note) for s in resumed.plan.steps]


def test_preview_step_warn_and_limit_through_the_flags_when_no_pass_can_stop(tmp_path, monkeypatch, capsys):
    script = _fixture_script(tmp_path, monkeypatch)
    from placemat import layout
    real = layout.Board._recorded_settle
    n = []

    def settle(self, *a, **k):
        n.append(1)
        if len(n) == 4:
            time.sleep(1.2)                 # work with no search pass in it: nothing can be cut short
        return real(self, *a, **k)
    monkeypatch.setattr(layout.Board, "_recorded_settle", settle)
    assert _preview(script, "--step-warn", "0.3", "--step-limit", "0.6") == 0
    got = capsys.readouterr()
    out = got.out + got.err
    assert "still working after" in out and "(--step-warn 0.3 s)" in out and "gave up" not in out
    assert "past --step-warn 0.3 s and --step-limit 0.6 s" in out and "no pass was left to stop at" in out


def test_preview_step_limit_gives_up_a_search_and_names_the_pass(tmp_path, monkeypatch, capsys):
    script = _fixture_script(tmp_path, monkeypatch, "usb5v")
    from placemat import layout
    real = layout.scan

    def scan(occ, item, *a, **k):
        clock = timecap.active()
        if clock is not None and clock.item:
            time.sleep(1.0)                 # the one searched step of this module
        return real(occ, item, *a, **k)
    monkeypatch.setattr(layout, "scan", scan)
    assert _preview(script, "--step-limit", "0.5") == 0
    got = capsys.readouterr()
    out = got.out + got.err
    assert "buck: gave up after" in out and "(--step-limit 0.5 s) in the" in out and "left unplaced" in out


def test_run_max_time_records_stopped_with_the_cap_and_the_rerun_resumes(tmp_path, monkeypatch, capsys):
    pytest.importorskip("pcbnew")
    import shutil
    from placemat import cli, console, layout, runner
    from tests import real_modules as rm
    script = rm.stage(tmp_path, "logicsupply")
    src = runner.find_board(script)

    def restore(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        shutil.copytree(runner.cached_generation(src), src.layout_dir)
        return False
    monkeypatch.setattr(runner, "generate", restore)
    real = layout.Board._recorded_settle
    slow = {"on": True, "n": 0}

    def settle(self, *a, **k):
        slow["n"] += 1
        if slow["on"] and slow["n"] == 4:
            time.sleep(3.0)
        return real(self, *a, **k)
    monkeypatch.setattr(layout.Board, "_recorded_settle", settle)
    try:
        code = cli.main(["run", str(script), "--no-render", "--no-drc", "--max-time", "2"])
    finally:
        console.configure(quiet=False)
    out = capsys.readouterr()
    assert code == 143
    runs = [p for p in (src.board_dir / ".placemat" / "runs").iterdir() if (p / "run.json").exists() and not p.is_symlink()]
    assert len(runs) == 1
    doc = json.loads((runs[0] / "run.json").read_text())
    f = doc["failure"]
    assert doc["status"] == "stopped" and f["kind"] == "stopped" and f["stage"] == "resolve"
    assert f["cause"] == "max_time" and f["limit_s"] == 2.0 and f["steps_of"] and 3 <= f["steps_done"] < f["steps_of"]
    assert f["in_progress"]["item"] and f["findings"]["count"] >= 0
    for stream in (out.out, out.err):
        assert "stopped at --max-time 2 s during resolve" in stream and "run it again and it goes on from there" in stream, stream
    assert (runs[0] / "reuse.partial.jsonl").exists()
    slow["on"] = False
    try:
        code = cli.main(["run", str(script), "--no-render", "--no-drc"])
    finally:
        console.configure(quiet=False)
    got = capsys.readouterr()
    out = got.out + got.err
    assert code in (0, 1) and "(interrupted)" in out and "reused %d of" % f["steps_done"] in " ".join(out.split()), out
    ok = json.loads((runs[0] / "run.json").read_text())
    assert ok["status"] == "ok"
