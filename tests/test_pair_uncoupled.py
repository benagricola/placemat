"""A pair phase judges each pair by whether the pair router coupled it end to end: one it did not, or one whose members
run uncoupled further than the phase's max_uncoupled_mm, is a critical finding, its nets stay out of the later phases,
and the route exits 1. The pair router's records give each member's uncoupled and open length (the fork's "Uncoupled
length per pair member")."""
import json
import textwrap

import pytest

from placemat.findings import FindingCause as C
from placemat.finding_text import render
from placemat.kicad.route import RouteReport, held_nets, pair_report, read_pairs, uncoupled_pairs
from placemat.route_phase import PhaseError, parse_phases
from tests.conftest import needs_kicad
from tests.test_route_phases import _nets, rig  # noqa: F401 - the fixture


def _report(pair="USB_D", outcome="coupled", reason=None, hybrid=False, unc=(0.0, 0.0), opn=(0.0, 0.0)):
    r = {"pair": pair, "p_net": pair + "_P", "n_net": pair + "_N", "outcome": outcome, "failure_reason": reason,
         "uncoupled_mm": {"p": unc[0], "n": unc[1]}, "open_mm": {"p": opn[0], "n": opn[1]}, "min_coupled_mm": 3.0}
    if hybrid:
        r["escape"] = "hybrid"
    return r


def test_max_uncoupled_mm_is_a_pair_phases_key():
    phase, = parse_phases([{"name": "usb", "pairs": [["D_P", "D_N"]], "max_uncoupled_mm": 2}])
    assert phase.max_uncoupled_mm == 2.0
    with pytest.raises(PhaseError) as e:
        parse_phases([{"name": "fb", "nets": ["FB"], "max_uncoupled_mm": 2}])
    assert e.value.code == "uncoupled_not_pairs"
    with pytest.raises(PhaseError) as e:
        parse_phases([{"name": "usb", "pairs": True, "max_uncoupled_mm": -1}])
    assert e.value.code == "bad_uncoupled"


def test_the_pair_routers_records_are_read_with_their_lengths():
    log = "JSON_SUMMARY: " + json.dumps({"routed_diff_pairs": [], "single_ended_diff_pairs": ["USB_D"],
                                         "pair_reports": [_report(outcome="deferred", reason="electrically-short",
                                                                  opn=(1.2, 1.4))]})
    rep, = read_pairs(log).reports
    assert rep == {"pair": "USB_D", "p": "USB_D_P", "n": "USB_D_N", "outcome": "deferred",
                   "reason": "electrically-short", "hybrid": False, "uncoupled_mm": {"p": 0.0, "n": 0.0},
                   "open_mm": {"p": 1.2, "n": 1.4}, "min_coupled_mm": 3.0}


def test_a_pair_coupled_end_to_end_is_not_listed():
    assert uncoupled_pairs([pair_report(_report(unc=(0.4, 0.4)))], None) == []


@pytest.mark.parametrize("raw,cause", [(_report(hybrid=True, unc=(9.5, 0.3)), "hybrid"),
                                       (_report(outcome="deferred", reason="electrically-short", opn=(1, 1)), "short_leg"),
                                       (_report(outcome="deferred", reason="electrically-short",
                                                unc=(27.8, 8.1), opn=(0, 11.9)), "fallback"),
                                       (_report(outcome="partial", opn=(1, 1)), "peeled_leg"),
                                       (_report(outcome="failed", reason="no-route"), "failed")])
def test_a_pair_not_coupled_end_to_end_names_its_cause(raw, cause):
    r, = uncoupled_pairs([pair_report(raw)], None)
    assert r["cause"] == cause and not r["allowed"]


