"""The studio server: loopback only, a token on every request, and the event
stream end to end on a staged module (a worker process, a real resolve)."""
import http.client
import json
import queue
import threading
import time

import pytest

from tests.conftest import needs_kicad

from placemat.studio import Studio
from tests import real_modules

LED = 'board.place(Part("r_led_status"), at=Beside(Part("c_mcu_bulk"), Edge.WEST, align=Along.%s),'


def _get(studio, path, token=True, host=None, method="GET"):
    conn = http.client.HTTPConnection("127.0.0.1", studio.port, timeout=10)
    sep = "&" if "?" in path else "?"
    headers = {"Host": host} if host else {}
    conn.request(method, path + (sep + "t=" + studio.token if token is True else sep + "t=" + token if token else ""), headers=headers)
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, body


class Stream:
    """An SSE client on a thread: every event, in order."""

    def __init__(self, studio):
        self.events: list = []
        self._q: queue.Queue = queue.Queue()
        self.conn = http.client.HTTPConnection("127.0.0.1", studio.port, timeout=60)
        self.conn.request("GET", "/events?t=" + studio.token)
        self.resp = self.conn.getresponse()
        assert self.resp.status == 200
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        name = None
        try:
            for raw in self.resp:
                line = raw.decode().rstrip("\n")
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: "):
                    ev = (name, json.loads(line[6:]))
                    self.events.append(ev)
                    self._q.put(ev)
        except (OSError, ValueError):
            pass

    def until(self, name, timeout=60, where=lambda d: True):
        """Wait for the next `name` event after what was already taken."""
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                raise AssertionError("no %r event; saw %s" % (name, [n for n, _ in self.events][-20:]))
            try:
                n, d = self._q.get(timeout=left)
            except queue.Empty:
                continue
            if n == name and where(d):
                return d

    def close(self):
        self.conn.close()


@pytest.fixture(scope="module")
def studio(tmp_path_factory):
    script = real_modules.stage(tmp_path_factory.mktemp("studio"), "mcu")
    s = Studio(script, port=0, open_browser=False, debounce_ms=100, poll_ms=50)
    s.start()
    yield s
    s.stop()


def test_it_listens_on_loopback_only(studio):
    assert studio.server.server_address[0] == "127.0.0.1"
    assert studio.url.startswith("http://127.0.0.1:%d/?t=" % studio.port)


@pytest.mark.parametrize("path", ["/", "/events", "/history", "/resolve/1", "/diff?a=1&b=2", "/nothing"])
def test_every_request_needs_the_token(studio, path):
    assert _get(studio, path, token=False)[0] == 403
    assert _get(studio, path, token="wrong")[0] == 403
    assert _get(studio, path, token="")[0] == 403


def test_the_token_opens_the_page_and_the_header_does_too(studio):
    status, body = _get(studio, "/")
    assert status == 200 and b"<!doctype html>" in body.lower()
    conn = http.client.HTTPConnection("127.0.0.1", studio.port, timeout=10)
    conn.request("GET", "/history", headers={"X-Studio-Token": studio.token})
    assert conn.getresponse().status == 200


def test_a_request_for_another_host_name_is_refused(studio):
    assert _get(studio, "/", host="attacker.example:%d" % studio.port)[0] == 403
    assert _get(studio, "/", host="localhost:%d" % studio.port)[0] == 200


def test_only_get_is_answered_and_unknown_paths_are_404(studio):
    assert _get(studio, "/nothing")[0] == 404
    assert _get(studio, "/", method="POST")[0] == 405
    assert _get(studio, "/resolve/9999")[0] == 404


def _edit(studio, align):
    text = studio.script.read_text()
    for a in ("MID", "START", "END"):
        text = text.replace(LED % a, LED % "@@")
    studio.script.write_text(text.replace(LED % "@@", LED % align))


