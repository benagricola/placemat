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
