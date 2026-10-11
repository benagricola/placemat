"""Widths delivered by each named routing phase."""
"""A phase with a width is judged on the routed board, on the copper each of its calls added, per layer."""
import pytest

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


def test_an_unmeasured_width_is_not_clean_and_counts_as_failed():
    from placemat.kicad.phase_run import is_clean, widths_failed
    result = {"joined": True, "violated": False, "under": {}, "width_unknown": True}
    obligation = {"net": "V", "from": {}, "to": {}}
    assert not is_clean(result, None)
    assert widths_failed([{}], [[obligation]], [[result]]) == 1


def test_pair_width_is_refused_instead_of_ignored():
    import pytest
    from placemat.route_phase import parse_phases, PhaseError
    with pytest.raises(PhaseError) as err:
        parse_phases(({"name": "pair", "pairs": [["P", "N"]], "width": 0.8},))
    assert err.value.code == "pair_width"


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


def test_disconnected_custom_pad_islands_do_not_bridge_track_ends():
    from dataclasses import replace
    from placemat.kicad.phase_run import joining_spans
    from placemat.values import Box
    from tests.test_route_widths_board import _board, _track
    middle = footprint("U3", 21.6, 10, nets=("V", "X"))
    a = ((19.8, 9.9), (20.1, 9.9), (20.1, 10.1), (19.8, 10.1))
    b = ((20.3, 9.9), (20.6, 9.9), (20.6, 10.1), (20.3, 10.1))
    pad = replace(middle.pads[0], custom=True, outlines=(a, b), box=Box.of_points(a + b))
    middle = replace(middle, pads=(pad,) + middle.pads[1:])
    geometry = _board(_track((5, 10), (20, 10), 0.2), _track((20.4, 10), (40, 10), 0.2))
    geometry = replace(geometry, footprints=geometry.footprints + (middle,))
    ob = {"net": "V", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "U2", "pad": "1"}, "widths": {"F.Cu": 1}}
    assert joining_spans(geometry, ob) is None


def test_a_measured_shortfall_is_under_and_not_width_unknown(monkeypatch, tmp_path):
    from placemat.kicad import phase_run
    from tests.test_route_widths_board import _board, _track
    geometry = _board(_track((5, 10), (40, 10), 0.2))
    monkeypatch.setattr("placemat.kicad.read.read_board", lambda _: geometry)
    monkeypatch.setattr(phase_run, "joined_pairs", lambda *_: [True])
    drc = tmp_path / "drc.json"
    drc.write_text('{"violations": [], "unconnected_items": []}')
    ob = {"net": "V", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "U2", "pad": "1"}, "widths": {"F.Cu": 1}}
    (judged,) = phase_run.judge_obligations("board.kicad_pcb", [ob], drc, is_real=lambda _: True)
    assert judged == {"joined": True, "violated": False, "under": {"F.Cu": 0.2}}


# Joins through filled copper: a pour's width is the narrowest neck of its filled copper along the join (as the
# current-path check measures a fill, checks._Fill.width); an intermediate pad is measured by its outline the same way.

def _zone(*outlines, kind="zone"):
    from placemat.board_geometry import CopperItem
    from placemat.values import Box
    return CopperItem(kind, "V", frozenset((F,)), outlines, Box.of_points(tuple(p for poly in outlines for p in poly)))


_OB = {"net": "V", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "U2", "pad": "1"}, "widths": {"F.Cu": 1.0}}
_LEFT = ((4, 9), (20, 9), (20, 11), (4, 11))
_RIGHT = ((25, 9), (41, 9), (41, 11), (25, 11))
_WIDE = ((4, 9), (41, 9), (41, 11), (4, 11))
_HOURGLASS = ((4, 9), (20, 9), (20, 9.9), (25, 9.9), (25, 9), (41, 9),
              (41, 11), (25, 11), (25, 10.1), (20, 10.1), (20, 11), (4, 11))


