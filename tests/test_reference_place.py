import json
import shutil

from fixtures.reference import fetch, place_ref, prepare, route_ref

VERSIONS = {"placemat": "0", "krt": "0", "pcb": "0"}
BOARD = fetch.Board(name="x", repo="github:o/r", commit="c", files={}, board="x.kicad_pcb", licence="MIT", tests=("a", "b"),
                    islands=(), fixed=("J1",), human_track_mm=None, kicad5=False)
PREPARED = prepare.Prepared(None, None, [], 2, prepare.HumanCopper(4, 20.0))


import pytest


@pytest.fixture(autouse=True)
def _digest(monkeypatch):
    monkeypatch.setattr(place_ref, "generation_inputs", lambda script: "d1")


def _m(**over):
    fields = dict(script="fam/X", closure_clean=1.0, area_mm2=100.0, run_score=5.0, seconds=1.0, versions=VERSIONS, failure="", inputs_digest="d1")
    return place_ref.MResult(**dict(fields, **over))


def _b(**over):
    fields = dict(board="x", closure_clean=1.0, open=0, new_violations=[], vias=3, track_mm=10.0, run_score=5.0, ref_vias=4,
                  ref_track_mm=20.0, a_closure_clean=1.0, seconds=1.0, versions=VERSIONS, failure="", inputs_digest="d1")
    return place_ref.BResult(**dict(fields, **over))


def _folder(tmp_path, script_text):
    folder = tmp_path / "boards" / "x"
    folder.mkdir(parents=True)
    (folder / "X_layout.py").write_text(script_text)
    return folder


def test_a_script_that_fails_the_lint_is_refused_and_placemat_is_not_run(tmp_path, monkeypatch):
    folder = _folder(tmp_path, 'board.place(Part("U1"), at=Location(1, 2))\n')
    monkeypatch.setattr(place_ref, "placemat_run", lambda *a, **k: raise_("placemat run must not start"))
    r = place_ref.run_b(BOARD, folder, tmp_path / "work", prepared=PREPARED, versions=VERSIONS, a_closure_clean=1.0)
    assert (r.failure, r.closure_clean) == ("lint", 0.0)
    assert (r.ref_vias, r.ref_track_mm, r.a_closure_clean) == (4, 20.0, 1.0)


def raise_(message):
    raise AssertionError(message)


def test_a_refused_run_is_a_failed_result_with_its_failure_kind(tmp_path, monkeypatch):
    folder = _folder(tmp_path, 'board.place(Part("J1"), at=Location(1, 2), why="mechanical: connector")\n')
    refused = {"status": "failed", "failure": {"kind": "placement", "message": "Firm placements collide"}, "metrics": {}}
    monkeypatch.setattr(place_ref, "placemat_run", lambda *a, **k: (refused, 3.0))
    r = place_ref.run_b(BOARD, folder, tmp_path / "work", prepared=PREPARED, versions=VERSIONS, a_closure_clean=1.0)
    assert (r.failure, r.closure_clean, r.seconds) == ("placement", 0.0, 3.0)
    assert "Firm placements collide" in r.detail


def test_a_run_with_no_record_is_a_failed_result(tmp_path, monkeypatch):
    folder = _folder(tmp_path, 'board.place(Part("J1"), at=Location(1, 2), why="mechanical: connector")\n')
    monkeypatch.setattr(place_ref, "placemat_run", lambda *a, **k: (None, 1.0))
    r = place_ref.run_b(BOARD, folder, tmp_path / "work", prepared=PREPARED, versions=VERSIONS, a_closure_clean=None)
    assert (r.failure, r.a_closure_clean) == ("no run record", None)


