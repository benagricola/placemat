"""An explore can quick-route its best `explore.route_top` variants, each on its own written board in its own folder, one at
a time: each one's route closure is reported beside its run score, and `--accept` takes the best closure, ties going to the
better score. A route that fails is reported for its variant and the explore's result stands. The router here is a stand-in
(`route_board` patched); tests/test_explore_route_real.py routes for real."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from placemat import explore, lock
from placemat.kicad import route as route_mod
from tests.test_pinmap_explore import SEEDS, _searched_board

# seeds 0-7 of `_searched_board` rank 2, 6, 5 first by run score (tests/test_pinmap_explore.py)


def _report(closure_clean, closure, open_before=10, open_after=3, seconds=1.5):
    return SimpleNamespace(closure_clean=closure_clean, closure=closure, open_before=open_before, open_after=open_after,
                           seconds=seconds, valid=True, invalid_reason="")


@pytest.fixture
def router(monkeypatch):
    """The stand-in router: `router.closures[seed]` is (clean, raw) for that variant's route, or an exception it raises.
    `router.calls` keeps each call's board, work folder and the nets it was told to leave out."""
    calls, closures = [], {}

    def write(make_board, board, plan, folder):
        folder.mkdir(parents=True, exist_ok=True)
        pcb = folder / "layout.kicad_pcb"
        pcb.write_text("seed %s" % folder.name)
        return pcb

    def route_board(pcb, work, exclude_nets=(), quick=False, **kw):
        seed = int(Path(pcb).parent.name.split("-")[1])
        calls.append({"seed": seed, "pcb": Path(pcb), "work": Path(work), "exclude": set(exclude_nets), "quick": quick,
                      "resume": kw.get("resume", True)})
        got = closures[seed]
        if isinstance(got, BaseException):
            raise got
        return _report(*got)
    monkeypatch.setattr(explore, "_write_variant", write)
    monkeypatch.setattr(route_mod, "route_board", route_board)
    return SimpleNamespace(calls=calls, closures=closures)


def test_the_top_variants_are_routed_one_by_one_in_their_own_folders_and_their_closures_reported(tmp_path, router):
    router.closures.update({2: (0.8, 0.9), 6: (0.85, 0.95)})
    report, _ = explore.search(_searched_board, tmp_path / "Board_layout.py", seconds=60, jobs=1, seeds=SEEDS,
                               route_top=2, variants_dir=tmp_path / "explore")
    assert report["best_seed"] == 2
    assert [c["seed"] for c in router.calls] == [2, 6] and all(c["quick"] for c in router.calls)
    assert [c["work"] for c in router.calls] == [tmp_path / "explore" / "seed-2" / "route", tmp_path / "explore" / "seed-6" / "route"]
    r2, r6 = report["routes"]
    assert (r2["seed"], r2["closure_clean"], r2["closure"], r2["open_before"], r2["open_after"]) == (2, 0.8, 0.9, 10, 3)
    assert r6["seed"] == 6 and r6["closure_clean"] == 0.85 and r2["score"] == round(report["best"], 1)
    assert r2["dir"] == str(tmp_path / "explore" / "seed-2") and isinstance(r2["seconds"], float)
    lines = explore.report_lines(report)
    assert "  route, seed 2 at %.1f mm: closure 80.0%% clean (90.0%% raw), 3 open, in %s" % (
        r2["score"], explore.duration(r2["seconds"])) in lines
    assert any(l.startswith("  routes: 2 variants quick-routed in ") and l.endswith("taken by closure: seed 6") for l in lines)
    record = json.loads(Path(report["record"]).read_text()) if report.get("record") else None
    if record is not None:
        assert record["routes"] == report["routes"] and record["taken_seed"] == 6


def test_the_record_and_the_done_event_carry_the_routes(tmp_path, monkeypatch):
    from placemat import channel, project
    sent = []

    class Rep:
        def send(self, ev):
            sent.append(ev)
    monkeypatch.setattr(channel, "current", lambda: Rep())
    monkeypatch.setattr(project, "find_board", lambda p: SimpleNamespace(board_dir=tmp_path))
    result = SimpleNamespace(focus=["r1"], seconds=1.0, jobs=1, baseline=10.0, plain={}, plain_order=[], best_seed=2, best=9.0,
                             variants=[], curve=[], ended=None, tried=3)
    routes = [{"seed": 2, "score": 9.0, "closure_clean": 0.8, "closure": 0.9, "open_before": 10, "open_after": 3,
               "seconds": 1.5, "dir": "x"}]
    report = {"accepted": False, "routes": routes, "taken_seed": 2}
    explore._write_record(tmp_path / "Board_layout.py", result, report, "", None)
    doc = json.loads(open(report["record"]).read())
    assert doc["routes"] == routes and doc["taken_seed"] == 2
    (done,) = [e for e in sent if e["ev"] == "explore_done"]
    assert done["routes"] == routes and done["taken_seed"] == 2


