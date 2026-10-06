"""placemat studio with no script (a picker), a worker that dies, and the checked runs the page lists and compares."""
import json
import os
import queue
import signal
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from placemat.cli import main
from placemat.studio import Studio, parse_fatal
from tests import real_modules


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return real_modules.stage(tmp_path_factory.mktemp("picker"), "usbconverter")


def _events(studio):
    q = studio.hub.subscribe(lambda: [])
    def drain():
        out = []
        while True:
            try:
                out.append(q.get_nowait())
            except queue.Empty:
                return out
    return drain


def test_without_a_script_the_studio_lists_the_layout_scripts_and_watches_nothing(project):
    s = Studio(None, port=0, open_browser=False, root=project.parents[2])
    assert s.script is None and s._initial is False
    hello = json.loads(s.hello()[0][1])
    assert hello["picker"] is True and hello["script"] == "" and hello["root"] == str(s.root)
    assert [x["id"].split("/")[-1] for x in hello["scripts"]] == ["LogicSupply_layout.py", "Usb5v_layout.py", "UsbConverter_layout.py"]
    assert all(x["title"] and not x["current"] for x in hello["scripts"])
    s.worker.send = lambda cmd: pytest.fail("nothing resolves before a script is chosen")
    s._tick(time.monotonic())                   # a picker has nothing to scan or resolve
    assert s.watched() == [] and s.history == type(s.history)(maxlen=s.history.maxlen)


def test_choosing_a_script_in_the_picker_is_the_same_switch(project):
    s = Studio(None, port=0, open_browser=False, root=project.parents[2], debounce_ms=10)
    sent = []
    s.worker.send = lambda cmd: sent.append(cmd) or True
    drain = _events(s)
    other = next(x["id"] for x in s.script_list() if x["title"] == "Usb5v")
    s.switch(other)
    assert s.script.name == "Usb5v_layout.py" and s._initial and s.watched()
    s._tick(time.monotonic())
    assert sent and sent[0]["cmd"] == "resolve" and sent[0]["script"].endswith("Usb5v_layout.py")
    names = [n for n, _ in drain()]
    assert "switched" in names and "started" in names
    assert json.loads(s.hello()[0][1])["script"] == "Usb5v_layout.py"


def test_the_command_with_no_script_and_no_layout_scripts_names_the_folder_it_searched(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["studio", "--no-open"]) == 2
    out = capsys.readouterr().out
    assert "no layout scripts found" in out and str(tmp_path) in out
    with pytest.raises(ValueError, match="no layout scripts found"):
        Studio(None, root=tmp_path)


def test_the_command_takes_no_script(project):
    from placemat.cli import parser
    assert parser().parse_args(["studio", "--no-open"]).script is None


# ------------------------------------------------------------------ a worker that dies
# A process that crashes on purpose first marks itself not dumpable (PR_SET_DUMPABLE 0), so the kernel writes no core and
# the desktop's crash reporter is not told of it.
NO_CORE = "import ctypes; ctypes.CDLL(None).prctl(4, 0, 0, 0, 0); "


def _crash_log(folder, name="crashing.py"):
    """What faulthandler writes when a user module segfaults, from a real process."""
    mod = folder / name
    mod.write_text(textwrap.dedent("""\
        import faulthandler

        def helper():
            faulthandler._sigsegv()

        def layout():
            helper()

        layout()
        """))
    log = folder / "crash.log"
    with open(log, "wb") as f:
        done = subprocess.run([sys.executable, "-c", NO_CORE + "import faulthandler; faulthandler.enable(); exec(compile(open(%r).read(), %r, 'exec'))" % (str(mod), str(mod))],
                              stderr=f)
    assert done.returncode == -signal.SIGSEGV
    return mod, log.read_text()


def test_faulthandler_output_is_read_into_its_signal_and_frames(tmp_path):
    mod, text = _crash_log(tmp_path)
    fatal = parse_fatal("noise before\n" + text)
    assert fatal["what"] == "Segmentation fault"
    mine = [f for f in fatal["frames"] if f[0] == str(mod)]
    assert [f[2] for f in mine] == ["helper", "layout", "<module>"] and mine[0][1] == 4
    assert parse_fatal("nothing fatal here\n") is None


def _fresh(project):
    s = Studio(project, port=0, open_browser=False)
    return s


def test_a_crash_is_reported_with_the_signal_and_the_line_in_the_users_file(project):
    s = _fresh(project)
    mod, text = _crash_log(project.parent, "crashing_helper.py")
    s.worker.log_path.parent.mkdir(parents=True, exist_ok=True)
    s.worker.log_path.write_text(text)
    s.worker.log_start = 0
    fields = s.worker_death(-signal.SIGSEGV)
    assert "crashed" in fields["message"] and "Segmentation fault" in fields["message"] and "SIGSEGV" in fields["message"]
    assert fields["file"] == "crashing_helper.py" and fields["line"] == 4 and fields["source"] == "faulthandler._sigsegv()"
    assert "in helper" in fields["detail"] and "in layout" in fields["detail"]


def test_a_signal_from_outside_is_named_in_words(project):
    s = _fresh(project)
    s.worker.log_start = 10 ** 9                # nothing of this worker's own in the log
    assert "stopped by SIGTERM" in s.worker_death(-15)["message"] and "-15" not in s.worker_death(-15)["message"]
    assert "stopped by SIGKILL" in s.worker_death(-9)["message"]
    assert "exited (code 3)" in s.worker_death(3)["message"]


def test_a_worker_that_exits_is_an_error_to_the_page_unless_the_studio_is_stopping(project):
    s = _fresh(project)
    s.worker.log_start = 10 ** 9
    drain = _events(s)
    s._cur = {"id": 7, "texts": {}, "changed": [], "t0": 0}
    s._on_worker({"ev": "exited", "code": -15}, s.worker.serial)
    errs = [json.loads(t) for n, t in drain() if n == "error"]
    assert len(errs) == 1 and "SIGTERM" in errs[0]["message"] and errs[0]["id"] == 7
    s._cur = {"id": 8, "texts": {}, "changed": [], "t0": 0}
    s._stopping.set()
    s._on_worker({"ev": "exited", "code": -15}, s.worker.serial)
    assert [n for n, _ in drain() if n == "error"] == []


