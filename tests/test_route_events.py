"""Routing progress: the hooks the router's process installs (kicad/route_events.py, checked against stand-ins for the router's modules), the
tail that sends them on the command's socket, the route record, and the replay document made from it."""
import dataclasses
import importlib.util
import json
import sys
import threading
import time
import types

import pytest

from placemat import route_progress, route_view

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


def test_the_hooks_write_a_net_per_line_a_commit_a_rip_and_the_queue(router, tmp_path):
    out = tmp_path / "events.jsonl"
    hooks = _hooks()
    assert hooks.install(str(out)) == ""
    pm, ser, loop = router["pcb_modification"], router["single_ended_routing"], router["single_ended_loop"]
    pcb = PCB()
    loop.route_single_ended_nets(None, [("A", 1), ("B", 2)])
    result = loop.route_net_with_obstacles(pcb, 1)                       # through the module that bound the original earlier
    pm.add_route_to_pcb_data(pcb, result)
    pm.add_route_to_pcb_data(pcb, result, trace_event="restore")
    pm.remove_route_from_pcb_data(pcb, result)
    ser.route_net_with_obstacles(pcb, 2)
    events = [json.loads(l) for l in out.read_text().splitlines()]
    assert [e["ev"] for e in events] == ["queue", "queue_end", "net_begin", "net_end", "commit", "commit", "rip", "net_begin", "net_end"]
    assert events[0]["nets"] == ["A", "B"] and events[1] == dict(events[1], routed=1, failed=1)
    assert events[4]["net"] == "A" and events[4]["how"] == "route" and events[5]["how"] == "restore"
    assert events[4]["seg"] == [[0.0, 0.0, 1.0, 0.0, "F.Cu", 0.2]] and events[4]["via"] == [[1.0, 0.0, 0.6, 0.3, ["F.Cu", "B.Cu"]]]
    assert [e["ok"] for e in events if e["ev"] == "net_end"] == [True, False] and all("t" in e for e in events)
    assert pm.log == [("add", "route"), ("add", "restore"), ("remove", "rip")]       # the router's own functions still ran


def test_a_net_search_inside_another_is_one_net_begin_and_one_net_end(router, tmp_path):
    out = tmp_path / "events.jsonl"
    ser = router["single_ended_routing"]
    inner = ser.route_net_with_obstacles
    ser.route_multipoint_main = lambda pcb_data, net_id, config=None, obstacles=None: (ser.route_net_with_obstacles(pcb_data, net_id), inner(pcb_data, net_id))[0]
    assert _hooks().install(str(out)) == ""
    ser.route_multipoint_main(PCB(), 1)
    assert [json.loads(l)["ev"] for l in out.read_text().splitlines()] == ["net_begin", "net_end"]


@pytest.mark.parametrize("what", ["add_route_to_pcb_data", "route_oracle_links", "route_single_ended_nets"])
def test_a_missing_hook_target_patches_nothing_and_says_why(router, tmp_path, what):
    for mod in router.values():
        if hasattr(mod, what):
            delattr(mod, what)
    originals = {n: getattr(m, a) for n, m, a in (("add", router["pcb_modification"], "add_route_to_pcb_data"), ("net", router["single_ended_routing"], "route_net_with_obstacles")) if hasattr(m, a)}
    why = _hooks().install(str(tmp_path / "events.jsonl"))
    assert what in why and not (tmp_path / "events.jsonl").exists()
    if "net" in originals:
        assert router["single_ended_routing"].route_net_with_obstacles is originals["net"]


def test_a_changed_signature_or_field_patches_nothing(router, tmp_path):
    router["single_ended_routing"].route_net_with_obstacles = lambda pcb, net: None            # no pcb_data parameter
    assert "pcb_data" in _hooks().install(str(tmp_path / "e.jsonl"))
    router["single_ended_routing"].route_net_with_obstacles = lambda pcb_data, net_id: None
    router["kicad_parser"].Segment = dataclasses.make_dataclass("Segment", [("start_x", float)])
    assert "Segment has no field" in _hooks().install(str(tmp_path / "e2.jsonl"))


