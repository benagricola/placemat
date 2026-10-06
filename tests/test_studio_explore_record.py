"""A finished explore opened in the studio: its record and the board of its best variant, from the run it was part of
(the board that run wrote, or its build when it routed) or from the best variant's own plan the explore kept."""
import json
import shutil
import time

import pytest

from placemat import explore_view
from placemat.studio import Studio
from tests import real_modules
from tests.test_studio_picker import _board_dirs, _run_folder


@pytest.fixture
def own_project(tmp_path):
    return real_modules.stage(tmp_path, "usbconverter")


def _studio(own_project):
    s = Studio(None, port=0, open_browser=False, root=own_project.parents[2])
    s.worker.send = lambda cmd: pytest.fail("a past explore is opened, not resolved")
    jobs = []
    s.m3d.submit = lambda js: jobs.append(list(js)) or len(js)
    board_dir = next(d for d in _board_dirs(s) if (d / ".placemat" / "generated").is_dir())
    script = next(e["path"] for e in s.scripts() if e["src"].board_dir == board_dir)
    return s, jobs, board_dir, script


def _record(board_dir, script, focus, plain, variants, best_seed, kept=False, name="20261004-082238-77.json", **extra):
    d = board_dir / ".placemat" / "views" / "explore"
    d.mkdir(parents=True, exist_ok=True)
    best = next(v["score"] for v in variants if v["seed"] == best_seed)
    doc = {"version": 1, "script": str(script), "at": time.time() - 5, "pid": 77, "focus": focus, "seconds": 30.0, "jobs": 2, "baseline": variants[0]["score"],
           "plain": plain, "order": focus, "best_seed": best_seed, "best": best, "kept": kept, "variants": variants, "curve": [], "found": None,
           "ended": {"rule": "budget"}, **extra}
    (d / name).write_text(json.dumps(doc))
    return d / name


def _explore_run(board_dir, rid, script, record, kept):
    folder = _run_folder(board_dir, rid, script, pid=77)
    doc = json.loads((folder / "run.json").read_text())
    doc["metrics"]["explore"] = {"record": "/elsewhere/.placemat/views/explore/" + record.name, "best_seed": 3, "accepted": kept}   # a copied project: the name is what is matched
    (folder / "run.json").write_text(json.dumps(doc))
    return folder


def _a_part(cached):
    """A footprint of the board with a 3D model, as an explore focused on it alone would record it."""
    from placemat.kicad.read import read_board
    fp = next(f for f in read_board(str(cached)).footprints if getattr(f, "models", ()))
    return fp.inst, [round(fp.location.x, 3), round(fp.location.y, 3), round(fp.rotation, 3), fp.face.value]


def _variants(key, plain):
    moved = [plain[0] + 2.0, plain[1], (plain[2] + 90) % 360, plain[3]]
    return [{"seed": 0, "score": 10.0, "placements": {key: plain}}, {"seed": 3, "score": 8.0, "placements": {key: moved}},
            {"seed": 4, "score": 12.0, "placements": {key: plain}}], moved


def _item(doc, key):
    return next(it for it in doc["items"] if it["key"] == key)


