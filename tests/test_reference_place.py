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
    fields.update(over)
    _evidence(fields)
    return place_ref.MResult(**fields)


def _b(**over):
    fields = dict(board="x", closure_clean=1.0, open=0, new_violations=[], vias=3, track_mm=10.0, run_score=5.0, ref_vias=4,
                  ref_track_mm=20.0, a_closure_clean=1.0, seconds=1.0, versions=VERSIONS, failure="", inputs_digest="d1")
    fields.update(over)
    _evidence(fields)
    fields.setdefault('reference_drc', {'baseline': 'human', 'new_violations': len(fields['new_violations'])})
    return place_ref.BResult(**fields)


def _evidence(fields):
    from placemat.settings import Settings
    measures = fields.setdefault('measures', {'v': 2, 'area_mm2': fields.get('area_mm2', 0.0)})
    fields.setdefault('score_settings', place_ref._score_settings(Settings()))
    fields.setdefault('route_report', {
        'closure_clean': fields['closure_clean'], 'drc_new': measures.get('drc', 0),
        'widths_failed': 0, 'critical_checks': 0, 'critical_unknown': [], 'final_findings': {},
        'required_width_unknown': [],
        'vias': measures.get('vias', 3), 'track_mm': measures.get('copper_mm', 10.0),
        'segments': measures.get('segments', 20),
        'phases': [{'name': 'REST', 'comparison_contract': 'same-original-asks',
                    'final_closure_clean': fields['closure_clean']}],
    })


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
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder, **kwargs: 12.5)
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
    assert place_ref.compare_b(place_ref.asdict(_b(closure_clean=0.0, failure="placement")), _b(closure_clean=0.5), {"placemat"}).status == "not comparable"
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


def test_results_with_measures_are_ranked_by_score_rank():
    """With the run's measures recorded, a board or module is judged by `score.rank`: a new violation outranks closure
    (D11), a fitted module's area is traded in the run score (D16), and a complete board's routed quality decides
    before the score (D17)."""
    m = {"v": 2, "airwire_mm": 100.0, "crossings": {}, "area_mm2": 100.0, "vias": 5, "copper_mm": 50.0, "segments": 20}
    old = place_ref.asdict(_b(measures=m))
    assert place_ref.compare_b(old, _b(measures=m, closure_clean=0.9), {"placemat"}).status == "worse"
    assert place_ref.compare_b(old, _b(measures=dict(m, vias=4)), {"placemat"}).status == "better"
    assert place_ref.compare_b(place_ref.asdict(_b(measures=m, closure_clean=0.9)),
                               _b(measures=dict(m, vias=1), new_violations=[prepare.Violation("clearance", ("A", "B"), (1.0, 2.0))]), {"placemat"}).status == "worse"
    small = place_ref.asdict(_m(measures=m))
    larger = dict(m, area_mm2=101.0, airwire_mm=99.5)   # 1 mm2 more area at score.area 0.25 against 0.5 mm less wire
    assert place_ref.compare_module(small, _m(area_mm2=101.0, measures=larger), {"placemat"}).status == "same"
    assert place_ref.compare_module(small, _m(area_mm2=140.0, measures=dict(m, area_mm2=140.0)), {"placemat"}).status == "worse"


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
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder, **kwargs: 3.0)
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
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder, **kwargs: 3.0)
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
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder, **kwargs: 8.0)
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
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder, **kwargs: 3.0)
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
                        lambda boards, root, rec, v, ch, results, comparisons, save, **kwargs:
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
    def run(name, script, work, versions=None, overrides=None):
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


def test_module_drc_errors_outrank_better_closure_and_score():
    m = {'v': 2, 'drc': 0, 'airwire_mm': 100.0}
    old = place_ref.asdict(_m(measures=m, closure_clean=0.9))
    dirty = _m(measures=dict(m, drc=1, airwire_mm=1.0), closure_clean=1.0)
    assert place_ref.compare_module(old, dirty, {'placemat'}).status == 'worse'


def test_place_only_records_measures_and_overrides_only_copied_workspace(tmp_path, monkeypatch):
    script = tmp_path / "fixtures" / "family" / "modules" / "cell" / "Cell_layout.py"
    script.parent.mkdir(parents=True)
    script.write_text("")
    original = script.parent / "placemat.toml"
    original.write_text("[score]\narea = 0.25\n")
    record = {"status": "ok", "metrics": {"placed": 2, "crossings": 0, "airwire_mm": 5.0,
              "extent": [10.0, 5.0],
              "measures": {"v": 2, "airwire_mm": 5.0, "area_mm2": 50.0}}}
    def run(copied, **kwargs):
        from placemat.settings import load
        assert kwargs == {"route": False}
        assert load(copied.parent, script=copied).score_area == 1.0
        assert copied != script
        return record, 1.0
    monkeypatch.setattr(place_ref, "placemat_run", run)
    from contextlib import nullcontext
    monkeypatch.setattr(place_ref.lock, "realboard", nullcontext)
    monkeypatch.setattr(place_ref, "module_scripts", lambda: {"family/Cell": script})
    monkeypatch.setattr(route_ref, "current_versions", lambda: VERSIONS)
    path = tmp_path / "results.json"
    assert place_ref.main(["--place-only", "--modules", "Cell", "--set", "score_area=1.0",
                           "--results", str(path), "--update"]) == 0
    row = json.loads(path.read_text())["placement"]["family/Cell"]
    assert {"run_score", "crossings", "airwire_mm", "area_mm2", "placed", "versions"} <= row.keys()
    assert row["run_score"] == 55.0
    assert original.read_text() == "[score]\narea = 0.25\n"


