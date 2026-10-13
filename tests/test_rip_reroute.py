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


def test_a_net_named_in_both_its_evidence_and_the_preexisting_blockers_is_named_once():
    """Parked Task 3 minor: a whole-net unit named by its net_evidence and by a preexisting blocker names the net once,
    in the router's order."""
    summary = {"net_evidence": {"N": _ev(_pre("V"))},
               "blockers": [{"net": "N", "stage": "preexisting", "blocked_by": [{"net": "V", "preexisting": True},
                                                                               {"net": "W", "preexisting": True}]}]}
    (unit,) = rr.blocked_of("rest", summary=summary)
    assert [n.record() for n in unit.named] == [{"net": "V", "found_by": "preexisting"},
                                                {"net": "W", "found_by": "preexisting"}]


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


def test_a_join_no_phase_asks_with_an_end_that_is_no_pad_skips_the_unit():
    """The victim's copper joins an island whose end is no pad (final review finding 4): taking it off would open the
    island with nothing to route it, so the unit is skipped, not spent as an attempt; an island still open is left."""
    import types
    stub = dict(_ob("V", ("U1", "1"), ("J1", "1")), to={"ref": None, "pad": None, "at": [1.0, 2.0]})
    hist = types.SimpleNamespace(asked=([],), selections=(None,), input_open=(stub,), boards=[], receipt={},
                                 phases=(types.SimpleNamespace(name="a"),))
    assert rr.plan_moves({"V"}, hist, 0, _st([[]])) == ([], "victim_end_not_pad")
    assert rr.plan_moves({"V"}, hist, 0, _st([[]], open_nets={"V": 1})) == ([], None)


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
    # the Selection as picked names F.Cu; the owner's settings (what its calls are routed at) name B.Cu, its own
    # clearance for V and a base clearance of its own: the calls take theirs (parked Task 7 minor)
    sel = Selection("legs", "current_paths", buses=(("S", "T", "Q"), ("W", "X")), layers=("F.Cu",))
    st = PhaseSettings({"V": 0.4}, 0.25, None, {}, ("B.Cu",))
    both = lambda w: {"F.Cu": w, "B.Cu": w}
    moves = [rr.Move(0, _ob("V", ("U1", "1"), ("J1", "1"), {"F.Cu": 1.0, "B.Cu": 1.2}), True),
             rr.Move(0, _ob("S", ("U1", "4"), ("J1", "4"), both(0.2)), True),
             rr.Move(0, _ob("T", ("U1", "5"), ("J1", "5"), both(0.2)), True),
             rr.Move(0, _ob("W", ("U1", "6"), ("J1", "6"), both(0.2)), True)]
    calls = rr.owner_calls(sel, moves, st)
    # a bus cut to one moved net (W) is no bus: W goes with the plain tasks
    assert [(c.kind, c.nets, sorted(t.net for t in c.tasks), c.clearance) for c in calls] == [
        ("bus_tasks", ("S", "T"), ["S", "T"], None), ("tasks", (), ["V"], 0.4), ("tasks", (), ["W"], 0.25)]
    assert {t.net: t.widths for c in calls for t in c.tasks} == {
        "V": (("B.Cu", 1.2),), "S": (("B.Cu", 0.2),), "T": (("B.Cu", 0.2),), "W": (("B.Cu", 0.2),)}


def _st(judged, open_nets=None, errors=()):
    from pathlib import Path
    return rr.Standing(Path("b"), Path("c"), Path("d"), dict(open_nets or {}), list(errors), judged, None)


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


def test_rank_is_placemats_measure_alone():
    # S8: the router's joined_narrow does not decide; a join under its width on the joining path is joined, not clean
    assert (rr.rank(J_CLEAN), rr.rank(J_UNDER), rr.rank(J_OPEN)) == (2, 1, 0)


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


