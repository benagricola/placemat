"""A part's `Pm.KeepOut` holds in the plan as well as in the check: copper on
the nets it says to stay away from keeps its distance from that part's pads
on the nets it keeps clear, as a clearance between those and nothing else.
Other copper on the same nets keeps the netclass figure. Pure: synthetic
boards, and kicad-cli's DRC for the rule written beside the board."""
import dataclasses
import math

import pytest

from placemat.checks import keep_out
from placemat.copper import Pour, Track
from placemat.geometry import poly_distance
from placemat.layout import Board
from placemat.rules import ClearanceRules, Rule, rules_text
from placemat.board_geometry import Footprint
from placemat.values import Box, CopperLayer, Face, Net, PadRef, Part, Location
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, declared_findings, footprint, pad
from tests.test_clearance_rules import _one_pad
from tests.test_pour_fitted import CLEARANCE, _copper, _part, _pours, _refs

F = CopperLayer.F
CITE = "datasheet rev B, section 10.2, layout example"
KEEP = 1.0
ANNOTATION = {"Pm.KeepOut": "%gmm pads=FB away=SW; %s" % (KEEP, CITE)}


def _with(fp, **fields):
    return dataclasses.replace(fp, fields=dict(fields))


def _regulator(ref, cx, cy, far=8.0, fields=None):
    """A part with an FB pad (1 x 1, centred at (cx, cy)) and an SW pad `far` mm east of it."""
    a, b = pad(ref, ref.lower(), 1, "FB", cx, cy), pad(ref, ref.lower(), 2, "SW", cx + far, cy)
    body = Box(cx - 0.5, cy - 0.5, cx + far + 0.5, cy + 0.5)
    return Footprint(ref, ref.lower(), None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body,
                     (a, b), fields=dict(fields or {}))


# ---------------------------------------------------------------- the rule

def test_a_rule_of_a_part_matches_its_pad_against_copper_that_is_not_its_own_pad():
    rule = Rule("clearance", 1.0, "keep", between=("SW", "FB"), of="U1")
    rules = ClearanceRules([rule], {})
    assert rules.match("SW", "FB", "", "U1") is rule                  # a track of SW and U1's FB pad
    assert rules.match("FB", "SW", "U1", "") is rule
    assert rules.match("SW", "FB", "L1", "U1") is rule                # another part's SW pad
    assert rules.match("SW", "FB", "U1", "U1") is None                # its own SW pad: the footprint sets that gap
    assert rules.match("SW", "FB", "", "R1") is None                  # another part's FB pad
    assert rules.match("SW", "GND", "", "U1") is None


def test_the_rule_is_written_for_kicad_by_the_part_and_both_nets():
    text = rules_text([Rule("clearance", 1.0, "U1 keep-out SW to FB: datasheet", between=("SW", "FB"), of="U1")])
    assert "B.Reference == 'U1'" in text and "!(A.Reference == 'U1')" in text and "(min 1mm)" in text
    assert "A.Reference == 'U1'" in text and "B.NetName == 'SW'" in text      # and in the other order


# ----------------------------------------------------------------- a track

def _run(annotated=True, gap=0.5, owner_has_it=True, width=0.2):
    """Track SW from U1's east pad (11.4, 10) to (25, 16): along the 45 first when that clears, else along
    y = 10. A 1 mm pad of net FB stands `gap` mm off the 45's north-east side; it is X1's, which carries
    the annotation when `annotated`, or R1's, a part that does not, when `owner_has_it` is False."""
    u1 = footprint("U1", 10, 10, nets=("SW", "SW"))
    t = 0.5 * math.sqrt(2.0) + width / 2.0 + gap
    cx, cy = 14.4 + t / math.sqrt(2.0), 13.0 - t / math.sqrt(2.0)
    near = _regulator("X1", cx, cy, fields=ANNOTATION if annotated else None) if owner_has_it \
        else _one_pad("R1", cx, cy, "FB")
    parts = [u1, near]
    if annotated and not owner_has_it:
        parts.append(_regulator("X1", 30, 35, fields=ANNOTATION))
    b = Board(board_geometry(parts, width=50, height=50, clearance=0.2), edge_margin=0.5, keep_going=True)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part(near.inst), at=Location(cx, cy))
    if annotated and not owner_has_it:
        b.place(Part("x1"), at=Location(30, 35))
    b.track(Net("SW"), [PadRef(Part("u1"), 2), Location(25, 16)], layer=F, width=width, chamfer=0)
    return b.resolve(), near


def _tracks(plan):
    return [op for op in plan.copper if isinstance(op, Track)]


def _nearest(plan, fp):
    return min(poly_distance(t.polygon, p.outlines[0]) for t in _tracks(plan) for p in fp.pads if p.net == "FB")


def test_without_the_annotation_the_track_runs_the_45_half_a_millimetre_off_the_pad():
    plan, near = _run(annotated=False)
    assert _tracks(plan)[0].end.y == pytest.approx(16.0)
    assert _nearest(plan, near) == pytest.approx(0.5, abs=1e-6)


def test_a_track_on_an_away_net_keeps_the_parts_distance_from_its_pad():
    plan, near = _run()
    assert _nearest(plan, near) >= KEEP - 1e-6, _nearest(plan, near)
    assert not [f for f in declared_findings(plan) if f.kind == "copper"]