@needs_kicad
def test_the_stream_shows_a_resolve_then_an_edit_with_what_it_moved(studio):
    s = Stream(studio)
    try:
        hello = s.until("hello")
        assert hello["script"] == "Mcu_layout.py"
        started = s.until("started")
        first_id = started["id"]
        assert "Mcu_layout.py" in started["texts"] and started["changed"] == []
        kinds = []
        fin = s.until("finished", where=lambda d: d["id"] == first_id)
        kinds = [n for n, d in s.events if isinstance(d, dict) and d.get("id") == first_id]
        assert kinds[0] == "started" and kinds.index("board") < kinds.index("step")
        assert kinds.count("step") >= 10
        order = [k for k in kinds if k != "step" and k != "board"]
        assert order == ["started", "copper", "links", "congestion", "findings", "items", "finished"]
        assert fin["counts"]["placed"] > 10 and fin["timing"]["total_s"] > 0
        steps = [d["item"] for n, d in s.events if n == "step" and d["id"] == first_id]
        assert {"key", "kind", "face", "rotation", "note", "findings", "line", "file", "members"} <= set(steps[0])
        assert any(i["key"] == "r_led_status" and i["line"] > 0 and i["file"] == "Mcu_layout.py" for i in steps)

        _edit(studio, "START")
        changed = s.until("changed")
        assert changed["files"] == ["Mcu_layout.py"]
        started2 = s.until("started")
        assert [c["file"] for c in started2["changed"]] == ["Mcu_layout.py"]
        unified = started2["changed"][0]["unified"]
        assert "-" + (LED % "MID") in unified and "+" + (LED % "START") in unified
        fin2 = s.until("finished", where=lambda d: d["id"] == started2["id"])
        assert "reused" in fin2["reused"]
        cmp = s.until("compare")
        assert (cmp["a"], cmp["b"]) == (first_id, started2["id"])
        assert [m["key"] for m in cmp["diff"]["moved"]] == ["r_led_status"]
        assert cmp["trace"]["items"]["r_led_status"]["lines"]["new"]       # a changed line declares it
        assert cmp["trace"]["knock_on"] == []
        assert any(h["id"] == started2["id"] for h in fin2["history"])
    finally:
        s.close()


@needs_kicad
def test_a_page_that_connects_later_is_given_the_latest_resolve_whole(studio):
    s = Stream(studio)
    try:
        s.until("hello")
        state = s.until("state")
        assert state["doc"]["counts"]["placed"] > 10 and "Mcu_layout.py" in state["texts"]
        assert state["compare"]["diff"]["moved"] or state["compare"] is None
    finally:
        s.close()


@needs_kicad
def test_a_change_during_a_resolve_cancels_it_and_the_last_edit_is_what_finishes(studio):
    s = Stream(studio)
    try:
        s.until("hello")
        _edit(studio, "END")
        started = s.until("started")
        _edit(studio, "MID")                                   # while that one is under way
        ended = None
        while ended is None:
            n, d = s._q.get(timeout=60)
            if n in ("cancelled", "superseded") and d["id"] == started["id"]:
                ended = n
            elif n == "finished" and d["id"] == started["id"]:
                raise AssertionError("a plan for text that had already changed was finished as current")
        last = s.until("started", where=lambda d: d["id"] > started["id"])
        assert (LED % "MID") in last["texts"]["Mcu_layout.py"]
        fin = s.until("finished", where=lambda d: d["id"] == last["id"])
        assert fin["counts"]["placed"] > 10
    finally:
        s.close()


@needs_kicad
def test_a_script_that_fails_is_an_error_event_and_the_next_good_edit_recovers(studio):
    s = Stream(studio)
    try:
        s.until("hello")
        good = studio.script.read_text()
        studio.script.write_text(good + "\nboard.nonsense(1)\n")
        err = s.until("error")
        assert "nonsense" in err["message"] and err["file"] == "Mcu_layout.py" and err["line"]
        studio.script.write_text(good)
        s.until("finished")
    finally:
        s.close()


@needs_kicad
def test_stop_leaves_no_worker_behind(tmp_path):
    script = real_modules.stage(tmp_path, "mcu")
    s = Studio(script, port=0, open_browser=False, debounce_ms=50, poll_ms=50)
    s.start()
    st = Stream(s)
    st.until("finished")
    proc = s.worker.proc
    assert proc is not None and proc.poll() is None
    st.close()
    s.stop()
    assert proc.poll() is not None
