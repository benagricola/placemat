"""The live channel: a command owns a socket and tells any reader what it does, and is never in a reader's way."""
import io
import json
import os
import socket
import threading
import time

import pytest

from placemat import channel
from placemat.explore import explore
from tests import test_explore_search as ex
from tests.test_preview_json import _board


@pytest.fixture(autouse=True)
def _fresh_channel():
    channel.reset()
    yield
    channel.reset()


class Reader:
    """A reader of a command's socket that collects what arrives."""

    def __init__(self, entry):
        self.events, self.lock = [], threading.Lock()
        self.thread = threading.Thread(target=self._run, args=(entry,), daemon=True)
        self.thread.start()

    def _run(self, entry):
        for ev in channel.follow(entry):
            with self.lock:
                self.events.append(ev)

    def names(self):
        with self.lock:
            return [e["ev"] for e in self.events]

    def wait(self, name, timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if name in self.names():
                return
            time.sleep(0.02)
        raise AssertionError("no %r; saw %s" % (name, self.names()[-12:]))

    def of(self, name):
        with self.lock:
            return [e for e in self.events if e["ev"] == name]


def _start(tmp_path, name="x_layout.py"):
    script = tmp_path / name
    script.write_text("")
    rep = channel.reporter(script)
    assert rep is not None
    live, dead = channel.scan(channel.sockets_dir(tmp_path))
    assert not dead and len(live) == 1
    return script, rep, live[0]


def test_a_command_listens_from_its_first_resolve_and_a_reader_gets_hello_then_the_steps_and_the_plan(tmp_path):
    script = tmp_path / "x_layout.py"
    script.write_text("")
    b = _board()
    b._script = script
    assert channel.current() is None
    plan = b.resolve()
    live, _ = channel.scan(channel.sockets_dir(tmp_path))
    assert [e["pid"] for e in live] == [os.getpid()] and live[0]["script"] == str(script)
    reader = Reader(live[0])
    reader.wait("plan")                                                 # connected after the resolve: the catch-up has it all
    names = reader.names()
    assert names[0] == "hello" and names.index("resolve") < names.index("board") < names.index("item") < names.index("plan")
    items = reader.of("item")
    assert {i["item"]["key"] for i in items} >= {s.item for s in plan.steps if s.placement is not None and s.kind == "part"}
    assert any(e["kind"] == "total" for e in reader.of("begin")) and reader.of("plan")[0]["doc"]["steps"]
    channel.finish(tmp_path / "run.json")
    reader.wait("done")
    assert reader.of("done")[0]["record"].endswith("run.json")


def test_a_reader_that_connects_mid_run_is_caught_up_then_given_the_live_events(tmp_path):
    _, rep, entry = _start(tmp_path)
    rep.send({"ev": "board", "w": 1})
    rep.send({"ev": "item", "item": {"key": "u1"}})
    reader = Reader(entry)
    reader.wait("item")
    rep.send({"ev": "item", "item": {"key": "u2"}})
    deadline = time.monotonic() + 10
    while len(reader.of("item")) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert [i["item"]["key"] for i in reader.of("item")] == ["u1", "u2"] and reader.names()[:2] == ["hello", "board"]
    rep.send({"ev": "resolve", "n": 2})                                 # a new resolve forgets the board the catch-up held
    late = Reader(entry)
    late.wait("resolve")
    assert "item" not in late.names() and late.names()[0] == "hello"


def test_with_no_script_a_command_makes_no_socket_and_no_file(tmp_path):
    ours = lambda: {t for t in threading.enumerate() if t.name.startswith("placemat-channel")}      # not the process's other threads: a parallel worker has its own
    before = ours()
    assert channel.reporter(None) is None
    b = _board()
    plan = b.resolve()
    assert ours() == before and channel.current() is None and not (tmp_path / ".placemat").exists()
    assert [(s.item, s.placement) for s in _board().resolve().steps] == [(s.item, s.placement) for s in plan.steps]


def test_a_reader_that_does_not_read_costs_the_command_nothing_events_are_dropped(tmp_path):
    _, rep, entry = _start(tmp_path)
    stuck = socket.socket(socket.AF_UNIX)
    stuck.connect(entry["socket"])                                      # connects, never reads
    time.sleep(0.2)
    t0 = time.perf_counter()
    for n in range(20000):
        rep.send({"ev": "item", "pad": "x" * 2000, "n": n})
    spent = time.perf_counter() - t0
    assert spent < 3.0 and rep.dropped > 0                              # no waiting: what did not fit was dropped
    stuck.close()


def test_a_reader_that_goes_away_is_dropped_and_the_command_goes_on(tmp_path):
    _, rep, entry = _start(tmp_path)
    s = socket.socket(socket.AF_UNIX)
    s.connect(entry["socket"])
    time.sleep(0.2)
    assert len(rep.readers) == 1
    s.close()
    for n in range(300):
        rep.send({"ev": "begin", "kind": "begin", "item": "b", "n": n})
        time.sleep(0.001)
    deadline = time.monotonic() + 5
    while rep.readers and time.monotonic() < deadline:
        rep.send({"ev": "begin", "kind": "begin", "item": "c"})
        time.sleep(0.01)
    assert not rep.readers
    rep.finish()                                                        # no error, no hang


def test_the_socket_and_entry_go_when_the_command_ends_and_a_dead_ones_are_cleaned_by_a_reader(tmp_path):
    _, rep, entry = _start(tmp_path)
    assert os.path.exists(entry["socket"]) and os.path.exists(entry["_file"])
    rep.finish()
    assert not os.path.exists(entry["socket"]) and not os.path.exists(entry["_file"])
    d = channel.sockets_dir(tmp_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "999999999.json").write_text(json.dumps({"pid": 999999999, "socket": str(d / "999999999.sock")}))
    (d / "999999999.sock").write_text("")
    live, dead = channel.scan(d)
    assert not live and [e["pid"] for e in dead] == [999999999]
    channel.clean(dead[0])
    assert not list(d.iterdir())


def test_a_socket_path_too_long_for_an_address_moves_to_a_short_one_named_in_the_entry(tmp_path):
    deep = tmp_path
    for part in ("a" * 40, "b" * 40, "c" * 40):
        deep = deep / part
    deep.mkdir(parents=True)
    _, rep, entry = _start(deep)
    assert len(entry["socket"].encode()) <= 100 and os.path.exists(entry["socket"])
    reader = Reader(entry)
    reader.wait("hello")


def test_the_events_are_mirrored_in_short_form_and_the_next_command_deletes_a_dead_ones_file(tmp_path):
    script, rep, entry = _start(tmp_path)
    progress = channel.sockets_dir(tmp_path).parent / "views" / "x" / "nothing"
    path = rep.progress_path
    rep.send({"ev": "begin", "kind": "total", "n": 5})
    notes = [{"kind": "lock_held"}, {"kind": "slid", "mm": 0.5, "units": "mm"}]
    rep.send({"ev": "item", "item": {"key": "u1", "kind": "part", "placed": True, "notes": notes}, "ops": [1] * 100})
    rep.send({"ev": "plan", "doc": {"items": [1, 2], "findings": [3], "copper": []}})
    rep.send({"ev": "begin", "kind": "phase", "what": "scan"})          # a phase is not kept
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    assert [x["ev"] for x in lines] == ["hello", "begin", "item", "plan"] and lines[0]["pid"] == os.getpid()
    assert lines[2]["notes"] == notes and "ops" not in lines[2] and lines[3] == {"ev": "plan", "items": 2, "findings": 1, "copper": 0}
    assert lines[0]["format"] == channel.FORMAT
    rep.finish()
    assert path.exists() and not progress.exists()                      # a command that ended leaves its file until the next one
    # the next command of the script, the first one's pid being gone: its file is deleted, the current one kept
    first = json.loads(path.read_text().splitlines()[0])
    path.unlink()
    path = path.with_name("progress-999999999.jsonl")
    path.write_text(json.dumps(dict(first, pid=999999999)) + "\n")
    other = path.with_name("progress-1.jsonl")
    other.write_text(json.dumps(dict(first, pid=1, script=str(tmp_path / "y_layout.py"))) + "\n")   # another script's: kept
    channel.reset()
    _, rep2, _ = _start(tmp_path)
    assert not path.exists() and other.exists() and rep2.progress_path.exists()


def test_a_run_keeps_its_crash_trail_in_its_folder(tmp_path):
    run = tmp_path / ".placemat" / "runs" / "abc"
    run.mkdir(parents=True)
    channel.hint_progress(run / "progress.jsonl")
    _, rep, entry = _start(tmp_path)
    assert (run / "progress.jsonl").exists() and entry["progress"] == str(run / "progress.jsonl")


def test_the_watcher_follows_a_live_command_and_shows_a_dead_one_from_its_progress_file(tmp_path):
    script, rep, entry = _start(tmp_path)
    seen, dead, lock = [], [], threading.Lock()
    w = channel.Watcher(tmp_path, lambda cid, ev: seen.append((cid, ev)), lambda cid, e, events: dead.append((e, events)), interval=0.1)
    w.start()
    try:
        rep.send({"ev": "item", "item": {"key": "u1", "kind": "part", "placed": True}})
        deadline = time.monotonic() + 10
        while not any(e["ev"] == "item" for _, e in seen) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert [e["ev"] for _, e in seen][:2] == ["hello", "item"]
        # a command that died: its entry and progress file stay, its pid is gone
        d = channel.sockets_dir(tmp_path)
        gone = tmp_path / "gone.jsonl"
        gone.write_text(json.dumps({"ev": "hello", "pid": 999999999}) + "\n" + json.dumps({"ev": "item", "key": "u7"}) + "\n")
        (d / "999999999.json").write_text(json.dumps({"pid": 999999999, "started": 1.0, "socket": str(d / "x.sock"), "progress": str(gone)}))
        deadline = time.monotonic() + 10
        while (not dead or (d / "999999999.json").exists()) and time.monotonic() < deadline:
            time.sleep(0.05)              # the watcher reports the dead command, then cleans its entry
        assert dead and [e["ev"] for e in dead[0][1]] == ["hello", "item"] and not (d / "999999999.json").exists()
    finally:
        w.stop()
    rep.finish()
    deadline = time.monotonic() + 10
    while seen[-1][1]["ev"] != "lost" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert [e["ev"] for _, e in seen][-2:] == ["done", "lost"]


def test_watch_prints_a_line_per_event_until_done_and_exits_by_how_it_ended(tmp_path):
    _, rep, entry = _start(tmp_path)
    out = io.StringIO()
    result = []
    t = threading.Thread(target=lambda: result.append(channel.watch(tmp_path, str(os.getpid()), False, out)))
    t.start()
    time.sleep(0.3)
    rep.send({"ev": "item", "item": {"key": "u1", "kind": "part", "notes": [{"kind": "lock_held"}]}})
    rep.send({"ev": "variant", "seed": 3, "score": 12.5})
    rep.finish(tmp_path / "r.json")
    t.join(10)
    lines = out.getvalue().splitlines()
    assert result == [0] and lines[0].startswith("resolve") is False and "x_layout.py" in lines[0]
    assert "u1 part: held by lock" in lines and "variant seed 3 score 12.5" in lines and lines[-1].startswith("done ")
    # an error exits 1, the events as sent with --json, a command not there 2
    channel.reset()
    _, rep, entry = _start(tmp_path)
    out = io.StringIO()
    result = []
    t = threading.Thread(target=lambda: result.append(channel.watch(tmp_path, None, True, out)))
    t.start()
    time.sleep(0.3)
    rep.error("exception", "x_layout.py", 4, type="ValueError", detail="it broke")
    rep.finish()
    t.join(10)
    events = [json.loads(x) for x in out.getvalue().splitlines()]
    assert result == [1] and events[-1] == {"ev": "error", "kind": "exception", "file": "x_layout.py", "line": 4, "type": "ValueError", "detail": "it broke"}
    assert channel.describe(events[-1]) == "error: ValueError: it broke (x_layout.py:4)"
    assert channel.watch(tmp_path, "nothing", False, io.StringIO()) == 2
    assert channel.watch(tmp_path, None, False, io.StringIO()) == 0


def test_watch_shows_a_dead_command_with_its_last_state_and_exits_2(tmp_path):
    d = channel.sockets_dir(tmp_path)
    d.mkdir(parents=True)
    log = tmp_path / "p.jsonl"
    log.write_text(json.dumps({"ev": "hello", "pid": 999999999, "command": "preview", "script": "a_layout.py"}) + "\n" +
                   json.dumps({"ev": "item", "key": "u7", "kind": "part", "notes": [{"kind": "lock_held"}]}) + "\n")
    (d / "999999999.json").write_text(json.dumps({"pid": 999999999, "label": "mine", "socket": str(d / "s.sock"), "progress": str(log)}))
    out = io.StringIO()
    assert channel.watch(tmp_path, "mine", False, out) == 2
    assert "u7 part: held by lock" in out.getvalue() and "died" in out.getvalue() and not list(d.iterdir())


def test_an_explore_tells_a_reader_the_plain_placement_each_variant_and_the_end(tmp_path):
    script, rep, entry = _start(tmp_path)
    reader = Reader(entry)
    reader.wait("hello")
    r = explore(ex._make, ex.FOCUS, seconds=60, jobs=2, seeds=range(1, 7))
    channel.finish()
    reader.wait("done")
    start = reader.of("explore")[0]
    assert start["focus"] == sorted(ex.FOCUS) and set(start["plain"]) == set(ex.FOCUS) and start["jobs"] == 2
    variants = reader.of("variant")
    assert sorted(v["seed"] for v in variants) == [1, 2, 3, 4, 5, 6] and all(set(v["placements"]) == set(ex.FOCUS) and v["order"] for v in variants)
    assert min(v["score"] for v in variants + [{"score": start["baseline"]}]) == r.best
    assert [v["seed"] for v in r.variants][0] == 0 and len(r.variants) == r.tried


def test_a_routes_events_reach_a_late_reader_in_order_and_describe_one_line_per_net(tmp_path, monkeypatch):
    script, rep, entry = _start(tmp_path)
    rep.send({"ev": "route_board", "doc": {"items": []}})
    rep.send({"ev": "route_stage", "stage": "main"})
    rep.send({"ev": "route_queue", "nets": ["A", "B"]})
    rep.send({"ev": "route_net_begin", "net": "A"})
    rep.send({"ev": "route_commit", "net": "A", "how": "route", "seg": [[0, 0, 1, 0, "F.Cu", 0.2]], "via": []})
    rep.send({"ev": "route_net_end", "net": "A", "ok": True})
    reader = Reader(entry)                                                    # attaches after all of it
    reader.wait("route_net_end")
    names = reader.names()
    assert names[0] == "hello" and names[1:] == ["route_board", "route_stage", "route_queue", "route_net_begin", "route_commit", "route_net_end"]
    assert [channel.describe(e) for e in reader.events[1:]] == ["", "route main", "route: 2 nets to route", "", "", "net A: routed"]
    monkeypatch.setattr(channel, "MAX_ROUTE_LOG", 3)
    for i in range(5):
        rep.send({"ev": "route_commit", "net": "B", "how": "route", "seg": [], "via": []})
    assert rep.route_truncated and len(rep.route_log) == 7 and rep.route_log[-1]["ev"] == "route_truncated"
    channel.finish()


def test_a_command_in_a_board_folder_and_watch_from_the_workspace_root_use_one_sockets_folder(tmp_path):
    from placemat.studio import project_root
    (tmp_path / "pcb.toml").write_text('[workspace]\nname = "w"\n')
    board = tmp_path / "boards" / "core"
    board.mkdir(parents=True)
    (board / "placemat.toml").write_text("")
    script = board / "Core_layout.py"
    script.write_text("")
    rep = channel.reporter(script)
    assert rep is not None
    assert project_root(board) == project_root(tmp_path) == project_root(tmp_path / "boards") == tmp_path.resolve()
    live, _ = channel.scan(channel.sockets_dir(project_root(tmp_path)))
    assert [e["pid"] for e in live] == [os.getpid()]
    assert not (board / ".placemat" / "sockets").exists()
    out = io.StringIO()
    t = threading.Thread(target=lambda: channel.watch(project_root(tmp_path), None, True, out), daemon=True)
    t.start()
    time.sleep(0.5)
    channel.finish()
    t.join(10)
    assert "hello" in out.getvalue()


def test_the_project_root_is_the_outermost_placemat_toml_or_workspace_above_the_board(tmp_path):
    from placemat.studio import project_root
    lone = tmp_path / "a" / "b"
    lone.mkdir(parents=True)
    assert project_root(lone) == lone.resolve()
    (tmp_path / "a" / "placemat.toml").write_text("")
    assert project_root(lone) == (tmp_path / "a").resolve()
    (tmp_path / "pcb.toml").write_text("[workspace]\n")
    assert project_root(lone) == tmp_path.resolve()


def test_watch_lines_say_what_a_step_is_doing_and_how_long_it_has_taken():
    d = channel.describe
    assert d({"ev": "begin", "kind": "total", "items": 40, "searched": 12, "copper": 3, "replay": 0}) == "40 items to place (12 searched), 3 copper declared"
    assert d({"ev": "begin", "kind": "begin", "item": "ble", "what": "searched", "rank": 3, "of": 12, "replaying": False, "n": 7}) == "ble: searching, rank 3 of 12"
    assert d({"ev": "begin", "kind": "begin", "item": "ble", "what": "decided", "rank": None, "of": None, "replaying": True, "n": 1}) == "ble: replaying"
    assert d({"ev": "begin", "kind": "phase", "stage": "refine", "within": [2, 3], "item": "ble", "elapsed_s": 12.4}) == \
        "ble: refining around the best spots, 2 of 3, 12.4 s"
    assert d({"ev": "begin", "kind": "phase", "stage": "scan", "face": "either", "radius": 12.0, "item": "ble", "elapsed_s": 0.1}) == \
        "ble: scanning the front or back, radius 12 mm, 0.1 s"
    assert d({"ev": "begin", "kind": "phase", "stage": "coarse", "item": "ble", "elapsed_s": 5.0, "firm_pass": 2}) == \
        "ble: coarse pass over the radius (firm pass 2), 5.0 s"
    assert d({"ev": "item", "item": {"key": "ble", "kind": "part", "notes": [{"kind": "required"}], "seconds": 31.25}}) == "ble part, 31.2 s: required"
    assert d({"ev": "step_warn", "item": "ble", "elapsed_s": 30.4, "bound_s": 30, "pass": "refine", "within": [2, 3]}) == \
        "ble: still working after 30.4 s (--step-warn 30 s) in the refine pass 2 of 3"
    assert d({"ev": "step_limit", "item": "ble", "elapsed_s": 60.1, "bound_s": 60, "pass": "firm pass 1"}) == \
        "ble: gave up after 60.1 s (--step-limit 60 s) in the firm pass 1"
    for line in (d({"ev": "begin", "kind": "begin", "item": "x", "what": "searched"}), d({"ev": "begin", "kind": "phase", "stage": "fine"})):
        assert "begin" not in line and "phase" not in line


def test_a_command_streams_phases_with_their_item_and_seconds_and_watch_reads_them(tmp_path, monkeypatch):
    """The resolve's own events through a command's socket, described as `placemat watch` prints them."""
    monkeypatch.delenv("PLACEMAT_CHANNEL", raising=False)
    b = _board()
    b._script = str(tmp_path / "x_layout.py")
    (tmp_path / "x_layout.py").write_text("")
    (tmp_path / "placemat.toml").write_text("")
    rep = channel.reporter(b._script)
    assert rep is not None
    reader = Reader(channel.scan(channel.sockets_dir(tmp_path))[0][0])
    time.sleep(0.2)
    b.resolve()
    time.sleep(0.5)
    rep.finish()
    lines = [channel.describe(e) for e in reader.events]
    assert not [l for l in lines if "begin begin" in l or l == "begin phase"]
    stepped = [e for e in reader.events if e.get("ev") == "begin" and e.get("kind") == "phase" and "item" in e]
    assert stepped and all(e["elapsed_s"] >= 0 and "text" not in e for e in stepped)


def test_a_progress_file_keeps_each_steps_seconds():
    ev = {"ev": "item", "item": {"key": "ble", "kind": "cell", "placed": True, "note": "", "seconds": 12.5, "first_seconds": None}}
    kept = channel.compact(ev)
    assert kept["seconds"] == 12.5 and kept["first_seconds"] is None


def test_a_command_is_named_by_what_it_is_for_the_studio():
    assert channel.kind_of("preview", ["preview", "x.py"]) == "preview"
    assert channel.kind_of("run", ["run", "x.py", "--route"]) == "run"                      # a run that routes is still a full run
    assert channel.kind_of("run", ["run", "x.py", "--explore", "60"]) == "explore"
    assert channel.kind_of("preview", ["preview", "x.py", "--explore=30"]) == "explore"
    assert channel.kind_of("run", ["run", "x.py"], explored=True) == "explore"             # explore events say it is one whatever its arguments were
    assert channel.kind_of("route", ["route", "x.pcb"]) == "route" and channel.kind_of("apply", None) == "apply" and channel.kind_of("", ()) == ""
