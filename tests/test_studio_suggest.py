"""The studio's part of finding suggestions: the dry-run diff, a try (the edited text resolved in the warm worker and compared
with the resolve it was made on, nothing written), apply (written, the watcher re-resolves) and undo. A real fixture module,
staged as a copy; the fixture itself is never written."""
import http.client
import json
import time

import pytest

from placemat import context
from placemat.studio import Studio
from tests import real_modules
from tests.conftest import needs_kicad

MODULE = "usb5v"
OVER = '\nboard.link(PadRef(Part("c_hf1"), "VSHUNT"), PadRef(Part("buck"), VIN_N), limit_mm=0.01)\n'


def _post(studio, path, body=None, host=None, token=True):
    conn = http.client.HTTPConnection("127.0.0.1", studio.port, timeout=120)
    headers = {"Content-Type": "application/json"}
    if host:
        headers["Host"] = host
    conn.request("POST", path + ("?t=" + studio.token if token else ""), body=json.dumps(body or {}), headers=headers)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    try:
        return r.status, json.loads(data)
    except ValueError:
        return r.status, data.decode()


def _settled(s, count=1, seconds=300):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        with s.lock:
            if len(s.history) >= count and s._cur is None and not s._dirty:
                return
        time.sleep(0.1)
    raise AssertionError("the resolve did not finish")


@pytest.fixture
def studio(tmp_path):
    script = real_modules.stage(tmp_path, MODULE, edit=lambda t: t + OVER)
    s = Studio(script, port=0, open_browser=False, debounce_ms=100, poll_ms=50)
    s.start()
    _settled(s)
    yield s
    s.stop()


def _first(s):
    rec = s.history[-1]
    f = next(f for f in rec.doc["findings"] if f.get("suggestions"))
    return rec, f, f["suggestions"][0]


def test_the_overlay_runs_a_script_and_its_modules_from_the_text_it_holds_and_leaves_the_files_alone(tmp_path):
    helper = tmp_path / "helper.py"
    helper.write_text("VALUE = 1\n")
    script = tmp_path / "x_layout.py"
    script.write_text("import helper\nSEEN.append(helper.VALUE)\n")

    class Board:
        pass
    seen = []
    import builtins
    builtins.SEEN = seen
    try:
        context.run_script(script, Board())
        with context.overlay({str(helper): "VALUE = 2\n", str(script): "import helper\nSEEN.append(helper.VALUE * 10)\n"}):
            context.run_script(script, Board())
        context.run_script(script, Board())
    finally:
        del builtins.SEEN
    assert seen == [1, 20, 1] and helper.read_text() == "VALUE = 1\n" and context.overlay_text(helper) is None


@needs_kicad
def test_show_is_the_dry_run_diff_and_writes_nothing(studio):
    rec, f, s = _first(studio)
    text = studio.script.read_text()
    code, out = _post(studio, "/suggest/show", {"resolve": rec.id, "id": s["id"]})
    assert code == 200 and out["dry_run"] and out["text"] == s["text"]
    assert "C_HF1_LINK_LIMIT_MM" in out["diff"] and out["files"][0]["file"] == studio.script.name and out["files"][0]["hunks"]
    assert out["targets"][0]["line"] > 0 and out["targets"][0]["file"] == studio.script.name
    assert studio.script.read_text() == text
    assert _post(studio, "/suggest/show", {"resolve": rec.id, "id": "s99z"})[0] == 404
    assert _post(studio, "/suggest/show", {"resolve": 9999, "id": s["id"]})[0] == 404


@needs_kicad
def test_a_try_resolves_the_edited_text_compares_it_and_writes_nothing(studio):
    rec, f, s = _first(studio)
    text = studio.script.read_text()
    code, out = _post(studio, "/suggest/try", {"resolve": rec.id, "id": s["id"]})
    assert code == 200 and out["state"] == "done" and out["base"] == rec.id
    assert out["cleared"] is True and any(g["kind"] == "link_over" for g in out["lost"])
    assert out["score"]["delta"] < 0 and out["compare"]["files"][studio.script.name]["added"] >= 1
    assert all(not x["suggestions"] for x in out["doc"]["findings"])            # a try's own suggestions are never offered
    assert studio.script.read_text() == text and len(studio.history) == 1       # not written, not in the history
    assert "C_HF1_LINK_LIMIT_MM" in out["texts"][studio.script.name]


@needs_kicad
def test_a_try_is_refused_while_a_resolve_runs_and_is_stopped_by_a_change_to_a_watched_file(studio):
    rec, f, s = _first(studio)
    import threading
    got = {}
    t = threading.Thread(target=lambda: got.update(zip(("code", "out"), _post(studio, "/suggest/try", {"resolve": rec.id, "id": s["id"]}))))
    t.start()
    deadline = time.monotonic() + 30
    while studio._try is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _post(studio, "/suggest/try", {"resolve": rec.id, "id": s["id"]})[0] == 409          # one at a time
    studio.script.write_text(studio.script.read_text() + "\n# touched\n")
    t.join(120)
    assert got["code"] == 200 and got["out"]["state"] in ("cancelled", "done")
    if got["out"]["state"] == "cancelled":
        assert "changed" in got["out"]["message"]
    _settled(studio, 2)
    code, out = _post(studio, "/suggest/try", {"resolve": rec.id, "id": s["id"]})        # the digest of the file moved on
    assert code == 409 and "changed" in out["error"]