def _judge(monkeypatch, tmp_path, geometry, ob=_OB, neck_mm=0.0):
    from placemat.kicad import phase_run
    monkeypatch.setattr("placemat.kicad.read.read_board", lambda _: geometry)
    monkeypatch.setattr(phase_run, "joined_pairs", lambda *_: [True])
    drc = tmp_path / "drc.json"
    drc.write_text('{"violations": [], "unconnected_items": []}')
    (judged,) = phase_run.judge_obligations("board.kicad_pcb", [ob], drc, neck_mm, is_real=lambda _: True)
    return judged


def test_a_track_entering_its_end_pad_off_the_anchor_joins_the_pad(monkeypatch, tmp_path):
    from tests.test_route_widths_board import _board, _track
    geometry = _board(_track((5, 10), (40, 10), 1.0))       # U1's pad 1 is at (5.2, 10): the track ends 0.2 mm off it
    assert _judge(monkeypatch, tmp_path, geometry) == {"joined": True, "violated": False, "under": {}}


def test_a_pour_neck_narrower_than_asked_fails_on_its_measured_width(monkeypatch, tmp_path):
    from placemat.kicad import phase_run
    from tests.test_route_widths_board import _board
    judged = _judge(monkeypatch, tmp_path, _board(_zone(_HOURGLASS)))
    assert set(judged) == {"joined", "violated", "under"} and 0.1 <= judged["under"]["F.Cu"] <= 0.25
    assert not phase_run.is_clean(judged, None)
    assert phase_run.widths_failed([{}], [[_OB]], [[judged]]) == 1


def test_a_pour_wider_than_asked_passes(monkeypatch, tmp_path):
    from placemat.kicad import phase_run
    from tests.test_route_widths_board import _board
    judged = _judge(monkeypatch, tmp_path, _board(_zone(_WIDE)))
    assert judged == {"joined": True, "violated": False, "under": {}}
    assert phase_run.is_clean(judged, None)
    drawn = _judge(monkeypatch, tmp_path, _board(_zone(_WIDE, kind="poly")))
    assert drawn == {"joined": True, "violated": False, "under": {}}


def test_a_pour_neck_inside_the_neck_allowance_is_not_counted(monkeypatch, tmp_path):
    from tests.test_route_widths_board import _board, _track
    near_pad = ((4, 9), (6, 9), (6, 9.9), (7, 9.9), (7, 9), (12, 9), (12, 11), (7, 11), (7, 10.1), (6, 10.1),
                (6, 11), (4, 11))                           # 0.2 mm neck 1-2 mm from U1's pad
    geometry = _board(_zone(near_pad), _track((11, 10), (40, 10), 1.0))
    assert _judge(monkeypatch, tmp_path, geometry, neck_mm=3.0)["under"] == {}
    assert _judge(monkeypatch, tmp_path, geometry, neck_mm=0.0)["under"]


def test_a_pour_and_a_narrow_track_in_series_fail_on_the_track(monkeypatch, tmp_path):
    from tests.test_route_widths_board import _board, _track
    geometry = _board(_zone(_LEFT), _track((19, 10), (40, 10), 0.2))
    assert _judge(monkeypatch, tmp_path, geometry) == {"joined": True, "violated": False, "under": {"F.Cu": 0.2}}


def test_a_wide_track_beside_a_pour_neck_passes(monkeypatch, tmp_path):
    from tests.test_route_widths_board import _board, _track
    geometry = _board(_zone(_HOURGLASS), _track((5, 10), (5, 20), 1), _track((5, 20), (40, 20), 1),
                      _track((40, 20), (40, 10), 1))
    assert _judge(monkeypatch, tmp_path, geometry) == {"joined": True, "violated": False, "under": {}}


def test_pours_that_do_not_touch_do_not_join():
    from placemat.kicad.phase_run import joining_spans
    from tests.test_route_widths_board import _board
    assert joining_spans(_board(_zone(_LEFT, _RIGHT)), _OB) is None


