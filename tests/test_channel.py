"""The live channel: a command tells the studios of its project what it does, and is never in their way."""
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


class Fake:
    """A studio's socket that collects what arrives."""

    def __init__(self, root, pid=None):
        self.events, self.lock = [], threading.Lock()
        self.listener = channel.Listener(root, self.on_event, address="http://127.0.0.1:1/", script="x_layout.py")
        if pid is not None:
            self.listener.pid = pid                                     # a second studio in one project needs a pid of its own
        self.listener.start()

    def on_event(self, cid, ev):
        with self.lock:
            self.events.append((cid, ev))

    def names(self):
        with self.lock:
            return [e["ev"] for _, e in self.events]

    def wait(self, name, timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if name in self.names():
                return
            time.sleep(0.02)
        raise AssertionError("no %r; saw %s" % (name, self.names()[-12:]))

    def of(self, name):
        with self.lock:
            return [e for _, e in self.events if e["ev"] == name]


def test_a_real_resolve_reaches_a_studio_as_its_steps_phases_and_finished_plan(tmp_path):
    fake = Fake(tmp_path)
    try:
        script = tmp_path / "x_layout.py"
        script.write_text("")
        b = _board()
        b._script = script
        plan = b.resolve()
        channel.finish(tmp_path / "run.json")
        fake.wait("done")
        names = fake.names()
        assert names[0] == "hello" and names.index("resolve") < names.index("board") < names.index("item") < names.index("plan") < names.index("done")
        hello = fake.of("hello")[0]
        assert hello["pid"] == os.getpid() and hello["script"] == str(script) and isinstance(hello["started"], float)
        items = fake.of("item")
        assert {i["item"]["key"] for i in items} >= {s.item for s in plan.steps if s.placement is not None and s.kind == "part"}
        assert any(e.get("ops") for e in items) and any(e["kind"] == "total" for e in fake.of("begin"))
        doc = fake.of("plan")[0]["doc"]
        assert [i["key"] for i in doc["items"]] and doc["steps"] and "copper" in doc
        assert fake.of("done")[0]["record"].endswith("run.json")
    finally:
        fake.listener.stop()


def test_with_no_studio_a_command_looks_once_starts_nothing_and_resolves_as_before(tmp_path):
    script = tmp_path / "x_layout.py"
    threads = threading.active_count()
    assert channel.reporter(script) is None and channel.reporter(script) is None
    b = _board()
    b._script = script
    plan = b.resolve()
    assert threading.active_count() == threads and channel.current() is None
    assert [(s.item, s.placement) for s in _board().resolve().steps] == [(s.item, s.placement) for s in plan.steps]


def test_a_studio_that_does_not_read_costs_the_command_nothing_events_are_dropped(tmp_path):
    d = tmp_path / ".placemat" / "studio"
    d.mkdir(parents=True)
    path = d / "stuck.sock"
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    server.listen(1)                                                    # accepts nothing: the buffer fills and the sender blocks
    (d / "stuck.json").write_text(json.dumps({"pid": os.getpid(), "socket": str(path)}))
    rep = channel.reporter(tmp_path / "x_layout.py")
    assert rep is not None
    t0 = time.perf_counter()
    for n in range(20000):
        rep.send({"ev": "item", "pad": "x" * 2000, "n": n})
    spent = time.perf_counter() - t0
    assert spent < 2.0 and rep.dropped > 0                             # no waiting: what did not fit was dropped
    server.close()


def test_a_studio_that_goes_away_is_dropped_silently_and_the_command_goes_on(tmp_path):
    fake = Fake(tmp_path)
    rep = channel.reporter(tmp_path / "x_layout.py")
    rep.send({"ev": "begin", "kind": "begin", "item": "a"})
    fake.wait("begin")
    fake.listener.stop()
    for n in range(300):
        rep.send({"ev": "begin", "kind": "begin", "item": "b", "n": n})
        time.sleep(0.001)
    rep.finish()                                                        # no error, no hang


def test_every_studio_of_the_project_is_told_and_a_dead_ones_files_are_cleaned_away(tmp_path):
    one, two = Fake(tmp_path), Fake(tmp_path, pid=1)                    # pid 1 is always alive
    d = tmp_path / ".placemat" / "studio"
    (d / "999999999.json").write_text(json.dumps({"pid": 999999999, "socket": str(d / "999999999.sock")}))
    (d / "999999999.sock").write_text("")
    try:
        rep = channel.reporter(tmp_path / "x_layout.py")
        assert not (d / "999999999.json").exists() and not (d / "999999999.sock").exists()     # found dead, removed
        rep.send({"ev": "begin", "kind": "begin", "item": "a"})
        one.wait("begin")
        two.wait("begin")                                               # both are told
    finally:
        one.listener.stop()
        two.listener.stop()
    assert not list(d.glob("*.json"))


def test_a_listener_removes_its_socket_and_entry_when_it_stops_and_keeps_a_short_socket_path(tmp_path):
    deep = tmp_path
    for part in ("a" * 40, "b" * 40, "c" * 40):
        deep = deep / part
    fake = Fake(deep)
    entry = json.loads((deep / ".placemat" / "studio" / ("%d.json" % os.getpid())).read_text())
    assert len(entry["socket"].encode()) <= 100 and os.path.exists(entry["socket"])               # too long a path moves to a short one
    fake.listener.stop()
    assert not os.path.exists(entry["socket"]) and not (deep / ".placemat" / "studio" / ("%d.json" % os.getpid())).exists()


def test_an_explore_tells_the_studio_the_plain_placement_each_variant_and_the_end(tmp_path):
    fake = Fake(tmp_path)
    try:
        script = tmp_path / "x_layout.py"
        script.write_text("")
        channel.reporter(script)
        r = explore(ex._make, ex.FOCUS, seconds=60, jobs=2, seeds=range(1, 7))
        channel.finish()
        fake.wait("done")
        start = fake.of("explore")[0]
        assert start["focus"] == sorted(ex.FOCUS) and set(start["plain"]) == set(ex.FOCUS) and start["jobs"] == 2
        variants = fake.of("variant")
        assert sorted(v["seed"] for v in variants) == [1, 2, 3, 4, 5, 6] and all(set(v["placements"]) == set(ex.FOCUS) and v["order"] for v in variants)
        assert min(v["score"] for v in variants + [{"score": start["baseline"]}]) == r.best
        assert [v["seed"] for v in r.variants][0] == 0 and len(r.variants) == r.tried          # the result keeps them, the plain one first
    finally:
        fake.listener.stop()