def test_accept_takes_the_best_closure_not_the_best_score(tmp_path, router):
    router.closures.update({2: (0.8, 0.9), 6: (0.9, 0.9), 5: (0.85, 0.99)})
    script = tmp_path / "Board_layout.py"
    report, entries = explore.search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS, accept=True,
                                     route_top=3, variants_dir=tmp_path / "explore")
    assert report["best_seed"] == 2 and report["taken_seed"] == 6 and report["accepted"]
    # what the lock now holds is seed 6's placement: a plain resolve under it places the focused items where seed 6 did
    held = _searched_board().resolve(lock=lock.read(lock.path_for(script)))
    six = _searched_board().resolve(explore=explore.Explore(6, frozenset(report["focus"])))
    for key in report["focus"]:
        assert held.placement(key).location.distance(six.placement(key).location) < 1e-6, key
    assert report["moves"] == [m for m in (explore._move_of(k, _searched_board().resolve().placement(k), six.placement(k))
                                           for k in sorted(report["focus"])) if m]
    assert "accepted: written to the lock" in explore.report_lines(report)


def test_a_tie_on_closure_goes_to_the_better_score(tmp_path, router):
    router.closures.update({2: (0.9, 0.9), 6: (0.9, 1.0)})
    report, _ = explore.search(_searched_board, tmp_path / "Board_layout.py", seconds=60, jobs=1, seeds=SEEDS,
                               route_top=2, variants_dir=tmp_path / "explore")
    assert report["taken_seed"] == 2


def test_the_current_placement_routing_best_is_taken_and_nothing_is_accepted(tmp_path, router, monkeypatch):
    """With the plain placement in the top N (a seed of 0) and closing best, the lock is left as it is."""
    real = explore.explore

    def plain_first(*a, **kw):
        r = real(*a, **kw)
        r.results = sorted(r.results, key=lambda row: row[0] != 0)          # the plain placement ranked first
        return r
    monkeypatch.setattr(explore, "explore", plain_first)
    router.closures.update({0: (1.0, 1.0), 2: (0.5, 0.5)})
    script = tmp_path / "Board_layout.py"
    report, entries = explore.search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS, accept=True,
                                     route_top=2, variants_dir=tmp_path / "explore")
    assert report["taken_seed"] == 0 and not report["accepted"] and report["moves"] == []
    assert not lock.path_for(script).exists() and entries == []
    assert any("taken by closure: seed 0, the current placement" in l for l in explore.report_lines(report))


def test_route_top_0_routes_nothing_and_reports_as_before(tmp_path, router):
    script = tmp_path / "Board_layout.py"
    plain, _ = explore.search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS)
    zero, _ = explore.search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS, route_top=0,
                             variants_dir=tmp_path / "explore")
    assert router.calls == [] and not (tmp_path / "explore").exists()
    assert "routes" not in zero and "taken_seed" not in zero
    assert set(zero) == set(plain)
    strip = lambda ls: [l for l in ls if "variants in" not in l]          # the head line carries the seconds
    assert strip(explore.report_lines(zero)) == strip(explore.report_lines(plain))


def _routing_one():
    """`_searched_board` with `explore.route_top` 1."""
    from dataclasses import replace
    b = _searched_board()
    b.settings = replace(b.settings, explore_route_top=1)
    return b


def test_route_top_defaults_to_the_setting_which_is_0(tmp_path, router):
    from placemat.settings import Settings
    assert Settings().explore_route_top == 0
    router.closures.update({2: (0.8, 0.9)})
    report, _ = explore.search(_routing_one, tmp_path / "Board_layout.py", seconds=60, jobs=1, seeds=SEEDS,
                               variants_dir=tmp_path / "explore")
    assert [r["seed"] for r in report["routes"]] == [2]


def test_a_failing_route_is_reported_for_its_variant_and_the_explore_stands(tmp_path, router):
    router.closures.update({2: RuntimeError("router exited 1 without a routed board; log x\ntail"), 6: (0.7, 0.8)})
    script = tmp_path / "Board_layout.py"
    report, _ = explore.search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS, accept=True,
                               route_top=2, variants_dir=tmp_path / "explore")
    r2, r6 = report["routes"]
    assert r2["seed"] == 2 and r2["error"] == {"type": "RuntimeError",
                                                "message": "router exited 1 without a routed board; log x\ntail"}
    assert "closure_clean" not in r2 and r6["closure_clean"] == 0.7
    assert report["best_seed"] == 2 and report["taken_seed"] == 6 and report["accepted"]
    lines = explore.report_lines(report)
    assert "  route, seed 2 at %.1f mm: the route failed with RuntimeError: router exited 1 without a routed board; log x" % (
        r2["score"]) in lines


