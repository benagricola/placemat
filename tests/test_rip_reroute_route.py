"""Rip and reroute through a whole route: a stand-in router that lays copper (tests/rip_helpers.py), real pcbnew and
DRC."""
import json

import pytest

from placemat.kicad.route import copper_items, route_board
from placemat.settings import Settings, bind
from tests.conftest import needs_kicad
from tests.phase_helpers import phases
from tests.rip_helpers import rip_board, toy_router


@pytest.fixture
def toy(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    krt = toy_router(tmp_path)
    monkeypatch.setenv("FAKE_ROUTER_LOG", str(tmp_path / "calls"))

    class Toy:
        def calls(self):
            log = tmp_path / "calls"
            return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

        def route(self, *raw, pcb=None, settings=None, **kw):
            with bind(Settings(**(settings or {}))):
                return route_board(pcb or rip_board(tmp_path), tmp_path / "route", router_dir_override=str(krt),
                                   layers=["F.Cu", "B.Cu"], phases=phases(*raw), **kw)
    return Toy()


A = {"name": "a", "nets": ["A"]}
B = {"name": "b", "nets": ["B"]}


@needs_kicad
def test_every_phase_records_its_rip_and_rip_off_changes_nothing(toy):
    report = toy.route(A, B, settings={"route_rip_attempts": 0})
    assert [p["rip"] for p in report.phases] == [{"attempts": [], "skipped": []}] * 2
    assert [p["joined"] for p in report.phases] == [1, 0]


@needs_kicad
def test_a_later_phase_moves_an_earlier_phases_copper_and_both_join_clean(toy):
    report = toy.route(A, B)
    a, b = report.phases
    assert [x["kept"] for x in b["rip"]["attempts"]] == [True]
    att = b["rip"]["attempts"][0]
    assert att["victims"] == ["A"] and att["named"] == [{"net": "A", "found_by": "preexisting"}]
    assert att["removed"] == {"tracks": 1, "arcs": 0, "vias": 0, "track_mm": 20.0}
    assert [(r["phase"], r["index"], r["net"], r["status"], r["asked"]) for r in att["rerouted"]] == [
        ("a", 0, "A", "routed", True)]
    assert b["joined"] == 1 and a["final_closure_clean"] == 1.0 and b["final_closure_clean"] == 1.0
    assert a["final_joined"] == 1
    assert ("segment", "A", 0, (105.0, 110.0, 125.0, 110.0)) not in copper_items(report.routed_pcb)


@needs_kicad
def test_an_attempt_that_would_lose_an_earlier_connection_is_restored(toy, monkeypatch, tmp_path):
    monkeypatch.setenv("TOY_DETOUR", "0")                  # A cannot go round B
    report = toy.route(A, B)
    att = report.phases[1]["rip"]["attempts"][0]
    assert (att["kept"], att["reason"]) == (False, "obligation_worse")
    assert att["worse"] == [{"phase": "a", "net": "A", "from": {"ref": "P1", "pad": "1"},
                             "to": {"ref": "P2", "pad": "1"}, "before": "clean", "after": "open"}]
    assert report.phases[0]["final_closure_clean"] == 1.0 and report.phases[1]["joined"] == 0
    work = tmp_path / "route"
    assert copper_items(work / "p1_0.kicad_pcb") == copper_items(work / "router_out.kicad_pcb")


@needs_kicad
def test_a_later_call_of_the_same_phase_moves_the_earlier_calls_copper(toy, monkeypatch):
    from placemat.kicad import net_clearance
    monkeypatch.setattr(net_clearance, "class_clearances", lambda *a, **kw: {"A": 0.3})
    report = toy.route({"name": "signals"})
    (p,) = report.phases
    nets = [c[c.index("--nets") + 1:c.index("--layers")] for c in toy.calls() if "--nets" in c]
    assert nets[:2] == [["A"], ["*", "!A"]]                   # A alone (its clearance), then the rest
    assert len(p["rip"]["attempts"]) == 1
    att = p["rip"]["attempts"][0]
    assert (att["call"], att["kept"], att["rerouted"][0]["phase"]) == (1, True, "signals")
    assert p["final_closure_clean"] == 1.0


@needs_kicad
def test_script_copper_is_never_moved(toy, tmp_path):
    report = toy.route(B, pcb=rip_board(tmp_path, a_track=True))
    rip = report.phases[0]["rip"]
    assert rip["attempts"] == []
    assert rip["skipped"] == [{"call": 0, "net": "B", "named": [{"net": "A", "found_by": "preexisting"}],
                               "not_ripped": [{"net": "A", "reason": "no_router_copper"}], "reason": "no_victim"}]


@needs_kicad
def test_a_current_paths_owner_moves_at_its_current_widths_layers_and_neckdown(toy, tmp_path):
    legs = {"name": "legs", "current_paths": True, "layers": ["F"], "neckdown": False}
    report = toy.route(legs, B, pcb=rip_board(tmp_path, currents=True))
    att = report.phases[1]["rip"]["attempts"][0]
    asked = report.asked[0][0]["widths"]                       # the legs phase's current width, F.Cu only
    assert set(asked) == {"F.Cu"} and asked["F.Cu"] > 0.2
    assert att["kept"] and att["rerouted"][0]["widths"] == asked
    moved = [c for c in toy.calls() if "--connections" in c and "rip0_v0" in c[c.index("--connections") + 1]]
    assert moved and moved[0][moved[0].index("--layers") + 1:moved[0].index("--escalation")] == ["F.Cu"]
    assert "--no-power-tap-neckdown" in moved[0]
    assert report.phases[0]["final_closure_clean"] == 1.0


@needs_kicad
def test_joins_no_phase_asks_move_at_the_settings_of_the_phase_that_made_them(toy, tmp_path):
    legs = {"name": "legs", "current_paths": True, "layers": ["F"]}
    report = toy.route(legs, {"name": "signals"}, {"name": "b2", "nets": ["B"]},
                       pcb=rip_board(tmp_path, currents=True, third=True))
    legs_r, signals, b2 = report.phases
    # the rest call laid A's leftover leg (P2-P3) itself, so it may not move A
    assert [(s["net"], s["reason"], s["not_ripped"]) for s in signals["rip"]["skipped"]] == [
        ("B", "no_victim", [{"net": "A", "reason": "routed_by_call"}])]
    att = b2["rip"]["attempts"][0]
    assert att["kept"] and att["removed"]["tracks"] == 2
    got = [(r["phase"], r["index"], frozenset((r["from"]["ref"], r["to"]["ref"])), r["asked"]) for r in att["rerouted"]]
    assert got == [("legs", 0, frozenset(("P1", "P2")), True), ("signals", 1, frozenset(("P2", "P3")), False)]
    assert b2["joined"] == 1 and legs_r["final_closure_clean"] == 1.0


@needs_kicad
def test_only_takes_the_given_boards_copper_as_the_scripts(toy, tmp_path):
    report = toy.route(A, B, pcb=rip_board(tmp_path, a_track=True), upto="b", only=True)
    (b,) = report.phases
    assert b["rip"]["attempts"] == []
    assert b["rip"]["skipped"][0]["not_ripped"] == [{"net": "A", "reason": "no_router_copper"}]


@needs_kicad
def test_a_router_failure_in_an_attempt_restores_and_ends_the_calls_attempts(toy, monkeypatch):
    import placemat.kicad.rip_reroute as rr_mod
    from placemat.kicad.route import RouterFailed

    def broken(*a, **kw):
        raise RouterFailed("stand-in", 3, "/dev/null", "")
    monkeypatch.setattr(rr_mod, "route_tasks", broken)        # rip_reroute imports route_tasks at module level
    report = toy.route(A, B)
    att = report.phases[1]["rip"]["attempts"][0]
    assert (att["kept"], att["reason"], att["router"]["exit_code"]) == (False, "router_failed", 3)
    assert report.phases[1]["joined"] == 0 and report.phases[0]["final_closure_clean"] == 1.0


@needs_kicad
def test_the_net_limit_skips_a_unit_naming_too_many_nets(toy):
    report = toy.route(A, B, settings={"route_rip_max_nets": 0})
    assert report.phases[1]["rip"]["skipped"][0]["reason"] == "too_many_victims"


@needs_kicad
def test_the_attempt_limit_skips_the_calls_later_units(toy, tmp_path):
    report = toy.route(A, {"name": "b", "nets": ["B", "C"]}, pcb=rip_board(tmp_path, c_net=True),
                       settings={"route_rip_attempts": 1})
    rip = report.phases[1]["rip"]
    assert [(a["blocked"][0]["net"], a["kept"]) for a in rip["attempts"]] == [("B", True)]
    assert [(s["net"], s["reason"]) for s in rip["skipped"]] == [("C", "limit")]


@needs_kicad
def test_a_victim_set_restored_once_is_not_tried_again_in_the_call(toy, tmp_path, monkeypatch):
    monkeypatch.setenv("TOY_DETOUR", "0")                  # A cannot go round: the first attempt is restored
    report = toy.route(A, {"name": "b", "nets": ["B", "C"]}, pcb=rip_board(tmp_path, c_net=True))
    rip = report.phases[1]["rip"]
    assert [(a["blocked"][0]["net"], a["kept"]) for a in rip["attempts"]] == [("B", False)]
    assert [(s["net"], s["reason"]) for s in rip["skipped"]] == [("C", "tried")]


@needs_kicad
def test_a_moved_connection_replaces_its_earlier_record_and_width_rows(toy, monkeypatch):
    monkeypatch.setenv("TOY_NARROW", "A")                  # phase a's call lays A at half width: joined_narrow
    a = {"name": "a", "connections": [{"from": {"part": "P1", "pad": "1"}, "to": {"part": "P2", "pad": "1"}}]}
    report = toy.route(a, B)
    assert report.phases[0]["connections"][0]["status"] == "joined_narrow"   # phase a's own record stands
    assert report.phases[1]["rip"]["attempts"][0]["kept"]
    assert report.phases[0]["final_closure_clean"] == 1.0                     # read from the moved record
    assert not [w for w in report.widths if w.get("stage") == "a" and w.get("net") == "A"]


@needs_kicad
def test_a_moved_nets_summary_row_is_reported_once_under_its_owner(toy, monkeypatch):
    monkeypatch.setenv("TOY_SUMMARY_NARROW", "A")          # every call that lays A says it shipped A narrow
    report = toy.route(A, B)
    assert report.phases[1]["rip"]["attempts"][0]["kept"]
    # phase a's call's row describes copper the attempt took off; the reroute's row is phase a's
    assert [(w["net"], w["stage"]) for w in report.widths] == [("A", "a")]


@needs_kicad
def test_a_moved_nets_summary_row_from_an_earlier_call_of_the_phase_goes(toy, monkeypatch):
    from placemat.kicad import net_clearance
    monkeypatch.setattr(net_clearance, "class_clearances", lambda *a, **kw: {"A": 0.3})
    monkeypatch.setenv("TOY_SUMMARY_NARROW", "A")
    report = toy.route({"name": "signals"})
    assert report.phases[0]["rip"]["attempts"][0]["kept"]
    assert [(w["net"], w["stage"]) for w in report.widths] == [("A", "signals")]
