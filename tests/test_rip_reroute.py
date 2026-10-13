"""Rip and reroute (kicad/rip_reroute.py): the pure parts."""
from placemat.kicad import rip_reroute as rr
from placemat.settings import Settings


def test_rip_and_reroute_is_on_by_default_with_its_limits():
    s = Settings()
    assert (s.route_rip_attempts, s.route_rip_max_nets) == (4, 3)


def test_a_negative_rip_limit_is_refused_at_load(tmp_path):
    import pytest
    from placemat.settings import SettingsError, load
    for key in ("rip_attempts", "rip_max_nets"):
        (tmp_path / "placemat.toml").write_text("[route]\n%s = -1\n" % key)
        with pytest.raises(SettingsError):
            load(tmp_path)
    (tmp_path / "placemat.toml").write_text("[route]\nrip_attempts = 0\nrip_max_nets = 0\n")
    assert (load(tmp_path).route_rip_attempts, load(tmp_path).route_rip_max_nets) == (0, 0)


def _ev(*blocked):
    return {"scope": "net", "search": None, "verdicts": [], "narrow": [], "diagnosis": "unknown",
            "blocked_by": list(blocked)}


def _pre(net):
    return {"found_by": "preexisting", "kind": "copper", "net": net}


def _rec(net, status, *blocked, a=("U1", "1"), b=("J1", "2")):
    return {"net": net, "from": {"ref": a[0], "pad": a[1]}, "to": {"ref": b[0], "pad": b[1]},
            "widths": {"F.Cu": 0.2}, "status": status, "evidence": _ev(*blocked) if blocked else None}


def test_a_task_call_blocks_each_net_with_a_failed_task_whose_router_names_other_copper():
    recs = [_rec("N", "failed", _pre("V"), {"found_by": "static", "kind": "track", "net": "W"},
                 {"found_by": "static", "kind": "pad", "net": "X", "ref": "U9"},
                 {"found_by": "frontier", "kind": "routed_copper", "net": "Y"}),
            _rec("N", "failed", _pre("V"), a=("U1", "3")),
            _rec("M", "routed"),
            _rec("K", "failed")]                      # no evidence: nothing named
    got = rr.blocked_of("tasks", recs)
    assert [(u.net, [n.record() for n in u.named], len(u.connections)) for u in got] == [
        ("N", [{"net": "V", "found_by": "preexisting"}, {"net": "W", "found_by": "static"}], 2)]
    assert got[0].connections[0] == {"net": "N", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "J1", "pad": "2"},
                                     "widths": {"F.Cu": 0.2}}


def test_a_whole_net_call_reads_net_evidence_and_the_preexisting_blockers():
    summary = {"net_evidence": {"N": _ev(), "M": _ev(_pre("W"))},
               "blockers": [{"net": "N", "stage": "preexisting", "blocked_by": [{"net": "V", "preexisting": True}]},
                            {"net": "M", "stage": "phase3", "blocked_by": [{"net": "Z"}]},
                            {"net": "K", "stage": "preexisting", "blocked_by": [{"net": "V", "preexisting": True}]}]}
    got = rr.blocked_of("rest", summary=summary)
    assert [(u.net, [n.net for n in u.named], u.connections) for u in got] == [("N", ["V"], ()), ("M", ["W"], ())]


def test_a_pair_call_blocks_nothing():
    assert rr.blocked_of("pairs", [_rec("N", "failed", _pre("V"))], {"blockers": []}) == []


def test_victims_are_named_nets_with_router_copper_laid_before_the_call():
    unit = rr.Blocked("N", tuple(rr.Named(n, "preexisting") for n in ("N", "S", "L", "P", "D", "X", "V")))
    victims, skipped = rr.victims_of(unit, router_nets={"L": 3, "P": 2, "D": 2, "X": 1, "V": 4}, laid_by_call={"L"},
                                     pour_nets={"P"}, pair_nets={"D"}, excluded={"X"})
    assert victims == ("V",)
    assert skipped == ({"net": "N", "reason": "own_net"}, {"net": "S", "reason": "no_router_copper"},
                       {"net": "L", "reason": "routed_by_call"}, {"net": "P", "reason": "pour_net"},
                       {"net": "D", "reason": "pair_net"}, {"net": "X", "reason": "excluded"})


