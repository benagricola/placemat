"""A part's `Pm.KeepOut` holds in the plan as well as in the check: a pour or another part's pad on the nets it
says to stay away from keeps its distance from that part's pads on the nets it keeps clear, as a clearance between
those and nothing else. Tracks and vias of those nets are the part's own pad escapes and keep the netclass figure,
as do other copper on the same nets. Pure: synthetic boards, and kicad-cli's DRC for the rule written beside the
board."""
import math

import pytest

from placemat.checks import keep_out
from placemat.copper import Track
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


def _regulator(ref, cx, cy, far=8.0, fields=None):
    """A part with an FB pad (1 x 1, centred at (cx, cy)) and an SW pad `far` mm east of it."""
    a, b = pad(ref, ref.lower(), 1, "FB", cx, cy), pad(ref, ref.lower(), 2, "SW", cx + far, cy)
    body = Box(cx - 0.5, cy - 0.5, cx + far + 0.5, cy + 0.5)
    return Footprint(ref, ref.lower(), None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body,
                     (a, b), fields=dict(fields or {}))


# ---------------------------------------------------------------- the rule

def test_a_rule_of_a_part_matches_its_pad_against_copper_that_is_neither_its_pad_nor_a_track_or_a_via():
    rule = Rule("clearance", 1.0, "keep", between=("SW", "FB"), of="U1")
    rules = ClearanceRules([rule], {})
    assert rules.match("SW", "FB", "", "U1") is rule                  # a pour of SW (no owner) and U1's FB pad
    assert rules.match("FB", "SW", "U1", "") is rule
    assert rules.match("SW", "FB", "L1", "U1") is rule                # another part's SW pad
    assert rules.match("SW", "FB", "U1", "U1") is None                # its own SW pad: the footprint sets that gap
    assert rules.match("SW", "FB", "", "R1") is None                  # another part's FB pad
    assert rules.match("SW", "GND", "", "U1") is None
    assert rules.match("SW", "FB", "", "U1", wire_a=True) is None     # a track or a via of SW: the part's pad escapes
    assert rules.match("FB", "SW", "U1", "", wire_b=True) is None


def test_the_rule_is_written_for_kicad_by_the_part_and_both_nets():
    text = rules_text([Rule("clearance", 1.0, "U1 keep-out SW to FB: datasheet", between=("SW", "FB"), of="U1")])
    assert "B.Reference == 'U1'" in text and "!(A.Reference == 'U1')" in text and "(min 1mm)" in text
    assert "A.Reference == 'U1'" in text and "B.NetName == 'SW'" in text      # and in the other order
    assert "A.Type != 'Track' && A.Type != 'Via'" in text and "B.Type != 'Track' && B.Type != 'Via'" in text


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


def test_a_track_on_an_away_net_is_not_held_to_the_distance():
    """A track of SW leaves the part's SW pad: its pad escapes are not the rule's, wherever they run, so the
    track runs the same 45 half a millimetre off the FB pad as it does with no annotation."""
    plan, near = _run()
    plain, _ = _run(annotated=False)
    assert _tracks(plan) == _tracks(plain)
    assert _nearest(plan, near) == pytest.approx(0.5, abs=1e-6)
    assert not [f for f in declared_findings(plan) if f.kind == "copper"]


def test_a_via_on_an_away_net_is_not_held_to_the_distance_either():
    u1 = footprint("U1", 10, 10, nets=("SW", "SW"))
    x1 = _regulator("X1", 12.4, 12.0, far=8.0, fields=ANNOTATION)
    b = Board(board_geometry([u1, x1], width=50, height=50, clearance=0.2), edge_margin=0.5, keep_going=True)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("x1"), at=Location(12.4, 12.0))
    b.via(Net("SW"), Location(12.4, 11.0), why="0.5 mm from X1's FB pad")
    plan = b.resolve()
    assert [op for op in plan.copper if type(op).__name__ == "Via"]
    assert not [f for f in declared_findings(plan) if f.kind == "copper"], plan.findings


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

def _pours_as_copper(plan):
    from placemat.board_geometry import CopperItem
    return [CopperItem("poly", p.net, frozenset([F]), (_copper(p),), Box.of_points(_copper(p))) for p in _pours(plan)]


def test_the_check_and_the_plan_hold_the_same_distance():
    plan, x1, _ = _pour_plan(True)
    parts = [_part("S0", "SW", 10.0, 10.0), _part("S1", "SW", 16.0, 10.0), _part("S2", "SW", 13.0, 15.0), x1]
    judged = keep_out(board_geometry(parts, copper=_pours_as_copper(plan), width=60, height=60))
    (v,) = [v for v in judged if v.subject == "SW"]
    assert v.limit == pytest.approx(KEEP) and v.value >= KEEP - 0.03, v.line()      # the arc sag and stroke the fit allows for


# ------------------------------------------------------------------- kicad