def test_the_distance_is_that_parts_only():
    """The same pad on the same net, a part that does not carry the annotation: the track runs as it did."""
    plan, near = _run(annotated=True, owner_has_it=False)
    assert _tracks(plan)[0].end.y == pytest.approx(16.0)
    assert _nearest(plan, near) == pytest.approx(0.5, abs=1e-6)


def test_the_plans_rules_carry_the_derived_rule_once_however_often_it_resolves():
    plan, _ = _run()
    ours = [r for r in plan.rules if r.of is not None]
    assert len(ours) == 1 and ours[0].between == ("SW", "FB") and ours[0].min_mm == pytest.approx(KEEP)
    assert CITE in ours[0].why


def test_a_distance_below_the_netclass_figure_does_not_lower_it():
    low = {"Pm.KeepOut": "0.05mm pads=FB away=SW; " + CITE}
    u1 = footprint("U1", 10, 10, nets=("SW", "SW"))
    x1 = _regulator("X1", 20, 20, fields=low)
    b = Board(board_geometry([u1, x1], width=50, height=50, clearance=0.2), edge_margin=0.5, keep_going=True)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("x1"), at=Location(20, 20))
    (rule,) = [r for r in b.resolve().rules if r.of is not None]
    assert rule.min_mm == pytest.approx(0.2)


def test_a_script_rule_that_asks_for_more_is_not_lowered_by_the_datasheet():
    u1 = footprint("U1", 10, 10, nets=("SW", "SW"))
    x1 = _regulator("X1", 20, 20, fields={"Pm.KeepOut": "0.5mm pads=FB away=SW; " + CITE})
    b = Board(board_geometry([u1, x1], width=50, height=50, clearance=0.2), edge_margin=0.5, keep_going=True)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("x1"), at=Location(20, 20))
    b.rule(clearance=0.9, between=(Net("SW"), Net("FB")), why="a script's own")
    (rule,) = [r for r in b.resolve().rules if r.of is not None]
    assert rule.min_mm == pytest.approx(0.9)


def test_a_part_keep_out_that_does_not_read_refuses_the_run():
    u1 = footprint("U1", 10, 10, nets=("SW", "SW"))
    x1 = _regulator("X1", 20, 20, fields={"Pm.KeepOut": "1mm pads=FB away=SW"})
    b = Board(board_geometry([u1, x1], width=50, height=50), edge_margin=0.5, keep_going=True)
    with pytest.raises(ValueError, match="no citation"):
        b.resolve()


# ------------------------------------------------------------------ a pour

def _pour_plan(annotated):
    """Three SW pads in a triangle, and an FB pad beside each of its two long sides, as near as the netclass
    clearance lets the pour pass: X1's (the part with the annotation) and R1's."""
    s0, s1, s2 = _part("S0", "SW", 10.0, 10.0), _part("S1", "SW", 16.0, 10.0), _part("S2", "SW", 13.0, 15.0)
    x1 = _regulator("X1", 16.2, 12.5, far=14.0, fields=ANNOTATION if annotated else None)
    r1 = _part("R1", "FB", 9.8, 12.5)
    b = Board(board_geometry([s0, s1, s2, x1, r1], width=60, height=60, clearance=CLEARANCE), edge_margin=1.0)
    b.pour(Net("SW"), _refs("s", 3), layer=F, swallow_pads=True)
    return b.resolve(), x1, r1


def _gap(plan, fp):
    (p,) = _pours(plan)
    return poly_distance(_copper(p), fp.pads[0].outlines[0])


def test_a_fitted_pour_keeps_the_distance_from_the_parts_pad_and_not_from_anothers():
    plain, x1_plain, r1_plain = _pour_plan(False)
    held, x1, r1 = _pour_plan(True)
    assert not [f for f in declared_findings(held) if f.kind == "pour"], held.findings
    assert _gap(plain, x1_plain) < 0.3                                 # the fit passes it at the netclass clearance
    assert _gap(held, x1) >= KEEP - 0.03                               # the arc sag and stroke the fit allows for
    assert _gap(held, r1) == pytest.approx(_gap(plain, r1_plain), abs=1e-6)     # R1's pad is no concern of X1's rule


# ----------------------------------------------------------------- the check

def test_the_check_and_the_plan_hold_the_same_distance():
    plan, near = _run()
    judged = keep_out(board_geometry([footprint("U1", 10, 10, nets=("SW", "SW"), fields={"Pm.Aggressor": "true"}),
                                      near], copper=_tracks_as_copper(plan)))
    assert judged and all(v.ok is not False for v in judged), [v.line() for v in judged]


def _tracks_as_copper(plan):
    from placemat.board_geometry import CopperItem
    from placemat.values import Box
    return [CopperItem("track", t.net, frozenset([F]), (t.polygon,), Box.of_points(t.polygon), None, t.width,
                       anchors=((t.start.x, t.start.y), (t.end.x, t.end.y)),
                       length_mm=math.hypot(t.end.x - t.start.x, t.end.y - t.start.y)) for t in _tracks(plan)]


# ------------------------------------------------------------------- kicad

@needs_kicad
def test_kicad_flags_a_track_that_ignores_the_rule_and_passes_the_one_that_keeps_it(tmp_path):
    from tests.test_clearance_rules_drc import _clearance_violations
    held, _ = _run()
    plain, _ = _run(annotated=False)
    assert _clearance_violations(tmp_path, plain, held.rules, "plain_under_rule")       # the rule is real to KiCad
    assert _clearance_violations(tmp_path, held, held.rules, "held_under_rule") == []
    assert _clearance_violations(tmp_path, plain, [], "plain_under_netclass") == []