def test_a_phases_settings_are_its_clearances_layers_and_flags(tmp_path, monkeypatch):
    import types
    from placemat.kicad import phase_run, net_clearance
    from placemat.route_phase import parse_phases
    from placemat.settings import Settings
    phase = parse_phases(({"name": "legs", "layers": ["F"], "neckdown": False, "router_args": ["--via-cost", "9"]},))[0]
    sel = types.SimpleNamespace(layers=("F.Cu",))
    ctx = types.SimpleNamespace(cfg=Settings(), class_clearances={"A": 0.3}, stated_clearances={"B": 0.5}, env={},
                                geometry=types.SimpleNamespace(default_clearance=0.2), work=tmp_path,
                                iterations=None, probe=None, quick=True)
    got = phase_run.phase_settings(ctx, phase, sel, "p0_1_rip0_v0")
    assert got.layers == ("F.Cu",) and got.clearance_map["A"] == 0.3 and got.clearance_map["B"] == 0.5
    assert got.clearances_file == tmp_path / "p0_1_rip0_v0_net_clearances.json" and got.clearances_file.exists()
    assert got.common["neckdown"] is False and got.common["extra_args"] == ("--via-cost", "9")
    assert got.common["clearances"] == got.clearances_file


def _ob(net, a, b, widths=None):
    return {"net": net, "from": {"ref": a[0], "pad": a[1]}, "to": {"ref": b[0], "pad": b[1]},
            "widths": widths if widths is not None else {"F.Cu": 0.2, "B.Cu": 0.2}}


def test_the_asked_moves_are_the_victims_joined_obligations_owned_by_the_earliest_phase_asking():
    legs = [_ob("V", ("U1", "1"), ("J1", "1"), {"F.Cu": 1.2})]
    signals = [_ob("V", ("J1", "1"), ("U1", "1")), _ob("V", ("U1", "1"), ("C1", "1")), _ob("V", ("C2", "1"), ("U1", "1")),
               _ob("N", ("Q1", "1"), ("Q2", "1"))]
    moves, why = rr.asked_moves({"V"}, [legs, signals], 1, [[True], [True, True, False, False]])
    assert why is None
    assert [(m.owner, m.obligation["to"]["ref"], m.asked) for m in moves] == [(0, "J1", True), (1, "C1", True)]
    assert moves[0].obligation["widths"] == {"F.Cu": 1.2}


def test_an_obligation_that_cannot_be_a_task_stops_the_moves():
    assert rr.asked_moves({"V"}, [[_ob("V", ("U1", "1"), ("J1", "1"), {})]], 0, [[True]])[1] == "victim_width_unknown"
    loose = dict(_ob("V", ("U1", "1"), ("J1", "1")), to={"ref": None, "pad": None, "at": [1.0, 2.0]})
    assert rr.asked_moves({"V"}, [[loose]], 0, [[True]])[1] == "victim_end_not_pad"


def test_joins_no_phase_asks_are_moved_too():
    moves, _ = rr.asked_moves({"V"}, [[_ob("V", ("U1", "1"), ("J1", "1"))]], 0, [[True]])
    open0 = [_ob("V", ("J1", "1"), ("U1", "1")), _ob("V", ("U1", "1"), ("R1", "2")), _ob("V", ("R1", "1"), ("R2", "1")),
             _ob("W", ("A", "1"), ("B", "1"))]
    got = rr.unasked_pairs({"V"}, open0, moves, [True, True, False, True])
    assert [(o["from"]["ref"], o["to"]["ref"]) for o in got] == [("U1", "R1")]