@needs_kicad
def test_apply_writes_the_file_the_watcher_resolves_again_and_undo_puts_it_back(studio):
    rec, f, s = _first(studio)
    before = studio.script.read_text()
    code, out = _post(studio, "/suggest/apply", {"resolve": rec.id, "id": s["id"]})
    assert code == 200 and out["undo"] and "C_HF1_LINK_LIMIT_MM" in studio.script.read_text()
    _settled(studio, 2)
    assert studio.history[-1].applied == "applied from a suggestion: " + s["text"]
    assert not [x for x in studio.history[-1].doc["findings"] if x["kind"] == "link_over"]
    assert studio.applied_list()[-1]["undone"] is False
    # the plan the suggestion came from is stale now
    assert _post(studio, "/suggest/apply", {"resolve": rec.id, "id": s["id"]})[0] == 409
    code, out = _post(studio, "/suggest/undo")
    assert code == 200 and studio.script.read_text() == before
    _settled(studio, 3)
    assert studio.history[-1].applied.startswith("undid: ")
    assert _post(studio, "/suggest/undo")[0] == 409                                           # nothing left to undo


@needs_kicad
def test_undo_refuses_when_the_file_has_moved_on_and_apply_false_refuses_writing(studio):
    rec, f, s = _first(studio)
    before = studio.script.read_text()
    assert _post(studio, "/suggest/apply", {"resolve": rec.id, "id": s["id"]})[0] == 200
    studio.script.write_text(studio.script.read_text() + "\n# edited since\n")
    code, out = _post(studio, "/suggest/undo")
    assert code == 409 and out["error"]
    import dataclasses
    studio.cfg = dataclasses.replace(studio.cfg, studio_apply=False)
    studio.script.write_text(before)
    code, out = _post(studio, "/suggest/apply", {"resolve": rec.id, "id": s["id"]})
    assert code == 403 and "apply" in out["error"] and "C_HF1" not in studio.script.read_text()
    assert _post(studio, "/suggest/show", {"resolve": rec.id, "id": s["id"]})[0] == 200                  # it still shows them


@needs_kicad
def test_the_endpoints_need_the_token_and_are_allowed_over_another_address(studio):
    rec, f, s = _first(studio)
    assert _post(studio, "/suggest/show", {"resolve": rec.id, "id": s["id"]}, token=False)[0] == 403
    assert _post(studio, "/suggest/show", {"resolve": rec.id, "id": s["id"]}, host="attacker.example:%d" % studio.port)[0] == 403
    studio.host = "0.0.0.0"                                               # listening on all addresses (--host): the token still guards
    import socket
    name = ("%s:%d" % (socket.gethostname(), studio.port)).lower()
    code, out = _post(studio, "/suggest/show", {"resolve": rec.id, "id": s["id"]}, host=name)
    assert code == 200


@needs_kicad
def test_redo_makes_the_undone_apply_again_and_refuses_when_there_is_nothing_or_the_file_moved(studio):
    rec, f, s = _first(studio)
    before = studio.script.read_text()
    assert _post(studio, "/suggest/redo")[0] == 409 and studio.redo_text() == ""                 # nothing undone yet
    assert _post(studio, "/suggest/apply", {"resolve": rec.id, "id": s["id"]})[0] == 200
    after = studio.script.read_text()
    assert _post(studio, "/suggest/undo")[0] == 200 and studio.script.read_text() == before
    assert studio.redo_text() == s["text"] and json.loads(studio.hello()[0][1])["redo"] == s["text"]
    code, out = _post(studio, "/suggest/redo")
    assert code == 200 and studio.script.read_text() == after and out["files"][0]["file"] == studio.script.name
    end = time.monotonic() + 120
    while time.monotonic() < end and not (studio.history and studio.history[-1].applied == "redid: " + s["text"]):       # undo and redo may share one resolve
        time.sleep(0.1)
    _settled(studio, len(studio.history))
    assert studio.history[-1].applied == "redid: " + s["text"] and studio.redo_text() == ""
    # undo again, then a change by someone else: the redo does not write over it
    assert _post(studio, "/suggest/undo")[0] == 200
    studio.script.write_text(studio.script.read_text() + "\n# someone else\n")
    code, out = _post(studio, "/suggest/redo")
    assert code == 409 and "changed" in out["error"] and "# someone else" in studio.script.read_text() and "C_HF1_LINK_LIMIT_MM" not in studio.script.read_text()
