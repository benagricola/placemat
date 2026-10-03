"""The studio's start and stop of a probe (a `placemat apply <id> --search --yes` command that reports over the live channel) and
the probe events it keeps for the page. The process itself is a fake here; tests/test_probe_cli.py runs the real command."""
import json

import pytest

from placemat import suggestions as sg
from placemat.studio import Studio, SuggestRefused
from tests import real_modules
from tests.conftest import needs_kicad
from tests.test_studio_suggest import MODULE, OVER, _settled

pytestmark = needs_kicad


class FakeProc:
    pid = 4242
    returncode = None

    def __init__(self, *a, **k):
        self.args, self.stopped = a, False

    def poll(self):
        return None if not self.stopped else 143

    def terminate(self):
        self.stopped = True


def _searched(studio, kind="track"):
    """A searched suggestion added to the first finding of the last resolve (what a finding's builder would offer)."""
    rec = studio.history[-1]
    f = rec.doc["findings"][0]
    figure = {"name": "chamfer", "unit": "mm", "kind": "bisect", "edit": 0, "declared": 0.5, "far": 0.1, "lo": 0.1, "hi": 0.5,
              "direction": "lower clears", "what": "the chamfer of the A track", "const": "A_CHAMFER_MM",
              "finding": ["copper", "copper.meets", "A"], "severity": "critical"}
    edit = {"op": "set_kwarg", "args": {"name": "chamfer"},
            "target": {"kind": kind, "key": "track A#1", "file": str(studio.script), "line": 1, "shared": 1, "digest": "x"}}
    f["suggestions"] = list(f.get("suggestions", ())) + [{"id": "s9z", "text": "Changing the chamfer of the A track might fix this: "
                                                          "search options?", "rank": 9, "lever": "chamfer", "edits": [edit],
                                                          "how": "searched", "figure": figure}]
    return rec


@pytest.fixture
def studio(tmp_path):
    script = real_modules.stage(tmp_path, MODULE, edit=lambda t: t + OVER)
    s = Studio(script, port=0, open_browser=False, debounce_ms=100, poll_ms=50)
    s.start()
    _settled(s)
    yield s
    s.stop()


def test_a_board_wide_probe_asks_for_confirmation_first_with_what_it_will_cost(studio, monkeypatch):
    rec = _searched(studio)
    started = []
    monkeypatch.setattr("placemat.studio.subprocess.Popen", lambda *a, **k: started.append(a) or FakeProc())
    out = studio.probe_start(rec.id, "s9z")
    assert out["state"] == "confirm" and out["estimate"]["board_wide"] and out["estimate"]["candidates"] == 12
    assert "resolves the whole board for each candidate" in out["line"] and not started


def test_start_with_yes_keeps_the_plan_in_the_store_and_runs_the_search_command(studio, monkeypatch):
    rec = _searched(studio)
    started = []
    monkeypatch.setattr("placemat.studio.subprocess.Popen", lambda *a, **k: started.append(a[0]) or FakeProc())
    out = studio.probe_start(rec.id, "s9z", yes=True)
    assert out["state"] == "started" and out["pid"] == 4242
    cmd = started[0]
    assert cmd[1:4] == ["-m", "placemat", "apply"] and cmd[4] == "s9z" and "--search" in cmd and "--yes" in cmd
    assert cmd[cmd.index("--script") + 1] == str(studio.script)
    kept = sg.recall(studio.src.board_dir, studio.script)[str(studio.script.resolve())]["suggestions"]
    assert "s9z" in [s.id for s in kept] and next(s for s in kept if s.id == "s9z").figure["name"] == "chamfer"


def test_one_probe_at_a_time_and_stop_asks_it_to_end(studio, monkeypatch):
    rec = _searched(studio)
    procs = []
    monkeypatch.setattr("placemat.studio.subprocess.Popen", lambda *a, **k: procs.append(FakeProc()) or procs[-1])
    with pytest.raises(SuggestRefused) as e:
        studio.probe_stop()
    assert e.value.status == 409
    studio.probe_start(rec.id, "s9z", yes=True)
    with pytest.raises(SuggestRefused) as e:
        studio.probe_start(rec.id, "s9z", yes=True)
    assert e.value.status == 409 and "already running" in str(e.value)
    assert studio.probe_stop()["state"] == "stopping" and procs[0].stopped


def test_an_instant_suggestion_is_not_probed(studio):
    rec, f = studio.history[-1], next(f for f in studio.history[-1].doc["findings"] if f.get("suggestions"))
    with pytest.raises(SuggestRefused) as e:
        studio.probe_start(rec.id, f["suggestions"][0]["id"], yes=True)
    assert e.value.status == 422


def test_the_probe_events_are_kept_in_the_commands_summary(studio):
    cid = 99
    studio._on_channel(cid, {"ev": "hello", "pid": 1, "command": "apply", "script": str(studio.script), "args": []})
    start = {"ev": "probe", "id": "s9z", "figure": {"name": "chamfer", "kind": "bisect"}, "budget_s": 120, "candidates": 12}
    studio._on_channel(cid, start)
    studio._on_channel(cid, {"ev": "candidate", "id": "s9z", "value": 0.1, "cleared": True, "n": 1})
    studio._on_channel(cid, {"ev": "probe_done", "id": "s9z", "state": "found", "n": 1, "best": {"value": 0.1}})
    (c,) = [c for c in studio.commands() if c["id"] == cid]
    assert c["probe"]["start"] == start and len(c["probe"]["candidates"]) == 1 and c["probe"]["done"]["state"] == "found"
    detail = studio.cmd_detail(cid)
    assert [e["ev"] for e in detail["events"]] == ["probe", "candidate", "probe_done"]


def test_the_endpoints_start_and_stop_a_probe_and_need_the_token(studio, monkeypatch):
    from tests.test_studio_suggest import _post
    rec = _searched(studio)
    procs = []
    monkeypatch.setattr("placemat.studio.subprocess.Popen", lambda *a, **k: procs.append(FakeProc()) or procs[-1])
    assert _post(studio, "/suggest/probe", {"resolve": rec.id, "id": "s9z"}, token=False)[0] == 403
    code, out = _post(studio, "/suggest/probe", {"resolve": rec.id, "id": "s9z"})
    assert code == 200 and out["state"] == "confirm"
    code, out = _post(studio, "/suggest/probe", {"resolve": rec.id, "id": "s9z", "yes": True})
    assert code == 200 and out["state"] == "started"
    assert _post(studio, "/suggest/probe", {"resolve": rec.id, "id": "s9z", "yes": True})[0] == 409
    code, out = _post(studio, "/suggest/probe/stop")
    assert code == 200 and out["state"] == "stopping" and procs[0].stopped
    assert _post(studio, "/suggest/probe/stop")[0] == 409