def test_a_phases_width_answer_for_a_net():
    receipt = {"policies": [{"name": "signals", "kind": "nets",
                             "by_net": {"V": {"status": "known", "widths": {"F.Cu": 0.5, "B.Cu": 0.5}},
                                        "U": {"status": "unknown", "widths": None}}}]}
    assert rr.receipt_widths(receipt, "signals", "V") == {"F.Cu": 0.5, "B.Cu": 0.5}
    assert rr.receipt_widths(receipt, "signals", "U") is None and rr.receipt_widths(receipt, "legs", "V") is None
    two = {"policies": receipt["policies"] + [{"name": "signals", "kind": "pairs",
                                                "by_net": {"V": {"status": "known", "widths": {"F.Cu": 0.3, "B.Cu": 0.3}}}}]}
    assert rr.receipt_widths(two, "signals", "V") is None          # two records disagree, as width_policy.apply reads it


def test_a_moved_task_keeps_its_current():
    from placemat.kicad.phase_select import Selection, Task
    sel = Selection("legs", "current_paths", tasks=(Task("V", ("U1", "1"), ("J1", "1"), (("F.Cu", 1.2),), amps=2.0),),
                    layers=("F.Cu",))
    o = _ob("V", ("J1", "1"), ("U1", "1"), {"F.Cu": 1.2})
    assert rr.task_amps(sel, o) == 2.0
    assert rr.task_of(o, ("F.Cu",), amps=2.0).amps == 2.0
    moves, _ = rr.asked_moves({"V"}, [[o]], 0, [[True]], selections=[sel])
    assert moves[0].amps == 2.0


def test_an_owners_calls_carry_its_widths_layers_and_buses():
    from placemat.kicad.phase_run import PhaseSettings
    from placemat.kicad.phase_select import Selection
    sel = Selection("legs", "current_paths", buses=(("S", "T", "Q"), ("W", "X")), layers=("F.Cu",))
    st = PhaseSettings({}, 0.2, None, {}, ("F.Cu",))
    moves = [rr.Move(0, _ob("V", ("U1", "1"), ("J1", "1"), {"F.Cu": 1.2}), True),
             rr.Move(0, _ob("S", ("U1", "4"), ("J1", "4"), {"F.Cu": 0.2}), True),
             rr.Move(0, _ob("T", ("U1", "5"), ("J1", "5"), {"F.Cu": 0.2}), True),
             rr.Move(0, _ob("W", ("U1", "6"), ("J1", "6"), {"F.Cu": 0.2}), True)]
    calls = rr.owner_calls(sel, moves, st)
    # a bus cut to one moved net (W) is no bus: W goes with the plain tasks
    assert [(c.kind, c.nets, sorted(t.net for t in c.tasks)) for c in calls] == [
        ("bus_tasks", ("S", "T"), ["S", "T"]), ("tasks", (), ["V"]), ("tasks", (), ["W"])]


def _st(judged, outcomes=None, open_nets=None, errors=()):
    from pathlib import Path
    return rr.Standing(Path("b"), Path("c"), Path("d"), dict(open_nets or {}), list(errors), judged,
                       outcomes or [[None] * len(j) for j in judged], None)


J_CLEAN = {"joined": True, "violated": False, "under": {}}
J_UNDER = {"joined": True, "violated": False, "under": {"F.Cu": 0.1}}
J_OPEN = {"joined": False, "violated": False, "under": {}}
ASKED = [[_ob("V", ("U1", "1"), ("J1", "1"))], [_ob("N", ("Q1", "1"), ("Q2", "1")), _ob("M", ("R1", "1"), ("R2", "1"))]]


def test_an_attempt_that_loses_nothing_is_kept():
    v = rr.verdict(_st([[J_CLEAN], [J_OPEN, J_OPEN]]), _st([[J_CLEAN], [J_CLEAN, J_OPEN]]), ASKED, ["legs", "signals"],
                   [True], 0)
    assert (v.kept, v.reason, v.worse) == (True, None, ())