def test_a_routed_run_is_read_from_its_record_and_routed_board(tmp_path, monkeypatch):
    folder = _folder(tmp_path, 'board.place(Part("J1"), at=Location(1, 2), why="mechanical: connector")\n')
    from placemat.kicad.route import RouteReport
    drc = {"violations": [{"type": "shorting_items", "severity": "error",
                           "items": [{"description": "Track [A] on F.Cu", "pos": {"x": 1, "y": 2}}]}]}
    # the route dict as RouteReport writes it: drc_after is the parsed DRC report, not a path
    route = RouteReport(valid=True, closure=0.9, closure_clean=0.9, open_before=5, open_after=2, open_nets={}, shorted=[],
                        excluded=[], layers=[], seconds=1.0, router_version="r", drc_after=drc,
                        routed_pcb=tmp_path / "r.kicad_pcb", log=tmp_path / "log", work=tmp_path).as_dict()
    record = {"status": "ok", "failure": None, "metrics": {"closure_clean": 0.9, "measures": {}, "route": route}}
    monkeypatch.setattr(place_ref, "placemat_run", lambda *a, **k: (record, 7.0))
    monkeypatch.setattr(place_ref.prepare, "measure", lambda pcb: (2, prepare.HumanCopper(9, 33.0)))
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder: 12.5)
    monkeypatch.setattr(place_ref, "krt_version", lambda folder: "k")
    r = place_ref.run_b(BOARD, folder, tmp_path / "work", prepared=PREPARED, versions=VERSIONS, a_closure_clean=1.0)
    assert (r.failure, r.closure_clean, r.open, r.vias, r.track_mm, r.run_score) == ("", 0.9, 2, 9, 33.0, 12.5)
    assert [v.type for v in r.new_violations] == ["shorting_items"]
    assert (r.versions["krt"], r.seconds) == ("k", 7.0)


def test_a_board_is_clean_closure_lower_or_a_lint_failure_is_worse():
    old = route_ref.asdict(_b())
    assert place_ref.compare_b(old, _b(), {"placemat"}).status == "same"
    assert place_ref.compare_b(old, _b(closure_clean=0.9), {"placemat"}).status == "worse"
    assert place_ref.compare_b(old, _b(closure_clean=0.0, failure="lint"), {"placemat"}).status == "worse"
    assert place_ref.compare_b(place_ref.asdict(_b(closure_clean=0.0, failure="placement")), _b(closure_clean=0.5), {"placemat"}).status == "better"
    assert place_ref.compare_b(None, _b(), {"placemat"}).status == "new"


def test_a_module_with_a_larger_area_at_equal_closure_is_worse():
    old = place_ref.asdict(_m())
    assert place_ref.compare_module(old, _m(area_mm2=101.0), {"placemat"}).status == "worse"
    assert place_ref.compare_module(old, _m(area_mm2=99.0), {"placemat"}).status == "better"
    assert place_ref.compare_module(old, _m(), {"placemat"}).status == "same"


def test_a_module_with_lower_closure_is_worse_whatever_its_area():
    old = place_ref.asdict(_m())
    assert place_ref.compare_module(old, _m(closure_clean=0.9, area_mm2=10.0), {"placemat"}).status == "worse"
    assert place_ref.compare_module(old, _m(closure_clean=1.0, area_mm2=500.0, failure="x"), {"placemat"}).status == "worse"
    assert place_ref.compare_module(place_ref.asdict(_m(closure_clean=0.8)), _m(area_mm2=900.0), {"placemat"}).status == "better"


def test_other_versions_make_results_not_comparable():
    c = place_ref.compare_module(place_ref.asdict(_m()), _m(versions=dict(VERSIONS, krt="1")), {"placemat"})
    assert (c.status, c.differ) == ("not comparable", ["krt"])


def test_update_rewrites_only_the_entries_it_ran(tmp_path):
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"a": {"x": {"class": {"k": 1}}}, "b": {"y": {"k": 2}}, "modules": {"fam/Old": {"k": 3}}}))
    place_ref.save_results(path, [_b(board="x")], [_m(script="fam/X")])
    data = json.loads(path.read_text())
    assert data["a"] == {"x": {"class": {"k": 1}}}
    assert data["b"]["y"] == {"k": 2} and data["b"]["x"]["board"] == "x"
    assert data["modules"]["fam/Old"] == {"k": 3} and data["modules"]["fam/X"]["area_mm2"] == 100.0