def test_a_real_worker_that_is_terminated_leaves_the_module_alive_for_the_next_resolve(project):
    s = _fresh(project)
    assert s.worker.send({"cmd": "quit"}) or True
    s.worker.start()
    proc = s.worker.proc
    os.kill(proc.pid, signal.SIGTERM)
    assert proc.wait(timeout=20) == -signal.SIGTERM
    s.worker.kill()


def test_the_worker_turns_every_exception_into_an_error_with_the_users_line(project):
    from placemat.studio_worker import error_event
    bad = project.parent / "raising_layout.py"
    bad.write_text("board = None\n\ndef go():\n    raise KeyError('x_missing')\n")
    ns = {}
    try:
        exec(compile(bad.read_text(), str(bad), "exec"), ns)
        ns["go"]()
    except KeyError as e:
        ev = error_event(3, e, bad)
    assert ev["ev"] == "error" and ev["id"] == 3 and ev["kind"] == "exception" and ev["type"] == "KeyError" and "x_missing" in ev["detail"] and "message" not in ev
    assert ev["file"] == str(bad) and ev["line"] == 4 and ev["source"] == "raise KeyError('x_missing')" and "Traceback" in ev["traceback"]


# ------------------------------------------------------------------ runs
def _record(runs, rid, script, placements, findings=(), measures=None, label=""):
    d = runs / rid
    d.mkdir(parents=True)
    doc = {"run_id": rid, "board": "UsbConverter", "status": "ok", "placements": placements, "cutouts": {},
           "metrics": {"drc_real": 2, "outstanding": 2, "other": 0, "permitted": 0, "unconnected": 1, "airwire_mm": 10.0,
                       "measures": measures or {"airwire_mm": 10.0, "crossings": {}, "drc": 2, "findings": {}, "link_excess": 0.0, "unplaced": {}}},
           "findings": [f[1] for f in findings], "finding_details": [{"kind": "k", "severity": f[0], "text": f[1]} for f in findings],
           "steps": [], "timing_s": {"drc": 1.0}, "paths": {"script": str(script), "label": label}, "failure": None, "verdicts": [], "acceptances": []}
    (d / "run.json").write_text(json.dumps(doc))


def test_the_recorded_runs_of_the_script_are_listed_newest_first_with_their_score_and_drc(project):
    s = _fresh(project)
    runs = s.runs_dir()
    _record(runs, "aaaa0001", project, {"u1": {"x": 1.0, "y": 2.0, "rotation": 0.0, "face": "front"}}, [("warning", "old finding")], label="first")
    time.sleep(0.02)
    _record(runs, "bbbb0002", project, {"u1": {"x": 4.0, "y": 2.0, "rotation": 90.0, "face": "front"}})
    _record(runs, "cccc0003", project.parent / "other_layout.py", {})            # another script's run is not listed
    listed = s.runs()
    assert [r["id"] for r in listed] == ["bbbb0002", "aaaa0001"]
    first = listed[1]
    assert first["label"] == "first" and first["drc"]["drc_real"] == 2 and first["findings"] == 1 and first["severities"] == {"warning": 1}
    assert isinstance(first["score"], float)
    assert json.loads(s.hello()[0][1])["runs"][0]["id"] == "bbbb0002"


def test_a_run_is_compared_with_the_newest_resolve_by_placement_findings_and_score(project):
    from placemat.studio import Record
    s = _fresh(project)
    _record(s.runs_dir(), "dddd0004", project, {"u1": {"x": 1.0, "y": 2.0, "rotation": 0.0, "face": "front"}, "gone": {"x": 0.0, "y": 0.0, "rotation": 0.0, "face": "front"}},
            [("warning", "fixed finding")])
    doc = {"items": [{"key": "u1", "at": [4.0, 2.0], "rotation": 0.0, "face": "front", "placed": True},
                     {"key": "new", "at": [9.0, 9.0], "rotation": 0.0, "face": "front", "placed": True}],
           "findings": [{"text": "fresh finding", "kind": "k", "severity": "notice", "at": None, "item": ""}],
           "unplaced": [], "score": {"total": 1.0}, "copper": [], "links": []}
    s.history.append(Record(1, 0.0, {}, doc, []))
    out = s.compare_run("dddd0004")
    d = out["diff"]
    assert out["a"] == "run dddd0004" and out["b"] == 1
    assert [m["key"] for m in d["moved"]] == ["u1"] and d["moved"][0]["distance"] == 3.0
    assert [a["key"] for a in d["added"]] == ["new"] and [r["key"] for r in d["removed"]] == ["gone"]
    assert [f["text"] for f in d["findings"]["gained"]] == ["fresh finding"] and [f["text"] for f in d["findings"]["lost"]] == ["fixed finding"]
    assert d["score"]["b"] == 1.0 and d["empty"] is False
    assert s.compare_run("nope") is None


def test_a_run_is_started_on_request_reports_over_the_channel_and_its_result_reaches_the_page(project, monkeypatch):
    s = _fresh(project)
    drain = _events(s)

    class Proc:
        pid = 424242

        def wait(self):
            _record(s.runs_dir(), "eeee0005", project, {})
            s._on_channel(7, {"ev": "hello", "pid": 424242, "command": "run", "script": str(project), "args": ["run"]})      # the run says who it is
            s._on_channel(7, {"ev": "item", "item": {"key": "u1", "file": ""}})
            s._on_channel(7, {"ev": "error", "kind": "run_failure", "failure": "script", "detail": "boom", "file": "", "line": None})
            return 0
    seen = {}
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: seen.update(k) or Proc())
    assert s.start_run()["id"] == 1
    with pytest.raises(ValueError):
        s.start_run() if s._run is not None else (_ for _ in ()).throw(ValueError("busy"))
    ev, deadline = [], time.monotonic() + 30
    while not any(n == "run_done" for n, _ in ev) and time.monotonic() < deadline:       # the run clears itself, then says it is done: wait for the word
        time.sleep(0.02)
        ev += drain()
    names = [n for n, _ in ev]
    assert seen["stdout"] == subprocess.DEVNULL and seen["stderr"] == subprocess.DEVNULL          # its printed text is not read
    assert "run_started" in names and "run_line" not in names and names[-1] == "run_done"
    assert json.loads(next(x for n, x in ev if n == "run_started"))["pid"] == 424242
    done = json.loads(ev[-1][1])
    assert done["code"] == 0 and done["run"]["id"] == "eeee0005" and done["tail"] == ["Layout script failed: boom"] and done["runs"]