def test_the_first_failing_check_is_the_reason_and_every_finding_is_kept():
    before = _st([[J_CLEAN], [J_OPEN, J_UNDER]], open_nets={"N": 1, "GND": 0})
    clearance = {"type": "clearance", "nets": ("N", "V"), "at_mm": (10.0, 5.0),        # drc.real_errors' shape
                 "items": (("Track [N] on F.Cu", 10.0, 5.0), ("Track [V] on F.Cu", 10.2, 5.0))}
    after = _st([[J_UNDER], [J_CLEAN, J_OPEN]], open_nets={"N": 0, "GND": 2}, errors=[clearance])
    v = rr.verdict(before, after, ASKED, ["legs", "signals"], [False], 1)
    assert v.kept is False and v.reason == "blocked_not_clean"
    assert v.worse == ({"phase": "legs", "net": "V", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "J1", "pad": "1"},
                        "before": "clean", "after": "joined"},
                       {"phase": "signals", "net": "M", "from": {"ref": "R1", "pad": "1"}, "to": {"ref": "R2", "pad": "1"},
                        "before": "joined", "after": "open"})
    assert v.open_rose == {"GND": [0, 2]} and v.drc_new == 1 and v.off_layer == 1
    assert rr.verdict(before, after, ASKED, ["legs", "signals"], [True], 0).reason == "obligation_worse"


def test_a_joined_narrow_outcome_ranks_as_joined():
    assert rr.rank(J_CLEAN, "joined_narrow") == 1 and rr.rank(J_CLEAN, "routed") == 2 and rr.rank(J_OPEN, None) == 0


def test_the_gate_skips_in_order():
    r = rr.CallRip()
    assert rr.gate((), rip=r, max_nets=3, attempts=4) == "no_victim"
    assert rr.gate(("A", "B", "C", "D"), rip=r, max_nets=3, attempts=4) == "too_many_victims"
    assert rr.gate(("A",), rip=rr.CallRip(stopped=True), max_nets=3, attempts=4) == "stopped"
    assert rr.gate(("A",), rip=rr.CallRip(made=4), max_nets=3, attempts=4) == "limit"
    assert rr.gate(("A",), rip=rr.CallRip(tried={frozenset({"A"})}), max_nets=3, attempts=4) == "tried"
    assert rr.gate(("A",), rip=r, max_nets=3, attempts=4) is None
    assert rr.gate(("A",), rip=r, max_nets=3, attempts=0) == "limit"


def _err(net, x):
    return {"type": "clearance", "nets": ("GND", net), "at_mm": (x, 5.0),
            "items": (("Track [GND] on F.Cu", x, 5.0), ("Track [%s] on F.Cu" % net, x + 0.2, 5.0))}


def test_each_later_check_is_the_reason_when_it_is_the_first_to_fail():
    judged = [[J_CLEAN], [J_CLEAN, J_CLEAN]]
    old = _err("N", 10.0)
    before = _st(judged, open_nets={"N": 1}, errors=[old])
    names = ["legs", "signals"]
    rose = rr.verdict(before, _st(judged, open_nets={"N": 2}, errors=[old]), ASKED, names, [True], 0)
    assert (rose.kept, rose.reason, rose.open_rose, rose.drc_new) == (False, "net_open_rose", {"N": [1, 2]}, 0)
    new = rr.verdict(before, _st(judged, open_nets={"N": 1}, errors=[old, _err("M", 20.0)]), ASKED, names, [True], 0)
    assert (new.kept, new.reason, new.open_rose, new.drc_new) == (False, "drc_new", {}, 1)
    off = rr.verdict(before, _st(judged, open_nets={"N": 1}, errors=[old]), ASKED, names, [True], 1)
    assert (off.kept, off.reason, off.drc_new, off.off_layer) == (False, "off_layer", 0, 1)