def test_modules_are_the_layout_scripts_of_the_fixture_families(tmp_path):
    for rel in ("fam/modules/A/A_layout.py", "fam/modules/B/B_layout.py", "fam/modules/B/BSide_layout.py",
                "fam2/modules/C/C.zen", "fam2/modules/D/D_layout.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    found = place_ref.module_scripts(tmp_path)
    assert sorted(found) == ["fam/A", "fam/B", "fam/BSide", "fam2/D"]
    assert found["fam/BSide"] == tmp_path / "fam/modules/B/BSide_layout.py"


def test_a_module_run_reads_closure_area_and_score(tmp_path, monkeypatch):
    folder = tmp_path / "fam" / "modules" / "A"
    folder.mkdir(parents=True)
    (folder / "A_layout.py").write_text("")
    record = {"status": "ok", "failure": None, "metrics": {"closure_clean": 0.75, "extent": [10.0, 4.5], "measures": {}}}
    monkeypatch.setattr(place_ref, "placemat_run", lambda *a, **k: (record, 2.0))
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder: 3.0)
    monkeypatch.setattr(place_ref, "krt_version", lambda folder: "k")
    r = place_ref.run_module("fam/A", folder / "A_layout.py", tmp_path / "work", versions=VERSIONS)
    assert (r.script, r.closure_clean, r.area_mm2, r.run_score, r.seconds, r.failure) == ("fam/A", 0.75, 45.0, 3.0, 2.0, "")


def test_a_lint_refusal_costs_no_prepare(tmp_path, monkeypatch):
    folder = _folder(tmp_path, 'board.place(Part("U1"), at=Location(1, 2))\n')
    monkeypatch.setattr(place_ref.prepare, "prepare", lambda *a, **k: raise_("prepare must not run"))
    monkeypatch.setattr(place_ref.fetch, "fetch", lambda *a, **k: raise_("fetch must not run"))
    assert place_ref.run_b(BOARD, folder, tmp_path / "work", versions=VERSIONS).failure == "lint"


def test_a_changed_capture_is_a_difference_not_a_regression():
    old = place_ref.asdict(_m())
    c = place_ref.compare_module(old, _m(inputs_digest="d2", closure_clean=0.5), {"placemat"})
    assert (c.status, c.differ) == ("not comparable", ["inputs"])
    c = place_ref.compare_b(route_ref.asdict(_b()), _b(inputs_digest="d2"), {"placemat"})
    assert (c.status, c.differ) == ("not comparable", ["inputs"])


def test_the_generation_digest_follows_the_capture(tmp_path, monkeypatch):
    monkeypatch.undo()   # the autouse stand-in
    folder = tmp_path / "M"
    folder.mkdir()
    (folder / "M.zen").write_text('Board(name="M")\n')
    (folder / "M_layout.py").write_text("")
    first = place_ref.generation_inputs(folder / "M_layout.py")
    assert first == place_ref.generation_inputs(folder / "M_layout.py")
    (folder / "M.zen").write_text('Board(name="M")\n# changed\n')
    assert place_ref.generation_inputs(folder / "M_layout.py") != first
    (folder / "layout").mkdir()
    (folder / "layout" / "layout.kicad_pcb").write_text("(segment)")   # the checked-in board is not an input
    assert place_ref.generation_inputs(folder / "M_layout.py") != first