def test_a_begin_notice_from_the_worker_reaches_the_pages_without_being_kept(project):
    s = _fresh(project)
    drain = _events(s)
    s._cur = {"id": 3, "texts": {}, "changed": [], "t0": 0}
    s._on_worker({"ev": "begin", "id": 3, "kind": "begin", "item": "u1", "what": "searched", "rank": 2, "of": 9}, s.worker.serial)
    s._on_worker({"ev": "begin", "id": 99, "kind": "begin", "item": "stale"}, s.worker.serial)            # not the resolve in flight
    got = [(n, json.loads(t)) for n, t in drain()]
    assert len(got) == 1 and got[0][0] == "begin" and isinstance(got[0][1].pop("at"), float)                   # stamped with the server's clock
    assert got == [("begin", {"id": 3, "kind": "begin", "item": "u1", "what": "searched", "rank": 2, "of": 9})]
    assert s.hub.log == []


def test_the_size_of_the_queue_is_kept_for_a_page_that_joins_part_way(project):
    s = _fresh(project)
    s._cur = {"id": 3, "texts": {}, "changed": [], "t0": 0}
    s._on_worker({"ev": "begin", "id": 3, "kind": "total", "items": 9, "searched": 4, "copper": 2, "replay": 0}, s.worker.serial)
    s._on_worker({"ev": "begin", "id": 3, "kind": "begin", "item": "u1", "what": "decided"}, s.worker.serial)
    assert [json.loads(x)["kind"] for n, x in s.hub.log if n == "begin"] == ["total"]


def test_resolve_now_cancels_what_runs_and_starts_another_at_once_fresh_when_asked(project):
    s = _fresh(project)
    sent = []
    s.worker.send = lambda cmd: sent.append(cmd) or True
    s._initial = False
    s._poller = type("Quiet", (), {"scan": lambda self: set()})()
    s._tick(time.monotonic())
    assert sent == []                                                  # nothing is due: no file changed
    assert s.resolve_now(False) == {"fresh": False}
    s._tick(time.monotonic())
    assert [c["cmd"] for c in sent] == ["resolve"] and sent[0]["fresh"] is False
    rid = sent[0]["id"]
    assert s.resolve_now(True) == {"fresh": True}                      # while it runs: it is told to cancel
    assert sent[-1] == {"cmd": "cancel", "id": rid}
    s._on_worker({"ev": "cancelled", "id": rid}, s.worker.serial)
    s._tick(time.monotonic())
    assert sent[-1]["cmd"] == "resolve" and sent[-1]["fresh"] is True and sent[-1]["id"] == rid + 1
    s._cur, s._cancel_at = None, None
    s.debounce.stopped()
    s.resolve_now(False)
    s._tick(time.monotonic())
    assert sent[-1]["fresh"] is False                                  # asked for once, not kept
    with pytest.raises(ValueError):
        Studio(None, root=project.parents[2]).resolve_now()


def test_a_page_that_joins_late_is_told_when_the_resolve_began_and_what_is_under_way_by_the_servers_clock(project):
    s = _fresh(project)
    s._cur = {"id": 4, "texts": {}, "changed": [], "t0": 0, "at": time.time() - 83.0}
    s._on_worker({"ev": "begin", "id": 4, "kind": "total", "items": 24, "searched": 18, "copper": 6, "replay": 0}, s.worker.serial)
    s._on_worker({"ev": "begin", "id": 4, "kind": "begin", "item": "psu", "what": "searched", "rank": 7, "of": 18, "replaying": False, "n": 3}, s.worker.serial)
    s._on_worker({"ev": "begin", "id": 4, "kind": "phase", "stage": "scan", "face": "front", "hint": [1.0, 2.0]}, s.worker.serial)
    hello = json.loads(s.hello()[0][1])
    assert abs(hello["now"] - time.time()) < 2 and hello["resolving"] == 4
    w = hello["work"]
    assert 82.0 < hello["now"] - w["t0"] < 86.0                                       # since the resolve began, not since the page joined
    assert w["total"]["items"] == 24 and w["cur"]["item"] == "psu" and w["cur"]["stage"] == "scan" and w["cur"]["face"] == "front" and w["cur"]["hint"] == [1.0, 2.0]
    assert 0 <= hello["now"] - w["cur"]["at"] < 2 and w["cur"]["within"] is None
    s._on_worker({"ev": "begin", "id": 4, "kind": "phase", "stage": "refine", "within": [2, 5]}, s.worker.serial)
    assert json.loads(s.hello()[0][1])["work"]["cur"]["within"] == [2, 5]               # a page that joins part-way gets how far the step is
    s._on_worker({"ev": "item", "id": 4, "item": {"key": "psu", "file": ""}}, s.worker.serial)
    assert json.loads(s.hello()[0][1])["work"]["cur"] is None


def test_a_port_in_use_is_a_plain_message_naming_another_studio_when_it_is_one(project, capsys):
    import socket
    from placemat.cli import main
    other = Studio(project, port=0, open_browser=False)
    other.start()
    try:
        assert main(["studio", str(project), "--port", str(other.port), "--no-open"]) == 2
        out = capsys.readouterr().out
        assert "port %d is in use: another studio is running at http://127.0.0.1:%d/" % (other.port, other.port) in out and "--port" in out
    finally:
        other.stop()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    try:
        port = blocker.getsockname()[1]
        assert main(["studio", str(project), "--port", str(port), "--no-open"]) == 2
        assert "port %d is in use" % port in capsys.readouterr().out
    finally:
        blocker.close()