def test_every_earlier_phase_of_a_moved_net_is_named():
    moved = {"net": "V", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "J1", "pad": "1"}, "status": "routed",
             "phase": "legs", "index": 0, "asked": True}
    phases = [{"name": "legs", "rip": {"attempts": [], "skipped": []}},
              {"name": "rest", "rip": {"attempts": [], "skipped": []}},
              {"name": "signals", "rip": {"attempts": [{"kept": True, "victims": ["V"], "rerouted": [moved]},
                                                       {"kept": False, "victims": ["W"],
                                                        "rerouted": [dict(moved, status="failed")]}],
                                          "skipped": []}}]
    # every earlier phase's rows of a moved net go, whichever phase owns the moved connection (finding F7)
    assert rr.moved_nets(phases) == {(0, "V"), (1, "V")}


def test_the_phase_lines_say_what_was_moved_restored_and_not_tried():
    from placemat.kicad.route import phase_lines
    end = lambda r, p: {"ref": r, "pad": p}
    kept = {"call": 1, "attempt": 0, "kept": True, "reason": None, "victims": ["V"],
            "blocked": [{"net": "N", "from": end("J1", "2"), "to": end("U2", "1")}],
            "rerouted": [{"net": "V", "phase": "legs", "index": 0}] * 6, "worse": []}
    lost = {"call": 1, "attempt": 1, "kept": False, "reason": "obligation_worse", "victims": ["W"],
            "blocked": [{"net": "M", "from": end("A", "1"), "to": end("B", "2")}], "rerouted": [],
            "worse": [{"phase": "legs", "net": "W", "from": end("C", "1"), "to": end("D", "2"),
                       "before": "clean", "after": "open"}]}
    drc = dict(lost, attempt=2, reason="drc_new", drc_new=2, worse=[])
    one = dict(lost, attempt=3, reason="drc_new", drc_new=1, worse=[])
    skipped = [{"call": 1, "net": "K", "named": [], "not_ripped": [], "reason": "too_many_victims"},
               {"call": 1, "net": "Q", "named": [], "not_ripped": [], "reason": "no_victim"}]
    base = {"selector": "rest", "joined": 1, "asked": 2, "closure_clean": 0.5, "seconds": 3.0, "open": []}
    lines = phase_lines([dict(base, name="legs", rip={"attempts": [], "skipped": []}),
                         dict(base, name="signals", rip={"attempts": [kept, lost, drc, one], "skipped": skipped})])
    assert lines[0].endswith("; moved by phase signals: V")
    assert "; moved earlier copper: N J1.2-U2.1 joined after moving V (legs, 6 connections)" in lines[1]
    assert "; restored: M A.1-B.2 after moving W: W C.1-D.2 would be open" in lines[1]
    assert "after moving W: 2 new DRC errors" in lines[1]
    assert "after moving W: 1 new DRC error" in lines[1] and "1 new DRC errors" not in lines[1]
    assert "; not moved for K: too many nets named" in lines[1] and "for Q" not in lines[1]
    assert "(" not in lines[1].split("; restored")[1]          # no bracketed plurals


SKIP_REASONS = ("too_many_victims", "victim_width_unknown", "victim_end_not_pad", "blocked_width_unknown",
                "blocked_end_not_pad", "joined_since", "tried", "limit", "stopped")


