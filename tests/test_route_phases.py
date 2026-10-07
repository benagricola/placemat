"""The phase engine (kicad/route.py _route_board): phases route in order, each on the board the one before left with
its copper locked; a phase's kept result is reused while its key and every earlier key hold; a route with no phases,
or with a setting the phases replaced, is refused. The router is a stand-in that copies its board and logs its call."""
import json
import sys
import textwrap

import pytest

from placemat.kicad import phase_run
from placemat.kicad.route import RouteRefused, RouterFailed, route_board
from placemat.settings import Settings, bind
from tests.conftest import needs_kicad
from tests.phase_helpers import fake_capabilities, phases
from tests.test_net_halos import _two_part_board

FAKE = textwrap.dedent('''
    import json, os, shutil, sys
    a = sys.argv[1:]
    with open(os.environ["FAKE_ROUTER_LOG"], "a") as f:
        f.write(json.dumps(a) + "\\n")
    fail = os.environ.get("FAKE_ROUTER_FAIL")
    if fail and fail in a:
        sys.exit(3)
    shutil.copy(a[0], a[1])
    if "--json-out" in a:
        doc = {}
        if "--connections" in a:
            tasks = json.load(open(a[a.index("--connections") + 1]))
            refuse = os.environ.get("FAKE_ROUTER_REFUSE")
            failed = os.environ.get("FAKE_ROUTER_FAILED")
            ev = {"scope": "net", "search": None, "verdicts": [], "narrow": [], "diagnosis": "unknown",
                  "blocked_by": [{"found_by": "static", "kind": "pad", "net": "X", "ref": "U9", "pad": "1",
                                  "layer": None, "at": [0.0, 0.0], "cells": 3, "seen_from": "forward",
                                  "near_source_cells": None, "near_target_cells": None}]}
            status = "refused" if refuse else "failed" if failed else "routed"
            doc["connections"] = [dict(t, status=status, reason=refuse, joined=status == "routed", length_mm=1.0,
                                       min_width_mm=t["widths"], layers=list(t["widths"]),
                                       evidence=ev if failed else None) for t in tasks]
        open(a[a.index("--json-out") + 1], "w").write(json.dumps(doc))
''')
CLASSES = 'def net_clearance_map_by_id(pcb_path, nets, design_rules=None):\n    return {}\n'