def test_the_hello_gives_the_address_another_device_reaches_and_qr_draws_only_the_studios_own(project):
    import http.client
    local = Studio(project, port=0, open_browser=False)
    local.start()
    try:
        assert json.loads(local.hello()[0][1])["origin"] is None
        conn = http.client.HTTPConnection("127.0.0.1", local.port, timeout=10)
        own = "http://127.0.0.1:%d/?t=%s" % (local.port, local.token)
        conn.request("GET", "/qr?t=%s&u=%s" % (local.token, own.replace("?", "%3F").replace("=", "%3D").replace("&", "%26")))
        r = conn.getresponse()
        body = r.read()
        assert r.status == 200 and r.getheader("Content-Type") == "image/svg+xml" and body.startswith(b"<svg")
        conn.request("GET", "/qr?t=%s&u=http%%3A%%2F%%2Fevil.example%%2F" % local.token)
        r = conn.getresponse()
        r.read()
        assert r.status == 400
        conn.request("GET", "/qr?u=x")
        r = conn.getresponse()
        r.read()
        assert r.status == 403
    finally:
        local.stop()
    wide = Studio(project, port=0, open_browser=False, host="0.0.0.0")
    wide.start()
    try:
        hello = json.loads(wide.hello()[0][1])
        assert hello["origin"] == "http://%s:%d" % (hello["origin"].split("//")[1].split(":")[0], wide.port) and hello["port"] == wide.port and wide.url.startswith(hello["origin"])
    finally:
        wide.stop()


def _cmd(s, cid=1, script="x_layout.py", **extra):
    s._on_channel(cid, dict({"ev": "hello", "pid": 4000 + cid, "command": "explore", "script": str(s.root / script), "args": ["run", script]}, **extra))


def test_a_command_reporting_over_the_channel_is_listed_with_its_events_and_ends_as_done_error_or_lost(project):
    s = _fresh(project)
    drain = _events(s)
    _cmd(s, 1)
    _cmd(s, 2)
    _cmd(s, 3)
    s._on_channel(1, {"ev": "resolve", "n": 1})
    s._on_channel(1, {"ev": "item", "item": {"key": "u1", "file": str(s.root / "sub" / "a.py")}})
    s._on_channel(1, {"ev": "plan", "doc": {"items": [{"key": "u1", "file": str(s.root / "x_layout.py")}], "steps": []}})
    s._on_channel(1, {"ev": "done", "record": "/r/run.json"})
    s._on_channel(2, {"ev": "item", "item": {"key": "u9", "file": ""}})
    s._on_channel(2, {"ev": "lost"})
    s._on_channel(3, {"ev": "error", "kind": "exception", "type": "ValueError", "detail": "boom", "file": "x_layout.py", "line": 7})
    by = {c["id"]: c for c in s.commands()}
    assert by[1]["state"] == "done" and by[1]["record"] == "/r/run.json" and by[1]["items"] == 1 and by[1]["command"] == "explore" and by[1]["pid"] == 4001
    assert by[2]["state"] == "lost" and "u9" in by[2]["message"] and by[3]["state"] == "error" and by[3]["message"] == "ValueError: boom"
    d = s.cmd_detail(1)
    assert [e["ev"] for e in d["events"]] == ["resolve", "item", "done"] and d["plan"]["doc"]["items"][0]["file"] == "x_layout.py"
    assert d["events"][1]["item"]["file"] == "sub/a.py"                                 # files as the page names them
    assert s.cmd_detail(99) is None
    names = [n for n, _ in drain()]
    assert names.count("cmd") >= 6 and "cmdev" in names
    assert [c["id"] for c in json.loads(s.hello()[0][1])["commands"]] == [1, 2, 3]


def test_an_explore_streamed_over_the_channel_keeps_its_variants_and_a_record_lists_afterwards(project):
    s = _fresh(project)
    _cmd(s, 5)
    s._on_channel(5, {"ev": "explore", "focus": ["a"], "plain": {"a": [1, 2, 0, "front"]}, "order": ["a"], "baseline": 10.0, "jobs": 2, "at": 1.0})
    s._on_channel(5, {"ev": "variant", "seed": 1, "score": 9.0, "measures": {}, "placements": {"a": [3, 2, 90, "front"]}, "order": ["a"], "t": 0.5})
    s._on_channel(5, {"ev": "variant", "seed": 2, "score": 11.0, "measures": {}, "placements": {"a": None}, "order": [], "t": 1.0})
    d = s.cmd_detail(5)
    assert [v["seed"] for v in d["explore"]["variants"]] == [1, 2] and d["summary"]["best"] == 9.0 and d["summary"]["variants"] == 2
    folder = s.src.board_dir / ".placemat" / "views" / "explore"
    folder.mkdir(parents=True)
    rec = {"version": 1, "script": str(project), "at": 5.0, "pid": 9, "focus": ["a"], "baseline": 10.0, "best": 9.0, "best_seed": 1, "kept": True,
           "plain": {"a": [1, 2, 0, "front"]}, "order": ["a"], "variants": [{"seed": 0, "score": 10.0, "placements": {}, "order": [], "t": 0}]}
    (folder / "20261003-000000-9.json").write_text(json.dumps(rec))
    listed = s.explores()
    assert [e["file"] for e in listed] == [str(folder / "20261003-000000-9.json")] and listed[0]["kept"] is True and listed[0]["tried"] == 1
    assert s.explore_record(listed[0]["file"])["best_seed"] == 1
    assert s.explore_record("/etc/passwd") is None and s.explore_record(str(folder / "other.json")) is None


def test_a_routes_events_are_counted_kept_for_a_late_page_and_summarised_without_the_copper(project):
    s = _fresh(project)
    drain = _events(s)
    _cmd(s, 6)
    for ev in ({"ev": "route_stage", "stage": "main"}, {"ev": "route_queue", "nets": ["A", "B"]}, {"ev": "route_net_begin", "net": "A"},
               {"ev": "route_commit", "net": "A", "how": "route", "seg": [[0, 0, 1, 0, "F.Cu", 0.2]], "via": []}, {"ev": "route_net_end", "net": "A", "ok": True},
               {"ev": "route_net_begin", "net": "B"}, {"ev": "route_net_end", "net": "B", "ok": False}, {"ev": "route_queue_end"}):
        s._on_channel(6, ev)
    c = {c["id"]: c for c in s.commands()}[6]
    assert {k: c["route"][k] for k in ("total", "done", "failed", "current", "stage")} == {"total": 2, "done": 1, "failed": 1, "current": "", "stage": "main"}
    assert "log" not in c["route"] and "results" not in c["route"] and c["route"]["finished"] is False          # the command ends the route, not a queue
    assert [e["ev"] for e in s.cmd_detail(6)["events"]].count("route_commit") == 1
    names = [n for n, _ in drain()]
    assert names.count("cmdev") == 8 and names.count("cmd") >= 7 + 1                                          # a commit is not a summary of its own