def test_when_every_route_fails_the_best_score_is_taken(tmp_path, router):
    import subprocess
    router.closures.update({2: subprocess.TimeoutExpired(["router"], 5), 6: FileNotFoundError("router not found")})
    script = tmp_path / "Board_layout.py"
    report, _ = explore.search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS, accept=True,
                               route_top=2, variants_dir=tmp_path / "explore")
    assert [r["error"]["type"] for r in report["routes"]] == ["TimeoutExpired", "FileNotFoundError"]
    assert "taken_seed" not in report and report["accepted"] and report["best_seed"] == 2
    assert any(l.startswith("  routes: 2 variants quick-routed in ") and l.endswith("every route failed: the best score is taken")
               for l in explore.report_lines(report))


def test_a_variant_whose_board_cannot_be_written_is_reported_as_failed(tmp_path, router, monkeypatch):
    def broken(make_board, board, plan, folder):
        raise OSError("disk full")
    monkeypatch.setattr(explore, "_write_variant", broken)
    report, _ = explore.search(_searched_board, tmp_path / "Board_layout.py", seconds=60, jobs=1, seeds=SEEDS,
                               route_top=1, variants_dir=tmp_path / "explore")
    assert report["routes"][0]["error"] == {"type": "OSError", "message": "disk full"} and router.calls == []


def test_a_stop_during_a_route_stops_the_explore_keeping_the_routes_done_and_accepting_nothing(tmp_path, router):
    import signal
    from placemat import stop
    router.closures.update({2: (0.8, 0.9), 6: stop.Stopped(signal.SIGTERM)})
    script = tmp_path / "Board_layout.py"
    with pytest.raises(stop.Stopped) as e:
        explore.search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS, accept=True,
                       route_top=2, variants_dir=tmp_path / "explore")
    r = e.value.explore
    assert e.value.stage == "explore" and r["stopped"] == "SIGTERM" and not r["accepted"]
    assert [x["seed"] for x in r["routes"]] == [2] and not lock.path_for(script).exists()


def test_without_a_folder_for_the_variants_nothing_is_routed_and_the_report_says_so(tmp_path, router):
    report, _ = explore.search(_searched_board, tmp_path / "Board_layout.py", seconds=60, jobs=1, seeds=SEEDS, route_top=2)
    assert router.calls == [] and report["routes"] == [] and report["routes_skipped"] == "no_board"
    assert "  routes: none; a preview writes no board to route: explore in a run to route its variants" in \
        explore.report_lines(report)


def test_the_routes_leave_out_the_runs_route_exclusions(tmp_path, router):
    router.closures.update({2: (0.8, 0.9)})
    explore.search(_searched_board, tmp_path / "Board_layout.py", seconds=60, jobs=1, seeds=SEEDS, route_top=1,
                   variants_dir=tmp_path / "explore", route_exclude=("G1",))
    assert router.calls[0]["exclude"] >= {"G1"}


def test_route_top_is_a_flag_with_explore():
    from placemat.cli import _explore_options, parser as build_parser
    args = build_parser().parse_args(["run", "x.py", "--explore", "60", "--route-top", "3"])
    assert _explore_options(args).route_top == 3
    args = build_parser().parse_args(["run", "x.py", "--explore", "60"])
    assert _explore_options(args).route_top is None
    with pytest.raises(SystemExit):
        _explore_options(build_parser().parse_args(["run", "x.py", "--route-top", "3"]))


def test_route_top_is_not_part_of_what_a_variant_is():
    from placemat.reuse import placement_settings
    from placemat.settings import Settings
    assert "explore_route_top" not in placement_settings(Settings())


def test_the_setting_reads_from_the_toml_and_refuses_a_negative(tmp_path):
    from placemat.settings import SettingsError, load
    (tmp_path / "placemat.toml").write_text("[explore]\nroute_top = 3\n")
    assert load(tmp_path).explore_route_top == 3
    (tmp_path / "placemat.toml").write_text("[explore]\nroute_top = -1\n")
    with pytest.raises(SettingsError, match="explore.route_top"):
        load(tmp_path)


def test_a_stop_during_the_routes_keeps_the_saved_bests_accept_command(tmp_path, router):
    import signal
    from placemat import stop
    router.closures.update({2: (0.8, 0.9), 6: stop.Stopped(signal.SIGTERM)})
    script = tmp_path / "Board_layout.py"
    with pytest.raises(stop.Stopped) as e:
        explore.search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS, accept=True, route_top=2,
                       variants_dir=tmp_path / "explore", checkpoint_dir=tmp_path / "state", keep_state=True)
    r = e.value.explore
    assert r["best_seed"] == 2 and r["accept"] == explore.accept_command(script, 2) and not r["accepted"]


