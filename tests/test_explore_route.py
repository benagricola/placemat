"""`--route-best`: a routing worker quick-routes the plain placement at the start of an explore and each new best by run
score as the search finds it, in the variant's own folder, keeping only the latest best waiting while it is busy; it
finishes what it has when the search ends. Each closure is said as it comes and kept; `--accept` takes the best clean
closure, ties going to the better score. The router here is a stand-in (explore_boards.StandInRouter);
tests/test_explore_route_real.py routes for real."""
import json
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

from placemat import channel, explore, lock, stop
from tests import explore_boards as eb


@pytest.fixture(scope="module")
def seeds():
    """Three seeds, each better than the one before and than the plain placement."""
    return eb.improving(3)


def _log(tmp_path):
    return [json.loads(l) for l in (tmp_path / "routes.log").read_text().splitlines()] if (tmp_path / "routes.log").exists() else []


def _search(tmp_path, order, router=None, jobs=2, delay=0.0, **kw):
    """An explore of make() trying `order` (seed 0 first), each variant taking `delay` s, routing with `router`."""
    script = kw.pop("script", tmp_path / "Board_layout.py")
    kw.setdefault("route_best", True)
    kw.setdefault("variants_dir", tmp_path / "explore")
    return explore.search(eb.Recording(tmp_path / "pids", delay=delay), script, seconds=120, jobs=jobs, seeds=[0] + list(order),
                          router=router or eb.StandInRouter(tmp_path / "routes.log"), **kw)


@pytest.fixture
def events(monkeypatch):
    sent = []

    class Rep:
        def send(self, ev):
            sent.append(ev)
    monkeypatch.setattr(channel, "current", lambda: Rep())
    return sent


def test_the_plain_placement_and_each_new_best_are_routed_in_their_own_folders_as_they_come(tmp_path, seeds, events, capsys,
                                                                                             monkeypatch):
    from placemat import project
    monkeypatch.setattr(project, "find_board", lambda p: SimpleNamespace(board_dir=tmp_path))
    a, b, c = seeds
    report, _ = _search(tmp_path, [a, b, c], delay=2.0,
                        router=eb.StandInRouter(tmp_path / "routes.log", {0: (0.6, 0.7), a: (0.7, 0.8), b: (0.8, 0.9), c: (0.75, 0.9)}))
    assert [r["seed"] for r in _log(tmp_path)] == [0, a, b, c]
    assert all(r["quick"] and r["work"] == str(tmp_path / "explore" / ("seed-%d" % r["seed"]) / "route") for r in _log(tmp_path))
    routes = report["routes"]
    assert [r["seed"] for r in routes] == [0, a, b, c] and routes[2]["closure_clean"] == 0.8 and routes[2]["closure"] == 0.9
    assert routes[0]["score"] == round(report["baseline"], 1) and routes[3]["score"] == round(report["best"], 1)
    assert all(r["dir"] == str(tmp_path / "explore" / ("seed-%d" % r["seed"])) and r["seconds"] >= 0 for r in routes)
    assert [e["seed"] for e in events if e["ev"] == "explore_route"] == [0, a, b, c]           # live, as each came
    out = capsys.readouterr().out
    assert "route, seed %d at %.1f mm: closure 80.0%% clean (90.0%% raw), 3 open" % (b, routes[2]["score"]) in out
    assert report["taken_seed"] == b
    assert any(l.startswith("  routes: 4 variants quick-routed") and l.endswith("taken by closure: seed %d" % b)
               for l in explore.report_lines(report))
    (done,) = [e for e in events if e["ev"] == "explore_done"]
    assert done["routes"] == routes and done["taken_seed"] == b


def test_a_best_overtaken_while_the_worker_is_busy_is_not_routed_only_the_latest_waits(tmp_path, seeds):
    a, b, c = seeds
    report, _ = _search(tmp_path, [a, b, c], delay=0.05, router=eb.StandInRouter(tmp_path / "routes.log", delay=4.0))
    assert [r["seed"] for r in _log(tmp_path)] == [0, c]                       # a and b were overtaken while 0 was routed
    assert [r["seed"] for r in report["routes"]] == [0, c]


def test_with_one_job_the_routes_run_after_the_search(tmp_path, seeds):
    a, b, c = seeds
    report, _ = _search(tmp_path, [a, b, c], jobs=1, delay=1.5)
    assert [r["seed"] for r in _log(tmp_path)] == [0, c]           # a and b were bests while the search ran, and overtaken


def test_the_router_takes_one_of_the_jobs(tmp_path, seeds, monkeypatch):
    real, workers = explore.explore, []

    def spy(*a, **kw):
        r = real(*a, **kw)
        workers.append(r.jobs)
        return r
    monkeypatch.setattr(explore, "explore", spy)
    _search(tmp_path, seeds, jobs=3)
    _search(tmp_path, seeds, jobs=3, route_best=False, script=tmp_path / "Other_layout.py")
    assert workers == [2, 3]


