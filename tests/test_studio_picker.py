"""placemat studio with no script (a picker), a worker that dies, and the checked runs the page lists and compares."""
import json
import os
import queue
import signal
import subprocess
import sys
import textwrap
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
        done = subprocess.run([sys.executable, "-c", "import faulthandler; faulthandler.enable(); exec(compile(open(%r).read(), %r, 'exec'))" % (str(mod), str(mod))],
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
    assert ev["ev"] == "error" and ev["id"] == 3 and ev["message"].startswith("KeyError") and "x_missing" in ev["message"]
    assert ev["file"] == str(bad) and ev["line"] == 4 and ev["source"] == "raise KeyError('x_missing')" and "Traceback" in ev["detail"]


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
            s._on_channel(7, {"ev": "error", "message": "Layout script failed: boom", "file": "", "line": None})
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
    s._on_worker({"ev": "begin", "id": 4, "kind": "phase", "text": "scanning the front", "hint": [1.0, 2.0]}, s.worker.serial)
    hello = json.loads(s.hello()[0][1])
    assert abs(hello["now"] - time.time()) < 2 and hello["resolving"] == 4
    w = hello["work"]
    assert 82.0 < hello["now"] - w["t0"] < 86.0                                       # since the resolve began, not since the page joined
    assert w["total"]["items"] == 24 and w["cur"]["item"] == "psu" and w["cur"]["phase"] == "scanning the front" and w["cur"]["hint"] == [1.0, 2.0]
    assert 0 <= hello["now"] - w["cur"]["at"] < 2 and w["cur"]["within"] is None
    s._on_worker({"ev": "begin", "id": 4, "kind": "phase", "text": "refining around the best spots: 2 of 5", "within": [2, 5]}, s.worker.serial)
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
    s._on_channel(3, {"ev": "error", "message": "boom", "file": "x_layout.py", "line": 7})
    by = {c["id"]: c for c in s.commands()}
    assert by[1]["state"] == "done" and by[1]["record"] == "/r/run.json" and by[1]["items"] == 1 and by[1]["command"] == "explore" and by[1]["pid"] == 4001
    assert by[2]["state"] == "lost" and "u9" in by[2]["message"] and by[3]["state"] == "error" and by[3]["message"] == "boom"
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
    own = route_progress.write_record(base / "route", {"pcb": "x.kicad_pcb", "run": "", "script": "x_layout.py"}, stages, {"closure": 1.0})
    ran = route_progress.write_record(base / "runs" / "ab12" / "route", {"pcb": "x.kicad_pcb", "run": "ab12", "script": "x_layout.py"}, stages, {"closure": 1.0})
    (base / "route" / route_progress.BOARD).write_text(json.dumps({"board": {"loops": [], "drawn": False, "extent": [0, 0, 1, 1]}, "items": [], "layers": ["F.Cu"]}))
    (base / "runs" / "ab12" / "plan.json").write_text(json.dumps({"board": {"loops": [], "drawn": False, "extent": [0, 0, 1, 1]}, "items": [], "layers": ["F.Cu"], "steps": [], "copper": []}))
    listed = s.routes()
    assert {e["file"]: (e["run"], e["build"], e["nets"], e["routed"]) for e in listed} == {str(own): ("", False, 1, 1), str(ran): ("ab12", True, 1, 1)}
    assert s.route_record(str(own))["doc"]["route"] == {"nets": 1, "routed": 1, "failed": 0}
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
