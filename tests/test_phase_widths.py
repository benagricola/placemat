"""Widths delivered by each named routing phase."""
"""A phase with a width is judged on the routed board, on the copper each of its calls added, per layer."""
from placemat.kicad.route_widths import board_widths, findings_of
from placemat.values import CopperLayer
from tests.fixtures import board_geometry, footprint, track

F, B = CopperLayer.F, CopperLayer.B


def test_added_copper_under_its_asked_width_is_recorded_per_layer_naming_the_phase():
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"))
    q1 = footprint("Q1", 25, 10, nets=("VB", "OUT"))
    narrow = track("VB", 8, 10, 20, 10, w=0.3)
    tap = track("VB", 8, 12, 20, 12, w=0.2)                 # an earlier phase's tap: not this call's copper
    g = board_geometry([j1, q1], copper=[narrow, tap])
    (r,) = board_widths(g, {"VB": {F: 1.0, B: 1.0}}, "legs", only=[narrow], neck_mm=0.0)
    assert r["stage"] == "legs" and r["layers"][0]["layer"] == "F.Cu" and r["layers"][0]["need_mm"] == 1.0
    assert r["length_under_mm"] == 12.0
    (f,) = findings_of([r])
    assert f.severity == "critical" and f.facts["stage"] == "legs"


def test_copper_at_its_width_is_not_recorded():
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"))
    wide = track("VB", 8, 10, 20, 10, w=1.0)
    assert board_widths(board_geometry([j1], copper=[wide]), {"VB": {F: 1.0}}, "legs", only=[wide]) == []


def test_a_task_left_joined_narrow_is_judged_on_its_joining_path(monkeypatch):
    """D3's fallback: KRT reports a task joined by narrower copper and does not route it; the phase judges the
    path the record names, and only that path, against the task's widths."""
    from types import SimpleNamespace as N
    from placemat.kicad import phase_run
    from placemat.route_phase import parse_phases
    from placemat.settings import Settings
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"))
    q1 = footprint("Q1", 25, 10, nets=("VB", "OUT"))
    stub = track("VB", 8, 10, 20, 10, w=0.2)
    sense = track("VB", 8, 14, 20, 14, w=0.15)               # the same net, not on the path: not judged
    g = board_geometry([j1, q1], copper=[stub, sense])
    monkeypatch.setattr("placemat.kicad.read.read_board", lambda path: g)
    (phase,) = parse_phases(({"name": "legs", "width": 1.0, "connections": [
        {"from": {"part": "J1", "pad": "1"}, "to": {"part": "Q1", "pad": "1"}}]},))
    task = N(net="VB", start=("J1", "1"), end=("Q1", "1"), widths=(("F.Cu", 1.0),), amps=None)
    rec = {"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "Q1", "pad": "1"}, "status": "joined_narrow",
           "joined": True, "min_width_mm": {"F.Cu": 0.2},
           "path": [{"layer": "F.Cu", "start": [8, 10], "end": [20, 10], "width": 0.2}]}
    (r,) = phase_run.narrow_join_widths(phase, N(tasks=(task,)), [rec], "routed.kicad_pcb", Settings())
    assert r["stage"] == "legs" and r["net"] == "VB" and r["length_under_mm"] == 12.0
    assert phase_run.narrow_join_widths(phase, N(tasks=(task,)), [dict(rec, path=None)], "x", Settings()) == []


def test_widths_failed_counts_joins_under_width_on_their_path_and_joined_narrow():
    from placemat.kicad import phase_run
    a = {"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "Q1", "pad": "1"}, "widths": {"F.Cu": 1.0}}
    b = dict(a, to={"ref": "Q1", "pad": "2"})
    c = {"net": "SW", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "L1", "pad": "1"}, "widths": {"F.Cu": 0.5}}
    legs = {"name": "legs", "connections": []}
    sw = {"name": "sw", "connections": [dict(c, status="joined_narrow")]}
    judged = [[{"joined": True, "violated": False, "under": {"F.Cu": 0.3}},
               {"joined": True, "violated": False, "under": {}}],
              [{"joined": True, "violated": False, "under": {"F.Cu": 0.2}}]]
    assert phase_run.widths_failed([legs, sw], [[a, b], [c]], judged) == 2
    judged[0][0] = {"joined": False, "violated": False, "under": {}}       # open: closure's, not a width failure
    assert phase_run.widths_failed([legs, sw], [[a, b], [c]], judged) == 1


def test_without_neckdown_the_routers_own_minimum_per_task_is_judged():
    from types import SimpleNamespace as N
    from placemat.kicad import phase_run
    from placemat.kicad.route_widths import brief
    from placemat.route_phase import parse_phases
    raw = {"name": "legs", "width": 1.0, "neckdown": False,
           "connections": [{"from": {"part": "J1", "pad": "1"}, "to": {"part": "Q1", "pad": "1"}}]}
    (off,) = parse_phases((raw,))
    (on,) = parse_phases((dict(raw, neckdown=True),))
    task = N(net="VB", start=("J1", "1"), end=("Q1", "1"), widths=(("F.Cu", 1.0), ("B.Cu", 1.0)), amps=None)
    rec = {"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "Q1", "pad": "1"}, "status": "routed",
           "joined": True, "length_mm": 20.0, "min_width_mm": {"F.Cu": 0.6, "B.Cu": 1.0}}
    (r,) = phase_run.task_widths(off, N(tasks=(task,)), [rec])
    assert r["source"] == "router" and r["layers"] == [{"layer": "F.Cu", "need_mm": 1.0, "min_mm": 0.6, "by": "asked"}]
    assert r["delivered_min_mm"] == 0.6 and r["stage"] == "legs" and r["declared"]
    assert brief(r) == "VB J1.1-Q1.1 under F.Cu 1 (router min 0.6)"
    (f,) = findings_of([r])
    assert f.severity == "critical" and f.facts["from"] == {"ref": "J1", "pad": "1"}
    assert phase_run.task_widths(on, N(tasks=(task,)), [rec]) == []
    assert phase_run.task_widths(off, N(tasks=(task,)), [dict(rec, status="refused", min_width_mm={})]) == []