def test_accept_takes_the_best_closure_not_the_best_score(tmp_path, seeds):
    a, b, c = seeds
    script = tmp_path / "Board_layout.py"
    report, _ = _search(tmp_path, [a, b, c], delay=2.0, accept=True,
                        router=eb.StandInRouter(tmp_path / "routes.log", {0: (0.5, 0.5), a: (0.9, 0.9), b: (0.6, 0.6), c: (0.7, 0.7)}))
    assert report["best_seed"] == c and report["taken_seed"] == a and report["accepted"]
    board = eb.make()
    plan = board.resolve(explore=explore.Explore(a, eb.FOCUS))
    held = eb.make().resolve(lock=lock.read(lock.path_for(script)))
    for key in eb.KEYS:
        if plan.placement(key) is not None:
            assert held.placement(key).location.distance(plan.placement(key).location) < 1e-6, key
    assert "accepted: written to the lock" in explore.report_lines(report)


def test_a_tie_on_closure_goes_to_the_better_score(tmp_path, seeds):
    a, b, c = seeds
    report, _ = _search(tmp_path, [a, b, c], delay=2.0,
                        router=eb.StandInRouter(tmp_path / "routes.log", {0: (0.9, 0.9), a: (0.9, 0.9), b: (0.9, 1.0), c: (0.9, 0.9)}))
    assert report["taken_seed"] == c


def test_when_the_plain_placement_routes_best_nothing_is_accepted(tmp_path, seeds):
    script = tmp_path / "Board_layout.py"
    report, entries = _search(tmp_path, seeds, jobs=1, accept=True,
                              router=eb.StandInRouter(tmp_path / "routes.log", {0: (1.0, 1.0)}))
    assert report["taken_seed"] == 0 and not report["accepted"] and report["moves"] == []
    assert not lock.path_for(script).exists() and entries == []
    assert any("taken by closure: seed 0, the current placement" in l for l in explore.report_lines(report))
    assert "nothing to accept: the current placement's route closed best" in explore.report_lines(report)


def test_a_failing_route_is_reported_and_the_explore_stands(tmp_path, seeds):
    a, b, c = seeds
    report, _ = _search(tmp_path, seeds, jobs=1, accept=True,
                        router=eb.StandInRouter(tmp_path / "routes.log", {0: (0.4, 0.5), c: "router exited 1 without a routed board\ntail"}))
    r0, rc = report["routes"]
    assert rc["seed"] == c and rc["error"] == {"type": "RuntimeError", "message": "router exited 1 without a routed board\ntail"}
    assert report["best_seed"] == c and report["taken_seed"] == 0 and not report["accepted"]
    assert "  route, seed %d at %.1f mm: the route failed with RuntimeError: router exited 1 without a routed board" % (
        c, rc["score"]) in explore.route_lines(report)


def test_when_every_route_fails_the_best_score_is_taken(tmp_path, seeds):
    a, b, c = seeds
    report, _ = _search(tmp_path, seeds, jobs=1, accept=True,
                        router=eb.StandInRouter(tmp_path / "routes.log", {0: "no router", c: "no router"}))
    assert [r["error"]["type"] for r in report["routes"]] == ["RuntimeError", "RuntimeError"]
    assert "taken_seed" not in report and report["accepted"] and report["best_seed"] == c
    assert any(l.endswith("every route failed: the best score is taken") for l in explore.report_lines(report))


def test_a_routing_worker_that_dies_is_reported_and_the_explore_stands(tmp_path, seeds):
    report, _ = _search(tmp_path, seeds, jobs=1, router=Dying(tmp_path / "routes.log"))
    assert report["routes"] and all("error" in r for r in report["routes"])
    assert "routing worker" in report["routes"][0]["error"]["message"] and report["best_seed"] == seeds[-1]


class Dying(eb.StandInRouter):
    """A router whose process is killed as it routes (the out-of-memory killer)."""

    def route(self, *a, **kw):
        import os
        os.kill(os.getpid(), signal.SIGKILL)


def test_route_best_off_routes_nothing_and_starts_no_routing_worker(tmp_path, seeds):
    report, _ = _search(tmp_path, seeds, jobs=1, route_best=False)
    assert not (tmp_path / "routes.log").exists() and not (tmp_path / "explore").exists()
    assert "routes" not in report and "taken_seed" not in report


def test_the_setting_turns_it_on_and_is_off_by_default(tmp_path, seeds):
    from placemat.settings import Settings
    assert Settings().explore_route_best is False
    report, _ = explore.search(eb.Settled(explore_route_best=True), tmp_path / "Board_layout.py", seconds=60, jobs=1,
                               seeds=[0] + seeds, variants_dir=tmp_path / "explore",
                               router=eb.StandInRouter(tmp_path / "routes.log"))
    assert [r["seed"] for r in report["routes"]] == [0, seeds[-1]]


