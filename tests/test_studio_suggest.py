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


# ------------------------------------------------------------------ a suggestion of a past run or explore
# A past run or an explore opened from the Runs list is not a resolve of this studio: the page names the view it shows
# ({kind, ref}), and the studio finds the suggestion in that view's own plan.
def _past_run(s, rid, doc):
    """A recorded run of the watched script that kept `doc` as its plan (what a routed run writes as plan.json)."""
    d = s.src.board_dir / ".placemat" / "runs" / rid
    d.mkdir(parents=True)
    rec = {"run_id": rid, "board": s.src.name, "status": "ok", "placements": {}, "cutouts": {}, "metrics": {}, "findings": [], "finding_details": [],
           "steps": [], "timing_s": {}, "paths": {"script": str(s.script), "label": ""}, "failure": None, "verdicts": [], "acceptances": []}
    (d / "run.json").write_text(json.dumps(rec))
    (d / "plan.json").write_text(json.dumps(doc))
    return d


def _past_explore(s, name, doc):
    """A finished explore whose best variant's plan was kept beside its record (explore_view.BEST_DIR)."""
    views = s.src.board_dir / ".placemat" / "views" / "explore"
    (views / "best").mkdir(parents=True)
    record = views / name
    record.write_text(json.dumps({"script": str(s.script), "focus": [], "plain": {}, "variants": [], "best_seed": 0, "best": 1.0,
                                  "baseline": 1.0, "kept": False, "at": time.time()}))
    (views / "best" / name).write_text(json.dumps(doc))
    return record


@needs_kicad
def test_show_and_try_act_on_a_suggestion_of_a_past_run_that_is_not_a_resolve_of_this_studio(studio):
    rec, f, s = _first(studio)
    _past_run(studio, "eeee0001", rec.doc)
    studio.history.clear()                                         # the run is not one of this studio's resolves
    text = studio.script.read_text()
    view = {"kind": "run", "ref": "eeee0001"}
    code, out = _post(studio, "/suggest/show", {"resolve": None, "view": view, "id": s["id"]})
    assert code == 200, out
    assert out["dry_run"] and "C_HF1_LINK_LIMIT_MM" in out["diff"] and out["files"][0]["file"] == studio.script.name
    code, out = _post(studio, "/suggest/try", {"resolve": None, "view": view, "id": s["id"]})
    assert code == 200 and out["state"] == "done", out
    assert out["view"] == view and out["base"] == "run eeee0001" and out["cleared"] is True
    assert out["compare"]["files"][studio.script.name]["added"] >= 1
    assert studio.script.read_text() == text
    code, out = _post(studio, "/suggest/apply", {"view": view, "id": s["id"]})
    assert code == 200 and out["undo"] and "C_HF1_LINK_LIMIT_MM" in studio.script.read_text()


@needs_kicad
def test_show_and_try_act_on_a_suggestion_of_an_explores_best_variant(studio):
    rec, f, s = _first(studio)
    record = _past_explore(studio, "eeee0002.json", rec.doc)
    studio.history.clear()
    view = {"kind": "explore", "ref": str(record)}
    code, out = _post(studio, "/suggest/show", {"view": view, "id": s["id"]})
    assert code == 200 and "C_HF1_LINK_LIMIT_MM" in out["diff"], out
    code, out = _post(studio, "/suggest/try", {"view": view, "id": s["id"]})
    assert code == 200 and out["state"] == "done" and out["cleared"] is True, out


@needs_kicad
def test_a_past_run_whose_script_changed_since_is_refused_saying_so(studio):
    rec, f, s = _first(studio)
    _past_run(studio, "eeee0003", rec.doc)
    studio.script.write_text(studio.script.read_text() + "\n# edited since the run\n")
    view = {"kind": "run", "ref": "eeee0003"}
    for path in ("/suggest/show", "/suggest/try", "/suggest/apply"):
        code, out = _post(studio, path, {"view": view, "id": s["id"]})
        assert code == 409 and out["error"].startswith("this run's script has changed since") and "re-run to act on its suggestions" in out["error"], (path, out)
    code, out = _post(studio, "/suggest/show", {"view": {"kind": "run", "ref": "nope"}, "id": s["id"]})
    assert code == 404 and "no such resolve" not in out["error"]


# ------------------------------------------------------------------ a suggestion of a followed command
# A studio with no script chosen follows the commands of the project. While the followed command runs its plan is not its last, so
# Try, Apply and Search are refused (409, reason "running") and the run is left alone; once it has finished they act on the command's
# own script, as if it had been chosen.
@needs_kicad
def test_a_followed_commands_suggestions_wait_for_it_to_finish_then_act_on_its_script(tmp_path):
    script = real_modules.stage(tmp_path, MODULE, edit=lambda t: t + OVER)
    first = Studio(script, port=0, open_browser=False, debounce_ms=100, poll_ms=50)
    raw = []
    finish = first._finish
    first._finish = lambda cur, ev: (raw.append(json.loads(json.dumps(ev["doc"]))), finish(cur, ev))
    first.start()
    try:
        _settled(first)
        _, _, s = _first(first)
    finally:
        first.stop()
    studio = Studio(None, port=0, open_browser=False, root=script.parents[2], debounce_ms=100, poll_ms=50)
    studio.start()
    try:
        assert studio.script is None
        studio._on_channel(3, {"ev": "hello", "pid": 99999999, "command": "preview", "script": str(script), "args": ["preview"]})
        studio._on_channel(3, {"ev": "plan", "doc": raw[0]})
        view = {"kind": "cmd", "ref": "3"}
        text = script.read_text()
        code, out = _post(studio, "/suggest/show", {"view": view, "id": s["id"]})
        assert code == 200 and "C_HF1_LINK_LIMIT_MM" in out["diff"] and out["files"][0]["file"] == script.name, out
        for path in ("/suggest/try", "/suggest/apply", "/suggest/probe"):
            code, out = _post(studio, path, {"view": view, "id": s["id"]})
            assert code == 409 and out["reason"] == "running" and out["cmd"] == 3 and "when it has finished" in out["error"], (path, out)
        assert studio.cmds[3]["state"] == "running" and script.read_text() == text
        studio._on_channel(3, {"ev": "done", "record": ""})
        code, out = _post(studio, "/suggest/try", {"view": view, "id": s["id"]})
        assert code == 200 and out["state"] == "done" and out["cleared"] is True and out["view"] == view, out
        assert out["compare"]["files"][script.name]["added"] >= 1 and script.read_text() == text
        code, out = _post(studio, "/suggest/apply", {"view": view, "id": s["id"]})
        assert code == 200 and out["undo"] and "C_HF1_LINK_LIMIT_MM" in script.read_text(), out
        assert studio.script is None and [a["id"] for a in studio.applied_list()] == [s["id"]]
        code, out = _post(studio, "/suggest/undo")
        assert code == 200 and script.read_text() == text, out
        # the script has changed since the command ran: refused, as for a past run
        script.write_text(text + "\n# edited since the command\n")
        code, out = _post(studio, "/suggest/apply", {"view": view, "id": s["id"]})
        assert code == 409 and "has changed since" in out["error"], out
    finally:
        studio.stop()
