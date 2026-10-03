"""Routing progress: the hooks the router's process installs (kicad/route_events.py, checked against stand-ins for the router's modules), the
tail that sends them on the command's socket, the route record, and the replay document made from it."""
import dataclasses
import importlib.util
import json
import os
import sys
import time
import types

import pytest

from placemat import route_progress, route_view
from tests.conftest import needs_breakout, needs_kicad

HOOKS = importlib.util.spec_from_file_location("route_events", str(__import__("pathlib").Path(__import__("placemat").__file__).parent / "kicad" / "route_events.py"))


def _hooks():
    mod = importlib.util.module_from_spec(HOOKS)
    HOOKS.loader.exec_module(mod)
    return mod


@dataclasses.dataclass
class Segment:
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    width: float
    layer: str
    net_id: int


@dataclasses.dataclass
class Via:
    x: float
    y: float
    size: float
    drill: float
    layers: list
    net_id: int


class Net:
    def __init__(self, name):
        self.name = name


class PCB:
    nets = {1: Net("A"), 2: Net("B")}


@pytest.fixture
def router(monkeypatch):
    """Stand-ins for the router's modules with the functions and signatures the hooks expect."""
    mods = {}
    for name in ("pcb_modification", "single_ended_routing", "single_ended_loop", "kicad_parser"):
        mods[name] = types.ModuleType(name)
        monkeypatch.setitem(sys.modules, name, mods[name])
    pm, ser, loop, parser = (mods[n] for n in ("pcb_modification", "single_ended_routing", "single_ended_loop", "kicad_parser"))
    parser.Segment, parser.Via = Segment, Via
    pm.log = []
    pm.add_route_to_pcb_data = lambda pcb_data, result, debug_lines=False, trace_event="route": pm.log.append(("add", trace_event))
    pm.remove_route_from_pcb_data = lambda pcb_data, result, trace_event="rip": pm.log.append(("remove", trace_event))

    def route_net_with_obstacles(pcb_data, net_id, config=None, obstacles=None):
        if net_id == 2:
            return None
        return {"new_segments": [Segment(0, 0, 1, 0, 0.2, "F.Cu", net_id)], "new_vias": [Via(1, 0, 0.6, 0.3, ["F.Cu", "B.Cu"], net_id)]}
    ser.route_net_with_obstacles = route_net_with_obstacles
    ser.route_multipoint_main = lambda pcb_data, net_id, config=None, obstacles=None: route_net_with_obstacles(pcb_data, net_id)
    ser.route_oracle_links = lambda pcb_data, net_id, config=None, obstacles=None: None
    loop.route_single_ended_nets = lambda state, single_ended_nets, route_index_start=0: (len([n for n in single_ended_nets if n[1] != 2]), 1, 0.1, 0, 0, False)
    loop.route_net_with_obstacles = ser.route_net_with_obstacles          # a module that bound the function before the hooks went in
    return mods


class Pipe:
    """An events pipe as placemat gives one to the router: the hooks write to `w`, the test reads what arrived."""

    def __init__(self):
        self.r, self.w = os.pipe()

    def events(self, hooks):
        hooks._flush()                                        # the writer passes on what is queued (the router does this at exit)
        os.close(self.w)
        data = b""
        while True:
            chunk = os.read(self.r, 65536)
            if not chunk:
                break
            data += chunk
        os.close(self.r)
        return [json.loads(l) for l in data.decode().splitlines()]


def test_the_hooks_write_a_net_per_line_a_commit_a_rip_and_the_queue(router):
    pipe = Pipe()
    hooks = _hooks()
    assert hooks.install(pipe.w) == ""
    pm, ser, loop = router["pcb_modification"], router["single_ended_routing"], router["single_ended_loop"]
    pcb = PCB()
    loop.route_single_ended_nets(None, [("A", 1), ("B", 2)])
    result = loop.route_net_with_obstacles(pcb, 1)                       # through the module that bound the original earlier
    pm.add_route_to_pcb_data(pcb, result)
    pm.add_route_to_pcb_data(pcb, result, trace_event="restore")
    pm.remove_route_from_pcb_data(pcb, result)
    ser.route_net_with_obstacles(pcb, 2)
    events = pipe.events(hooks)
    assert [e["ev"] for e in events] == ["queue", "queue_end", "net_begin", "net_end", "commit", "commit", "rip", "net_begin", "net_end"]
    assert events[0]["nets"] == ["A", "B"] and events[1] == dict(events[1], routed=1, failed=1)
    assert events[4]["net"] == "A" and events[4]["how"] == "route" and events[5]["how"] == "restore"
    assert events[4]["seg"] == [[0.0, 0.0, 1.0, 0.0, "F.Cu", 0.2]] and events[4]["via"] == [[1.0, 0.0, 0.6, 0.3, ["F.Cu", "B.Cu"]]]
    assert [e["ok"] for e in events if e["ev"] == "net_end"] == [True, False] and all("t" in e for e in events)
    assert pm.log == [("add", "route"), ("add", "restore"), ("remove", "rip")]       # the router's own functions still ran