def test_every_reason_has_its_own_wording_on_the_phase_line():
    """Parked Task 14 minor: each keep check, router reason and skip reason is said in words of its own, never as the
    fallback (the code with its underscores as spaces)."""
    from placemat.kicad.route import phase_lines
    end = {"ref": "A", "pad": "1"}
    base = {"name": "b", "selector": "rest", "joined": 0, "asked": 1, "closure_clean": 0.0, "seconds": 1.0, "open": []}
    for reason in rr.KEEP_CHECKS + rr.ROUTER_REASONS:
        att = {"call": 0, "attempt": 0, "kept": False, "reason": reason, "victims": ["V"], "rerouted": [],
               "blocked": [{"net": "N", "from": end, "to": end}], "drc_new": 1, "open_rose": {"N": [0, 1]},
               "worse": [{"phase": "a", "net": "V", "from": end, "to": end, "before": "clean", "after": "open"}]
               if reason == "obligation_worse" else []}
        (line,) = phase_lines([dict(base, rip={"attempts": [att], "skipped": []})])
        said = line.split("after moving V: ")[1]
        assert said and not said.startswith(reason.replace("_", " ")), (reason, said)
    for reason in SKIP_REASONS:
        skip = {"call": 0, "net": "K", "named": [], "not_ripped": [], "reason": reason}
        (line,) = phase_lines([dict(base, rip={"attempts": [], "skipped": [skip]})])
        said = line.split("not moved for K: ")[1]
        assert said and said != reason.replace("_", " "), (reason, said)


def test_a_pour_calls_blocked_net_is_joined_to_its_pour_again(monkeypatch, tmp_path):
    """Step 2 of an attempt after a pour call is join_pour on the ripped board, not a plain task call."""
    import types
    import placemat.kicad.pour_join as pj
    seen = []

    def join_pour(ctx, board, out, net, width, layers, stem, phase, common):
        seen.append((net, stem, width, tuple(layers)))
        return {"net": net}, types.SimpleNamespace(board=out, records=[], summaries=[], calls=[])

    def no_tasks(*a, **kw):
        raise AssertionError("route_tasks called for a pour call")
    monkeypatch.setattr(pj, "join_pour", join_pour)
    monkeypatch.setattr(rr, "route_tasks", no_tasks)
    call = types.SimpleNamespace(kind="pour", width=0.5, nets=("GND",))
    joined, run = rr.reroute_blocked(types.SimpleNamespace(work=tmp_path), call, rr.Blocked("GND", ()), [],
                                     tmp_path / "r.kicad_pcb", types.SimpleNamespace(layers=("F.Cu",), common={}),
                                     "p2_0_rip0", types.SimpleNamespace(name="pours", width=0.5))
    assert seen == [("GND", "p2_0_rip0_b", 0.5, ("F.Cu",))]
    assert joined == {"net": "GND"} and run.board == tmp_path / "p2_0_rip0_b.kicad_pcb"