def test_a_finished_explore_opens_on_its_best_variant_moved_on_the_board_its_run_wrote(own_project):
    pytest.importorskip("pcbnew")
    s, jobs, board_dir, script = _studio(own_project)
    cached = next((board_dir / ".placemat" / "generated").glob("*/layout.kicad_pcb"))
    key, plain = _a_part(cached)
    variants, best = _variants(key, plain)
    record = _record(board_dir, script, [key], {key: plain}, variants, 3)
    folder = _explore_run(board_dir, "eeee0007", script, record, kept=False)
    shutil.copy(cached, folder / "layout.kicad_pcb")
    shown = s.run_view("eeee0007")["doc"]                                                          # the run's own board: the plain placement

    view = s.explore_view(str(record))
    doc = view["doc"]
    assert (view["source"], view["run"], view["record"]["best_seed"], view["file"]) == ("moved", "eeee0007", 3, str(record.resolve()))
    assert view["drawn"] == {key: best} and view["unmoved"] == []
    it, was = _item(doc, key), _item(shown, key)
    assert (it["at"], it["rotation"], it["face"]) == (best[:2], best[2], best[3])
    want, _ = explore_view.move_items(shown, {key: (plain, best)}, shown["stackup"]["thickness"])
    assert it["members"][0]["shapes"] == _item(want, key)["members"][0]["shapes"] != was["members"][0]["shapes"]
    m, m0 = it["members"][0]["models"][0]["matrix"], was["members"][0]["models"][0]["matrix"]
    assert m != m0 and abs(m[13] - m0[13]) < 1e-6                                                   # moved on the board, at the same height
    assert doc["score"] == {"total": 8.0} and doc["findings"] == [] and len(doc["steps"]) == len(doc["items"])
    assert [i["key"] for i in doc["items"] if i["key"] != key] == [i["key"] for i in shown["items"] if i["key"] != key]   # the others as the run placed them
    assert jobs and doc["models"]

    assert s.run_summary(folder / "run.json")["explore"] == str(record.resolve())                   # a past run that explored names its record
    by_run = s.explore_view(run="eeee0007")
    assert by_run["file"] == view["file"] and by_run["source"] == "moved"
    assert s.explore_view(str(own_project.parents[3] / "x.json")) is None and s.explore_view(run="nope") is None


def test_an_explore_its_run_kept_opens_on_the_runs_own_board_or_its_build(own_project):
    pytest.importorskip("pcbnew")
    from placemat import route_progress
    s, jobs, board_dir, script = _studio(own_project)
    cached = next((board_dir / ".placemat" / "generated").glob("*/layout.kicad_pcb"))
    key, plain = _a_part(cached)
    variants, best = _variants(key, plain)
    record = _record(board_dir, script, [key], {key: plain}, variants, 3, kept=True, run="ffff0008")
    folder = _run_folder(board_dir, "ffff0008", script)
    shutil.copy(cached, folder / "layout.kicad_pcb")                                               # the lock took the best: the board the run wrote is it
    view = s.explore_view(str(record))
    assert (view["source"], view["run"], view["drawn"]) == ("run", "ffff0008", {key: best})
    it = _item(view["doc"], key)
    assert it["members"] == _item(s.run_view("ffff0008")["doc"], key)["members"]                    # not moved
    from placemat import route_view
    from placemat.kicad.read import read_board
    (folder / "plan.json").write_text(json.dumps(route_view.board_doc(read_board(str(cached)))))        # a routed run keeps its plan
    (folder / "route").mkdir()
    stages = [{"stage": "main", "resumed": False, "seconds": 1.0, "events": [{"ev": "net_begin", "net": "A"}, {"ev": "commit", "net": "A", "seg": [[0, 0, 1, 0, "F.Cu", 0.2]], "via": []}, {"ev": "net_end", "net": "A", "ok": True}]}]
    route_progress.write_record(folder / "route", {"pcb": str(cached), "run": "ffff0008", "script": str(script)}, stages, {"closure": 1.0}, complete=True)
    view = s.explore_view(str(record))
    assert view["source"] == "build" and view["doc"]["route"]["routed"] == 1 and _item(view["doc"], key)["members"]
    assert [o["origin"] for o in view["doc"]["copper"] if o.get("origin")] == ["routed"]


