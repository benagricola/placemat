"""A route that is stopped or fails keeps the stages it finished (pairs,
islands, main) in its work folder, and a rerun with the same inputs skips
them. The router is a stand-in script here (it copies its board and logs the
call): what is tested is placemat's stage handling, not routing."""
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

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / "fixtures/fairing/keep_out/modules/usb5v/generated/Usb5v"

FAKE = textwrap.dedent('''
    import json, os, shutil, sys, time
    a = sys.argv[1:]
    pcb_in, pcb_out = a[0], a[1]
    nets = []
    for x in a[a.index("--nets") + 1:]:
        if x.startswith("--"):
            break
        nets.append(x)
    kind = "main" if "*" in nets else "island"
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
        open(a[a.index("--json-out") + 1], "w").write("{}")
''')


# ---------------------------------------------------------------- the state file, alone
def test_a_finished_stage_is_found_by_its_digest_and_only_by_it(tmp_path):
    s = RouteState(tmp_path)
    s.record("pairs", "d1", {"board": "pairs.kicad_pcb", "seconds": 2.0})
    again = RouteState(tmp_path)
    assert again.result("pairs", "d1") == {"board": "pairs.kicad_pcb", "seconds": 2.0}
    assert again.result("pairs", "other") is None and again.result("islands", "d1") is None
    assert json.loads((tmp_path / "state.json").read_text())["stages"]["pairs"]["digest"] == "d1"


def test_dropping_a_stage_drops_it_its_files_and_every_stage_after_it(tmp_path):
    s = RouteState(tmp_path)
    for st in route_state.STAGES:
        s.record(st, "d-" + st, {"seconds": 1.0})
    for name in ("pairs.kicad_pcb", "pairs.log", "islands0.kicad_pcb", "islands.kicad_pcb", "router.log", "router_out.kicad_pcb",
                 "routed.kicad_pcb", "route.json", "in.kicad_pcb", "drc_before.json"):
        (tmp_path / name).write_text("x")
    s.drop_from("islands")
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["drc_before.json", "in.kicad_pcb", "pairs.kicad_pcb", "pairs.log", "state.json"]
    assert RouteState(tmp_path).finished == ["pairs"]


def test_a_state_file_that_is_not_readable_is_no_state(tmp_path):
    (tmp_path / "state.json").write_text("{not json")
    assert RouteState(tmp_path).finished == []
    (tmp_path / "state.json").write_text(json.dumps({"version": 99, "stages": {"pairs": {"digest": "d"}}}))
    assert RouteState(tmp_path).finished == []


def test_without_resume_everything_is_dropped(tmp_path):
    RouteState(tmp_path).record("pairs", "d", {})
    (tmp_path / "pairs.kicad_pcb").write_text("x")
    s = RouteState(tmp_path, resume=False)
    assert s.finished == [] and not (tmp_path / "pairs.kicad_pcb").exists()


def test_the_pairs_outcome_survives_the_state_file():
    from placemat.kicad.route import Pairs
    p = Pairs(["A"], ["B"], ["C"], ["D"], {"A_P", "A_N"})
    assert Pairs.from_dict(json.loads(json.dumps(p.to_dict()))) == p