def test_a_net_search_inside_another_is_one_net_begin_and_one_net_end(router):
    pipe, hooks = Pipe(), _hooks()
    ser = router["single_ended_routing"]
    inner = ser.route_net_with_obstacles
    ser.route_multipoint_main = lambda pcb_data, net_id, config=None, obstacles=None: (ser.route_net_with_obstacles(pcb_data, net_id), inner(pcb_data, net_id))[0]
    assert hooks.install(pipe.w) == ""
    ser.route_multipoint_main(PCB(), 1)
    assert [e["ev"] for e in pipe.events(hooks)] == ["net_begin", "net_end"]


@pytest.mark.parametrize("what", ["add_route_to_pcb_data", "route_oracle_links", "route_single_ended_nets"])
def test_a_missing_hook_target_patches_nothing_and_says_why(router, what):
    for mod in router.values():
        if hasattr(mod, what):
            delattr(mod, what)
    originals = {n: getattr(m, a) for n, m, a in (("add", router["pcb_modification"], "add_route_to_pcb_data"), ("net", router["single_ended_routing"], "route_net_with_obstacles")) if hasattr(m, a)}
    pipe = Pipe()
    why = _hooks().install(pipe.w)
    assert what in why
    os.close(pipe.w)
    assert os.read(pipe.r, 10) == b""                                        # nothing was written
    if "net" in originals:
        assert router["single_ended_routing"].route_net_with_obstacles is originals["net"]


def test_a_changed_signature_or_field_patches_nothing(router):
    router["single_ended_routing"].route_net_with_obstacles = lambda pcb, net: None            # no pcb_data parameter
    pipe = Pipe()
    assert "pcb_data" in _hooks().install(pipe.w)
    router["single_ended_routing"].route_net_with_obstacles = lambda pcb_data, net_id: None
    router["kicad_parser"].Segment = dataclasses.make_dataclass("Segment", [("start_x", float)])
    assert "Segment has no field" in _hooks().install(pipe.w)


def test_without_a_pipe_or_with_events_off_the_hooks_do_nothing(router, monkeypatch):
    monkeypatch.delenv("PLACEMAT_ROUTE_EVENTS", raising=False)
    monkeypatch.delenv("PLACEMAT_ROUTE_EVENTS_FD", raising=False)
    assert _hooks().install() == ""
    pipe = Pipe()
    monkeypatch.setenv("PLACEMAT_ROUTE_EVENTS_FD", str(pipe.w))
    monkeypatch.setenv("PLACEMAT_ROUTE_EVENTS", "off")
    original = router["pcb_modification"].add_route_to_pcb_data
    assert _hooks().install() == "" and router["pcb_modification"].add_route_to_pcb_data is original
    monkeypatch.delenv("PLACEMAT_ROUTE_EVENTS")
    hooks = _hooks()
    assert hooks.install() == "" and router["pcb_modification"].add_route_to_pcb_data is not original         # the descriptor from the environment
    pipe.events(hooks)
    assert "is not open" in _hooks().install(987654)


def test_a_router_that_outruns_its_reader_drops_events_and_one_that_lost_its_reader_goes_on_silently(router):
    hooks = _hooks()
    pipe = Pipe()
    assert hooks.install(pipe.w) == ""
    pm = router["pcb_modification"]
    hooks.QUEUE_MAX = 5
    os.close(pipe.r)                                                         # the reader has gone: writes fail, the route goes on
    for _ in range(50):
        pm.add_route_to_pcb_data(PCB(), {"new_segments": [Segment(0, 0, 1, 0, 0.2, "F.Cu", 1)], "new_vias": []})
    assert len(pm.log) == 50
    hooks._flush()
    assert hooks._state["dead"] is True
    os.close(pipe.w)