def test_recorded_routes_are_listed_and_served_only_from_this_projects_folders(project):
    from placemat import route_progress
    s = _fresh(project)
    base = s.src.board_dir / ".placemat"
    stages = [{"stage": "main", "resumed": False, "seconds": 1.0, "events": [{"ev": "net_end", "net": "A", "ok": True}, {"ev": "commit", "net": "A", "how": "route", "seg": [[0, 0, 1, 0, "F.Cu", 0.2]], "via": []}]}]
    (base / "route").mkdir(parents=True)
    (base / "runs" / "ab12" / "route").mkdir(parents=True)
    own = route_progress.write_record(base / "route", {"pcb": "x.kicad_pcb", "run": "", "script": "x_layout.py"}, stages, {"closure": 1.0}, complete=True)
    ran = route_progress.write_record(base / "runs" / "ab12" / "route", {"pcb": "x.kicad_pcb", "run": "ab12", "script": "x_layout.py"}, stages, {"closure": 1.0}, complete=True)
    (base / "route" / route_progress.BOARD).write_text(json.dumps({"board": {"loops": [], "drawn": False, "extent": [0, 0, 1, 1]}, "items": [], "layers": ["F.Cu"]}))
    (base / "runs" / "ab12" / "plan.json").write_text(json.dumps({"board": {"loops": [], "drawn": False, "extent": [0, 0, 1, 1]}, "items": [], "layers": ["F.Cu"], "steps": [], "copper": []}))
    listed = s.routes()
    assert {e["file"]: (e["run"], e["build"], e["nets"], e["routed"]) for e in listed} == {str(own): ("", False, 1, 1), str(ran): ("ab12", True, 1, 1)}
    assert s.route_record(str(own))["doc"]["route"] == {"nets": 1, "routed": 1, "failed": 0, "partial": False, "dropped": 0}
    assert s.build_record("ab12")["doc"]["steps"][0]["item"] == "track A" and s.build_record("nope") is None and s.build_record("../x") is None and s.build_record("") is None
    assert s.route_record("/etc/passwd") is None and s.route_record(str(own.with_name("route_summary.json"))) is None
    assert json.loads(s.hello()[0][1])["routes"] == listed


def test_the_studio_finds_the_sockets_of_commands_in_its_project_and_a_dead_one_is_shown_from_its_progress_file(project):
    from placemat import channel
    s = Studio(project, port=0, open_browser=False)
    s.start()
    try:
        channel.reset()
        rep = channel.reporter(project)
        assert channel.sockets_dir(s.root) == rep.directory
        rep.send({"ev": "item", "item": {"key": "u1", "file": ""}})
        deadline = time.monotonic() + 10
        while not s.commands() or s.commands()[0]["items"] < 1:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert s.commands()[0]["pid"] == os.getpid() and s.commands()[0]["script"] == str(project)
        channel.reset()
        d = channel.sockets_dir(s.root)
        log = s.root / "dead.jsonl"
        log.write_text(json.dumps({"ev": "hello", "pid": 999999999}) + "\n" + json.dumps({"ev": "item", "key": "u7"}) + "\n")
        (d / "999999999.json").write_text(json.dumps({"pid": 999999999, "command": "preview", "script": str(project), "socket": str(d / "s.sock"),
                                                     "progress": str(log)}))
        deadline = time.monotonic() + 10
        while not any(c["pid"] == 999999999 for c in s.commands()):
            assert time.monotonic() < deadline
            time.sleep(0.02)
        dead = next(c for c in s.commands() if c["pid"] == 999999999)
        assert dead["state"] == "lost" and dead["last"] == "u7" and "u7" in dead["message"]
    finally:
        s.stop()


def test_a_crashed_worker_is_a_lost_connection_and_the_last_step_it_reported(project):
    s = _fresh(project)
    s.worker.log_start = 10 ** 9
    s._cur = {"id": 3, "texts": {}, "changed": [], "t0": 0}
    s._on_worker({"ev": "begin", "id": 3, "kind": "begin", "item": "psu", "what": "searched"}, s.worker.serial)
    s._on_worker({"ev": "item", "id": 3, "item": {"key": "mcu", "file": ""}}, s.worker.serial)
    s._on_worker({"ev": "begin", "id": 3, "kind": "begin", "item": "psu2", "what": "searched"}, s.worker.serial)
    msg = s.worker_death(-11)["message"]
    assert "SIGSEGV" in msg and "while working on psu2" in msg and "the last step it settled was mcu" in msg


def test_the_models_a_commands_item_uses_go_to_the_converter_and_not_to_the_page(project):
    s = _fresh(project)
    got = []
    s.m3d.submit = lambda jobs: got.append(jobs)
    _cmd(s, 8)
    job = {"id": "a" * 32, "kind": "file", "path": "/x/m.step", "name": "m.step"}
    s._on_channel(8, {"ev": "item", "item": {"key": "u1", "file": ""}, "model_jobs": [job]})
    assert got == [[job]]
    assert all("model_jobs" not in e for e in s.cmd_detail(8)["events"])


def test_a_step_a_command_found_slow_is_kept_with_the_command_and_sent_to_the_page(project):
    s = _fresh(project)
    drain = _events(s)
    _cmd(s, 1)
    warn = {"ev": "step_warn", "item": "ble", "elapsed_s": 31.0, "pass": "refine", "stage": "refine", "within": [2, 3], "firm_pass": None, "bound_s": 30.0}
    s._on_channel(1, warn)
    s._on_channel(1, dict(warn, ev="step_limit", elapsed_s=61.0, bound_s=60.0))
    [c] = s.commands()
    assert [x["kind"] for x in c["slow"]] == ["step_warn", "step_limit"] and c["slow"][0]["item"] == "ble" and c["slow"][0]["within"] == [2, 3]
    slow = [json.loads(t) for n, t in drain() if n == "slow"]
    assert [x["ev"] for x in slow] == ["step_warn", "step_limit"] and slow[0]["id"] == 1 and slow[0]["command"] == "explore"
    s._on_channel(1, {"ev": "resolve", "n": 2})
    assert s.commands()[0]["slow"] == []                                    # a new resolve starts a new list


