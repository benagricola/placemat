"""A route that is stopped or fails keeps the phases it finished in its work folder, and a rerun with the same inputs
skips them. The router is a stand-in script here (it copies its board and logs the call): what is tested is placemat's
phase handling, not routing. The rig routes two phases: the pour net GND alone, then the rest."""
import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from placemat.kicad import route_state
from placemat.kicad.route_state import RouteState
from tests.phase_helpers import fake_capabilities, phases

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / "fixtures/fairing/keep_out/modules/usb5v/generated/Usb5v"

FAKE = textwrap.dedent('''
    import json, os, shutil, sys, time
    a = sys.argv[1:]
    pcb_in, pcb_out = a[0], a[1]
    nets = []
    for x in a[a.index("--nets") + 1:] if "--nets" in a else ():
        if x.startswith("--"):
            break
        nets.append(x)
    # the pour phase's plane repair names its net; its tracks for pads still apart are --connections tasks
    kind = "tasks" if "--connections" in a else "main" if "*" in nets else "island"
    with open(os.environ["FAKE_ROUTER_LOG"], "a") as f:
        f.write(kind + "\\n")
    mode = os.environ.get("FAKE_ROUTER_" + kind.upper(), "")
    if mode == "fail":
        sys.exit(3)
    if mode == "hang":
        with open(os.environ["FAKE_ROUTER_PID"], "w") as f:
            f.write(str(os.getpid()))
        time.sleep(600)
    shutil.copy(pcb_in, pcb_out)
    if "--json-out" in a:
        doc = {}
        if "--connections" in a:
            doc["connections"] = [dict(t, status="routed", joined=True, length_mm=1.0, min_width_mm=t["widths"],
                                       layers=list(t["widths"]), evidence=None)
                                  for t in json.load(open(a[a.index("--connections") + 1]))]
        open(a[a.index("--json-out") + 1], "w").write(json.dumps(doc))
''')


# ---------------------------------------------------------------- the state file, alone
def test_a_finished_phase_is_found_by_its_digest_and_only_by_it(tmp_path):
    s = RouteState(tmp_path)
    s.set_order(["legs", "signals"])
    s.record("legs", "d1", {"board": "p0_0.kicad_pcb", "seconds": 2.0})
    again = RouteState(tmp_path)
    again.set_order(["legs", "signals"])
    assert again.result("legs", "d1") == {"board": "p0_0.kicad_pcb", "seconds": 2.0}
    assert again.result("legs", "other") is None and again.result("signals", "d1") is None


def test_dropping_a_phase_drops_it_its_files_and_every_phase_after_it(tmp_path):
    s = RouteState(tmp_path)
    s.set_order(["a", "b", "c"])
    for i, name in enumerate("abc"):
        (tmp_path / ("p%d_0.kicad_pcb" % i)).write_text("x")
        s.record(name, "d" + name, {})
    (tmp_path / "routed.kicad_pcb").write_text("x")
    s.drop_from("b")
    assert s.finished == ["a"] and (tmp_path / "p0_0.kicad_pcb").exists()
    assert not (tmp_path / "p1_0.kicad_pcb").exists() and not (tmp_path / "p2_0.kicad_pcb").exists()
    assert not (tmp_path / "routed.kicad_pcb").exists()


def test_a_reordered_or_renamed_phase_list_keeps_only_the_common_head(tmp_path):
    s = RouteState(tmp_path)
    s.set_order(["a", "b", "c"])
    for name in "abc":
        s.record(name, "d", {})
    again = RouteState(tmp_path)
    again.set_order(["a", "c", "b"])
    assert again.finished == ["a"]


def test_the_same_order_again_leaves_every_file_in_place(tmp_path):
    s = RouteState(tmp_path)
    s.set_order(["a", "b"])
    s.record("a", "d", {})
    names = ["p0_0.kicad_pcb", "p1_0.kicad_pcb", "routed.kicad_pcb", "router_out.kicad_pcb", "pairs.kicad_pcb"]
    for n in names:
        (tmp_path / n).write_text("x")
    RouteState(tmp_path).set_order(["a", "b"])
    assert all((tmp_path / n).exists() for n in names)