def test_placement_comparison_reweights_measures_and_keeps_validity_first():
    row = {'versions': VERSIONS, 'inputs_digest': 'd', 'failure': '',
           'measures': {'v': 2, 'airwire_mm': 100.0, 'area_mm2': 100.0, 'drc': 0}}
    new = dict(row, score_settings={'score_area': 1.0},
               measures=dict(row['measures'], airwire_mm=90.0, area_mm2=120.0))
    assert place_ref.compare_placement(row, new, {'placemat'}) == 'worse'
    new['score_settings']['score_area'] = 0.1
    assert place_ref.compare_placement(row, new, {'placemat'}) == 'better'
    new['measures']['drc'] = 1
    assert place_ref.compare_placement(row, new, {'placemat'}) == 'worse'


def test_place_only_refuses_invalid_override_before_lock_or_run(tmp_path, monkeypatch):
    monkeypatch.setattr(route_ref, "current_versions", lambda: VERSIONS)
    monkeypatch.setattr(place_ref.lock, "realboard", lambda: raise_("must validate before taking lock"))
    with pytest.raises(SystemExit) as stopped:
        place_ref.main(["--place-only", "--modules", "--set", "score_area=-1",
                        "--results", str(tmp_path / "results.json")])
    assert stopped.value.code == 2


@pytest.mark.parametrize('module', [False, True])
def test_routed_cli_applies_settings_only_to_copy_and_scores_with_them(tmp_path, monkeypatch, module):
    from contextlib import nullcontext
    from placemat.settings import load
    if module:
        script = tmp_path / 'fixtures' / 'family' / 'modules' / 'cell' / 'Cell_layout.py'
        script.parent.mkdir(parents=True)
        script.write_text('')
        monkeypatch.setattr(place_ref, 'module_scripts', lambda: {'family/Cell': script})
        selection = ['--modules', 'Cell']
        result_kind, result_name = 'modules', 'family/Cell'
    else:
        folder = _folder(tmp_path, 'board.place(Part("J1"), at=Location(1, 2), why="mechanical: connector")\n')
        script = folder / 'X_layout.py'
        monkeypatch.setattr(place_ref.lint, 'BOARDS_DIR', folder.parent)
        monkeypatch.setattr(place_ref.fetch, 'load_manifest', lambda: [BOARD])
        monkeypatch.setattr(place_ref.fetch, 'fetch', lambda board: tmp_path / 'human.kicad_pcb')
        monkeypatch.setattr(place_ref.prepare, 'prepare', lambda *args: PREPARED)
        monkeypatch.setattr(place_ref.prepare, 'measure', lambda pcb: (0, prepare.HumanCopper(0, 0.0)))
        selection = ['x']
        result_kind, result_name = 'b', 'x'
    original = script.parent / 'placemat.toml'
    original.write_text('[score]\narea = 0.25\n[place]\nsearch_wire = "clique"\n')
    source_bytes = {path: path.read_bytes() for path in (script, original)}
    seen = []

    def run(copied, *args, **kwargs):
        cfg = load(copied.parent, script=copied)
        assert copied != script and copied.read_bytes() == source_bytes[script]
        assert cfg.place_search_wire == 'mst' and cfg.score_area == 1.0
        assert kwargs.get('route', True) is True
        seen.append(copied)
        return {'status': 'ok', 'metrics': {'closure_clean': 0.75, 'placed': 2,
            'extent': [10.0, 5.0], 'measures': {'v': 2, 'airwire_mm': 5.0, 'area_mm2': 50.0},
            'route': {'routed_pcb': str(tmp_path / 'routed.kicad_pcb'),
                      'closure_clean': 0.75, 'open_after': 1, 'drc_after': {'violations': []}}}}, 1.0

    monkeypatch.setattr(place_ref, 'placemat_run', run)
    monkeypatch.setattr(place_ref.lock, 'realboard', nullcontext)
    monkeypatch.setattr(route_ref, 'current_versions', lambda: VERSIONS)
    monkeypatch.setattr(place_ref, 'krt_version', lambda folder: '0')
    results = tmp_path / 'results.json'
    assert place_ref.main([*selection, '--set', 'place.search_wire=mst', '--set', 'score.area=1.0',
                           '--results', str(results), '--work', str(tmp_path / 'work'), '--update']) == 0
    assert len(seen) == 1
    row = json.loads(results.read_text())[result_kind][result_name]
    assert row['run_score'] == 55.0 and row['placement']['run_score'] == 55.0
    assert all(path.read_bytes() == data for path, data in source_bytes.items())