def test_the_wrapper_scripts_load_the_hooks_by_path_and_report_the_reason_when_off(tmp_path):
    text = (__import__("pathlib").Path(route_progress.__file__).parent / "kicad" / "route_hooked.py").read_text()
    assert "route_events.install()" in text and "report_off" in text and "spec_from_file_location" in text
    one = (__import__("pathlib").Path(route_progress.__file__).parent / "kicad" / "route_one_round.py").read_text()
    assert "route_events.install()" in one and "final_reconcile=False" in one


# ------------------------------------------------------------------ the tail, the record and the replay
def _commit(net, x, how="route", via=None):
    return {"ev": "commit", "net": net, "how": how, "seg": [[x, 0, x + 1, 0, "F.Cu", 0.2]], "via": via or []}


def _send_lines(rev, *lines):
    """What the router's process does: write to the descriptor it was given."""
    fd = int(rev.env("x")["PLACEMAT_ROUTE_EVENTS_FD"])
    for line in lines:
        os.write(fd, line.encode())


def test_the_reader_sends_each_event_as_it_arrives_and_keeps_them_in_order(tmp_path):
    sent = []
    rev = route_progress.RouteEvents(tmp_path, sent.append)
    rev.begin("main")
    assert route_progress.pass_fds() == (int(rev.env("main")["PLACEMAT_ROUTE_EVENTS_FD"]),)
    whole = json.dumps(_commit("A", 0))
    _send_lines(rev, json.dumps({"ev": "queue", "nets": ["A", "B"]}) + "\n", whole[:30])               # a write cut short: not an event yet
    deadline = time.monotonic() + 5
    while len(sent) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert [e["ev"] for e in sent] == ["route_stage", "route_queue"]
    _send_lines(rev, whole[30:] + "\n", json.dumps({"ev": "net_end", "net": "A", "ok": True}) + "\n")
    events = rev.end("main")
    assert [e["ev"] for e in events] == ["queue", "commit", "net_end"] and route_progress.pass_fds() == ()
    assert [e["ev"] for e in sent] == ["route_stage", "route_queue", "route_commit", "route_net_end"] and sent[2]["stage"] == "main"
    assert rev.stages[0]["stage"] == "main" and not rev.stages[0]["resumed"]
    assert [p.name for p in tmp_path.iterdir()] == []                         # no events file: the record is the only file (written once the route has a board)


def test_a_stage_taken_from_an_earlier_route_sends_and_keeps_what_that_routes_record_held(tmp_path):
    info = {"pcb": "x.kicad_pcb", "run": "", "script": ""}
    route_progress.write_record(tmp_path, info, [{"stage": "islands", "resumed": False, "seconds": 1.0, "events": [{"ev": "queue", "nets": ["G"]}, _commit("G", 0)]}], {})
    sent = []
    rev = route_progress.RouteEvents(tmp_path, sent.append, info)
    rev.resumed("islands", 2.5)
    assert [e["ev"] for e in sent] == ["route_stage", "route_queue", "route_commit"] and sent[0]["resumed"] is True
    assert rev.stages == [{"stage": "islands", "resumed": True, "seconds": 2.5, "events": [{"ev": "queue", "nets": ["G"]}, _commit("G", 0)]}]


def test_each_stage_that_ends_leaves_the_record_as_it_stands_for_a_stopped_route(tmp_path):
    info = {"pcb": "x.kicad_pcb", "run": "", "script": ""}
    rev = route_progress.RouteEvents(tmp_path, None, info)
    rev.begin("islands")
    _send_lines(rev, json.dumps({"ev": "queue", "nets": ["G"]}) + "\n")
    rev.end("islands")
    assert [s["stage"] for s in route_progress.read_record(tmp_path / route_progress.RECORD)["stages"]] == ["islands"]


def test_the_pair_routers_aliases_are_turned_back_to_the_boards_nets(tmp_path):
    sent = []
    rev = route_progress.RouteEvents(tmp_path, sent.append)
    rev.names = {"PAIR0_P": "USB_DP", "PAIR0_N": "USB_DN"}
    rev.begin("pairs")
    _send_lines(rev, json.dumps(_commit(["PAIR0_P", "PAIR0_N"], 0)) + "\n" + json.dumps({"ev": "net_end", "net": "PAIR0_P", "ok": True}) + "\n")
    events = rev.end("pairs")
    assert events[0]["net"] == ["USB_DP", "USB_DN"] and events[1]["net"] == "USB_DP" and sent[-1]["net"] == "USB_DP"


