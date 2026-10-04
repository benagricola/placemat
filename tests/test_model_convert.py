"""The model converter: batches through kicad-cli into the model frame and the cache, a bad model failing alone, the self-test, the process."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from placemat import model_cache, model_convert as mc, model_mesh as mm, model_place
from tests.conftest import needs_kicad

PRISM = mc.SELFTEST_MODEL
CLI = mc.find_kicad_cli()
needs_cli = pytest.mark.skipif(CLI is None, reason="kicad-cli is not installed")
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "fairing" / "core" / "layout" / "layout.kicad_pcb"


@pytest.fixture
def cfg(tmp_path):
    return mc.Config(batch=4, timeout_s=120, model_tris=30000, cache_dir=str(tmp_path / "models"), cache_mb=64)


@pytest.fixture
def cache(cfg):
    return model_cache.Cache(cfg.cache_dir, cfg.cache_mb)


def job(i, kind="file", **kw):
    return dict({"id": "%032x" % i, "kind": kind, "path": str(PRISM), "name": PRISM.name}, **kw)


@needs_kicad
@needs_cli
def test_the_self_test_finds_the_prism_in_the_model_frame_and_the_planes_where_the_placement_says(cfg):
    r = mc.self_test(cfg, CLI)
    assert r["ok"], r
    assert r["front"] == pytest.approx(list(mc.SELFTEST_BOX), abs=2e-3) and r["back"][2] == pytest.approx(-1.0, abs=2e-3) and r["back"][5] == pytest.approx(0, abs=2e-3)


@needs_kicad
@needs_cli
def test_the_self_test_refuses_a_kicad_whose_planes_are_not_the_ones_modelled(cfg, monkeypatch):
    monkeypatch.setattr(model_place, "FRONT_BELOW", 0.5)
    r = mc.self_test(cfg, CLI)
    assert not r["ok"] and r["failure"]["code"] == "planes_differ" and r["version"] and r["failure"]["front"] == r["front"]
    assert "model planes" in mc.failure_text(r["failure"])


@needs_kicad
@needs_cli
def test_a_batch_converts_each_model_to_the_cache_and_a_second_run_converts_nothing(cfg, cache, monkeypatch):
    events = []
    mc.run_batch([job(1), job(2)], cfg, CLI, cache, events.append)
    models = [e for e in events if e["ev"] == "model"]
    assert [e["state"] for e in models] == ["ok", "ok"] and all(e["tris"] > 0 for e in models)
    mesh = mm.read_pmm(cache.get("%032x" % 1).read_bytes())
    assert mesh.header["bbox"] == pytest.approx(list(mc.SELFTEST_BOX), abs=2e-3)         # the L-prism in its own frame, notch and all
    xs = {round(mesh.materials[0].positions[i], 3) for i in range(0, len(mesh.materials[0].positions), 3)}
    assert {0.0, 2.0, 4.0} <= xs                                                          # the notch's x is there: the shape is the L, not a box
    monkeypatch.setattr(mc, "convert_step_batch", lambda *a, **k: pytest.fail("converted again"))
    again = []
    mc.run_batch([job(1), job(2)], cfg, CLI, cache, again.append)
    assert [e["state"] for e in again if e["ev"] == "model"] == ["ok", "ok"]


@needs_kicad
@needs_cli
def test_a_bad_model_fails_alone_and_is_not_tried_again_until_retry(cfg, cache, tmp_path):
    bad = tmp_path / "bad.step"
    bad.write_text("this is not a STEP file")
    events = []
    mc.run_batch([job(1), job(2, path=str(bad), name="bad.step"), job(3)], cfg, CLI, cache, events.append)
    states = {e["id"]: e["state"] for e in events if e["ev"] == "model"}
    assert states == {"%032x" % 1: "ok", "%032x" % 2: "failed", "%032x" % 3: "ok"}
    assert cache.failure("%032x" % 2) and cache.has("%032x" % 1)
    cache.retry("%032x" % 2)
    assert cache.failure("%032x" % 2) is None


def test_a_batch_that_times_out_is_split_and_each_model_tried_alone(cfg, cache, monkeypatch):
    calls = []

    def fake(jobs, cfg_, cli, back=frozenset()):
        calls.append(len(jobs))
        if len(jobs) > 1:
            raise mc.ConvertError("timeout", limit_s=120)
        m = mm.Mesh([mm.Material((1, 2, 3), 1.0, __import__("array").array("f", [0, 0, 0, 1, 0, 0, 0, 1, 0]), __import__("array").array("f", [0, 0, 1] * 3), __import__("array").array("I", [0, 1, 2]))])
        return {0: m}
    monkeypatch.setattr(mc, "convert_step_batch", fake)
    events = []
    mc.run_batch([job(1), job(2), job(3)], cfg, "kicad-cli", cache, events.append)
    assert calls == [3, 1, 1, 1] and [e["state"] for e in events if e["ev"] == "model"] == ["ok", "ok", "ok"]


def test_without_kicad_cli_every_step_model_fails_with_one_sentence_and_no_traceback(cfg, cache):
    events = []
    mc.run_batch([job(1), job(2)], cfg, None, cache, events.append)
    fails = [e["failure"] for e in events if e["ev"] == "model"]
    assert fails == [{"code": "no_cli"}] * 2 and "message" not in events[0]
    assert mc.failure_text(fails[0]) == "3D needs kicad-cli on the path, or set studio_3d_kicad_cli"


def test_a_failure_is_a_record_with_the_tools_own_text_beside_the_facts(cache):
    e = mc.ConvertError("export_failed", returncode=3, detail="boom")
    assert e.record == {"code": "export_failed", "returncode": 3, "detail": "boom"} and str(e) == "kicad-cli failed (3): boom"
    cache.put_failure("%032x" % 9, e.record)
    assert cache.failure("%032x" % 9) == e.record
    (cache.dir / cache.name("%032x" % 8, "fail")).write_text("an older sentence")
    assert cache.failure("%032x" % 8) == {"code": "text", "detail": "an older sentence"} and mc.failure_text(cache.failure("%032x" % 8)) == "an older sentence"


def test_a_vrml_model_is_read_by_placemat_and_needs_no_kicad_cli(cfg, cache, tmp_path):
    wrl = tmp_path / "v.wrl"
    wrl.write_text("#VRML V2.0 utf8\nShape { appearance Appearance { material Material { diffuseColor 1 0 0 } } geometry IndexedFaceSet { coordIndex [0 1 2 -1] coord Coordinate { point [0 0 0, 1 0 0, 0 1 0] } } }")
    events = []
    mc.run_batch([job(7, "vrml", path=str(wrl), name="v.wrl")], cfg, None, cache, events.append)
    assert [e["state"] for e in events if e["ev"] == "model"] == ["ok"]
    assert mm.read_pmm(cache.get("%032x" % 7).read_bytes()).header["bbox"] == pytest.approx([0, 0, 0, 2.54, 2.54, 0])


def test_a_model_over_the_cap_is_simplified_once_and_the_cache_holds_the_drawn_mesh(cfg, cache, tmp_path):
    rows = " ".join("%d %d 0, %d %d 0," % (i, j, i + 1, j) for i in range(30) for j in range(30))
    faces = " ".join("%d %d %d -1" % (3 * k, 3 * k + 1, 3 * k + 2) for k in range(600)) if False else ""
    pts = []
    idx = []
    n = 60
    for j in range(n + 1):
        for i in range(n + 1):
            pts.append("%d %d 0" % (i, j))
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            idx.append("%d %d %d -1 %d %d %d -1" % (a, a + 1, a + n + 2, a, a + n + 2, a + n + 1))
    wrl = tmp_path / "big.wrl"
    wrl.write_text("#VRML V2.0 utf8\nShape { geometry IndexedFaceSet { coordIndex [%s] coord Coordinate { point [%s] } } }" % (" ".join(idx), ", ".join(pts)))
    small = mc.Config(model_tris=2000, cache_dir=cfg.cache_dir, cache_mb=64)
    events = []
    mc.run_batch([job(8, "vrml", path=str(wrl), name="big.wrl")], small, None, cache, events.append)
    head = mm.read_pmm(cache.get("%032x" % 8).read_bytes()).header
    assert head["tris"] <= 2000 and head["tris_in"] == 7200


@needs_kicad
@needs_cli
@pytest.mark.skipif(not FIXTURE.exists(), reason="the fixture board is not here")
def test_an_embedded_model_is_exported_from_its_footprint_on_the_board_file(cfg, cache):
    j = {"id": "e-09f2b2b0fd0a7a3977a7123532cca0ce", "kind": "embedded", "board": str(FIXTURE), "ref": "R81", "name": "R_0402_1005Metric.step"}
    events = []
    mc.run_batch([j], cfg, CLI, cache, events.append)
    assert [e["state"] for e in events if e["ev"] == "model"] == ["ok"]
    box = mm.read_pmm(cache.get(j["id"]).read_bytes()).header["bbox"]
    assert 0.9 < box[3] - box[0] < 1.2 and 0.4 < box[4] - box[1] < 0.7 and -0.01 <= box[2] < 0.01 and 0.3 < box[5] < 0.6       # a 1.0 x 0.5 x 0.4 mm chip, on its face, centred


@needs_kicad
@needs_cli
def test_the_converter_process_speaks_json_lines_and_says_ready_with_its_self_test(tmp_path):
    p = subprocess.Popen([sys.executable, "-m", "placemat.model_convert"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                         cwd=str(Path(__file__).resolve().parents[1]), env=dict(__import__("os").environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")))
    try:
        p.stdin.write(json.dumps({"cmd": "start", "cfg": {"cache_dir": str(tmp_path / "m"), "batch": 2}}) + "\n")
        p.stdin.write(json.dumps({"cmd": "batch", "jobs": [job(5)]}) + "\n")
        p.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
        p.stdin.flush()
        evs = [json.loads(l) for l in p.stdout.read().splitlines()]
    finally:
        p.wait(timeout=60)
    assert evs[0]["ev"] == "ready" and evs[0]["selftest"]["ok"]
    assert [e["state"] for e in evs if e["ev"] == "model"] == ["ok"] and evs[-1]["ev"] == "batch_done"