@pytest.mark.parametrize('missing', ['route_report', 'score_settings'])
def test_legacy_routed_rows_cannot_certify_comparison(missing):
    old = place_ref.asdict(_m())
    old.pop(missing)
    comparison = place_ref.compare_module(old, _m(area_mm2=1.0), {'placemat'})
    assert comparison.status == 'not comparable'
    assert comparison.differ == ['routed evidence/settings']


@pytest.mark.parametrize('field', ['critical_checks', 'critical_unknown', 'widths_failed', 'phases'])
def test_missing_final_evidence_cannot_use_placement_counts(field):
    old = place_ref.asdict(_m())
    old['route_report'].pop(field)
    assert place_ref.compare_module(old, _m(), {'placemat'}).status == 'not comparable'


def test_changed_original_phase_contract_refuses_even_with_better_scalar_score():
    old = place_ref.asdict(_m())
    new = _m(measures={'v': 2, 'airwire_mm': 0.0})
    new.route_report['phases'][0]['comparison_contract'] = 'different-original-asks'
    assert place_ref.compare_module(old, new, {'placemat'}).status == 'not comparable'


def test_effective_prices_are_bound_and_used_for_partial_routes():
    from placemat.settings import Settings
    prices = dict(place_ref._score_settings(Settings()), score_area=1.0)
    old = _m(closure_clean=0.9, measures={'v': 2, 'airwire_mm': 10.0, 'area_mm2': 10.0}, score_settings=prices)
    new = _m(closure_clean=0.9, measures={'v': 2, 'airwire_mm': 5.0, 'area_mm2': 20.0}, score_settings=prices)
    assert place_ref.compare_module(place_ref.asdict(old), new, {'placemat'}).status == 'worse'
    different = dict(prices, score_area=0.1)
    assert place_ref.compare_module(place_ref.asdict(old), _m(score_settings=different), {'placemat'}).status == 'not comparable'


def test_human_drc_view_does_not_rewrite_runtime_report():
    old = _b()
    violation = prepare.Violation('clearance', ('A', 'B'), (1.0, 2.0))
    new = _b(new_violations=[violation])
    before = json.dumps(new.route_report, sort_keys=True)
    assert place_ref.compare_b(place_ref.asdict(old), new, {'placemat'}).status == 'worse'
    assert json.dumps(new.route_report, sort_keys=True) == before
    assert new.route_report['drc_new'] == 0


def test_missing_width_proof_is_not_known_empty():
    old = place_ref.asdict(_m())
    old['route_report'].pop('required_width_unknown')
    assert place_ref.compare_module(old, _m(), {'placemat'}).status == 'not comparable'


@pytest.mark.parametrize('unknown', ['width_policy_unknown', 'width_unknown'])
def test_raw_phase_open_unknown_width_cannot_certify(unknown):
    row = _m(closure_clean=0.0)
    row.route_report.pop('required_width_unknown')
    phase = row.route_report['phases'][0]
    phase.update(final_asked=1, final_joined=0, final_open=[{'net': 'A', unknown: True}],
                 width_policy=[{'name': 'REST', 'by_net': {'A': {'status': 'known', 'widths': {'F.Cu': 0.3}}}}])
    assert place_ref.compare_module(place_ref.asdict(row), row, {'placemat'}).status == 'not comparable'


def test_complete_raw_phase_width_proof_is_measured_without_augmented_list():
    row = _m(closure_clean=0.0)
    row.route_report.pop('required_width_unknown')
    phase = row.route_report['phases'][0]
    phase.update(final_asked=1, final_joined=0, final_open=[{'net': 'A'}],
                 width_policy=[{'name': 'REST', 'by_net': {'A': {'status': 'known', 'widths': {'F.Cu': 0.3}}}}])
    assert place_ref.compare_module(place_ref.asdict(row), row, {'placemat'}).status == 'same'
    phase['width_policy'][0]['by_net']['A']['status'] = 'unknown'
    assert place_ref.compare_module(place_ref.asdict(row), row, {'placemat'}).status == 'not comparable'


@pytest.mark.parametrize('value', [True, '1.0', float('nan'), float('inf'), -1.0, 10 ** 1000])
def test_same_malformed_historical_prices_are_incomparable(value):
    row = _m()
    row.score_settings['score_area'] = value
    assert place_ref.compare_module(place_ref.asdict(row), row, {'placemat'}).status == 'not comparable'