def test_an_intermediate_pad_is_judged_by_its_outline_width(monkeypatch, tmp_path):
    from dataclasses import replace
    from tests.test_route_widths_board import _board, _track
    middle = footprint("U3", 20.6 + 1.0, 10.0, nets=("V", "X"))        # its 1 x 1 mm pad 1 spans x 19.7 to 20.7
    # the tracks' round ends stop 0.1 mm short of the pad each side: they join it, not each other
    geometry = _board(_track((5, 10), (18.8, 10), 2.0), _track((21.6, 10), (40, 10), 2.0))
    geometry = replace(geometry, footprints=geometry.footprints + (middle,))
    wide = dict(_OB, widths={"F.Cu": 2.0})
    under = _judge(monkeypatch, tmp_path, geometry, wide)["under"]
    assert 0.85 <= under["F.Cu"] <= 1.05
    assert _judge(monkeypatch, tmp_path, geometry, dict(_OB, widths={"F.Cu": 0.5}))["under"] == {}


def test_a_wider_track_path_is_used_beside_one_through_a_narrow_pad():
    from dataclasses import replace
    from placemat.kicad.phase_run import joining_spans, width_shortfall
    from tests.test_route_widths_board import _board, _track
    middle = footprint("U3", 20.6 + 1.0, 10.0, nets=("V", "X"))
    geometry = _board(_track((5, 10), (18.8, 10), 2.0), _track((21.6, 10), (40, 10), 2.0),
                      _track((5, 10), (5, 20), 2.0), _track((5, 20), (40, 20), 2.0), _track((40, 20), (40, 10), 2.0))
    geometry = replace(geometry, footprints=geometry.footprints + (middle,))
    ob = dict(_OB, widths={"F.Cu": 2.0})
    spans = joining_spans(geometry, ob, full_width=True)
    assert spans is not None and width_shortfall(spans, ob["widths"], 0.0) == {}


def test_a_track_end_within_half_its_width_of_a_pour_joins_it():
    # KiCad joins a track to a zone when the track's end lies within half the track's width of the fill
    from placemat.kicad.phase_run import joining_spans, width_shortfall
    from tests.test_route_widths_board import _board, _track
    geometry = _board(_zone(_LEFT), _track((20.3, 10), (40, 10), 1.0))     # its end 0.3 mm past the fill's edge
    spans = joining_spans(geometry, _OB, full_width=True)
    assert spans is not None and width_shortfall(spans, _OB["widths"], 0.0) == {}
    apart = _board(_zone(_LEFT), _track((20.6, 10), (40, 10), 1.0))       # 0.6 mm past: not joined
    assert joining_spans(apart, _OB) is None


def test_a_short_track_whose_end_rounds_off_its_own_line_still_joins():
    # joints are taken at 1 um; a 0.6 mm track's end 1.7 um past its rounded joint is still that joint
    from placemat.kicad.phase_run import joining_spans
    from tests.test_route_widths_board import _board, _track
    end = 19.9000017
    geometry = _board(_track((5, 10), (end, 10), 1.0), _track((end, 10), (20.5, 10), 1.0), _track((20.5, 10), (40, 10), 1.0))
    assert joining_spans(geometry, _OB) is not None


def _arc(a, b, width, bulge=1.2):
    from dataclasses import replace
    from tests.test_route_widths_board import _track
    t = _track(a, b, width)
    return replace(t, length_mm=t.length_mm * bulge)        # a curved track: longer than its chord


def test_an_arc_at_full_width_is_measured_by_its_own_length(monkeypatch, tmp_path):
    from tests.test_route_widths_board import _board, _track
    geometry = _board(_track((5, 10), (15, 10), 1.0), _arc((15, 10), (30, 10), 1.0), _track((30, 10), (40, 10), 1.0))
    assert _judge(monkeypatch, tmp_path, geometry) == {"joined": True, "violated": False, "under": {}}