def _kicad_clearance(tmp_path, name, rule, items):
    """kicad-cli's clearance violations quoting `rule`, on a board with U1's FB pad at (10, 10) (and its SW pad at
    (10, 12)), L1's SW pad at (14, 10) and `items`, each (kind, net, geometry): 'track' (x1, y1, x2, y2), 'via'
    (x, y), 'poly' ((x, y), ...), 'pad' (ref, number, x, y, size) or 'own' (a further pad of U1: number, x, y, size),
    judged under `rule` written beside it."""
    import json
    import subprocess
    pcbnew = pytest.importorskip("pcbnew")
    from placemat.rules import write_rules
    mm = pcbnew.FromMM
    board = pcbnew.CreateEmptyBoard()
    nets = {}

    def net(n):
        if n not in nets:
            nets[n] = pcbnew.NETINFO_ITEM(board, n)
            board.Add(nets[n])
        return nets[n]

    def part(ref, pads):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPosition(pcbnew.VECTOR2I(mm(pads[0][2]), mm(pads[0][3])))
        for number, n, x, y, size in pads:
            p = pcbnew.PAD(fp)
            p.SetShape(pcbnew.PAD_SHAPE_RECT)
            p.SetSize(pcbnew.VECTOR2I(mm(size), mm(size)))
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            ls = pcbnew.LSET()
            ls.AddLayer(pcbnew.F_Cu)
            p.SetLayerSet(ls)
            p.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
            p.SetNumber(str(number))
            p.SetNet(net(n))
            fp.Add(p)
        board.Add(fp)
    mine = [(1, "FB", 10.0, 10.0, 0.6), (2, "SW", 10.0, 12.0, 0.6)]
    mine += [(geom[0], n, geom[1], geom[2], geom[3]) for kind, n, geom in items if kind == "own"]
    part("U1", mine)
    part("L1", [(1, "SW", 14.0, 10.0, 0.6)])
    for item in items:
        kind, n, geom = item
        if kind == "own":
            continue
        if kind == "pad":
            part(geom[0], [(geom[1], n, geom[2], geom[3], geom[4])])
        elif kind == "track":
            t = pcbnew.PCB_TRACK(board)
            t.SetLayer(pcbnew.F_Cu)
            t.SetWidth(mm(0.2))
            t.SetStart(pcbnew.VECTOR2I(mm(geom[0]), mm(geom[1])))
            t.SetEnd(pcbnew.VECTOR2I(mm(geom[2]), mm(geom[3])))
            t.SetNet(net(n))
            board.Add(t)
        elif kind == "via":
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(mm(geom[0]), mm(geom[1])))
            v.SetWidth(mm(0.45))
            v.SetDrill(mm(0.2))
            v.SetNet(net(n))
            board.Add(v)
        else:
            outline = pcbnew.SHAPE_POLY_SET()
            outline.NewOutline()
            for x, y in geom:
                outline.Append(mm(x), mm(y))
            sh = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
            sh.SetLayer(pcbnew.F_Cu)
            sh.SetFilled(True)
            sh.SetWidth(mm(0.1))
            sh.SetPolyShape(outline)
            sh.SetNetCode(net(n).GetNetCode())
            board.Add(sh)
    pcb = tmp_path / ("%s.kicad_pcb" % name)
    board.Save(str(pcb))
    write_rules(str(pcb), [rule])
    report = tmp_path / ("%s.json" % name)
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    return [v for v in json.loads(report.read_text()).get("violations", [])
            if v.get("type") == "clearance" and "keep-out" in v.get("description", "")]


RULE = Rule("clearance", 1.0, "U1 keep-out SW to FB: datasheet", between=("SW", "FB"), of="U1")
NEAR_POUR = ((10.0, 11.4), (13.0, 11.4), (13.0, 12.4), (10.0, 12.4))     # 1.1 mm under the FB pad's edge at 0.3: 1.1 off
CLOSE_POUR = ((10.4, 10.5), (13.0, 10.5), (13.0, 11.5), (10.4, 11.5))    # 0.2 mm from the pad's edge


@needs_kicad
@pytest.mark.parametrize("name, item, flagged", [
    ("a pour nearer than the distance", ("poly", "SW", CLOSE_POUR), True),
    ("a pour at the distance", ("poly", "SW", NEAR_POUR), False),
    ("another part's pad nearer than the distance", ("pad", "SW", ("L2", 1, 10.0, 11.0, 0.6)), True),
    ("another part's pad at the distance", ("pad", "SW", ("L2", 1, 10.0, 11.7, 0.6)), False),
    ("the part's own pad nearer than the distance", ("own", "SW", (3, 10.0, 10.9, 0.6)), False),
    ("a track of the part's own pad escape", ("track", "SW", (10.0, 12.0, 10.8, 10.4)), False),
    ("a track nearer than the distance, from nowhere", ("track", "SW", (10.5, 10.6, 12.0, 10.6)), False),
    ("a via nearer than the distance", ("via", "SW", (10.0, 11.0)), False),
    ("a pour of another net nearer", ("poly", "GND", CLOSE_POUR), False),
])
def test_kicad_holds_a_pour_and_another_parts_pad_to_the_rule_and_not_a_track_or_a_via(tmp_path, name, item, flagged):
    """The written rule, in kicad-cli's DRC: the part's pad on FB keeps 1.0 mm from SW copper that is a pour or
    another part's pad, and the part's own SW pad is never held. A track or a via of SW is not held, which is what
    keeps the part's own pad escapes out of it; KiCad's rule language cannot say which tracks leave a pad."""
    got = _kicad_clearance(tmp_path, "case", RULE, [item])
    assert bool(got) is flagged, (name, got)