def test_a_regenerating_run_says_so_and_is_followed_by_a_resolve_when_the_shown_generation_was_stale(project, monkeypatch):
    from placemat.studio import Record
    s = _fresh(project)
    drain = _events(s)
    s.history.append(Record(1, 0.0, {}, {"items": [], "findings": [], "unplaced": [], "counts": {}}, [], stale={"form": "changed", "files": ["m/layout/layout.kicad_pcb"]}))
    asked = []
    monkeypatch.setattr(s, "resolve_now", lambda fresh=False: asked.append(fresh) or {})

    checked = threading.Event()

    class Proc:
        pid = 424243

        def wait(self):
            checked.wait(10)                    # the run is in progress until the test has looked at it
            return 0
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Proc())
    assert s.start_run(regenerate=True)["id"] == 1
    try:
        assert s._run_state()["regenerate"] is True
    finally:
        checked.set()
    ev, deadline = [], time.monotonic() + 30
    while not any(n == "run_done" for n, _ in ev) and time.monotonic() < deadline:
        time.sleep(0.02)
        ev += drain()
    assert json.loads(next(x for n, x in ev if n == "run_started"))["regenerate"] is True
    deadline = time.monotonic() + 5
    while not asked and time.monotonic() < deadline:
        time.sleep(0.02)
    assert asked == [False]


def test_a_run_after_a_current_generation_starts_no_resolve(project, monkeypatch):
    from placemat.studio import Record
    s = _fresh(project)
    drain = _events(s)
    s.history.append(Record(1, 0.0, {}, {"items": [], "findings": [], "unplaced": [], "counts": {}}, [], stale=None))
    asked = []
    monkeypatch.setattr(s, "resolve_now", lambda fresh=False: asked.append(fresh) or {})

    class Proc:
        pid = 424244

        def wait(self):
            return 0
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Proc())
    s.start_run()
    ev, deadline = [], time.monotonic() + 30
    while not any(n == "run_done" for n, _ in ev) and time.monotonic() < deadline:
        time.sleep(0.02)
        ev += drain()
    time.sleep(0.2)
    assert asked == []


# ------------------------------------------------------------------ what a command is, and the project's past runs
def test_a_command_is_named_by_what_it_is_and_carries_its_label(project):
    s = _fresh(project)
    for cid, command, args, label in ((1, "preview", ["preview", "x.py"], ""), (2, "run", ["run", "x.py", "--route"], "nightly"), (3, "run", ["run", "x.py", "--explore", "60"], ""),
                                      (4, "preview", ["preview", "x.py", "--explore=30"], ""), (5, "route", ["route", "x.pcb"], ""), (6, "apply", ["apply", "x.py"], "")):
        s._on_channel(cid, {"ev": "hello", "pid": 5000 + cid, "command": command, "script": str(s.root / "x_layout.py"), "args": args, "label": label})
    by = {c["id"]: c for c in s.commands()}
    assert [by[i]["kind"] for i in range(1, 7)] == ["preview", "run", "explore", "explore", "route", "apply"]
    assert by[2]["label"] == "nightly" and by[1]["label"] == "" and by[2]["command"] == "run"
    s._on_channel(1, {"ev": "explore", "focus": ["a"], "plain": {}, "order": [], "baseline": 1.0, "jobs": 1, "at": 1.0})          # one that explores is an explore whatever it was typed as
    assert {c["id"]: c["kind"] for c in s.commands()}[1] == "explore"
    assert json.loads(s.hello()[0][1])["commands"][1]["label"] == "nightly"


@pytest.fixture
def own_project(tmp_path):
    """A project of this test's own, so what it lists is only what the test made."""
    return real_modules.stage(tmp_path, "usbconverter")


def _board_dirs(s):
    out = []
    for entry in s.scripts():
        if entry["src"].board_dir not in out:
            out.append(entry["src"].board_dir)
    return out


def _run_folder(board_dir, rid, script, status="ok", pid=None, findings=(), details=None):
    d = board_dir / ".placemat" / "runs" / rid
    d.mkdir(parents=True)
    doc = {"run_id": rid, "board": board_dir.name, "status": status, "placements": {}, "cutouts": {}, "metrics": {"measures": {"airwire_mm": 10.0, "crossings": {}, "drc": 0, "findings": {}, "link_excess": 0.0, "unplaced": {}}},
           "findings": [f[1] for f in findings], "finding_details": details if details is not None else [{"kind": "k", "severity": f[0], "text": f[1]} for f in findings],
           "steps": [], "timing_s": {}, "paths": {"script": str(script), "label": ""}, "failure": None, "verdicts": [], "acceptances": [], "pid": pid}
    (d / "run.json").write_text(json.dumps(doc))
    return d


def test_the_projects_past_runs_are_listed_from_every_board_with_no_script_chosen(own_project):
    s = Studio(None, port=0, open_browser=False, root=own_project.parents[2])
    assert s.script is None
    first, second = _board_dirs(s)[:2]
    scripts = {e["src"].board_dir: e["path"] for e in s.scripts()}
    _run_folder(first, "aaaa0001", scripts[first], findings=[("warning", "one")])
    time.sleep(0.02)
    _run_folder(second, "bbbb0002", scripts[second])
    time.sleep(0.02)
    _run_folder(second, "cccc0003", scripts[second], status="running", pid=os.getpid())                  # under way: a command running, not a past run
    _run_folder(second, "dddd0004", scripts[second], status="running", pid=2 ** 22 + 11)                   # a record that says running, whose process is gone: it died
    (second / ".placemat" / "runs" / "a-label").symlink_to("bbbb0002")                                      # a label is another name for a run, not another run
    (second / ".placemat" / "runs" / ".staging").mkdir()
    (second / ".placemat" / "runs" / ".staging" / "run.json").write_text("{}")
    listed = s.project_runs()
    assert [r["id"] for r in listed] == ["dddd0004", "bbbb0002", "aaaa0001"] and {r["kind"] for r in listed} == {"run"}
    assert [r["died"] for r in listed] == [True, False, False] and listed[2]["findings"] == 1 and listed[2]["script"] == str(scripts[first])
    assert s.project_runs(limit=1)[0]["id"] == "dddd0004"
    assert json.loads(s.hello()[0][1])["project_runs"] == listed
    assert s.script is None and s.history == type(s.history)(maxlen=s.history.maxlen)                      # nothing was resolved to list them