def test_an_explore_that_kept_its_best_plan_opens_on_it_and_one_with_neither_opens_on_its_record_alone(own_project):
    s, jobs, board_dir, script = _studio(own_project)
    variants = [{"seed": 0, "score": 10.0, "placements": {"a": [1, 1, 0, "front"]}}, {"seed": 3, "score": 8.0, "placements": {"a": [2, 1, 90, "front"]}}]
    record = _record(board_dir, script, ["a"], {"a": [1, 1, 0, "front"]}, variants, 3)
    view = s.explore_view(str(record))
    assert view["doc"] is None and view["source"] == "" and view["record"]["best"] == 8.0 and view["run"] == ""
    plan = {"board": {"loops": [], "drawn": False, "extent": [0, 0, 5, 5]}, "layers": ["F.Cu"], "items": [{"key": "a", "members": [{"ref": "U1", "inst": "a", "shapes": [], "models": []}],
            "at": [2, 1], "rotation": 90, "face": "front"}], "steps": [{"i": 0, "item": "a", "kind": "part", "placed": True, "notes": []}], "copper": [], "findings": [],
            "score": {"total": 8.0}, "models": {}, "stackup": {"thickness": 1.6}, "model_jobs": [{"id": "m1", "kind": "step", "path": "/x.step", "name": "x.step"}]}
    (record.parent / explore_view.BEST_DIR).mkdir()
    (record.parent / explore_view.BEST_DIR / record.name).write_text(json.dumps(plan))
    view = s.explore_view(str(record))
    assert view["source"] == "plan" and view["drawn"] == {"a": [2, 1, 90, "front"]} and view["doc"]["score"] == {"total": 8.0}
    assert _item(view["doc"], "a")["at"] == [2, 1] and "model_jobs" not in view["doc"] and jobs[-1] == plan["model_jobs"]       # its models go to the converter
    assert [e["file"] for e in s.explores()] == [str(record)]                                       # the best plan is not another record


def test_an_explore_whose_routes_took_another_variant_draws_that_variant(own_project):
    s, jobs, board_dir, script = _studio(own_project)
    variants = [{"seed": 0, "score": 10.0, "placements": {"a": [1, 1, 0, "front"]}}, {"seed": 3, "score": 8.0, "placements": {"a": [2, 1, 90, "front"]}},
                {"seed": 4, "score": 9.0, "placements": {"a": [5, 5, 0, "front"]}}]
    record = _record(board_dir, script, ["a"], {"a": [1, 1, 0, "front"]}, variants, 3, taken_seed=4)
    assert s.explore_view(str(record))["drawn"] == {"a": [5, 5, 0, "front"]}
    record = _record(board_dir, script, ["a"], {"a": [1, 1, 0, "front"]}, variants, 3, taken_seed=0, name="20261004-082239-77.json")
    assert s.explore_view(str(record))["drawn"] == {"a": [1, 1, 0, "front"]}


def test_an_explore_moved_onto_its_runs_board_draws_the_keepouts_and_reservations_its_plan_kept(own_project):
    s, jobs, board_dir, script = _studio(own_project)
    key, plain = "kk", [2.0, 2.0, 0, "front"]
    variants, best = _variants(key, plain)
    record = _record(board_dir, script, [key], {key: plain}, variants, 3)
    folder = _explore_run(board_dir, "eeee0008", script, record, kept=False)
    pad = {"kind": "pad", "poly": [[1.5, 1.5], [2.5, 1.5], [2.5, 2.5]], "faces": ["front"]}
    keepout = {"name": "ko", "poly": [[0, 0], [1, 0], [1, 1]], "faces": ["front"]}
    reservation = {"name": "res", "poly": [[5, 5], [6, 5], [6, 6]], "faces": ["front"]}
    plan = {"board": {"extent": [0, 0, 20, 20], "loops": [[[0, 0], [20, 0], [20, 20], [0, 20]]]}, "keepouts": [keepout], "reservations": [reservation],
            "items": [{"key": key, "kind": "part", "placed": True, "at": [2.0, 2.0], "rotation": 0, "face": "front", "members": [{"ref": "R1", "shapes": [pad]}]}],
            "steps": [], "copper": [], "findings": [{"text": "of the run's placement", "kind": "x"}], "counts": {"placed": 1, "findings": 1}}
    (folder / "plan.json").write_text(json.dumps(plan))
    view = s.explore_view(str(record))
    assert view["source"] == "moved" and view["doc"] is not None, view
    doc = view["doc"]
    assert doc["keepouts"] and doc["reservations"] and doc["findings"] == []
    assert _item(doc, key)["at"] == best[:2]
