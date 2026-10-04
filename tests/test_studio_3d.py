"""The studio's 3D side: the jobs it accepts, the converter process it keeps (a fake one here; test_model_convert runs the real one), the routes that
serve meshes and the viewer, and the whole thing over a live studio on a staged module."""
import sys
import textwrap
import time
from pathlib import Path

import pytest

from placemat import model_mesh as mm, studio_3d
from placemat.settings import Settings

FAKE = textwrap.dedent('''
    import json, sys, time
    from placemat import model_cache, model_mesh as mm
    from array import array
    cache = None
    for line in sys.stdin:
        msg = json.loads(line)
        if msg["cmd"] == "start":
            cache = model_cache.Cache(msg["cfg"]["cache_dir"], 64)
            print(json.dumps({"ev": "ready", "cli": "/usr/bin/kicad-cli", "selftest": {"ok": True, "version": "10.0"}}), flush=True)
        elif msg["cmd"] == "batch":
            for n, j in enumerate(msg["jobs"]):
                if j["name"].startswith("bad"):
                    print(json.dumps({"ev": "model", "id": j["id"], "state": "failed", "tris": None, "failure": {"code": "no_mesh"}}), flush=True)
                else:
                    m = mm.Mesh([mm.Material((1, 2, 3), 1.0, array("f", [0, 0, 0, 1, 0, 0, 0, 1, 0]), array("f", [0, 0, 1] * 3), array("I", [0, 1, 2]))])
                    cache.put(j["id"], mm.write_pmm(m))
                    print(json.dumps({"ev": "model", "id": j["id"], "state": "ok", "tris": 1}), flush=True)
                print(json.dumps({"ev": "progress", "done": n + 1, "total": len(msg["jobs"]), "current": j["id"]}), flush=True)
            print(json.dumps({"ev": "batch_done", "n": len(msg["jobs"])}), flush=True)
        elif msg["cmd"] == "quit":
            break
''')


def cfg(tmp_path):
    return Settings(studio_3d_cache_dir=str(tmp_path / "cache"), studio_3d_cache_mb=64)


def step(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"x")
    return p