def test_without_a_folder_for_the_variants_nothing_is_routed_and_the_report_says_so(tmp_path, seeds):
    report, _ = _search(tmp_path, seeds, jobs=1, variants_dir=None)
    assert not (tmp_path / "routes.log").exists() and report["routes"] == [] and report["routes_skipped"] == "no_board"
    assert "  routes: none; a preview writes no board to route: explore in a run to route its variants" in \
        explore.report_lines(report)


def test_the_routes_leave_out_the_runs_exclusions_and_no_resume_reaches_them(tmp_path, seeds):
    _search(tmp_path, seeds, jobs=1, route_exclude=("N3",), route_resume=False)
    assert all("N3" in r["exclude"] and r["resume"] is False for r in _log(tmp_path))


def test_a_stop_while_routing_keeps_the_routes_done_and_the_accept_command_and_sends_explore_done(tmp_path, seeds, monkeypatch):
    sent = []

    class Rep:
        def send(self, ev):
            sent.append(ev)
            if ev["ev"] == "explore_route":
                raise stop.Stopped(signal.SIGTERM)
    monkeypatch.setattr(channel, "current", lambda: Rep())
    script = tmp_path / "Board_layout.py"
    with pytest.raises(stop.Stopped) as e:
        _search(tmp_path, seeds, jobs=1, accept=True, checkpoint_dir=tmp_path / "state", keep_state=True)
    r = e.value.explore
    assert e.value.stage == "explore" and r["stopped"] == "SIGTERM" and not r["accepted"]
    assert [x["seed"] for x in r["routes"]] == [0] and r["accept"] == explore.accept_command(script, seeds[-1])
    (done,) = [ev for ev in sent if ev["ev"] == "explore_done"]
    assert done["kept"] is False and done["stopped"] == "SIGTERM" and [x["seed"] for x in done["routes"]] == [0]
    assert not lock.path_for(script).exists()


def test_the_record_carries_the_routes_and_keeps_the_taken_variants_plan(tmp_path, seeds, monkeypatch):
    from placemat import project
    kept = []
    monkeypatch.setattr(explore, "_write_best", lambda record, result, board, plan, total=None, measures=None: kept.append((plan, total)))
    monkeypatch.setattr(project, "find_board", lambda p: SimpleNamespace(board_dir=tmp_path))
    a, b, c = seeds
    report, _ = _search(tmp_path, [a, b, c], delay=2.0,
                        router=eb.StandInRouter(tmp_path / "routes.log", {a: (0.9, 0.9)}))
    doc = json.loads(Path(report["record"]).read_text())
    assert doc["routes"] == report["routes"] and doc["taken_seed"] == a
    (plan, total), = kept
    want = eb.make().resolve(explore=explore.Explore(a, eb.FOCUS))
    for key in eb.KEYS:
        if want.placement(key) is not None:
            assert plan.placement(key).location.distance(want.placement(key).location) < 1e-6, key


def test_route_best_is_a_flag_with_explore():
    from placemat.cli import _explore_options, parser
    assert _explore_options(parser().parse_args(["run", "x.py", "--explore", "60", "--route-best"])).route_best is True
    assert _explore_options(parser().parse_args(["run", "x.py", "--explore", "60"])).route_best is None
    with pytest.raises(SystemExit):
        _explore_options(parser().parse_args(["run", "x.py", "--route-best"]))


def test_route_best_is_not_part_of_what_a_variant_is():
    from placemat.reuse import placement_settings
    from placemat.settings import Settings
    assert "explore_route_best" not in placement_settings(Settings())


def test_the_setting_reads_from_the_toml(tmp_path):
    from placemat.settings import load
    (tmp_path / "placemat.toml").write_text("[explore]\nroute_best = true\n")
    assert load(tmp_path).explore_route_best is True


def test_the_runner_hands_the_runs_resume_and_its_folder_to_the_explore(tmp_path, monkeypatch):
    """`placemat run --no-resume` routes every stage again: the variants' routes too."""
    pytest.importorskip("pcbnew")
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


def test_the_released_route_top_setting_is_refused_naming_route_best(tmp_path):
    from placemat.settings import SettingsError, load
    (tmp_path / "placemat.toml").write_text("[explore]\nroute_top = 3\n")
    with pytest.raises(SettingsError, match="explore.route_top is retired; set explore.route_best"):
        load(tmp_path)


def test_a_stop_while_the_routing_worker_starts_still_ends_the_workers(tmp_path, seeds, monkeypatch):
    import multiprocessing.process as mpp
    ended = []
    real_end, real_start = explore._end, mpp.BaseProcess.start
    monkeypatch.setattr(explore, "_end", lambda procs: (ended.append([p.name for p in procs]), real_end(procs)))

    def start(self):
        if self.name == "explore-router":
            raise stop.Stopped(signal.SIGTERM)
        return real_start(self)
    monkeypatch.setattr(mpp.BaseProcess, "start", start)
    with pytest.raises(stop.Stopped):
        _search(tmp_path, seeds, jobs=2)
    assert any("explore-router" in names for names in ended)