# ---------------------------------------------------------------- route_board, with a stand-in router
@pytest.fixture
def rig(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    krt = tmp_path / "krt"
    (krt / ".venv/bin").mkdir(parents=True)
    (krt / ".venv/bin/python").symlink_to(sys.executable)
    (krt / "py_router").mkdir()
    (krt / "py_router/route.py").write_text(FAKE)
    (krt / "VERSION").write_text("fake-1\n")
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
            return self.calls_file.read_text().split() if self.calls_file.exists() else []

        def route(self, **kw):
            from placemat.kicad.route import route_board
            kw.setdefault("layers", ["F.Cu", "B.Cu"])
            kw.setdefault("islands", {"GND": None})
            kw.setdefault("exclude_nets", {"VBUS"})
            return route_board(self.pcb, self.work, router_dir_override=str(krt), **kw)
    return Rig()


def test_a_rerun_with_the_same_inputs_skips_every_stage_the_first_finished(rig):
    first = rig.route()
    assert rig.calls() == ["island", "main"] and first.resumed == []
    assert RouteState(rig.work).finished == ["islands", "main"]
    again = rig.route()
    assert rig.calls() == ["island", "main"]                          # no router ran
    assert again.resumed == ["islands", "main"]
    assert (again.closure, again.open_after, again.islands) == (first.closure, first.open_after, first.islands)
    assert Path(again.routed_pcb).exists() and again.seconds >= first.seconds


def test_a_main_pass_that_fails_leaves_the_islands_done_and_the_rerun_does_only_the_main(rig, monkeypatch):
    monkeypatch.setenv("FAKE_ROUTER_MAIN", "fail")
    with pytest.raises(RuntimeError, match="router exited 3"):
        rig.route()
    assert rig.calls() == ["island", "main"]
    assert RouteState(rig.work).finished == ["islands"]
    assert (rig.work / "islands.kicad_pcb").exists()
    monkeypatch.delenv("FAKE_ROUTER_MAIN")
    done = rig.route()
    assert rig.calls() == ["island", "main", "main"] and done.resumed == ["islands"]


def test_a_changed_input_reruns_the_stages_it_reaches(rig, monkeypatch):
    rig.route()
    # the excluded nets decide which pours are guarded in the board every stage routes on: every stage is new
    again = rig.route(exclude_nets={"VBUS", "V3V3"})
    assert rig.calls() == ["island", "main", "island", "main"] and again.resumed == []
    # a changed board is new for the same reason
    text = rig.pcb.read_text()
    rig.pcb.write_text(text.replace("(version", "(version", 1) + "\n")
    third = rig.route(exclude_nets={"VBUS", "V3V3"})
    assert rig.calls() == ["island", "main"] * 3 and third.resumed == []


def test_without_resume_every_stage_runs_again(rig):
    rig.route()
    again = rig.route(resume=False)
    assert rig.calls() == ["island", "main"] * 2 and again.resumed == []


def test_pairs_are_a_stage_too(rig, monkeypatch):
    import placemat.kicad.route as route_mod
    from placemat.kicad.route import Pairs
    calls = []

    def stand_in(rpy, router_dir_path, pcb_in, work, pairs, layers, cfg, iterations, probe, timeout, env):
        calls.append(1)
        out = work / "pairs.kicad_pcb"
        shutil.copy(pcb_in, out)
        return out, Pairs(["USB"], [], [], [], {"USB_P", "USB_N"})
    monkeypatch.setattr(route_mod, "route_pairs", stand_in)
    monkeypatch.setattr("placemat.pairs.board_pair_list", lambda netclasses: [("USB_P", "USB_N")])
    first = rig.route()
    assert calls == [1] and first.pairs["coupled"] == ["USB"]
    again = rig.route()
    assert calls == [1] and again.resumed == ["pairs", "islands", "main"] and again.pairs["coupled"] == ["USB"]
    # the main pass leaves the pair's nets alone: they are in its command, so in its digest
    assert rig.calls() == ["island", "main"]


# ---------------------------------------------------------------- a real stop
def test_a_stopped_route_keeps_the_finished_stages_ends_the_router_and_resumes(rig, monkeypatch):
    code = textwrap.dedent("""
        import sys
        from pathlib import Path
        from placemat import stop
        from placemat.kicad.route import route_board
        stop.install()
        try:
            route_board(Path(sys.argv[1]), Path(sys.argv[2]), router_dir_override=sys.argv[3], layers=["F.Cu", "B.Cu"],
                        islands={"GND": None}, exclude_nets={"VBUS"})
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
    assert RouteState(rig.work).finished == ["islands"] and (rig.work / "islands.kicad_pcb").exists()
    done = rig.route()
    assert rig.calls() == ["island", "main", "main"] and done.resumed == ["islands"]