def test_a_narrow_arc_is_under_its_width(monkeypatch, tmp_path):
    from placemat.kicad.phase_run import joining_spans
    from tests.test_route_widths_board import _board, _track
    geometry = _board(_track((5, 10), (15, 10), 1.0), _arc((15, 10), (30, 10), 0.3), _track((30, 10), (40, 10), 1.0))
    assert _judge(monkeypatch, tmp_path, geometry)["under"] == {"F.Cu": 0.3}
    spans = joining_spans(geometry, _OB)
    assert sum(length for _, length in spans) == pytest.approx(10 + 15 * 1.2 + 10, abs=1e-6)


# KiCad 10's connectivity joins same-net copper wherever it overlaps (pcbnew 10.0.6, GetConnectedItems after a zone
# fill), not only at track ends. Each case: does a copper path join U1.1 (5.2, 10) to U2.1 (40, 10)?
def _via(at):
    from tests.test_route_widths_board import _via as via
    return via(at)


def _rect(x0, y0, x1, y1):
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def _overlap_cases():
    from dataclasses import replace
    from tests.test_route_widths_board import _track
    B = CopperLayer.B
    pad = footprint("U3", 20.2 + 1.4, 10.0, nets=("V", "X"))          # its pad 1, 1 x 1 mm, at (20.2, 10)
    up = [_track((40, 15), (40, 10), 1.0)]
    return {
        "track end 0.3 mm outside a fill, width 1.0": (True, [_zone(_LEFT), _track((20.3, 10), (40, 10), 1.0)], []),
        "track end 0.6 mm outside a fill, width 1.0": (False, [_zone(_LEFT), _track((20.6, 10), (40, 10), 1.0)], []),
        "track end 0.3 mm outside the end pad, width 1.0": (True, [_track((5, 10), (39.2, 10), 1.0)], []),
        "track end 0.3 mm outside the end pad, width 0.4": (False, [_track((5, 10), (39.2, 10), 0.4)], []),
        "via centre 0.3 mm outside a fill, diameter 0.6 + 0.3": (True, [_zone(_LEFT), _via((20.3, 10)), _track(
            (20.3, 10), (30, 10), 1.0, layer=B), _via((30, 10)), _track((30, 10), (40, 10), 1.0)], []),
        "track crossing a fill, both ends outside": (True, [_zone(_rect(14, 5, 16, 20)), _track((5, 10), (25, 10), 1.0),
                                                            _track((10, 15), (40, 15), 1.0)] + up, []),
        "tracks crossing a pad, ends outside": (True, [_track((5, 9.7), (21, 9.7), 0.2),
                                                       _track((19.4, 10.3), (40, 10.3), 0.2)], [pad]),
        "track side over a fill edge": (True, [_zone(_LEFT), _track((20.4, 5), (20.4, 15), 1.0),
                                               _track((20.4, 15), (40, 15), 1.0)] + up, []),
        "X crossing of two tracks": (True, [_track((5, 10), (25, 10), 1.0), _track((22, 5), (22, 15), 1.0),
                                            _track((22, 15), (40, 15), 1.0)] + up, []),
        "parallel tracks overlapping by 0.05 mm": (True, [_track((5, 10), (25, 10), 1.0),
                                                          _track((15, 10.95), (40, 10.95), 1.0)], []),
        "T: a 1.0 mm end 0.4 mm off a 0.6 mm track": (True, [_track((5, 10), (19.6, 10), 1.0),
                                                            _track((20, 5), (20, 30), 0.6),
                                                            _track((20.4, 15), (40, 15), 1.0)] + up, []),
        "parallel tracks 0.05 mm apart": (False, [_track((5, 10), (25, 10), 1.0),
                                                  _track((15, 11.05), (40, 11.05), 1.0)], []),
    }


@pytest.mark.parametrize("case", sorted(_overlap_cases()))
def test_copper_joins_where_it_overlaps_as_kicad_joins_it(case):
    from dataclasses import replace
    from placemat.kicad.phase_run import joining_spans
    from tests.test_route_widths_board import _board
    joined, copper, parts = _overlap_cases()[case]
    geometry = _board(*copper)
    geometry = replace(geometry, footprints=geometry.footprints + tuple(parts))
    assert (joining_spans(geometry, dict(_OB, widths={"F.Cu": 0.2, "B.Cu": 0.2})) is not None) == joined