def test_events_off_gives_the_router_no_pipe(tmp_path, monkeypatch):
    monkeypatch.setenv("PLACEMAT_ROUTE_EVENTS", "off")
    rev = route_progress.RouteEvents(tmp_path, None)
    rev.begin("main")
    assert rev.env("main") == {} and not route_progress.enabled() and route_progress.pass_fds() == ()
    assert rev.end("main") == []


def test_laid_order_gives_each_nets_copper_what_a_rip_took_and_each_nets_result():
    via = [[1.0, 0.0, 0.6, 0.3, ["F.Cu", "B.Cu"]]]
    events = [{"ev": "queue", "nets": ["A", "B", "C"]}, {"ev": "net_begin", "net": "A"}, _commit("A", 0, via=via), {"ev": "net_end", "net": "A", "ok": True},
              {"ev": "net_begin", "net": "B"}, _commit("B", 5), {"ev": "net_end", "net": "B", "ok": True},
              {"ev": "rip", "net": "B", "seg": [[5, 0, 6, 0, "F.Cu", 0.2]], "via": []},
              {"ev": "net_begin", "net": "C"}, {"ev": "net_end", "net": "C", "ok": False}, _commit("A", 9, how="restore")]
    laid = route_view.lay(events)
    assert laid["order"] == ["A", "B", "C"] and [o["t"] for o in laid["ops"]["A"]] == ["track", "via", "track"] and laid["ops"]["B"] == [] and laid["ops"]["C"] == []
    assert laid["result"] == {"A": "routed", "B": "ripped", "C": "no route found"}


def test_a_route_record_replays_as_a_plan_with_a_step_per_part_then_per_net(tmp_path):
    board = {"board": {"loops": [[[0, 0], [10, 0], [10, 10]]], "drawn": True, "extent": [0, 0, 10, 10]}, "items": [{"key": "u1", "kind": "part", "placed": True, "members": []}], "layers": ["F.Cu"]}
    stages = [{"stage": "main", "resumed": False, "seconds": 1.0, "events": [{"ev": "net_begin", "net": "A"}, _commit("A", 0), {"ev": "net_end", "net": "A", "ok": True},
                                                                              {"ev": "net_end", "net": "B", "ok": False}]}]
    path = route_progress.write_record(tmp_path, {"pcb": "x.kicad_pcb", "run": "abc", "script": "x_layout.py"}, stages, {"closure": 0.9, "closure_clean": 0.8, "seconds": 3.0})
    record = route_progress.read_record(path)
    assert record["board"]["run"] == "abc" and record["stages"][0]["events"][1]["net"] == "A"
    summary = json.loads((tmp_path / route_progress.SUMMARY).read_text())
    assert (summary["nets"], summary["routed"], summary["failed"], summary["run"]) == (2, 1, 1, "abc")
    doc = route_view.route_doc(record, board)
    assert [s["item"] for s in doc["steps"]] == ["u1", "track A", "track B"] and [s["kind"] for s in doc["steps"]] == ["part", "copper", "copper"]
    assert doc["steps"][1]["copper"] == [0] and doc["copper"][0]["t"] == "track" and doc["steps"][2]["note"] == "no route found" and doc["steps"][1]["note"].startswith("routed: 1 track")
    assert doc["route"] == {"nets": 2, "routed": 1, "failed": 1}
    plan = dict(board, steps=[{"i": 0, "item": "u1", "kind": "part", "placed": True, "note": "", "copper": []}], copper=[{"t": "track", "layer": "F.Cu"}], counts={"placed": 1, "findings": 0}, score=None)
    whole = route_view.route_doc(record, plan)                                                    # a run's plan first: the whole build
    assert [s["item"] for s in whole["steps"]] == ["u1", "track A", "track B"] and whole["steps"][1]["copper"] == [1] and len(whole["copper"]) == 2


def test_a_record_that_is_not_one_is_not_read(tmp_path):
    assert route_progress.read_record(tmp_path / "none.json") is None
    (tmp_path / "bad.json").write_text("{not json")
    assert route_progress.read_record(tmp_path / "bad.json") is None
    (tmp_path / "old.json").write_text(json.dumps({"version": 9, "stages": []}))
    assert route_progress.read_record(tmp_path / "old.json") is None