@pytest.fixture
def rig(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    krt = tmp_path / "krt"
    (krt / ".venv/bin").mkdir(parents=True)
    (krt / ".venv/bin/python").symlink_to(sys.executable)
    (krt / "py_router").mkdir()
    (krt / "py_router/route.py").write_text(FAKE)
    (krt / "py_router/list_nets.py").write_text(CLASSES)
    fake_capabilities(krt)
    (krt / "VERSION").write_text("fake-1\n")
    monkeypatch.setenv("FAKE_ROUTER_LOG", str(tmp_path / "calls"))

    class Rig:
        pcb = _two_part_board(tmp_path)            # FB and VIN open between U1 and J1
        work = tmp_path / "route"

        def calls(self):
            log = tmp_path / "calls"
            return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

        def route(self, *raw, **kw):
            with bind(Settings()):
                return route_board(self.pcb, self.work, router_dir_override=str(krt), layers=["F.Cu", "B.Cu"],
                                   phases=phases(*raw), **kw)
    return Rig()


def _nets(call):
    if "--nets" not in call:
        return []
    i = call.index("--nets")
    return call[i + 1:call.index("--layers")]


LEG = {"name": "vin", "nets": ["VIN"], "width": 0.5}
FB = {"name": "fb", "nets": ["FB"]}


@needs_kicad
def test_phases_route_in_order_each_on_the_board_the_one_before_left(rig):
    report = rig.route(LEG, FB, {"name": "signals"})
    calls = rig.calls()
    assert [_nets(c) for c in calls[:2]] == [["VIN"], ["FB"]]
    assert calls[0][calls[0].index("--power-nets-widths") + 1] == "0.5"
    assert calls[1][0] == calls[0][1]
    assert [p["name"] for p in report.phases] == ["vin", "fb", "signals"]
    assert set(report.phases[0]) >= {"asked", "joined", "open", "closure_clean", "seconds", "reused", "calls"}


@needs_kicad
def test_a_net_phase_names_each_connection_it_left_open(rig):
    report = rig.route(FB)                                  # the stand-in router lays no copper
    assert report.phases[0]["open"] == [{"net": "FB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "U1", "pad": "2"},
                                         "widths": None, "outcome": None, "evidence": None}]


@needs_kicad
def test_each_phase_asks_what_the_input_board_has_open_and_is_judged_again_on_the_final_board(rig):
    report = rig.route(FB, {"name": "signals"})
    assert [(p["asked"], p["joined"]) for p in report.phases] == [(1, 0), (1, 0)]     # FB; then VIN, not FB again
    assert [p["final_closure_clean"] for p in report.phases] == [0.0, 0.0]
    assert report.phases[1]["final_open"][0]["net"] == "VIN"
    assert (report.vias, report.track_mm, report.segments, report.drc_new) == (0, 0.0, 0, 0)


@needs_kicad
def test_a_connection_the_router_failed_carries_its_evidence(rig, monkeypatch):
    monkeypatch.setenv("FAKE_ROUTER_FAILED", "1")
    report = rig.route({"name": "leg", "width": 0.4, "connections": [{"from": {"part": "U1", "pad": "3"},
                                                                    "to": {"part": "J1", "pad": "2"}}]})
    (o,) = report.phases[0]["open"]
    assert o["outcome"] == "failed" and o["evidence"]["blocked_by"][0]["ref"] == "U9"


def test_each_phase_asks_a_set_fixed_from_the_input_board():
    from types import SimpleNamespace as N
    fb = {"net": "FB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "U1", "pad": "2"}}
    vin = {"net": "VIN", "from": {"ref": "J1", "pad": "2"}, "to": {"ref": "U1", "pad": "3"}}
    sw = {"net": "SW", "from": {"ref": "L1", "pad": "1"}, "to": {"ref": "U1", "pad": "1"}}
    leg = {"net": "VB", "from": {"ref": "J2", "pad": "1"}, "to": {"ref": "Q1", "pad": "1"}}
    task = N(record=lambda: dict(leg, widths={"F.Cu": 1.0}), widths=(("F.Cu", 1.0),))
    none = dict(tasks=(), rest=False, nets=(), pour_nets=(), buses=(), pairs=(), width=None, layers=())
    sels = [N(**dict(none, tasks=(task,))), N(**dict(none, nets=("FB",), width=0.3, layers=("F.Cu",))),
            N(**dict(none, rest=True))]
    got = phase_run.obligations_of(sels, [fb, vin, sw], skip={"SW"})
    assert got == [[dict(leg, widths={"F.Cu": 1.0})], [dict(fb, widths={"F.Cu": 0.3})], [dict(vin, widths=None)]]


def test_a_later_short_never_makes_an_obligation_clean(tmp_path, monkeypatch):
    drc = tmp_path / "drc.json"
    drc.write_text(json.dumps({"violations": [{"type": "shorting_items", "items": [
        {"description": "Track [FB] on F.Cu"}, {"description": "Track [VIN] on F.Cu"}]}], "unconnected_items": []}))
    monkeypatch.setattr(phase_run, "joined_pairs", lambda pcb, pairs: [True] * len(pairs))
    ob = {"net": "FB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "U1", "pad": "2"}, "widths": None}
    (j,) = phase_run.judge_obligations(tmp_path / "x.kicad_pcb", [ob], drc)
    assert j == {"joined": True, "violated": True, "under": {}} and not phase_run.is_clean(j, None)


def test_a_join_narrower_than_asked_is_not_clean():
    from placemat.kicad import phase_run
    assert not phase_run.is_clean({"joined": True, "violated": False, "under": {"F.Cu": 0.2}}, None)
    assert not phase_run.is_clean({"joined": True, "violated": False, "under": {}}, "joined_narrow")
    assert phase_run.is_clean({"joined": True, "violated": False, "under": {}}, "routed")


def test_widths_are_judged_on_the_path_that_joins_the_pair_not_on_a_branch():
    from placemat.kicad import phase_run
    from tests.fixtures import board_geometry, footprint, track
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"))         # pad 1 at (3.6, 10)
    q1 = footprint("Q1", 25, 10, nets=("VB", "OUT"))        # pad 1 at (23.6, 10)
    c1 = footprint("C1", 15, 16, nets=("VB", "GND"))        # pad 1 at (13.6, 16)
    trunk = track("VB", 3.6, 10, 23.6, 10, w=1.0)
    branch = track("VB", 13.6, 10, 13.6, 16, w=0.2)         # a T off the trunk to C1: not on the J1-Q1 path
    g = board_geometry([j1, q1, c1], copper=[trunk, branch])
    ob = {"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "Q1", "pad": "1"}, "widths": {"F.Cu": 1.0}}
    path = phase_run.joining_path(g, ob)
    assert path == [trunk] and phase_run.width_shortfall(path, ob["widths"], 0.0) == {}
    narrow = board_geometry([j1, q1, c1], copper=[track("VB", 3.6, 10, 13.6, 10, w=0.3),
                                                  track("VB", 13.6, 10, 23.6, 10, w=1.0), branch])
    assert phase_run.width_shortfall(phase_run.joining_path(narrow, ob), ob["widths"], 0.0) == {"F.Cu": 0.3}
    assert phase_run.joining_path(board_geometry([j1, q1, c1]), ob) is None


@needs_kicad
def test_a_task_the_router_refuses_stops_the_route_naming_it(rig, monkeypatch):
    monkeypatch.setenv("FAKE_ROUTER_REFUSE", "pad_not_on_net")
    with pytest.raises(RouteRefused) as e:
        rig.route({"name": "fb", "width": 0.3,
                   "connections": [{"from": {"part": "U1", "pad": "2"}, "to": {"part": "J1", "pad": "1"}}]})
    assert e.value.code == "router_refused" and e.value.facts["tasks"][0]["reason"] == "pad_not_on_net"
    assert "the router refused FB U1.2-J1.1 pad_not_on_net" in str(e.value)


@needs_kicad
def test_each_calls_copper_is_locked_before_the_next_reads_it(rig, monkeypatch):
    locked = []
    real = phase_run.lock_copper
    monkeypatch.setattr(phase_run, "lock_copper", lambda p: (locked.append(str(p)), real(p))[1])
    rig.route(LEG, FB)
    calls = rig.calls()
    assert locked[:2] == [calls[0][1], calls[1][1]]


@needs_kicad
def test_an_edit_to_a_later_phase_reroutes_it_and_after_and_reuses_the_ones_before(rig):
    rig.route(LEG, FB, {"name": "signals"})
    n = len(rig.calls())
    report = rig.route(LEG, dict(FB, width=0.3), {"name": "signals"})
    later = rig.calls()[n:]
    assert [p["reused"] for p in report.phases] == [True, False, False]
    assert _nets(later[0]) == ["FB"]


@needs_kicad
def test_a_route_stopped_in_a_phase_resumes_from_that_phase(rig, monkeypatch):
    monkeypatch.setenv("FAKE_ROUTER_FAIL", "FB")
    with pytest.raises(RouterFailed):
        rig.route(LEG, FB)
    monkeypatch.delenv("FAKE_ROUTER_FAIL")
    n = len(rig.calls())
    report = rig.route(LEG, FB)
    assert [p["reused"] for p in report.phases] == [True, False] and _nets(rig.calls()[n]) == ["FB"]


@needs_kicad
def test_a_connections_phase_writes_its_tasks_and_reads_their_outcome(rig):
    report = rig.route({"name": "leg", "width": 0.4, "connections": [{"from": {"part": "U1", "pad": "3"},
                                                                    "to": {"part": "J1", "pad": "2"}}]})
    call = rig.calls()[0]
    tasks = json.loads(open(call[call.index("--connections") + 1]).read())
    assert tasks == [{"net": "VIN", "from": {"ref": "U1", "pad": "3"}, "to": {"ref": "J1", "pad": "2"},
                      "widths": {"F.Cu": 0.4, "B.Cu": 0.4}}]
    assert report.phases[0]["connections"][0]["status"] == "routed" and report.phases[0]["asked"] == 1


@needs_kicad
def test_upto_routes_the_phases_up_to_the_one_named(rig):
    report = rig.route(LEG, FB, {"name": "signals"}, upto="fb")
    assert [p["name"] for p in report.phases] == ["vin", "fb"] and len(rig.calls()) == 2


@needs_kicad
def test_upto_routes_a_stale_earlier_phase_first(rig):
    rig.route(LEG, FB, upto="fb")
    n = len(rig.calls())
    report = rig.route(dict(LEG, width=0.6), FB, upto="fb")
    assert [p["reused"] for p in report.phases] == [False, False] and [_nets(c) for c in rig.calls()[n:]] == [["VIN"], ["FB"]]


@needs_kicad
def test_only_routes_just_that_phase_and_names_earlier_ones_with_no_copper(rig):
    report = rig.route(LEG, FB, {"name": "signals"}, upto="fb", only=True)
    assert [p["name"] for p in report.phases] == ["fb"] and [_nets(c) for c in rig.calls()] == [["FB"]]
    assert report.phases_without_copper == ["vin"]


def test_a_route_with_no_phases_is_refused_with_the_specs_words(tmp_path):
    with bind(Settings()):
        with pytest.raises(RouteRefused) as e:
            route_board(tmp_path / "x.kicad_pcb", tmp_path / "w", phases=())
    assert str(e.value) == ("route: no routing phases in placemat.toml; `placemat settings --example` writes a "
                            "placemat.toml with the default phases")


@pytest.mark.parametrize("setting, value", [("route_islands", ("VB=0.5",)), ("route_pair_layers", {"A/B": ["F.Cu"]}),
                                            ("route_net_halos", {"SW": 2.0})])
def test_a_setting_the_phases_replaced_is_refused(tmp_path, setting, value):
    with bind(Settings(**{setting: value})):
        with pytest.raises(RouteRefused) as e:
            route_board(tmp_path / "x.kicad_pcb", tmp_path / "w", phases=phases())
    assert e.value.code == "legacy_setting" and e.value.facts["setting"] == setting.split("_", 1)[1]


def test_a_refusal_on_the_channel_reads_as_the_console_says_it():
    from placemat import channel
    e = RouteRefused("unknown_phase", phase="x", phases="a, b")
    assert channel.failure_text(dict({"ev": "error", "kind": "route_refused"}, **e.record())) == str(e)
    from placemat.route_phase import PhaseError
    p = PhaseError("not_on_board", name="fb", kind="net", value="FB")
    assert channel.failure_text({"ev": "error", "kind": "route_phase", "code": p.code, "facts": p.facts}) == str(p)


def test_the_route_command_says_a_refusal_and_exits_2(tmp_path, monkeypatch, capsys):
    from placemat import cli
    import placemat.kicad.route as route_mod

    def refuse(*a, **kw):
        raise RouteRefused("no_phases")
    monkeypatch.setattr(route_mod, "route_board", refuse)
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("")
    assert cli.main(["route", str(pcb)]) == 2
    assert "route: no routing phases in placemat.toml" in capsys.readouterr().out