def _family(tmp_path):
    root = tmp_path / "fam"
    for rel, text in (("pcb.toml", "[workspace]"), ("parts/p.zen", "p"), ("modules/B/B.zen", "b"),
                      ("modules/A/A_layout.py", ""), ("modules/A/A.zen", "a"),
                      ("modules/A/layout/layout.kicad_pcb", "(segment) (via)"),       # an old run's copper
                      ("modules/A/layout_side/layout.kicad_pcb", "(segment)"),
                      ("modules/A/.placemat/runs/x/run.json", "{}")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


def test_a_module_runs_on_a_fresh_generation_inside_a_copy_of_its_workspace(tmp_path, monkeypatch):
    root = _family(tmp_path)
    seen = {}

    def run(script, extra=()):
        c = script.parents[2]
        seen.update(script=script, parts=(c / "parts/p.zen").exists(), sibling=(c / "modules/B/B.zen").exists(),
                    pcb_toml=(c / "pcb.toml").exists(), cached=(script.parent / ".placemat/generated").exists(),
                    state=(script.parent / ".placemat/runs").exists(), side=(script.parent / "layout_side").exists())
        return {**PLACED, "metrics": dict(PLACED["metrics"], closure_clean=1.0)}, 1.0
    monkeypatch.setattr(place_ref, "placemat_run", run)
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder: 3.0)
    monkeypatch.setattr(place_ref, "krt_version", lambda folder: "k")
    r = place_ref.run_module("fam/A", root / "modules/A/A_layout.py", tmp_path / "work", versions=VERSIONS)
    assert r.failure == ""
    assert seen["script"] == tmp_path / "work/workspace/modules/A/A_layout.py"
    assert seen["parts"] and seen["sibling"] and seen["pcb_toml"] and seen["side"]
    assert not seen["cached"] and not seen["state"]       # nothing staged: placemat generates
    assert not (root / "modules/A/.placemat/generated").exists()
    assert (root / "modules/A/layout/layout.kicad_pcb").read_text() == "(segment) (via)"


PLACED = {"status": "ok", "failure": None, "metrics": {"placed": 5, "findings": 1, "crossings": 2, "airwire_mm": 40.5,
                                                         "extent": [10.0, 4.0], "measures": {"m": 1}}}


def test_placement_measures_are_kept_when_the_route_is_refused(tmp_path, monkeypatch):
    folder = _folder(tmp_path, 'board.place(Part("J1"), at=Location(1, 2), why="mechanical: connector")\n')
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder: 8.0)
    monkeypatch.setattr(place_ref, "krt_version", lambda folder: "k")
    failed = {**PLACED, "status": "failed", "failure": {"kind": "route", "message": "no router"}}
    monkeypatch.setattr(place_ref, "placemat_run", lambda *a, **k: (failed, 3.0))
    r = place_ref.run_b(BOARD, folder, tmp_path / "work", prepared=PREPARED, versions=VERSIONS)
    assert r.failure == "route"
    assert r.placement == {"crossings": 2, "airwire_mm": 40.5, "area_mm2": 40.0, "placed": 5, "findings": 1, "run_score": 8.0}
    monkeypatch.setattr(place_ref, "placemat_run", lambda *a, **k: (dict(PLACED, metrics=dict(PLACED["metrics"])), 3.0))
    r = place_ref.run_b(BOARD, folder, tmp_path / "work", prepared=PREPARED, versions=VERSIONS)
    assert (r.failure, r.placement["crossings"]) == ("no route", 2)


def test_a_module_records_its_placement_measures(tmp_path, monkeypatch):
    folder = tmp_path / "fam" / "modules" / "A"
    folder.mkdir(parents=True)
    (folder / "A_layout.py").write_text("")
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder: 3.0)
    monkeypatch.setattr(place_ref, "krt_version", lambda folder: "k")
    monkeypatch.setattr(place_ref, "placemat_run", lambda *a, **k: (PLACED, 2.0))
    r = place_ref.run_module("fam/A", folder / "A_layout.py", tmp_path / "work", versions=VERSIONS)
    assert (r.placement["airwire_mm"], r.placement["placed"], r.inputs_digest) == (40.5, 5, "d1")


def _main(tmp_path, monkeypatch, status, *extra):
    import contextlib
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"b": {"x": {"old": 1}}}))
    monkeypatch.setattr(place_ref.fetch, "load_manifest", lambda: [BOARD])
    monkeypatch.setattr(place_ref.lock, "realboard", contextlib.nullcontext)
    monkeypatch.setattr(place_ref.route_ref, "current_versions", lambda: {})
    monkeypatch.setattr(place_ref, "_run_boards",
                        lambda boards, root, rec, v, ch, results, comparisons, save:
                        results.append(_b()) or comparisons.append(status) or save() or False)
    rc = place_ref.main(["x", "--update", "--results", str(path), *extra])
    return rc, json.loads(path.read_text())


WORSE = route_ref.Comparison("worse", [])


