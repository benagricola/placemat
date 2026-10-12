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
from tests.test_net_clearance import _two_part_board

FAKE = textwrap.dedent('''
    import json, os, shutil, sys
    a = sys.argv[1:]
    with open(os.environ["FAKE_ROUTER_LOG"], "a") as f:
        f.write(json.dumps(a) + "\\n")
    fail = os.environ.get("FAKE_ROUTER_FAIL")
    if fail and fail in a:
        sys.exit(3)
    shutil.copy(a[0], a[1])
    if os.environ.get("FAKE_ROUTER_LOWER_HOLE"):
        import pathlib
        project = pathlib.Path(a[0]).with_suffix(".kicad_pro")
        doc = json.load(open(project))
        doc["board"]["design_settings"]["rules"]["min_hole_clearance"] = 0.2
        pathlib.Path(a[1]).with_suffix(".kicad_pro").write_text(json.dumps(doc))
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
            status = ("refused" if refuse else "failed" if failed else os.environ.get("FAKE_ROUTER_STATUS") or "routed")
            wide = os.environ.get("FAKE_ROUTER_WIDE")        # routed at or above this width, failed below it
            plain = os.environ.get("FAKE_ROUTER_PLAIN")      # echo each end as {ref, pad}, as KRT does
            def said(t):
                return status if not wide else "routed" if max(t["widths"].values()) >= float(wide) else "failed"
            def end(e):
                return {"ref": e["ref"], "pad": e["pad"]} if plain else e
            doc["connections"] = [dict(t, status=said(t), reason=refuse, joined=said(t) == "routed", length_mm=1.0,
                                       min_width_mm=t["widths"], layers=list(t["widths"]),
                                       evidence=ev if failed else None, **{"from": end(t["from"]), "to": end(t["to"])})
                                  for t in tasks]
        if os.environ.get("FAKE_ROUTER_TRUNCATE") and "connections" in doc:
            doc["connections"] = doc["connections"][:-1]
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
        router = krt
        pcb = _two_part_board(tmp_path)            # FB and VIN open between U1 and J1
        work = tmp_path / "route"

        def calls(self):
            log = tmp_path / "calls"
            return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

        def route(self, *raw, settings=None, **kw):
            with bind(Settings(**(settings or {}))):
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
    open_entry = dict(report.phases[0]["open"][0])
    assert [open_entry] == [{"net": "FB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "U1", "pad": "2"},
                                         "widths": {"F.Cu": 0.2, "B.Cu": 0.2}, "outcome": None, "evidence": None}]


@needs_kicad
def test_each_phase_asks_what_the_input_board_has_open_and_is_judged_again_on_the_final_board(rig):
    report = rig.route(FB, {"name": "signals"})
    assert [(p["asked"], p["joined"]) for p in report.phases] == [(1, 0), (1, 0)]     # FB; then VIN, not FB again
    assert [p["final_closure_clean"] for p in report.phases] == [0.0, 0.0]
    assert [o["net"] for o in report.phases[1]["final_open"]] == ["VIN"]        # the rest phase leaves FB to fb
    assert [p["final_asked"] for p in report.phases] == [p["asked"] for p in report.phases]
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
    none = dict(tasks=(), pour_served=(), rest=False, nets=(), pour_nets=(), buses=(), pairs=(), width=None, layers=())
    sels = [N(**dict(none, tasks=(task,))), N(**dict(none, nets=("FB",), width=0.3, layers=("F.Cu",))),
            N(**dict(none, rest=True))]
    got = phase_run.obligations_of(sels, [fb, vin, sw], skip={"SW"})
    assert got == [[dict(leg, widths={"F.Cu": 1.0})], [dict(fb, widths={"F.Cu": 0.3})], [dict(vin, widths=None)]]


def test_a_later_short_never_makes_an_obligation_clean(tmp_path, monkeypatch):
    drc = tmp_path / "drc.json"
    drc.write_text(json.dumps({"violations": [
        {"type": "shorting_items", "severity": "error",
         "items": [{"description": "Track [FB] on F.Cu"}, {"description": "Track [VIN] on F.Cu"}]},
        {"type": "clearance", "severity": "warning",
         "items": [{"description": "Track [EN] on F.Cu"}, {"description": "Track [VIN] on F.Cu"}]},
        {"type": "silk_overlap", "severity": "error", "items": [{"description": "Track [SW] on F.Cu"}]}],
        "unconnected_items": []}))
    monkeypatch.setattr(phase_run, "joined_pairs", lambda pcb, pairs: [True] * len(pairs))
    obs = [{"net": n, "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "U1", "pad": "2"}, "widths": None}
           for n in ("FB", "EN", "SW")]
    fb, en, sw = phase_run.judge_obligations(tmp_path / "x.kicad_pcb", obs, drc)
    assert fb == {"joined": True, "violated": True, "under": {}} and not phase_run.is_clean(fb, None)
    # one rule with drc_new: the real bucket at severity error; a warning, or a kind outside the bucket, is no fault
    assert not en["violated"] and not sw["violated"]


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
                            "placemat.toml with example phases")




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


def _spans(*pieces):
    from tests.fixtures import track
    out, x = [], 0.0
    for length, w in pieces:
        out.append(track("VB", x, 10, x + length, 10, w=w))
        x += length
    return out


def test_the_width_rule_is_on_points_of_the_path_not_on_how_its_copper_is_split():
    asked = {"F.Cu": 0.4}
    whole = _spans((3.0, 0.2), (14.0, 0.4), (3.0, 0.2))                # necks of 3 mm at each end of 20 mm
    split = _spans((1.0, 0.2), (2.0, 0.2), (7.0, 0.4), (7.0, 0.4), (2.0, 0.2), (1.0, 0.2))
    assert phase_run.width_shortfall(whole, asked, 3.0) == phase_run.width_shortfall(split, asked, 3.0) == {}
    long_neck = _spans((5.0, 0.2), (15.0, 0.4))                        # 5 mm narrow: 2 mm past the allowance
    long_split = _spans((3.0, 0.2), (2.0, 0.2), (15.0, 0.4))
    assert phase_run.width_shortfall(long_neck, asked, 3.0) == phase_run.width_shortfall(long_split, asked, 3.0) \
        == {"F.Cu": 0.2}
    assert phase_run.width_shortfall(whole, asked, 0.0) == {"F.Cu": 0.2}         # neckdown = false: no allowance


def test_a_short_connection_keeps_its_width_obligation():
    asked = {"F.Cu": 0.4}
    assert phase_run.width_shortfall(_spans((4.0, 0.2)), asked, 3.0) == {"F.Cu": 0.2}
    assert phase_run.width_shortfall(_spans((2.0, 0.2), (2.0, 0.2)), asked, 3.0) == {"F.Cu": 0.2}
    assert phase_run.width_shortfall(_spans((1.5, 0.2), (1.0, 0.4), (1.5, 0.2)), asked, 3.0) == {}   # full width mid


def test_the_widths_are_judged_on_the_part_of_a_track_the_path_runs_along():
    from tests.fixtures import board_geometry, footprint, track
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"))         # pad 1 at (3.6, 10)
    c1 = footprint("C1", 15, 16, nets=("VB", "GND"))        # pad 1 at (13.6, 16)
    long = track("VB", 3.6, 10, 33.6, 10, w=1.0)            # runs on past the T to C1
    branch = track("VB", 13.6, 10, 13.6, 16, w=1.0)
    g = board_geometry([j1, c1], copper=[long, branch])
    ob = {"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "C1", "pad": "1"}, "widths": {"F.Cu": 1.0}}
    assert sum(length for _, length in phase_run.joining_spans(g, ob)) == pytest.approx(16.0)


def test_each_pad_pair_is_asked_once():
    from types import SimpleNamespace as N
    fb = {"net": "FB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "U1", "pad": "2"}}
    flipped = {"net": "FB", "from": {"ref": "U1", "pad": "2"}, "to": {"ref": "J1", "pad": "1"}}
    sel = N(tasks=(), pour_served=(), rest=True, nets=(), pour_nets=(), buses=(), pairs=(), width=None, layers=())
    assert phase_run.obligations_of([sel], [fb, dict(fb), flipped], skip=set()) == [[dict(fb, widths=None)]]


@needs_kicad
def test_a_changed_rise_c_routes_every_phase_again(rig):
    rig.route(LEG, FB)
    again = rig.route(LEG, FB, settings={"check_rise_c": 20.0})
    assert [p["reused"] for p in again.phases] == [False, False]


@needs_kicad
def test_a_phase_whose_judgement_failed_keeps_its_routing_and_is_judged_on_the_rerun(rig, monkeypatch):
    real = phase_run.judge_phase

    def broken(*a, **kw):
        raise RuntimeError("kicad-cli drc wrote no report")
    monkeypatch.setattr(phase_run, "judge_phase", broken)
    with pytest.raises(RuntimeError):
        rig.route(LEG)
    n = len(rig.calls())
    monkeypatch.setattr(phase_run, "judge_phase", real)
    report = rig.route(LEG)
    assert len(rig.calls()) == n and report.phases[0]["asked"] == 1 and report.resumed == ["vin"]


@needs_kicad
def test_widths_failed_counts_joined_narrow_outcomes(rig, monkeypatch):
    monkeypatch.setenv("FAKE_ROUTER_STATUS", "joined_narrow")
    monkeypatch.setattr(phase_run, "judge_obligations",
                        lambda pcb, obs, drc, neck=0.0, is_real=None, baseline_json=None: [{"joined": True, "violated": False, "under": {}}
                                                                        for _ in obs])
    report = rig.route({"name": "leg", "width": 0.4, "connections": [{"from": {"part": "U1", "pad": "3"},
                                                                    "to": {"part": "J1", "pad": "2"}}]})
    assert report.widths_failed == 1 and report.phases[0]["final_closure_clean"] == 0.0


def test_a_refusal_carries_facts_not_sentences(tmp_path):
    from placemat.kicad.route import refused_text
    text = refused_text("capture", {"path": "b/nets.layout.json", "reason": "stale",
                                    "detail": {"file": "default.net"}})
    assert text == "route: b/nets.layout.json: stale file default.net"


def test_a_pair_call_takes_the_phases_router_flags():
    from placemat.kicad.route import pair_command
    with bind(Settings()):
        cmd = pair_command("py", "route_diff.py", "i", "o", ("P",), ["F.Cu"], extra_args=("--via-cost", "9"))
    assert cmd[-2:] == ["--via-cost", "9"]


def test_a_pair_phase_with_a_flag_the_pair_router_lacks_is_refused():
    from placemat.kicad.route import pair_flags_refused
    caps = {"flags": {"route_diff.py": ["--via-cost", "--diff-pair-gap"], "route.py": ["--neckdown-length"]}}
    pair, rest = phases({"name": "usb", "pairs": [["P", "N"]], "router_args": ["--via-cost", "9", "--neckdown-length=2"]},
                        {"name": "signals", "router_args": ["--neckdown-length", "2"]})
    assert pair_flags_refused(caps, [pair, rest]) == [{"phase": "usb", "flag": "--neckdown-length"}]
    assert pair_flags_refused(None, [pair]) == [{"phase": "usb", "flag": "--via-cost"},
                                                {"phase": "usb", "flag": "--neckdown-length"}]


@needs_kicad
def test_a_route_with_such_a_pair_phase_is_refused_before_it_routes(rig):
    with pytest.raises(RouteRefused) as e:
        rig.route({"name": "pair", "pairs": [["FB", "VIN"]], "router_args": ["--neckdown-length", "2"]})
    assert e.value.code == "pair_flag" and e.value.facts == {"phase": "pair", "flag": "--neckdown-length"}
    assert str(e.value).startswith("route: phase 'pair': router_args --neckdown-length is not a flag of the pair router")
    assert rig.calls() == []


def test_a_negative_number_in_a_pair_phases_router_args_is_a_value_not_a_flag():
    from placemat.kicad.route import pair_flags_refused
    caps = {"flags": {"route_diff.py": ["--track-width", "--via-cost"]}}
    (pair,) = phases({"name": "usb", "pairs": [["P", "N"]], "router_args": ["--track-width", "-1", "--via-cost=9"]})
    assert pair_flags_refused(caps, [pair]) == []


@needs_kicad
def test_capture_clearance_reaches_every_phase_call_and_setup_report(rig):
    from tests.test_capture_nets import write
    write(rig.pcb.parent, nets={"SW": {"type": "Power", "fields": {"clearance": {"value": 2.0, "unit": "mm"}}}})
    said = []
    report = rig.route(FB, {"name": "signals"}, on_setup=said.extend)
    calls = rig.calls()
    assert calls and all("--net-clearances" in c for c in calls)
    path = calls[0][calls[0].index("--net-clearances") + 1]
    assert json.loads(open(path).read())["SW"] == 2.0
    assert report.net_clearances == {"SW": 2.0}
    assert said and all(f.cause.value == "setup.net_clearance" for f in said)
    assert report.as_dict()["net_clearance_trapped"]


@needs_kicad
def test_width_findings_survive_a_judge_only_resume(rig, monkeypatch):
    original = phase_run.judge_phase
    failed = [False]
    record = {"net": "VIN", "stage": "vin", "requested_mm": 0.5, "delivered_min_mm": 0.2,
              "length_under_mm": 1.0, "length_mm": 1.0, "share": 1.0, "declared": True,
              "max_a": None, "bottleneck_mm": None}
    monkeypatch.setattr(phase_run, "phase_widths", lambda *a: [record])

    def stop_once(*args):
        if not failed[0]:
            failed[0] = True
            raise RuntimeError("judge failed")
        return original(*args)

    monkeypatch.setattr(phase_run, "judge_phase", stop_once)
    with pytest.raises(RuntimeError, match="judge failed"):
        rig.route(LEG)
    calls = len(rig.calls())
    report = rig.route(LEG)
    assert len(rig.calls()) == calls
    assert report.phases[0]["widths"] == [record] and report.widths == [record]


@needs_kicad
@pytest.mark.parametrize("flag", ["--clearance-ceiling", "--clearance-ceil"])
def test_phase_clearance_ceiling_uses_full_arg_order_and_preserves_capture_floor(rig, flag):
    from tests.test_capture_nets import write
    krt = rig.pcb.parent.parent / "krt"
    (krt / "py_router/list_nets.py").write_text(
        'def net_clearance_map_by_id(pcb_path, nets, design_rules=None):\n    return {n: 0.8 for n in nets}\n')
    write(rig.pcb.parent, nets={"SW": {"type": "Power", "fields": {"clearance": {"value": 2.0, "unit": "mm"}}}})
    rig.route(dict(FB, router_args=[flag, "0.4"]),
              {"name": "signals", "router_args": [flag + "=0.2"]},
              settings={"route_router_args": ("--clearance-ceiling", "0.5")})
    maps = [json.loads(open(c[c.index("--net-clearances") + 1]).read()) for c in rig.calls()]
    assert maps and {m["FB"] for m in maps} == {0.4, 0.2}
    assert all(m["SW"] == 2.0 for m in maps)


@needs_kicad
def test_current_bus_call_carries_tasks_and_bundle_flags(rig):
    rig.pcb.write_text(rig.pcb.read_text().replace('(property "Reference"', '(property "Pm.I" "VIN:1A") (property "Reference"'))
    result = rig.route({"name": "bus", "buses": [["VIN"]], "width": "current"})
    call, = rig.calls()
    assert "--connections" in call and call[call.index("--bus-nets") + 1] == "VIN"
    task, = json.loads(open(call[call.index("--connections") + 1]).read())
    assert task["net"] == "VIN" and all(w > 0 for w in task["widths"].values())
    assert result.phases[0]["connections"][0]["net"] == "VIN"


@needs_kicad
def test_a_truncated_task_summary_fails_without_dropping_obligations(rig, monkeypatch):
    monkeypatch.setenv("FAKE_ROUTER_TRUNCATE", "1")
    with pytest.raises(RouterFailed) as err:
        rig.route({"name": "leg", "width": 0.5, "connections": [{"from": {"part": "U1", "pad": "3"}, "to": {"part": "J1", "pad": "2"}}]})
    assert err.value.code == "malformed_summary" and err.value.facts["reason"] == "task_count"


@needs_kicad
def test_router_rule_writeback_cannot_weaken_phase_or_final_grading(rig, monkeypatch):
    from placemat.kicad import route
    from pathlib import Path
    project = rig.pcb.with_suffix(".kicad_pro")
    data = json.loads(project.read_text()) if project.exists() else {}
    data.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rules", {})["min_hole_clearance"] = 0.25
    project.write_text(json.dumps(data))
    custom = rig.pcb.with_suffix(".kicad_dru")
    custom.write_text('(version 1)\n(rule "original" (constraint hole_clearance (min 0.25mm)))\n')
    monkeypatch.setenv("FAKE_ROUTER_LOWER_HOLE", "1")
    checked = []
    real = route.run_drc
    def original_rules(pcb, *args, **kwargs):
        pcb = Path(pcb)
        assert json.loads(pcb.with_suffix(".kicad_pro").read_text())["board"]["design_settings"]["rules"]["min_hole_clearance"] == 0.25
        assert pcb.with_suffix(".kicad_dru").read_bytes() == custom.read_bytes()
        checked.append(pcb.name)
        return real(pcb, *args, **kwargs)
    monkeypatch.setattr(route, "run_drc", original_rules)
    monkeypatch.setattr(phase_run, "run_drc", original_rules)
    rig.route(FB, {"name": "signals"})
    assert {"in.kicad_pcb", "p0_drc.kicad_pcb", "p1_drc.kicad_pcb", "routed.kicad_pcb"} <= set(checked)


@needs_kicad
def test_missing_width_policy_refuses_before_any_router_call(rig):
    krt = rig.work.parent / 'krt'
    (krt / 'py_router/nominal_width_policy.py').unlink()
    with pytest.raises(RouteRefused) as error:
        rig.route(FB)
    assert error.value.code == 'width_policy_unavailable'
    assert rig.calls() == []
    assert error.value.facts['script'].endswith('nominal_width_policy.py')
    receipt = json.loads((rig.work / 'width_policy.json').read_text())
    assert receipt['failure']['code'] == 'unavailable'


@needs_kicad
def test_a_failed_width_query_refuses_the_route_naming_its_failure(rig):
    krt = rig.work.parent / 'krt'
    (krt / 'py_router/nominal_width_policy.py').write_text('import sys; sys.exit(3)\n')
    with pytest.raises(RouteRefused) as error:
        rig.route(FB)
    assert error.value.code == 'width_policy_failed' and rig.calls() == []
    assert error.value.facts['failure'] == 'failed' and error.value.facts['exit_code'] == 3


@needs_kicad
@pytest.mark.parametrize('changed', ['earlier_width', 'global_flags', 'original_rules', 'unknown_to_known'])
def test_a_changed_width_or_rule_routes_every_phase_again(rig, monkeypatch, changed):
    from placemat.kicad import width_policy
    if changed == 'unknown_to_known':
        original_resolve = width_policy.resolve
        state = {'known': False}
        def resolve(*args, **kwargs):
            result = original_resolve(*args, **kwargs)
            if not state['known']:
                for record in result['policies']:
                    for entry in record['by_net'].values():
                        entry.update(status='unknown', widths=None, reason='test unproved initial policy')
            return result
        monkeypatch.setattr(width_policy, 'resolve', resolve)
    rig.route(LEG, FB, {'name': 'signals'})
    n = len(rig.calls())
    leg, settings = LEG, None
    if changed == 'earlier_width':
        leg = dict(LEG, width=.7)
    elif changed == 'global_flags':
        settings = {'route_router_args': ('--track-width', '0.3')}
    elif changed == 'original_rules':
        project = rig.pcb.with_suffix('.kicad_pro')
        doc = json.loads(project.read_text())
        doc.setdefault('board', {}).setdefault('design_settings', {}).setdefault('rules', {})['min_hole_clearance'] = .3
        project.write_text(json.dumps(doc))
    else:
        state['known'] = True
    report = rig.route(leg, FB, {'name': 'signals'}, settings=settings)
    assert [record['reused'] for record in report.phases] == [False, False, False]
    assert len(rig.calls()) > n


@needs_kicad
def test_a_reference_two_footprints_share_routes_and_is_said_as_a_setup_finding(rig, tmp_path):
    text = rig.pcb.read_text()
    second = ('\t(footprint "t:p" (layer "F.Cu") (at 125 115)\n\t\t(property "Reference" "J1" (at 0 -2 0) '
              '(layer "F.SilkS"))\n\t\t(pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu" "F.Mask") (net "FB"))\n\t)\n')
    i = text.index("\t(segment")
    rig.pcb.write_text(text[:i] + second + text[i:])
    said = []
    report = rig.route(FB, on_setup=said.extend)
    (f,) = [f for f in said if f.cause.value == "setup.duplicate_reference"]
    assert f.facts["ref"] == "J1" and f.facts["nets"] == ["FB"] and len(f.facts["footprints"]) == 2
    assert [g.facts for g in report.setup_findings() if g.cause.value == "setup.duplicate_reference"] == [f.facts]
    assert report.phases[0]["asked"] == 2


def test_a_pair_phase_flag_is_read_as_the_pair_router_abbreviates_it():
    from placemat.kicad.route import pair_flags_refused
    caps = {"flags": {"route_diff.py": ["--track-width", "--track-proximity-cost", "--via-cost"]}}
    (pair,) = phases({"name": "usb", "pairs": [["P", "N"]], "router_args": ["--track-w", "0.3", "--via=2", "--track"]})
    assert pair_flags_refused(caps, [pair]) == [{"phase": "usb", "flag": "--track"}]



def _second_j1(rig, amps=None):
    """A second footprint with reference J1, its pad 1 on FB; each footprint states `amps` (U1, J1, the new J1)."""
    text = rig.pcb.read_text()
    def prop(a):
        return '\t\t(property "Pm.I" "%s" (at 0 0 0) (layer "F.Fab"))\n' % a if a else ""
    second = ('\t(footprint "t:p" (layer "F.Cu") (at 125 115)\n\t\t(property "Reference" "J1" (at 0 -2 0) '
              '(layer "F.SilkS"))\n%s\t\t(pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu" "F.Mask") (net "FB"))\n\t)\n'
              % prop(amps and amps[2]))
    if amps:
        for ref, a in (("U1", amps[0]), ("J1", amps[1])):
            mark = '(property "Reference" "%s" (at 0 -2 0) (layer "F.SilkS"))\n' % ref
            text = text.replace(mark, mark + prop(a), 1)
    i = text.index("\t(segment")
    rig.pcb.write_text(text[:i] + second + text[i:])


@needs_kicad
def test_route_calls_give_each_router_record_its_own_footprint(rig, monkeypatch):
    """Two J1s on FB at 1 A and 4 A: the 4 A task is sent first (widest first), the 1 A one after, and the router
    echoes both ends as plain ref and pad. Each obligation still takes its own task's record."""
    _second_j1(rig, amps=("4A", "1A", "4A"))
    monkeypatch.setenv("FAKE_ROUTER_PLAIN", "1")
    monkeypatch.setenv("FAKE_ROUTER_WIDE", "0.5")
    report = rig.route({"name": "c", "width": "current", "connections": [
        {"from": {"part": "U1", "pad": "2"}, "to": {"part": "J1", "pad": "1"}}]})
    (phase,) = report.phases
    by_fp = {o["to"].get("fp") or o["from"].get("fp"): o for o in phase["open"]}
    widths = {k: max(o["widths"].values()) for k, o in by_fp.items()}
    assert len(by_fp) == 2 and all(k for k in by_fp)
    for k, o in by_fp.items():
        assert o["outcome"] == ("routed" if widths[k] >= 0.5 else "failed")
    assert all((r["to"].get("fp") or r["from"].get("fp")) for r in phase["connections"])


@needs_kicad
def test_a_refused_task_on_a_shared_reference_names_its_footprint(rig, monkeypatch):
    _second_j1(rig)
    monkeypatch.setenv("FAKE_ROUTER_PLAIN", "1")
    monkeypatch.setenv("FAKE_ROUTER_REFUSE", "pad_not_on_net")
    with pytest.raises(RouteRefused) as e:
        rig.route({"name": "c", "width": 0.3, "connections": [
            {"from": {"part": "U1", "pad": "2"}, "to": {"part": "J1", "pad": "1"}}]})
    ends = [t["to"] if t["to"]["ref"] == "J1" else t["from"] for t in e.value.facts["tasks"]]
    assert len({end["fp"] for end in ends}) == 2


def _vin_pour(pcb, left, right):
    """Both parts carry current (Pm.I) and VIN has a filled F.Cu pour over x = left..right, y = 108..112."""
    import pcbnew
    pcb.write_text(pcb.read_text().replace('(property "Reference"', '(property "Pm.I" "1A") (property "Reference"'))
    brd = pcbnew.LoadBoard(str(pcb))
    z = pcbnew.ZONE(brd)
    z.SetLayer(pcbnew.F_Cu)
    z.SetNetCode(brd.GetNetcodeFromNetname("VIN"))
    o = z.Outline()
    o.NewOutline()
    for x, y in ((left, 108), (right, 108), (right, 112), (left, 112)):
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    brd.Add(z)
    pcbnew.ZONE_FILLER(brd).Fill(brd.Zones())
    brd.Save(str(pcb))


@needs_kicad
@pytest.mark.parametrize("left, right, joined", [(112.5, 127, True), (125.6, 127, False)])
def test_a_current_paths_phase_asks_the_pour_for_its_pour_nets_connections(rig, left, right, joined):
    """Ruling S13: VIN's connection is not routed; the pour over both carriers' VIN pads joins it, a pour over one
    leaves it open, counted in the phase's closure and named in its line."""
    from placemat.kicad.route import phase_lines
    _vin_pour(rig.pcb, left, right)
    report = rig.route({"name": "current", "current_paths": True, "width": "current"}, pour_nets={"VIN"})
    calls = rig.calls()
    assert not any("VIN" in c for c in calls)                     # no call routes VIN
    (p,) = report.phases
    (served,) = p["pour_served"]
    assert served["net"] == "VIN" and served["joined"] is joined
    vin_open = [o for o in p["open"] if o["net"] == "VIN"]
    assert bool(vin_open) is not joined and p["asked"] == 2       # FB's task and VIN's, asked of the pour
    (line,) = phase_lines(report.phases, (), report.pour_routed_by)
    if joined:
        assert "left to their pours: VIN 1 connection" in line and "not reached" not in line
    else:
        assert "not reached by the pour: VIN " in line and "left to their pours" not in line


@needs_kicad
def test_a_later_phase_that_names_the_pour_net_routes_it(rig):
    _vin_pour(rig.pcb, 125.6, 127)
    report = rig.route({"name": "current", "current_paths": True, "width": "current"}, {"name": "vin", "nets": ["VIN"]},
                       pour_nets={"VIN"})
    assert report.pour_routed_by == {"VIN": "vin"}
    assert any("VIN" in _nets(c) for c in rig.calls())