def test_a_kept_attempt_after_a_pour_call_is_the_join_its_pour_joins_entry_describes(monkeypatch, tmp_path):
    """Final review finding 6: the phase's pour_joins entry for the net is the kept attempt's join, not the failing
    call's, so the phase line and the S22 re-check read the groups the attempt left."""
    import types
    from pathlib import Path
    import placemat.kicad.pour_join as pj
    from placemat.kicad import phase_run
    from placemat.kicad.phase_select import Selection
    failed = {"net": "GND", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "J1", "pad": "1"},
              "widths": {"F.Cu": 0.5}, "status": "failed", "evidence": _ev(_pre("V"))}

    def join_pour(ctx, board, out, net, width, layers, stem, phase, common):
        Path(out).write_text("board")
        if "_rip" in stem:                         # the attempt's join: every group joined
            return ({"net": net, "groups_left": 1, "groups_after": 1, "tasks": [dict(failed, status="routed")]},
                    phase_run.TaskRun(Path(out), [dict(failed, status="routed")]))
        return ({"net": net, "groups_left": 1, "groups_after": 2, "tasks": [failed]},
                phase_run.TaskRun(Path(out), [failed]))
    clean = {"joined": True, "violated": False, "under": {}}
    monkeypatch.setattr(pj, "join_pour", join_pour)
    monkeypatch.setattr(pj, "pad_groups", lambda board, net: [object()])
    monkeypatch.setattr(phase_run, "lock_copper", lambda pcb: None)
    monkeypatch.setattr(phase_run, "phase_widths", lambda *a: [])
    monkeypatch.setattr(phase_run, "task_widths", lambda *a: [])
    monkeypatch.setattr(rr, "router_nets", lambda board, keys: {"V": 1})
    monkeypatch.setattr(rr, "laid_nets", lambda a, b: set())
    monkeypatch.setattr(rr, "standing", lambda ctx, asked, phases, upto, board, stem:
                        rr.Standing(Path(board), Path(board), Path(board), {}, [], [[]], None))
    monkeypatch.setattr(rr, "joined_pairs", lambda board, pairs: [False] * len(pairs))
    monkeypatch.setattr(rr, "plan_moves", lambda victims, hist, index, before: ([], None))
    monkeypatch.setattr(rr, "remove_copper", lambda src, dst, victims, keys: {"tracks": 1})
    monkeypatch.setattr(rr, "off_layer", lambda given, routed, layers: 0)
    monkeypatch.setattr(rr, "judge_obligations", lambda *a: [clean])
    phase = types.SimpleNamespace(name="pours", router_args=(), neckdown=True, width=0.5)
    sel = Selection("pours", "nets", pour_nets=("GND",), layers=("F.Cu",))
    hist = rr.History((phase,), (sel,), ([],), {}, frozenset(), ())
    ctx = phase_run.PhaseContext(tmp_path, "route.py", str(tmp_path), tmp_path, ["F.Cu"], None, None, False,
                                 60, {}, Settings(), types.SimpleNamespace(default_clearance=0.15), {}, 0.15, None,
                                 set(), {"GND"}, None, history=hist)
    board = tmp_path / "in.kicad_pcb"
    board.write_text("board")
    (tmp_path / "drc_before.json").write_text("{}")
    out = phase_run.route_calls(ctx, 0, phase, sel, board)
    (att,) = out.routed["rip"]["attempts"]
    assert att["kept"]
    (entry,) = out.routed["pour_joins"]
    assert (entry["groups_after"], entry["tasks"][0]["status"]) == (1, "routed")
    assert entry["rip"] == {"call": 0, "attempt": 0} and entry["groups_final"] == 1 and "rejoin" not in entry


def test_a_pair_call_never_starts_an_attempt(tmp_path, monkeypatch):
    import types
    import pytest
    from placemat.kicad import phase_run
    from placemat.kicad.phase_select import Selection

    def route_pairs(rpy, router_dir, board, work, pairs, layers, cfg, *a, stem, **kw):
        out = work / (stem + "_pairs.kicad_pcb")
        out.write_text("routed")
        return out, types.SimpleNamespace(as_dict=lambda: {"coupled": [list(p) for p in pairs]})

    def no_attempt(*a, **kw):
        pytest.fail("a pair call started rip and reroute")
    monkeypatch.setattr(phase_run, "route_pairs", route_pairs)
    monkeypatch.setattr(phase_run, "lock_copper", lambda pcb: None)
    monkeypatch.setattr(phase_run, "phase_widths", lambda *a: [])
    monkeypatch.setattr(phase_run, "task_widths", lambda *a: [])
    monkeypatch.setattr(rr, "after_call", no_attempt)
    phase = types.SimpleNamespace(name="pairs", router_args=(), neckdown=True, width=None)
    ctx = phase_run.PhaseContext(tmp_path, "route.py", str(tmp_path), tmp_path, ["F.Cu", "B.Cu"], None, None, False,
                                 60, {}, Settings(), types.SimpleNamespace(default_clearance=0.15), {}, 0.15, None,
                                 set(), set(), None, history=object())
    sel = Selection("pairs", "pairs", pairs=(("D_P", "D_N"),), layers=("F.Cu", "B.Cu"))
    board = tmp_path / "in.kicad_pcb"
    board.write_text("board")
    out = phase_run.route_calls(ctx, 0, phase, sel, board)
    assert [c.kind for c, _, _ in out.calls] == ["pairs"] and out.routed["rip"] == {"attempts": [], "skipped": []}