def test_the_accept_command_names_the_variant_taken(tmp_path, router):
    script = tmp_path / "Board_layout.py"
    router.closures.update({2: (0.9, 0.9), 6: (0.8, 0.9)})
    report, _ = explore.search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS, route_top=2,
                               variants_dir=tmp_path / "explore", checkpoint_dir=tmp_path / "s1", keep_state=True)
    assert report["taken_seed"] == 2 and report["accept"] == explore.accept_command(script, 2)
    router.closures.update({2: (0.8, 0.9), 6: (0.9, 0.9)})
    report, _ = explore.search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS, route_top=2,
                               variants_dir=tmp_path / "explore2", checkpoint_dir=tmp_path / "s2", keep_state=True)
    assert report["taken_seed"] == 6 and report["accept"] == explore.accept_command(script, 6)    # every variant is kept


def test_a_stop_during_the_routes_sends_explore_done_with_the_routes_so_far_and_nothing_kept(tmp_path, router, monkeypatch):
    import signal
    from placemat import channel, stop
    sent = []

    class Rep:
        def send(self, ev):
            sent.append(ev)
    monkeypatch.setattr(channel, "current", lambda: Rep())
    router.closures.update({2: (0.8, 0.9), 6: stop.Stopped(signal.SIGTERM)})
    with pytest.raises(stop.Stopped):
        explore.search(_searched_board, tmp_path / "Board_layout.py", seconds=60, jobs=1, seeds=SEEDS, accept=True,
                       route_top=2, variants_dir=tmp_path / "explore")
    (done,) = [e for e in sent if e["ev"] == "explore_done"]
    assert done["kept"] is False and done["stopped"] == "SIGTERM" and [r["seed"] for r in done["routes"]] == [2]
    assert done["best_seed"] == 2 and "taken_seed" not in done


def test_no_resume_reaches_the_variants_routes(tmp_path, router):
    router.closures.update({2: (0.8, 0.9)})
    explore.search(_searched_board, tmp_path / "a" / "Board_layout.py", seconds=60, jobs=1, seeds=SEEDS, route_top=1,
                   variants_dir=tmp_path / "explore")
    explore.search(_searched_board, tmp_path / "b" / "Board_layout.py", seconds=60, jobs=1, seeds=SEEDS, route_top=1,
                   variants_dir=tmp_path / "explore", route_resume=False)
    assert [c["resume"] for c in router.calls] == [True, False]


def test_the_runner_hands_the_runs_resume_and_its_folder_to_the_explore(tmp_path, monkeypatch):
    """`placemat run --no-resume` routes every stage again: the variants' routes too."""
    import signal
    pytest.importorskip("pcbnew")
    from placemat import stop
    from tests.test_stop_run import _stage_and_patch
    script, src, runner = _stage_and_patch(tmp_path, monkeypatch)
    seen = []

    def stopping(*a, **kw):
        seen.append(kw)
        raise stop.Stopped(signal.SIGTERM)
    monkeypatch.setattr(explore, "before_resolve", stopping)
    for resume in (True, False):
        with pytest.raises(stop.Stopped):
            runner.run(script, render=False, quiet=True, reuse=False, resume=resume, route_exclude=("X",))
    from placemat import console
    console.configure(quiet=False)
    assert [kw["route_resume"] for kw in seen] == [True, False] and seen[0]["route_exclude"] == ("X",)
    assert seen[0]["variants_dir"].name == "explore"


def test_the_plan_kept_beside_the_record_is_the_taken_variants(tmp_path, router, monkeypatch):
    kept = []
    monkeypatch.setattr(explore, "_write_best", lambda record, result, board, plan, total=None, measures=None: kept.append((plan, total)))
    from placemat import project
    monkeypatch.setattr(project, "find_board", lambda p: SimpleNamespace(board_dir=tmp_path))
    router.closures.update({2: (0.8, 0.9), 6: (0.9, 0.9)})
    report, _ = explore.search(_searched_board, tmp_path / "Board_layout.py", seconds=60, jobs=1, seeds=SEEDS, accept=True,
                               route_top=2, variants_dir=tmp_path / "explore")
    (plan, total), = kept
    six = _searched_board().resolve(explore=explore.Explore(6, frozenset(report["focus"])))
    for key in report["focus"]:
        assert plan.placement(key).location.distance(six.placement(key).location) < 1e-6, key
    assert total == next(r["score"] for r in report["routes"] if r["seed"] == 6) or abs(total - [r for r in report["routes"] if r["seed"] == 6][0]["score"]) < 0.06