def test_numeric_rest_keeps_width_obligations():
    from placemat.kicad.phase_run import obligations_of
    from placemat.kicad.phase_select import Selection
    obligation = {"net": "V", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "J2", "pad": "1"}}
    (asked,) = obligations_of([Selection("rest", "rest", rest=True, width=0.8, layers=("F.Cu",))], [obligation], set())
    assert asked[0]["widths"] == {"F.Cu": 0.8}


def test_unknown_required_width_is_not_clean_and_counts_as_unproven():
    from placemat.kicad.phase_run import is_clean, widths_failed
    result = {"joined": True, "violated": False, "under": {}, "width_unknown": True}
    obligation = {"net": "V", "from": {}, "to": {}}
    assert not is_clean(result, None)
    assert widths_failed([{}], [[obligation]], [[result]]) == 1


def test_intermediate_pad_bridges_track_ends_and_a_wider_alternative_is_used():
    from placemat.kicad.phase_run import joining_spans, width_shortfall
    from tests.test_route_widths_board import _track, _board
    from dataclasses import replace
    base = _board(_track((5, 10), (20, 10), 0.2), _track((20, 10), (40, 10), 0.2),
                  _track((5, 10), (5, 20), 1.0), _track((5, 20), (40, 20), 1.0),
                  _track((40, 20), (40, 10), 1.0))
    ob = {"net": "V", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "U2", "pad": "1"}, "widths": {"F.Cu": 1.0}}
    wide = joining_spans(base, ob, full_width=True)
    assert wide is not None and width_shortfall(wide, ob["widths"], 0.0) == {}
    midpoint = footprint("U3", 20.6 + 1.0, 10.0, nets=("V", "X"))
    bridged = _board(_track((5, 10), (20, 10), 1.0), _track((20.3, 10), (40, 10), 1.0))
    bridged = replace(bridged, footprints=bridged.footprints + (midpoint,))
    assert joining_spans(bridged, ob, full_width=True) is not None


def test_mixed_filled_region_and_narrow_track_keeps_track_shortfall():
    from placemat.kicad.phase_run import joining_spans, width_shortfall
    from tests.test_route_widths_board import _track, _board
    from placemat.board_geometry import CopperItem
    from placemat.values import Box
    outline = ((4, 9), (20, 9), (20, 11), (4, 11))
    pour = CopperItem("poly", "V", frozenset((F,)), (outline,), Box.of_points(outline))
    geometry = _board(pour, _track((19, 10), (40, 10), 0.2))
    ob = {"net": "V", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "U2", "pad": "1"}, "widths": {"F.Cu": 1.0}}
    assert joining_spans(geometry, ob, full_width=True) is None
    spans = joining_spans(geometry, ob)
    assert spans is not None and width_shortfall(spans, ob["widths"], 0.0) == {"F.Cu": 0.2}
    all_outline = ((4, 9), (41, 9), (41, 11), (4, 11))
    pure = _board(CopperItem("poly", "V", frozenset((F,)), (all_outline,), Box.of_points(all_outline)))
    assert joining_spans(pure, ob, full_width=True) == []


def test_pair_width_is_refused_instead_of_ignored():
    import pytest
    from placemat.route_phase import parse_phases, PhaseError
    with pytest.raises(PhaseError) as err:
        parse_phases(({"name": "pair", "pairs": [["P", "N"]], "width": 0.8},))
    assert err.value.code == "pair_width"


def test_comparison_contract_uses_pad_membership_not_airwire_topology():
    from placemat.kicad.phase_run import comparison_obligations, comparison_contract
    from placemat.kicad.phase_select import Selection
    from placemat.route_phase import parse_phases
    from dataclasses import replace
    geometry = board_geometry([footprint("U1", 5, 10, nets=("V", "X")),
                               footprint("U2", 15, 10, nets=("V", "Y")),
                               footprint("U3", 25, 10, nets=("V", "Z"))])
    selection = Selection("power", "nets", nets=("V",), layers=("F.Cu",), width=0.5)
    (phase,) = parse_phases(({"name": "power", "nets": ["V"], "width": 0.5},))
    (a,) = comparison_obligations([selection], geometry, set())
    moved = replace(geometry, footprints=tuple(reversed(geometry.footprints)))
    (b,) = comparison_obligations([selection], moved, set())
    assert a == b and len(a) == 2
    assert comparison_contract(phase, a) == comparison_contract(phase, b)
    assert comparison_contract(phase, a) != comparison_contract(phase, a[:1])


def test_compliant_neck_path_is_found_beside_a_shorter_narrow_path():
    from placemat.kicad.phase_run import joining_spans, width_shortfall
    from tests.test_route_widths_board import _track, _board
    geometry = _board(_track((5, 10), (40, 10), 0.2),
                      _track((5, 10), (5, 12), 0.2), _track((5, 12), (40, 12), 1.0),
                      _track((40, 12), (40, 10), 0.2))
    obligation = {"net": "V", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "U2", "pad": "1"},
                  "widths": {"F.Cu": 1.0}}
    assert width_shortfall(joining_spans(geometry, obligation), obligation["widths"], 3.0)
    spans = joining_spans(geometry, obligation, full_width=True, neck_mm=3.0)
    assert spans is not None and width_shortfall(spans, obligation["widths"], 3.0) == {}