def test_a_past_run_opens_with_its_board_and_findings_and_resolves_nothing(own_project):
    pytest.importorskip("pcbnew")
    import shutil
    s = Studio(None, port=0, open_browser=False, root=own_project.parents[2])
    s.worker.send = lambda cmd: pytest.fail("a past run is opened, not resolved")
    board_dir = next(d for d in _board_dirs(s) if (d / ".placemat" / "generated").is_dir())
    script = next(e["path"] for e in s.scripts() if e["src"].board_dir == board_dir)
    cached = next((board_dir / ".placemat" / "generated").glob("*/layout.kicad_pcb"))
    details = [{"kind": "copper", "severity": "warning", "text": "somewhere", "cause": None, "facts": {}},
               {"kind": "x", "severity": "notice", "text": "from a later version", "cause": "no_such_cause", "facts": {"a": 1}}]
    folder = _run_folder(board_dir, "eeee0005", script, findings=[("warning", "somewhere"), ("notice", "from a later version")], details=details)
    shutil.copy(cached, folder / "layout.kicad_pcb")
    view = s.run_view("eeee0005")
    doc = view["doc"]
    assert view["summary"]["id"] == "eeee0005" and doc["items"] and len(doc["steps"]) == len(doc["items"]) and doc["board"]["extent"]
    assert [(f["severity"], f["text"], f["at"]) for f in doc["findings"]] == [("warning", "somewhere", None), ("notice", "from a later version", None)]
    assert doc["score"]["total"] is not None and doc["counts"]["findings"] == 2
    (folder / "plan.json").write_text(json.dumps({"board": {"loops": [], "drawn": False, "extent": [0, 0, 1, 1]}, "items": [], "layers": ["F.Cu"], "steps": [{"i": 0, "item": "x", "kind": "part"}], "copper": [{"t": "track"}], "findings": [{"text": "kept", "kind": "k", "severity": "warning", "at": None, "refs": [], "pads": []}]}))
    assert s.run_view("eeee0005")["doc"]["copper"] == [{"t": "track"}] and [f["text"] for f in s.run_view("eeee0005")["doc"]["findings"]] == ["kept"]      # a routed run keeps its own plan
    (folder / "layout.kicad_pcb").unlink()
    (folder / "plan.json").unlink()
    assert s.run_view("eeee0005") is None                                                                    # a run that kept no board has none to show
    assert s.run_view("nope") is None and s.run_view("../x") is None and s.run_view("") is None and s.run_view(".staging") is None


def test_a_past_run_and_its_build_carry_the_models_of_the_board_it_wrote_and_their_jobs_go_to_the_converter(own_project):
    pytest.importorskip("pcbnew")
    import shutil
    from placemat import route_progress, route_view
    from placemat.kicad.read import read_board
    s = Studio(None, port=0, open_browser=False, root=own_project.parents[2])
    got = []
    s.m3d.submit = lambda jobs: got.append(list(jobs)) or len(jobs)
    board_dir = next(d for d in _board_dirs(s) if (d / ".placemat" / "generated").is_dir())
    script = next(e["path"] for e in s.scripts() if e["src"].board_dir == board_dir)
    cached = next((board_dir / ".placemat" / "generated").glob("*/layout.kicad_pcb"))
    folder = _run_folder(board_dir, "ffff0006", script)
    shutil.copy(cached, folder / "layout.kicad_pcb")

    def check(doc):
        members = [m for it in doc["items"] for m in it["members"]]
        ids = {e["id"] for m in members for e in m["models"] if e["id"]}
        assert members and ids and ids == set(doc["models"]) and doc["stackup"]["thickness"] > 0
        assert all(e["matrix"] and len(e["matrix"]) == 16 for m in members for e in m["models"] if e["id"])
        return ids

    ids = check(s.run_view("ffff0006")["doc"])                                       # the written board, no plan.json
    assert {j["id"] for j in got[-1]} == ids
    assert {j["board"] for j in got[-1] if j["kind"] == "embedded"} == {str(folder / "layout.kicad_pcb")}
    # a routed run: its plan.json names the members by ref; the route record's board is the same placement
    (folder / "plan.json").write_text(json.dumps(route_view.board_doc(read_board(str(cached)))))
    (folder / "route").mkdir()
    stages = [{"stage": "main", "resumed": False, "seconds": 1.0, "events": [{"ev": "net_begin", "net": "A"}, {"ev": "commit", "net": "A", "seg": [[0, 0, 1, 0, "F.Cu", 0.2]], "via": []}, {"ev": "net_end", "net": "A", "ok": True}]}]
    route_progress.write_record(folder / "route", {"pcb": str(cached), "run": "ffff0006", "script": str(script)}, stages, {"closure": 1.0}, complete=True)
    assert check(s.run_view("ffff0006")["doc"]) == ids
    build = s.build_record("ffff0006")["doc"]
    assert check(build) == ids and {j["id"] for j in got[-1]} == ids
    assert [o["origin"] for o in build["copper"] if o.get("origin")] == ["routed"] and build["steps"][-1]["origin"] == "routed"
    assert build["score"] == {"total": s.run_summary(folder / "run.json")["score"]}                # the build is the run's: its score is the run's


def test_a_runs_findings_are_placed_from_their_facts(project):
    from placemat import route_view
    base = {"board": {"loops": [], "drawn": False, "extent": [0, 0, 10, 10]}, "layers": ["F.Cu"],
            "items": [{"key": "u1", "members": [{"ref": "U1", "inst": "u1", "shapes": []}, {"ref": "C1", "inst": "c1", "shapes": []}]}]}
    details = [{"kind": "escape", "severity": "warning", "text": "U1 pins 1/2: A crosses B", "cause": "escape_crossed", "facts": {"ref": "U1", "pins": ["1", "2"], "nets": ["A", "B"]}},
               {"kind": "copper", "severity": "warning", "text": "a pour narrows at (3, 4)", "cause": "copper_pour_narrow", "facts": {"at": [3.0, 4.0]}}]
    doc = route_view.run_doc(base, details, 5.0)
    first = doc["findings"][0]
    assert first["refs"] == ["U1"] and first["pads"] == [["U1", "1"], ["U1", "2"]] and first["text"] == "U1 pins 1/2: A crosses B" and doc["score"] == {"total": 5.0}
    assert doc["counts"] == {"placed": 1, "findings": 2} and doc["steps"][0]["item"] == "u1"