def test_a_board_with_no_outline_is_framed_on_its_parts():
    from types import SimpleNamespace as NS
    box = NS(left=-1, top=-1, right=1, bottom=1)
    fp = NS(face=NS(value="front"), courtyard_poly=[(-1, -1), (1, -1), (1, 1), (-1, 1)], courtyard_box=box, pads=[], inst="u1", ref="U1", value="x", cell="", location=NS(x=0, y=0), rotation=0)
    doc = route_view.board_doc(NS(board_polygon=None, outline=[], footprints=[fp], layers=[NS(value="F.Cu")]))
    assert doc["board"] == {"loops": [], "drawn": False, "extent": [-3, -3, 3, 3]}


def _breakout_with_a_partial_pour(breakout_pcb, tmp_path, net):
    import pcbnew
    import shutil
    dest = tmp_path / "in"
    dest.mkdir()
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), dest / ("layout" + ext))
    pcb = dest / "layout.kicad_pcb"
    brd = pcbnew.LoadBoard(str(pcb))
    brd.SetCopperLayerCount(4)
    for t in list(brd.GetTracks()):
        brd.Delete(t)
    pads = sorted((p for f in brd.GetFootprints() for p in f.Pads() if p.GetNetname() == net and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH),
                  key=lambda p: p.GetPosition().y)
    near = pads[:len(pads) // 2]
    box = near[0].GetBoundingBox()
    for p in near[1:]:
        box.Merge(p.GetBoundingBox())
    box.Inflate(pcbnew.FromMM(1.5))
    z = pcbnew.ZONE(brd)
    z.SetLayer(brd.GetLayerID("In2.Cu"))
    z.SetNetCode(brd.GetNetcodeFromNetname(net))
    o = z.Outline()
    o.NewOutline()
    for x, y in ((box.GetLeft(), box.GetTop()), (box.GetRight(), box.GetTop()), (box.GetRight(), box.GetBottom()), (box.GetLeft(), box.GetBottom())):
        o.Append(x, y)
    brd.Add(z)
    brd.Save(str(pcb))
    return pcb


@needs_kicad
@needs_breakout
def test_the_real_router_sends_its_nets_as_it_routes_them_and_the_record_replays(breakout_pcb, tmp_path, monkeypatch):
    from pathlib import Path
    from placemat import channel
    from placemat.kicad.route import ROUTER_DEFAULT, route_board
    if not (Path(ROUTER_DEFAULT) / ".venv/bin/python").exists():
        pytest.skip("KiCadRoutingTools not at %s" % ROUTER_DEFAULT)
    net = "PERMIT_A"
    pcb = _breakout_with_a_partial_pour(breakout_pcb, tmp_path, net)
    sent = []
    monkeypatch.setattr(channel, "current", lambda: types.SimpleNamespace(send=sent.append))
    report = route_board(pcb, tmp_path / "route", exclude_nets={net, "GND", "V48P"}, layers=["F.Cu", "In2.Cu", "B.Cu"], quick=True, islands={net: None},
                         board_info={"run": "r1", "script": "x_layout.py"})
    kinds = [e["ev"] for e in sent]
    assert kinds[0] == "route_board" and "route_stage" in kinds and kinds.index("route_queue") < kinds.index("route_net_begin") < kinds.index("route_net_end")
    assert [e for e in sent if e["ev"] == "route_commit" and e["net"] == net]            # a net's copper is committed after its search ends; the pair stage sends commits only
    assert [e for e in sent if e["ev"] == "route_net_end" and e["net"] == net][0]["ok"] is True
    commit = [e for e in sent if e["ev"] == "route_commit" and e["net"] == net][0]
    assert commit["seg"] and all(len(s) == 6 for s in commit["seg"])
    assert report.record and Path(report.record).is_file()
    record = route_progress.read_record(Path(report.record))
    assert record["board"]["run"] == "r1" and [s["stage"] for s in record["stages"]][0] in ("pairs", "islands")
    doc = route_view.route_doc(record, json.loads((tmp_path / "route" / route_progress.BOARD).read_text()))
    assert doc["route"]["routed"] >= 1 and doc["copper"] and [s for s in doc["steps"] if s["kind"] == "copper"][0]["copper"]