def test_a_state_file_of_the_old_stages_is_no_state(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"version": 1, "stages": {"pairs": {"digest": "d", "result": {}}}}))
    s = RouteState(tmp_path)
    s.set_order(["pairs"])
    assert s.finished == []


def test_without_resume_everything_is_dropped(tmp_path):
    (tmp_path / "p0_0.kicad_pcb").write_text("x")
    RouteState(tmp_path, resume=False)
    assert not (tmp_path / "p0_0.kicad_pcb").exists()


def test_a_state_file_that_is_not_readable_is_no_state(tmp_path):
    (tmp_path / "state.json").write_text("{not json")
    assert RouteState(tmp_path).finished == []
    (tmp_path / "state.json").write_text(json.dumps({"version": 99, "phases": {"a": {"digest": "d"}}}))
    s = RouteState(tmp_path)
    s.set_order(["a"])
    assert s.finished == []


# ---------------------------------------------------------------- route_board, with a stand-in router
PHASES = phases({"name": "pour", "nets": ["GND"]}, {"name": "signals"})


@pytest.fixture
def rig(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    krt = tmp_path / "krt"
    (krt / ".venv/bin").mkdir(parents=True)
    (krt / ".venv/bin/python").symlink_to(sys.executable)
    (krt / "py_router").mkdir()
    (krt / "py_router/route.py").write_text(FAKE)
    (krt / "py_router/repair_planes.py").write_text(FAKE)
    (krt / "py_router/list_nets.py").write_text("def net_clearance_map_by_id(pcb_path, nets, design_rules=None):\n    return {}\n")
    (krt / "VERSION").write_text("fake-1\n")
    fake_capabilities(krt)
    board = tmp_path / "board"
    board.mkdir()
    for ext in (".kicad_pcb", ".kicad_pro"):
        shutil.copy(BOARD / ("layout" + ext), board / ("layout" + ext))
    monkeypatch.setenv("FAKE_ROUTER_LOG", str(tmp_path / "calls"))
    monkeypatch.setenv("FAKE_ROUTER_PID", str(tmp_path / "pid"))

    class Rig:
        pcb = board / "layout.kicad_pcb"
        work = tmp_path / "route"
        calls_file = tmp_path / "calls"
        root = tmp_path

        def calls(self):
            """Each router call: the pour phase's plane repair ("island") and its task calls for the groups the
            stand-in repair leaves apart ("tasks"), and the rest call ("main")."""
            return self.calls_file.read_text().split() if self.calls_file.exists() else []

        def route(self, **kw):
            from placemat.kicad.route import route_board
            kw.setdefault("layers", ["F.Cu", "B.Cu"])
            kw.setdefault("pour_nets", {"GND"})
            kw.setdefault("exclude_nets", {"VBUS"})
            kw.setdefault("phases", PHASES)
            return route_board(self.pcb, self.work, router_dir_override=str(krt), **kw)
    return Rig()


def _finished(work, order=("pour", "signals")) -> list:
    s = RouteState(work)
    s.set_order(list(order))
    return s.finished


def test_a_rerun_with_the_same_inputs_skips_every_phase_the_first_finished(rig):
    first = rig.route()
    assert rig.calls() == ["island", "tasks", "main"] and first.resumed == []
    assert _finished(rig.work) == ["pour", "signals"]
    again = rig.route()
    assert rig.calls() == ["island", "tasks", "main"]                          # no router ran
    assert again.resumed == ["pour", "signals"] and [p["reused"] for p in again.phases] == [True, True]
    assert (again.closure, again.open_after) == (first.closure, first.open_after)
    assert [p["asked"] for p in again.phases] == [p["asked"] for p in first.phases]
    assert Path(again.routed_pcb).exists() and abs(again.seconds - first.seconds) < 0.5


def test_a_rest_phase_that_fails_leaves_the_pour_phase_done_and_the_rerun_does_only_the_rest(rig, monkeypatch):
    monkeypatch.setenv("FAKE_ROUTER_MAIN", "fail")
    with pytest.raises(RuntimeError, match="router exited 3"):
        rig.route()
    assert rig.calls() == ["island", "tasks", "main"]
    assert _finished(rig.work) == ["pour"]
    assert (rig.work / "p0_0.kicad_pcb").exists()
    monkeypatch.delenv("FAKE_ROUTER_MAIN")
    done = rig.route()
    assert rig.calls() == ["island", "tasks", "main", "main"] and done.resumed == ["pour"]


def test_a_changed_input_reruns_the_phases_it_reaches(rig, monkeypatch):
    rig.route()
    # the excluded nets are in every phase's key: every phase is new
    again = rig.route(exclude_nets={"VBUS", "V3V3"})
    assert rig.calls() == ["island", "tasks", "main", "island", "tasks", "main"] and again.resumed == []
    # a changed board is new for the same reason
    text = rig.pcb.read_text()
    rig.pcb.write_text(text.replace("(version", "(version", 1) + "\n")
    third = rig.route(exclude_nets={"VBUS", "V3V3"})
    assert rig.calls() == ["island", "tasks", "main"] * 3 and third.resumed == []


def test_without_resume_every_phase_runs_again(rig):
    rig.route()
    again = rig.route(resume=False)
    assert rig.calls() == ["island", "tasks", "main"] * 2 and again.resumed == []


def test_a_pair_phase_is_kept_and_reused_like_any_other(rig, monkeypatch):
    import placemat.kicad.phase_run as phase_run
    from placemat.kicad.route import Pairs
    calls = []

    def stand_in(rpy, router_dir_path, pcb_in, work, pairs, layers, cfg, iterations, probe, timeout, env, events=None,
                 clearances=None, stem="pairs", extra_args=()):
        calls.append(list(pairs))
        out = work / (stem + ".kicad_pcb")
        shutil.copy(pcb_in, out)
        return out, Pairs(["FB_5V/FB_5V_GND"], [], [], [], {"FB_5V", "FB_5V_GND"})
    monkeypatch.setattr(phase_run, "route_pairs", stand_in)
    three = phases({"name": "pair", "pairs": [["FB_5V", "FB_5V_GND"]]}, {"name": "pour", "nets": ["GND"]},
                   {"name": "signals"})
    first = rig.route(phases=three)
    assert calls == [[("FB_5V", "FB_5V_GND")]] and first.phases[0]["pairs"]["coupled"] == ["FB_5V/FB_5V_GND"]
    again = rig.route(phases=three)
    assert len(calls) == 1 and again.resumed == ["pair", "pour", "signals"]
    assert again.phases[0]["pairs"]["coupled"] == ["FB_5V/FB_5V_GND"]
    assert rig.calls() == ["island", "tasks", "main"]


# ---------------------------------------------------------------- a real stop
def test_a_stopped_route_keeps_the_finished_phases_ends_the_router_and_resumes(rig, monkeypatch):
    code = textwrap.dedent("""
        import sys
        from pathlib import Path
        from placemat import stop
        from placemat.kicad.route import route_board
        from tests.test_route_resume import PHASES
        stop.install()
        try:
            route_board(Path(sys.argv[1]), Path(sys.argv[2]), router_dir_override=sys.argv[3], layers=["F.Cu", "B.Cu"],
                        pour_nets={"GND"}, exclude_nets={"VBUS"}, phases=PHASES)
        except stop.Stopped as s:
            print("stopped", flush=True)
            sys.exit(s.exit_code)
    """)
    env = dict(os.environ, FAKE_ROUTER_MAIN="hang")
    proc = subprocess.Popen([sys.executable, "-c", code, str(rig.pcb), str(rig.work), str(rig.root / "krt")],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pidfile = rig.root / "pid"
    try:
        t0 = time.time()
        while not pidfile.exists() and time.time() - t0 < 120 and proc.poll() is None:
            time.sleep(0.1)
        assert pidfile.exists(), proc.communicate()
        router = int(pidfile.read_text())
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 143 and "stopped" in out, (out, err)
    time.sleep(0.5)
    assert not Path("/proc/%d" % router).exists(), "the router outlived the stop"
    assert _finished(rig.work) == ["pour"] and (rig.work / "p0_0.kicad_pcb").exists()
    done = rig.route()
    assert rig.calls() == ["island", "tasks", "main", "main"] and done.resumed == ["pour"]