def wait(pred, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def fake(tmp_path):
    script = tmp_path / "fake_converter.py"
    script.write_text(FAKE)
    events = []
    import os
    src = str(Path(__file__).resolve().parents[1] / "src")
    mp = pytest.MonkeyPatch()
    mp.setenv("PYTHONPATH", src + os.pathsep + os.environ.get("PYTHONPATH", ""))
    m = studio_3d.Models3D(cfg(tmp_path), lambda n, d: events.append((n, d)), tmp_path / "c.log", command=[sys.executable, str(script)])
    yield m, events, tmp_path
    m.stop()
    mp.undo()


def test_a_job_must_name_a_real_model_or_board_file_of_the_kind_it_says(tmp_path):
    good = step(tmp_path, "a.step")
    wrl = step(tmp_path, "b.wrl")
    pcb = step(tmp_path, "c.kicad_pcb")
    ok = studio_3d.valid_job
    assert ok({"id": "a" * 32, "kind": "file", "path": str(good), "name": "a.step"}) == {"id": "a" * 32, "kind": "file", "name": "a.step", "path": str(good)}
    assert ok({"id": "b" * 32, "kind": "vrml", "path": str(wrl)})["kind"] == "vrml"
    assert ok({"id": "e-abc123", "kind": "embedded", "board": str(pcb), "ref": "R1", "name": "R.step"})["ref"] == "R1"
    for bad in ({"id": "../x", "kind": "file", "path": str(good)}, {"id": "a" * 32, "kind": "file", "path": str(tmp_path / "gone.step")},
                {"id": "a" * 32, "kind": "file", "path": str(wrl)}, {"id": "a" * 32, "kind": "vrml", "path": str(good)},
                {"id": "a" * 32, "kind": "file", "path": "/etc/passwd"}, {"id": "a" * 32, "kind": "embedded", "board": str(good), "ref": "R1"},
                {"id": "a" * 32, "kind": "embedded", "board": str(pcb), "ref": ""}, {"id": "a" * 32, "kind": "shell", "path": str(good)}, "x", None,
                {"id": "A" * 32, "kind": "file", "path": str(good)}):
        assert ok(bad) is None, bad


def test_models_are_converted_in_the_background_and_the_page_is_told_each_one_and_the_progress(fake):
    m, events, tmp = fake
    a, b = step(tmp, "a.step"), step(tmp, "bad.step")
    assert m.submit([{"id": "1" * 32, "kind": "file", "path": str(a), "name": "a.step"}, {"id": "2" * 32, "kind": "file", "path": str(b), "name": "bad.step"},
                     {"id": "../etc", "kind": "file", "path": str(a)}]) == 2
    assert m.table() == {"1" * 32: {"state": "loading", "tris": None, "message": ""}, "2" * 32: {"state": "loading", "tris": None, "message": ""}}
    assert wait(lambda: all(v["state"] != "loading" for v in m.table().values()) and m.status()["progress"]["total"] == 0)
    assert m.table()["1" * 32]["state"] == "ok" and m.table()["1" * 32]["tris"] == 1 and m.table()["2" * 32] == {"state": "failed", "tris": None, "message": "kicad-cli exported no mesh for this model"}
    names = [n for n, _ in events]
    assert names[0] == "models3d" and names.count("model") == 2 and "models" in names
    st = m.status()
    assert st["ready"] and st["ok"] and st["cli"] and st["version"] == "10.0"
    assert m.submit([{"id": "1" * 32, "kind": "file", "path": str(a)}]) == 0                    # known: not queued again


def test_a_mesh_is_served_by_a_valid_id_only(fake):
    m, events, tmp = fake
    m.submit([{"id": "3" * 32, "kind": "file", "path": str(step(tmp, "a.step")), "name": "a.step"}])
    assert wait(lambda: m.table().get("3" * 32, {}).get("state") == "ok")
    p = m.mesh_path("3" * 32)
    assert p is not None and mm.read_pmm(p.read_bytes()).header["tris"] == 1
    for bad in ("../../etc/passwd", "3" * 31, "3" * 33, "Z" * 32, "", None, "e-" + "g" * 4, "3" * 32 + "/x"):
        assert m.mesh_path(bad) is None
    assert m.mesh_path("4" * 32) is None


def test_a_failed_model_is_tried_again_on_retry_and_not_before(fake):
    m, events, tmp = fake
    b = step(tmp, "bad.step")
    m.submit([{"id": "5" * 32, "kind": "file", "path": str(b), "name": "bad.step"}])
    assert wait(lambda: m.table()["5" * 32]["state"] == "failed")
    assert m.submit([{"id": "5" * 32, "kind": "file", "path": str(b), "name": "bad.step"}]) == 0
    assert m.retry("5" * 32) == 1
    assert wait(lambda: m.table().get("5" * 32, {}).get("state") == "failed" and sum(1 for n, d in events if n == "model") >= 2)


def test_the_viewer_and_the_vendored_library_are_served_from_a_fixed_list_only():
    assert studio_3d.lib_file("three.module.min.js")[1] == "text/javascript" and studio_3d.lib_file("LICENSE")[0].read_text().startswith("The MIT License")
    for bad in ("../studio.py", "three.module.js", "", "viewer.js/../x", "/etc/passwd"):
        assert studio_3d.lib_file(bad) is None


def test_the_vendored_library_ships_with_its_licence_and_is_mit():
    lib = Path(studio_3d.__file__).with_name("vendor") / "three"
    assert "MIT License" in (lib / "LICENSE").read_text()
    assert "SPDX-License-Identifier: MIT" in (lib / "three.module.min.js").read_text()[:400]
    assert (lib / "three.core.min.js").stat().st_size > 100_000 and (lib / "OrbitControls.js").is_file()
    assert "./three.core.min.js" in (lib / "three.module.min.js").read_text()