_SPOKED = ((5.5, 9.8), (7.7, 9.8), (7.7, 8), (37.5, 8), (37.5, 9.8), (39.7, 9.8), (39.7, 10.2), (37.5, 10.2),
           (37.5, 12), (7.7, 12), (7.7, 10.2), (5.5, 10.2))       # a 4 mm pour, a 0.4 mm spoke into each end pad


def test_a_pour_with_a_spoke_at_each_end_pad_is_narrow_only_at_the_spokes(monkeypatch, tmp_path):
    geometry = __import__("tests.test_route_widths_board", fromlist=["_board"])._board(_zone(_SPOKED))
    assert _judge(monkeypatch, tmp_path, geometry, neck_mm=3.0)["under"] == {}
    assert 0.3 <= _judge(monkeypatch, tmp_path, geometry, neck_mm=0.0)["under"]["F.Cu"] <= 0.4


def test_the_narrow_runs_of_a_fill_are_its_spokes_each_measured_where_it_lies():
    from placemat.checks import _Fill
    from tests.test_route_widths_board import _board
    g = _board()
    pads = {fp.ref: (fp.pads[0].outlines[0],) for fp in g.footprints}
    fill = _Fill(_SPOKED, 0.05)
    got = fill.narrow_runs(pads["U1"], pads["U2"], 1.0)
    runs = got["runs"]
    assert len(runs) == 2 and all(0.3 <= r["width_mm"] <= 0.4 for r in runs)
    assert runs[0]["to_mm"] < 3.0 and runs[1]["from_mm"] > got["length_mm"] - 3.0


def test_a_discs_touching_cells_are_those_of_its_polygon():
    from placemat.checks import _Fill
    from placemat.geometry import circle_polygon
    from placemat.values import Location
    fill = _Fill(_WIDE, 0.05)
    for at, r in (((12.0, 10.0), 0.3), ((20.0, 10.6), 0.5), ((40.8, 10.0), 0.2)):
        tau = fill.level(1.0)
        disc = fill.touching_disc(at, r, tau)
        poly = fill.touching((circle_polygon(Location(*at), r, 64),), tau)
        assert len(disc ^ poly) <= 0.1 * max(len(poly), 1)


# a 4 mm pour with a 0.4 mm spoke into U1's pad and a 0.8 mm neck 5 mm long at x 20 to 25, its own end at U2's pad
_SPOKE_AND_NECK = ((5.5, 9.8), (7.7, 9.8), (7.7, 8), (20, 8), (20, 9.6), (25, 9.6), (25, 8), (41, 8), (41, 12), (25, 12),
                   (25, 10.4), (20, 10.4), (20, 12), (7.7, 12), (7.7, 10.2), (5.5, 10.2))


def test_each_narrow_run_of_a_fill_is_reported_at_its_own_width_and_length(monkeypatch, tmp_path):
    from placemat.checks import _Fill
    from tests.test_route_widths_board import _board
    geometry = _board(_zone(_SPOKE_AND_NECK))
    under = _judge(monkeypatch, tmp_path, geometry, neck_mm=3.0)["under"]
    assert 0.7 <= under["F.Cu"] <= 0.85                    # the mid-pour neck; the spoke is in the allowance
    pads = {fp.ref: (fp.pads[0].outlines[0],) for fp in geometry.footprints}
    runs = _Fill(_SPOKE_AND_NECK, 0.05).narrow_runs(pads["U1"], pads["U2"], 1.0)["runs"]
    spoke, neck = runs
    assert 0.3 <= spoke["width_mm"] <= 0.4 and 0.7 <= neck["width_mm"] <= 0.85
    assert 4.5 <= neck["narrow_mm"] <= 5.6 and 19.5 <= neck["at"][0] <= 25.5
