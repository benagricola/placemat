"""Closure is scored from the open connections before and after routing;
a net the router closed through a violation counts as fully open."""
from placemat.kicad.route import score


def test_closure_is_the_share_of_open_signal_items_closed():
    before = {"A": 2, "B": 3, "C": 1}
    after = {"B": 1}
    r = score(before, after, violated_nets=set())
    assert r.closure == 1 - 1 / 6
    assert r.closure_clean == r.closure and r.shorted == []


def test_a_net_closed_through_a_violation_counts_as_open_in_the_clean_number():
    before = {"A": 2, "B": 3}
    after = {}
    r = score(before, after, violated_nets={"A"})
    assert r.closure == 1.0
    assert r.closure_clean == 1 - 2 / 5 and r.shorted == ["A"]


def test_nothing_open_before_is_full_closure():
    r = score({}, {}, violated_nets=set())
    assert r.closure == 1.0 and r.closure_clean == 1.0


def _drc(kind, *nets):
    return {"type": kind, "items": [{"description": "Via [%s] on F.Cu - B.Cu" % n} for n in nets]}


def test_violations_by_net_lists_each_nets_kinds():
    from placemat.kicad.route import _violations_by_net
    drc = {"violations": [_drc("hole_to_hole", "INA_ALERT", "INA_ALERT"), _drc("clearance", "A", "B"),
                          _drc("hole_to_hole", "A"), _drc("silk_overlap", "Z")]}
    assert _violations_by_net(drc) == {"INA_ALERT": ["hole_to_hole"], "A": ["clearance", "hole_to_hole"],
                                       "B": ["clearance"]}


def _report(**kw):
    from pathlib import Path
    from placemat.kicad.route import RouteReport
    p = Path(".")
    r = RouteReport(True, 1.0, 0.9, 4, 0, {}, ["INA_ALERT"], [], ["F.Cu"], 1.0, "v", {}, p, p, p)
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def test_a_net_with_only_a_hole_to_hole_is_named_by_its_kind_not_as_shorted():
    r = _report(violations={"INA_ALERT": ["hole_to_hole"]})
    line = r.summary()
    assert "with DRC violations: INA_ALERT (hole_to_hole)" in line and "shorted" not in line


def test_route_json_keeps_shorted_and_carries_violations():
    r = _report(violations={"INA_ALERT": ["hole_to_hole"]})
    d = r.as_dict()
    assert d["shorted"] == ["INA_ALERT"] and d["violations"] == {"INA_ALERT": ["hole_to_hole"]}


def test_the_route_record_carries_violations():
    from placemat.route_progress import write_record
    import json, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        path = write_record(d, {}, [], {"shorted": ["A"], "violations": {"A": ["clearance"]}})
        assert json.loads(Path(path).read_text())["report"]["violations"] == {"A": ["clearance"]}
