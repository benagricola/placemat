import json
import shutil

from fixtures.reference import fetch, place_ref, prepare, route_ref

VERSIONS = {"placemat": "0", "krt": "0", "pcb": "0"}
BOARD = fetch.Board(name="x", repo="github:o/r", commit="c", files={}, board="x.kicad_pcb", licence="MIT", tests=("a", "b"),
                    islands=(), fixed=("J1",), human_track_mm=None, kicad5=False)
PREPARED = prepare.Prepared(None, None, [], 2, prepare.HumanCopper(4, 20.0))


def _m(**over):
    fields = dict(script="mnb/X", closure_clean=1.0, area_mm2=100.0, run_score=5.0, seconds=1.0, versions=VERSIONS, failure="")
    return place_ref.MResult(**dict(fields, **over))


def _b(**over):
    fields = dict(board="x", closure_clean=1.0, open=0, new_violations=[], vias=3, track_mm=10.0, run_score=5.0, ref_vias=4,
                  ref_track_mm=20.0, a_closure_clean=1.0, seconds=1.0, versions=VERSIONS, failure="")
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
    drc = tmp_path / "drc.json"
    drc.write_text(json.dumps({"violations": [{"type": "shorting_items", "severity": "error",
                                               "items": [{"description": "Track [A] on F.Cu", "pos": {"x": 1, "y": 2}}]}]}))
    record = {"status": "ok", "failure": None, "metrics": {"closure_clean": 0.9, "measures": {}, "route": {
        "closure_clean": 0.9, "open_after": 2, "routed_pcb": str(tmp_path / "r.kicad_pcb"), "drc_after": str(drc)}}}
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
    assert place_ref.compare_b(old, _b(), "placemat").status == "same"
    assert place_ref.compare_b(old, _b(closure_clean=0.9), "placemat").status == "worse"
    assert place_ref.compare_b(old, _b(closure_clean=0.0, failure="lint"), "placemat").status == "worse"
    assert place_ref.compare_b(place_ref.asdict(_b(closure_clean=0.0, failure="placement")), _b(closure_clean=0.5), "placemat").status == "better"
    assert place_ref.compare_b(None, _b(), "placemat").status == "new"


def test_a_module_with_a_larger_area_at_equal_closure_is_worse():
    old = place_ref.asdict(_m())
    assert place_ref.compare_module(old, _m(area_mm2=101.0), "placemat").status == "worse"
    assert place_ref.compare_module(old, _m(area_mm2=99.0), "placemat").status == "better"
    assert place_ref.compare_module(old, _m(), "placemat").status == "same"


def test_a_module_with_lower_closure_is_worse_whatever_its_area():
    old = place_ref.asdict(_m())
    assert place_ref.compare_module(old, _m(closure_clean=0.9, area_mm2=10.0), "placemat").status == "worse"
    assert place_ref.compare_module(old, _m(closure_clean=1.0, area_mm2=500.0, failure="x"), "placemat").status == "worse"
    assert place_ref.compare_module(place_ref.asdict(_m(closure_clean=0.8)), _m(area_mm2=900.0), "placemat").status == "better"


def test_other_versions_make_results_not_comparable():
    c = place_ref.compare_module(place_ref.asdict(_m()), _m(versions=dict(VERSIONS, krt="1")), "placemat")
    assert (c.status, c.differ) == ("not comparable", ["krt"])


def test_update_rewrites_only_the_entries_it_ran(tmp_path):
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"a": {"x": {"class": {"k": 1}}}, "b": {"y": {"k": 2}}, "modules": {"mnb/Old": {"k": 3}}}))
    place_ref.save_results(path, [_b(board="x")], [_m(script="mnb/X")])
    data = json.loads(path.read_text())
    assert data["a"] == {"x": {"class": {"k": 1}}}
    assert data["b"]["y"] == {"k": 2} and data["b"]["x"]["board"] == "x"
    assert data["modules"]["mnb/Old"] == {"k": 3} and data["modules"]["mnb/X"]["area_mm2"] == 100.0


def test_modules_are_the_layout_scripts_of_the_fixture_families(tmp_path):
    for rel in ("mnb/modules/A/A_layout.py", "mnb/modules/B/B_layout.py", "mnb/modules/B/BSide_layout.py",
                "fairing/modules/C/C.zen", "fairing/modules/D/D_layout.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    found = place_ref.module_scripts(tmp_path)
    assert sorted(found) == ["fairing/D", "mnb/A", "mnb/B", "mnb/BSide"]
    assert found["mnb/BSide"] == tmp_path / "mnb/modules/B/BSide_layout.py"


def test_a_module_run_reads_closure_area_and_score(tmp_path, monkeypatch):
    folder = tmp_path / "mnb" / "modules" / "A"
    folder.mkdir(parents=True)
    (folder / "A_layout.py").write_text("")
    record = {"status": "ok", "failure": None, "metrics": {"closure_clean": 0.75, "extent": [10.0, 4.5], "measures": {}}}
    monkeypatch.setattr(place_ref, "placemat_run", lambda *a, **k: (record, 2.0))
    monkeypatch.setattr(place_ref, "run_score", lambda record, folder: 3.0)
    monkeypatch.setattr(place_ref, "_stage_generation", lambda script: None)
    monkeypatch.setattr(place_ref, "krt_version", lambda folder: "k")
    r = place_ref.run_module("mnb/A", folder / "A_layout.py", tmp_path / "work", versions=VERSIONS)
    assert (r.script, r.closure_clean, r.area_mm2, r.run_score, r.seconds, r.failure) == ("mnb/A", 0.75, 45.0, 3.0, 2.0, "")