def test_without_a_path_or_with_events_off_the_hooks_do_nothing(router, tmp_path, monkeypatch):
    monkeypatch.delenv("PLACEMAT_ROUTE_EVENTS", raising=False)
    assert _hooks().install() == ""
    monkeypatch.setenv("PLACEMAT_ROUTE_EVENTS", "off")
    assert _hooks().install() == "" and router["pcb_modification"].add_route_to_pcb_data.__name__ == "<lambda>"
    assert "cannot be written" in _hooks().install(str(tmp_path / "no" / "such" / "events.jsonl"))


def test_the_wrapper_scripts_load_the_hooks_by_path_and_report_the_reason_when_off(tmp_path):
    text = (__import__("pathlib").Path(route_progress.__file__).parent / "kicad" / "route_hooked.py").read_text()
    assert "route_events.install()" in text and "report_off" in text and "spec_from_file_location" in text
    one = (__import__("pathlib").Path(route_progress.__file__).parent / "kicad" / "route_one_round.py").read_text()
    assert "route_events.install()" in one and "final_reconcile=False" in one


# ------------------------------------------------------------------ the tail, the record and the replay
def _commit(net, x, how="route", via=None):
    return {"ev": "commit", "net": net, "how": how, "seg": [[x, 0, x + 1, 0, "F.Cu", 0.2]], "via": via or []}


def test_the_tail_sends_each_event_as_it_is_written_and_keeps_them_in_order(tmp_path):
    sent = []
    rev = route_progress.RouteEvents(tmp_path, sent.append)
    rev.begin("main")
    path = rev.path("main")
    with open(path, "a") as f:
        f.write(json.dumps({"ev": "queue", "nets": ["A", "B"]}) + "\n")
        f.write(json.dumps(_commit("A", 0))[:30])                                 # a line cut short by the writer: not an event yet
        f.flush()
        deadline = time.monotonic() + 5
        while len(sent) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert [e["ev"] for e in sent] == ["route_stage", "route_queue"]
        f.write(json.dumps(_commit("A", 0))[30:] + "\n")
        f.write(json.dumps({"ev": "net_end", "net": "A", "ok": True}) + "\n")
    events = rev.end("main")
    assert [e["ev"] for e in events] == ["queue", "commit", "net_end"]
    assert [e["ev"] for e in sent] == ["route_stage", "route_queue", "route_commit", "route_net_end"] and sent[2]["stage"] == "main"
    assert rev.stages[0]["stage"] == "main" and not rev.stages[0]["resumed"]


def test_a_resumed_stage_sends_and_keeps_the_events_its_earlier_route_saved(tmp_path):
    sent = []
    rev = route_progress.RouteEvents(tmp_path, sent.append)
    rev.path("islands").write_text(json.dumps({"ev": "queue", "nets": ["G"]}) + "\n" + json.dumps(_commit("G", 0)) + "\n")
    rev.resumed("islands", 2.5)
    assert [e["ev"] for e in sent] == ["route_stage", "route_queue", "route_commit"] and sent[0]["resumed"] is True
    assert rev.stages == [{"stage": "islands", "resumed": True, "seconds": 2.5, "events": [{"ev": "queue", "nets": ["G"]}, _commit("G", 0)]}]


def test_the_pair_routers_aliases_are_turned_back_to_the_boards_nets(tmp_path):
    sent = []
    rev = route_progress.RouteEvents(tmp_path, sent.append)
    rev.names = {"PAIR0_P": "USB_DP", "PAIR0_N": "USB_DN"}
    rev.begin("pairs")
    with open(rev.path("pairs"), "a") as f:
        f.write(json.dumps(_commit(["PAIR0_P", "PAIR0_N"], 0)) + "\n" + json.dumps({"ev": "net_end", "net": "PAIR0_P", "ok": True}) + "\n")
    events = rev.end("pairs")
    assert events[0]["net"] == ["USB_DP", "USB_DN"] and events[1]["net"] == "USB_DP" and sent[-1]["net"] == "USB_DP"


def test_events_off_gives_the_router_nothing_to_write(tmp_path, monkeypatch):
    monkeypatch.setenv("PLACEMAT_ROUTE_EVENTS", "off")
    rev = route_progress.RouteEvents(tmp_path, None)
    assert rev.env("main") == {} and not route_progress.enabled()
    rev.begin("main")
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
