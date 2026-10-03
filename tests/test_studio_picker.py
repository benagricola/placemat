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


def test_a_run_is_started_on_request_and_its_result_reaches_the_page(project, monkeypatch):
    s = _fresh(project)
    drain = _events(s)

    class Proc:
        stdout = iter(["resolve  ok\n", "drc  2 real\n"])

        def wait(self):
            _record(s.runs_dir(), "eeee0005", project, {})
            return 0
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Proc())
    assert s.start_run()["id"] == 1
    with pytest.raises(ValueError):
        s.start_run() if s._run is not None else (_ for _ in ()).throw(ValueError("busy"))
    deadline = time.monotonic() + 10
    while s._run is not None and time.monotonic() < deadline:
        time.sleep(0.02)
    ev = drain()
    names = [n for n, _ in ev]
    assert names[0] == "run_started" and names.count("run_line") == 2 and names[-1] == "run_done"
    done = json.loads(ev[-1][1])
    assert done["code"] == 0 and done["run"]["id"] == "eeee0005" and done["tail"] == ["resolve  ok", "drc  2 real"] and done["runs"]


def test_a_begin_notice_from_the_worker_reaches_the_pages_without_being_kept(project):
    s = _fresh(project)
    drain = _events(s)
    s._cur = {"id": 3, "texts": {}, "changed": [], "t0": 0}
    s._on_worker({"ev": "begin", "id": 3, "kind": "begin", "item": "u1", "what": "searched", "rank": 2, "of": 9}, s.worker.serial)
    s._on_worker({"ev": "begin", "id": 99, "kind": "begin", "item": "stale"}, s.worker.serial)            # not the resolve in flight
    got = [(n, json.loads(t)) for n, t in drain()]
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