def test_a_short_leg_within_the_limit_is_allowed_and_a_long_escape_is_not():
    short = pair_report(_report(pair="A", outcome="deferred", reason="electrically-short", opn=(1.2, 1.4)))
    long_ = pair_report(_report(pair="B", hybrid=True, unc=(9.5, 0.3)))
    failed = pair_report(_report(pair="C", outcome="failed"))
    got = {r["pair"]: r for r in uncoupled_pairs([short, long_, failed], 2.0)}
    assert got["A"]["allowed"] and got["A"]["total_mm"] == {"p": 1.2, "n": 1.4}
    assert not got["B"]["allowed"] and not got["C"]["allowed"]


def test_a_router_that_does_not_measure_allows_none():
    r = pair_report(_report(outcome="deferred", reason="electrically-short"))
    r["uncoupled_mm"] = r["open_mm"] = None
    assert not uncoupled_pairs([r], 5.0)[0]["allowed"]


def test_the_held_nets_are_the_members_of_the_pairs_not_allowed():
    rec = {"pairs_uncoupled": uncoupled_pairs([pair_report(_report(pair="A", outcome="failed")),
                                               pair_report(_report(pair="B", outcome="partial", opn=(1, 1)))], 2.0)}
    assert held_nets(rec) == {"A_P", "A_N"}


def test_a_pair_not_coupled_is_a_critical_finding_naming_its_lengths():
    report = RouteReport(True, 1.0, 1.0, 0, 0, {}, [], [], [], 0.0, "v", {}, "out", "log", "work")
    report.phases = [{"name": "usb-data", "pairs_uncoupled": uncoupled_pairs(
        [pair_report(_report(hybrid=True, unc=(9.5, 0.3)))], 2.0)}]
    assert report.has_findings()
    f, = report.findings()
    assert f.cause is C.ROUTE_PAIR_UNCOUPLED and f.severity == "critical"
    assert f.facts["total_mm"] == {"p": 9.5, "n": 0.3} and f.facts["phase"] == "usb-data"
    text = render(f.cause, f.facts)
    assert "USB_D_P 9.5 mm" in text and "max_uncoupled_mm 2" in text and "later phases" in text


PAIR_ROUTER = textwrap.dedent('''
    import json, os, shutil, sys
    a = sys.argv[1:]
    with open(os.environ["FAKE_ROUTER_LOG"], "a") as f:
        f.write(json.dumps(a) + "\\n")
    shutil.copy(a[0], a[1])
    base = a[a.index("--nets") + 1]
    rep = dict(json.loads(os.environ["FAKE_PAIR_REPORT"]), pair=base, p_net=base + "_P", n_net=base + "_N")
    print("JSON_SUMMARY: " + json.dumps({"routed_diff_pairs": [], "failed_diff_pairs": [],
                                         "single_ended_diff_pairs": [base], "pair_reports": [rep]}))
''')


@needs_kicad
@pytest.mark.parametrize("limit,held", [(None, True), (2.0, False)])
def test_a_later_phase_leaves_a_pair_the_pair_phase_did_not_couple(rig, monkeypatch, limit, held):  # noqa: F811
    (rig.router / "py_router/route_diff.py").write_text(PAIR_ROUTER)
    (rig.router / "py_router/diff_pair_custody.py").write_text("rep['uncoupled_mm'] = {}\n")
    monkeypatch.setenv("FAKE_PAIR_REPORT", json.dumps(_report(outcome="deferred", reason="electrically-short",
                                                              opn=(1.2, 1.4))))
    usb = {"name": "usb", "pairs": [["FB", "VIN"]]}
    if limit is not None:
        usb["max_uncoupled_mm"] = limit
    report = rig.route(usb, {"name": "signals"})
    rest = [_nets(c) for c in rig.calls() if "--nets" in c and "PMPAIR0" not in _nets(c)]
    routes_them = any(n[0] == "*" and "!FB" not in n and "!VIN" not in n for n in rest)
    assert routes_them is not held          # held: the rest phase has nothing left, or leaves them out
    assert bool(report.pairs_not_coupled()) is held
    r, = report.phases[0]["pairs_uncoupled"]
    assert (r["pair"], r["p"], r["n"], r["cause"]) == ("FB/VIN", "FB", "VIN", "short_leg")