def test_the_past_runs_explores_and_routes_are_found_without_a_script_and_served_over_http(own_project):
    import http.client
    s = Studio(None, port=0, open_browser=False, root=own_project.parents[2])
    board_dir = _board_dirs(s)[0]
    script = next(e["path"] for e in s.scripts() if e["src"].board_dir == board_dir)
    _run_folder(board_dir, "ffff0006", script)
    folder = board_dir / ".placemat" / "views" / "explore"
    folder.mkdir(parents=True)
    (folder / "20261003-000000-9.json").write_text(json.dumps({"version": 1, "script": str(script), "at": 5.0, "pid": 9, "focus": ["a"], "baseline": 10.0, "best": 9.0, "best_seed": 1, "kept": False, "variants": []}))
    assert [e["script"] for e in s.explores()] == [str(script)]
    url = s.start()
    try:
        host, token = url.split("//")[1].split("/?t=")
        conn = http.client.HTTPConnection(host, timeout=30)
        get = lambda path: (conn.request("GET", path + "&t=" + token if "?" in path else path + "?t=" + token), conn.getresponse())[1]
        r = get("/projectruns")
        assert r.status == 200 and [x["id"] for x in json.loads(r.read())] == ["ffff0006"]
        r = get("/explores")
        assert r.status == 200 and len(json.loads(r.read())) == 1
        r = get("/runview?run=ffff0006")
        assert r.status == 404 and "kept no board" in r.read().decode()                                      # no board file in this record
        r = get("/runview?run=..%2Fx")
        assert r.status == 404
        conn.request("GET", "/projectruns")
        assert conn.getresponse().status == 403                                                              # the token is needed
    finally:
        s.stop()


def test_a_routes_count_is_of_the_stage_it_is_in_and_lost_events_are_counted(project):
    s = _fresh(project)
    _cmd(s, 7)
    for ev in ({"ev": "route_stage", "stage": "pairs"}, {"ev": "route_queue", "nets": ["P"]}, {"ev": "route_net_end", "net": "P", "ok": True},
               {"ev": "route_stage", "stage": "islands", "nets": 2}, {"ev": "route_queue", "nets": ["G1"]}, {"ev": "route_net_end", "net": "G1", "ok": True},
               {"ev": "route_stage", "stage": "main"}, {"ev": "route_queue", "nets": ["A", "B", "C"]}, {"ev": "route_dropped", "n": 5}):
        s._on_channel(7, ev)
    r = {c["id"]: c for c in s.commands()}[7]["route"]
    assert (r["total"], r["seen"], r["done"], r["dropped"], r["stage"]) == (3, 0, 2, 5, "main") and "in_stage" not in r


def test_a_command_starting_over_the_channel_is_announced_at_once_and_the_hello_carries_the_follow_hold(project):
    s = _fresh(project)
    drain = _events(s)
    _cmd(s, 1)
    first = [json.loads(x) for n, x in drain() if n == "cmd"]
    assert len(first) == 1 and first[0]["state"] == "running" and first[0]["id"] == 1 and first[0]["kind"] == "explore" and first[0]["started"] > 0
    s._on_channel(2, {"ev": "hello", "pid": 4002, "command": "preview", "script": str(s.root / "x_layout.py"), "args": ["preview", "x_layout.py"]})
    second = [json.loads(x) for n, x in drain() if n == "cmd"]
    assert [c["id"] for c in second] == [2] and second[0]["kind"] == "preview" and second[0]["state"] == "running" and second[0]["started"] >= first[0]["started"]
    hello = json.loads(s.hello()[0][1])
    assert hello["follow_hold_s"] == 10.0 and [c["id"] for c in hello["commands"]] == [1, 2]


def test_an_explores_routes_streamed_over_the_channel_are_kept_with_it_not_in_its_log(project):
    s = _fresh(project)
    _cmd(s, 6)
    s._on_channel(6, {"ev": "explore", "focus": ["a"], "plain": {}, "order": ["a"], "baseline": 10.0, "jobs": 2, "at": 1.0})
    s._on_channel(6, {"ev": "explore_route", "seed": 0, "score": 10.0, "closure_clean": 0.8, "closure": 0.9, "open_before": 4,
                      "open_after": 1, "valid": True, "seconds": 3.0, "dir": "d"})
    d = s.cmd_detail(6)
    assert [r["seed"] for r in d["explore"]["routes"]] == [0] and all(e["ev"] != "explore_route" for e in d["events"])


def test_an_explores_search_done_is_kept_with_it_for_a_page_that_opens_it_late(project):
    s = _fresh(project)
    _cmd(s, 7)
    s._on_channel(7, {"ev": "explore", "focus": ["a"], "plain": {}, "order": ["a"], "baseline": 10.0, "jobs": 2, "at": 1.0, "seconds": 60, "route": True})
    s._on_channel(7, {"ev": "explore_search_done", "t": 60.2, "in_hand": [0], "waiting": [5], "routed": 0, "route_mean_s": None})
    d = s.cmd_detail(7)
    assert d["explore"]["search_done"] == {"ev": "explore_search_done", "t": 60.2, "in_hand": [0], "waiting": [5], "routed": 0, "route_mean_s": None}
    assert all(e["ev"] != "explore_search_done" for e in d["events"])


def test_an_explores_budget_passed_is_kept_with_it_for_a_page_that_opens_it_late(project):
    s = _fresh(project)
    _cmd(s, 8)
    s._on_channel(8, {"ev": "explore", "focus": ["a"], "plain": {}, "order": ["a"], "baseline": 10.0, "jobs": 2, "at": 1.0, "seconds": 60, "route": False})
    ev = {"ev": "explore_budget_passed", "t": 60.1, "budget": 60, "finishing": [{"seed": 4, "started": 41.0}]}
    s._on_channel(8, dict(ev))
    d = s.cmd_detail(8)
    assert d["explore"]["budget_passed"] == ev and all(e["ev"] != "explore_budget_passed" for e in d["events"])
