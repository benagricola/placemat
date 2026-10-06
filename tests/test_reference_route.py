import json

from fixtures.reference import prepare, route_ref

V = prepare.Violation
VERSIONS = {"placemat": "0", "krt": "0", "pcb": "0"}


def _result(**over):
    fields = dict(board="x", widths="class", closure_clean=1.0, open=0, open_nets=[], new_violations=[], vias=3,
                  track_mm=10.0, human_vias=2, human_track_mm=9.0, passed=True, seconds=1.0, versions=VERSIONS)
    return route_ref.AResult(**dict(fields, **over))


def test_a_violation_already_in_the_baseline_is_not_new():
    base = [V("clearance", ("A", "B"), (10.0, 10.0))]
    after = [V("clearance", ("A", "B"), (10.02, 10.0)), V("short", ("A", "C"), (5.0, 5.0))]
    assert route_ref.new_violations(after, base) == [V("short", ("A", "C"), (5.0, 5.0))]


def test_a_baseline_violation_further_than_the_tolerance_does_not_match():
    base = [V("clearance", ("A", "B"), (10.0, 10.0))]
    after = [V("clearance", ("A", "B"), (10.2, 10.0))]
    assert route_ref.new_violations(after, base) == after


def test_passed_needs_full_clean_closure_and_nothing_new():
    r = _result()
    assert r.passed
    assert not route_ref.judge(dict(closure_clean=0.98), [], r).passed
    assert not route_ref.judge(dict(closure_clean=1.0), [V("short", ("A", "C"), (5.0, 5.0))], r).passed
    assert route_ref.judge(dict(closure_clean=1.0), [], r).passed


def test_judge_reads_the_route_report():
    report = dict(closure_clean=0.95, open_after=2, open_nets={"A": 1, "B": 1}, seconds=12.5, vias=7, track_mm=33.0)
    r = route_ref.judge(report, [], _result())
    assert (r.closure_clean, r.open, r.open_nets, r.seconds, r.vias, r.track_mm) == (0.95, 2, ["A", "B"], 12.5, 7, 33.0)
    assert (r.board, r.human_vias, r.versions) == ("x", 2, VERSIONS)


def test_a_board_that_passed_and_now_fails_is_worse():
    recorded = {"a": {"x": {"class": json.loads(json.dumps(route_ref.asdict(_result())))}}}
    now = _result(closure_clean=0.9, passed=False)
    c = route_ref.compare(recorded["a"]["x"]["class"], now, "placemat")
    assert (c.status, c.differ) == ("worse", [])
    assert route_ref.compare(recorded["a"]["x"]["class"], _result(), "placemat").status == "same"
    assert route_ref.compare(None, _result(), "placemat").status == "new"


def test_a_fall_in_closure_is_worse_even_when_both_fail():
    old = route_ref.asdict(_result(closure_clean=0.9, passed=False))
    assert route_ref.compare(old, _result(closure_clean=0.8, passed=False), "placemat").status == "worse"
    assert route_ref.compare(old, _result(closure_clean=0.95, passed=False), "placemat").status == "better"


def test_results_with_another_router_version_are_not_compared():
    old = route_ref.asdict(_result())
    now = _result(closure_clean=0.5, passed=False, versions=dict(VERSIONS, krt="1"))
    c = route_ref.compare(old, now, "placemat")
    assert (c.status, c.differ) == ("not comparable", ["krt"])
    assert route_ref.comparable(old["versions"], now.versions, "krt") == []
    assert route_ref.comparable(old["versions"], now.versions, "placemat") == ["krt"]


def test_update_rewrites_the_boards_it_ran_in_the_a_key_and_keeps_the_rest(tmp_path):
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"a": {"old": {"class": {}}}, "b": {"keep": 1}}))
    route_ref.save_results(path, [_result()])
    data = json.loads(path.read_text())
    assert data["b"] == {"keep": 1}
    assert sorted(data["a"]) == ["old", "x"] and data["a"]["x"]["class"]["closure_clean"] == 1.0


def test_more_new_violations_at_equal_closure_is_worse():
    old = route_ref.asdict(_result(closure_clean=0.9, passed=False, new_violations=[V("short", ("A", "B"), (1.0, 1.0))]))
    more = _result(closure_clean=0.9, passed=False, new_violations=[V("short", ("A", "B"), (1.0, 1.0)), V("short", ("A", "C"), (2.0, 2.0))])
    assert route_ref.compare(old, more, "placemat").status == "worse"


def test_the_console_line_names_the_components_that_differ():
    text = route_ref.line(_result(), route_ref.Comparison("not comparable", ["krt"]))
    assert "not comparable: krt differ" in text


def test_run_a_judges_the_route_json_against_the_baseline(tmp_path, monkeypatch):
    board = route_ref.fetch.Board(name="x", repo="github:o/r", commit="0" * 40, files={}, board="x.kicad_pcb", licence="MIT",
                                  tests=("a",), islands=("VCC",), fixed=(), human_track_mm=0.2, kicad5=False)
    seen = {}

    def route(pcb, work, islands, toml):
        seen.update(pcb=pcb, islands=islands, toml=toml)
        return dict(closure_clean=1.0, open_after=0, open_nets={}, seconds=2.0, routed_pcb=str(tmp_path / "routed.kicad_pcb"))

    def violations(path):
        return [V("clearance", ("A", "B"), (1.0, 1.0))] if path.name == prepare.BASELINE else [
            V("clearance", ("A", "B"), (1.0, 1.0)), V("short", ("A", "C"), (5.0, 5.0))]

    monkeypatch.setattr(route_ref, "_route", route)
    monkeypatch.setattr(route_ref, "_krt_version", lambda pcb: "krt1")
    monkeypatch.setattr(prepare, "measure", lambda pcb: (2, prepare.HumanCopper(4, 50.0)))
    monkeypatch.setattr(prepare, "violations", violations)
    r = route_ref.run_a(board, tmp_path, track_mm=0.2, versions={"placemat": "p", "pcb": "z"})
    assert seen["islands"] == ("VCC",) and "--track-width" in seen["toml"]
    assert r.widths == "human" and not r.passed and r.new_violations == [V("short", ("A", "C"), (5.0, 5.0))]
    assert (r.vias, r.track_mm, r.versions) == (4, 50.0, {"placemat": "p", "pcb": "z", "krt": "krt1"})


def _main_with_work_root_seen(tmp_path, monkeypatch, *extra):
    import contextlib
    import tempfile
    seen = []
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(route_ref.fetch, "load_manifest", lambda: [])
    monkeypatch.setattr(route_ref.lock, "realboard", contextlib.nullcontext)
    monkeypatch.setattr(route_ref, "current_versions", lambda: {})
    monkeypatch.setattr(route_ref, "_run_boards", lambda boards, root, *a: seen.append(root) or False)
    route_ref.main(["--results", str(tmp_path / "results.json"), *extra])
    return seen[0]


def test_a_temporary_work_root_is_removed_after_the_run(tmp_path, monkeypatch):
    root = _main_with_work_root_seen(tmp_path, monkeypatch)
    assert root.parent == tmp_path and not root.exists()


def test_a_work_root_given_with_work_is_kept(tmp_path, monkeypatch):
    work = tmp_path / "keep"
    work.mkdir()
    root = _main_with_work_root_seen(tmp_path, monkeypatch, "--work", str(work))
    assert root == work and work.exists()