def test_update_holds_back_a_worse_entry_unless_accepted(tmp_path, monkeypatch, capsys):
    rc, data = _main(tmp_path, monkeypatch, WORSE)
    assert rc == 1 and data["b"]["x"] == {"old": 1}
    assert "held back" in capsys.readouterr().out
    rc, data = _main(tmp_path, monkeypatch, WORSE, "--accept-worse")
    assert data["b"]["x"]["board"] == "x" and rc == 0


def test_update_writes_not_comparable_and_better_entries(tmp_path, monkeypatch):
    for status in (route_ref.Comparison("not comparable", ["krt"], "same"), route_ref.Comparison("better", []),
                   route_ref.Comparison("new", [])):
        rc, data = _main(tmp_path, monkeypatch, status)
        assert (rc, data["b"]["x"]["board"]) == (0, "x")


def test_a_dirty_checkout_ignores_the_runners_own_results_file(tmp_path):
    import subprocess
    run = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    run("init", "-q")
    (tmp_path / "fixtures" / "reference").mkdir(parents=True)
    results, other = tmp_path / "fixtures/reference/results.json", tmp_path / "other.txt"
    results.write_text("{}")
    other.write_text("1")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    clean = route_ref._git_head(str(tmp_path))
    assert not clean.endswith("-dirty")
    results.write_text('{"a": 1}')
    assert route_ref._git_head(str(tmp_path)) == clean
    other.write_text("2")
    assert route_ref._git_head(str(tmp_path)) == clean + "-dirty"


def test_a_lower_module_of_another_version_is_held_back():
    old = place_ref.asdict(_m())
    lower = _m(area_mm2=150.0, versions=dict(VERSIONS, krt="1"))
    c = place_ref.compare_module(old, lower, {"placemat"})
    assert (c.status, c.value) == ("not comparable", "worse")
    assert route_ref.ratchet([lower], [c], False) == ([], [lower])
    assert place_ref.compare_module(old, lower, {"placemat", "krt"}).status == "worse"


def _prepared_or_raise(board, src, work):
    if board.name == "bad":
        raise RuntimeError("DRC failed")
    return PREPARED


def test_a_board_whose_preparation_raises_is_a_failed_result_and_the_others_run(tmp_path, monkeypatch):
    monkeypatch.setattr(place_ref.fetch, "fetch", lambda board: tmp_path)
    monkeypatch.setattr(place_ref.prepare, "prepare", _prepared_or_raise)
    monkeypatch.setattr(place_ref, "run_b", lambda board, *a, **k: _b(board=board.name))
    monkeypatch.setattr(place_ref, "krt_version", lambda folder: "0")
    monkeypatch.setattr(place_ref.lint, "find_script", lambda name, root: tmp_path / "X_layout.py")
    results, comparisons, saves = [], [], []
    recorded = {"b": {"bad": place_ref.asdict(_b(board="bad"))}}
    worse = place_ref._run_boards([dataclasses_replace(BOARD, name="bad"), BOARD], tmp_path, recorded, VERSIONS,
                                  {"placemat"}, results, comparisons, lambda: saves.append(len(results)))
    assert worse and saves == [1, 2]
    assert (results[0].failure, results[0].detail, results[0].inputs_digest) == ("RuntimeError", "DRC failed", "d1")
    assert comparisons[0].status == "worse" and results[1].failure == ""


def test_a_module_that_raises_is_a_failed_result_and_the_others_run(tmp_path, monkeypatch):
    def run(name, script, work, versions=None):
        if name == "fam/Bad":
            raise OSError("copy failed")
        return _m(script=name)
    monkeypatch.setattr(place_ref, "run_module", run)
    monkeypatch.setattr(place_ref, "krt_version", lambda folder: "0")
    results, comparisons = [], []
    worse = place_ref._run_modules({"fam/Bad": tmp_path / "Bad_layout.py", "fam/X": tmp_path / "X_layout.py"}, tmp_path,
                                   {}, VERSIONS, {"placemat"}, results, comparisons, lambda: None)
    assert not worse and [c.status for c in comparisons] == ["new", "new"]
    assert (results[0].failure, results[0].detail, results[1].failure) == ("OSError", "copy failed", "")


def dataclasses_replace(obj, **over):
    import dataclasses
    return dataclasses.replace(obj, **over)
