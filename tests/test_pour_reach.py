"""`reach=` on a fitted pour: its copper is the fitted outline grown by `reach`
into the room round it, cut back by every other net's clearance outline
planned before it, of which the part joined to the members is kept - a
static polygon, never a zone. And a pad nearer another net's copper than the
clearance (its footprint sets the gap) is held only as far as it is clear.

Plan tests are pure (synthetic boards); the written-board tests build a
from-scratch pcbnew board with two parts, so the net carries a current
between them and `check current-path` has a route to measure."""
import dataclasses

import pcbnew
import pytest

from placemat import pourfit
from placemat.checks import current_paths
from placemat.copper import Pour
from placemat.geometry import point_in_polygon, poly_distance
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Net, PadRef, Part
from tests.conftest import needs_kicad
from tests.fixtures import declared_findings
from tests.test_pour_fitted import CLEARANCE, SAG, _board, _part, _pours, _refs

F = CopperLayer.F
ARC_ERROR = 0.005           # [geometry] arc_error_nm: what a read board's rounded stroke may be off by


def _node(extra=(), reach=None, **kw):
    """A switch node of a 1.0 x 2.5 pad and a 1.9 x 2.5 pad offset diagonally."""
    a = _part("S0", "SW", 10.0, 10.0, 1.0, 2.5)
    b = _part("S1", "SW", 12.7, 11.1, 1.9, 2.5)
    board = _board([a, b] + list(extra))
    board.pour(Net("SW"), _refs("s", 2), layer=F, swallow_pads=True, reach=reach, **kw)
    return board


def _copper(p):
    return pourfit.offset(p.points, p.stroke / 2.0)


def _hull_box(pads):
    return Box.union([Box.of_points(p) for p in pads])


def test_without_reach_the_pour_is_the_hull_of_its_pads():
    plan = _node().resolve()
    (p,) = _pours(plan)
    assert len(p.points) == 6                       # two rectangles' hull


def test_reach_grows_the_outline_into_the_room_round_it():
    plan = _node(reach=0.4).resolve()
    (p,) = _pours(plan)
    assert p.fitted
    base = _pours(_node().resolve())[0]
    box, bare = Box.of_points(p.points), Box.of_points(base.points)
    assert box.left == pytest.approx(bare.left - 0.4, abs=1e-5) and box.right == pytest.approx(bare.right + 0.4, abs=1e-5)
    assert box.top == pytest.approx(bare.top - 0.4, abs=1e-5) and box.bottom == pytest.approx(bare.bottom + 0.4, abs=1e-5)
    # every point of the hull is inside, and no vertex is further than the reach from it
    for x, y in base.points:
        assert point_in_polygon((x, y), p.points) or poly_distance(p.points, ((x, y), (x + 1e-6, y), (x, y + 1e-6))) < 1e-5
    for v in p.points:
        d = poly_distance(base.points, (v, (v[0] + 1e-6, v[1]), (v[0], v[1] + 1e-6)))
        assert d <= 0.4 + 1e-5, v
    assert not declared_findings(plan), plan.findings


def test_a_reach_is_drawn_as_a_graphic_polygon_the_plan_holds_as_copper():
    plan = _node(reach=0.4, stroke=0.3).resolve()
    (p,) = _pours(plan)
    (shape,) = [s for s in plan.occupancy.copper if s.kind == "copper" and s.net == "SW"]
    assert Box.of_points(shape.poly).left == pytest.approx(Box.of_points(p.points).left - 0.15, abs=1e-6)


def test_reach_is_cut_back_by_another_nets_pad_to_its_clearance():
    """A foreign pad stands in the room beside the hull: the grown copper stops a clearance short of it."""
    other = _part("B0", "B", 11.2, 7.9, 0.8, 0.8)
    plan = _node([other], reach=0.8).resolve()
    (p,) = _pours(plan)
    gap = poly_distance(_copper(p), other.pads[0].outlines[0])
    assert CLEARANCE - 1e-6 <= gap <= CLEARANCE + SAG + 1e-3, gap
    free = _pours(_node(reach=0.8).resolve())[0]
    assert abs(pourfit._area(p.points)) < abs(pourfit._area(free.points)) - 0.05    # the pad took its room
    assert not declared_findings(plan), plan.findings


def test_a_clearance_rule_between_the_nets_cuts_reach_back_by_the_rule():
    other = _part("B0", "B", 11.2, 7.9, 0.8, 0.8)
    board = _node([other], reach=0.8)
    board.rule(clearance=0.4, between=("SW", "B"), why="a wider gap")
    (p,) = _pours(board.resolve())
    gap = poly_distance(_copper(p), other.pads[0].outlines[0])
    assert 0.4 - 1e-6 <= gap <= 0.4 + SAG + 1e-3, gap


def test_reach_stops_at_the_board_edge_clearance():
    plan = _node(reach=3.0).resolve()
    (p,) = _pours(plan)
    box = Box.of_points(_copper(p))
    assert box.left >= 1.0 - 1e-6 and box.top >= 1.0 - 1e-6        # edge_margin of the test board


def test_a_pocket_of_copper_in_the_reach_leaves_a_hole_drawn_as_one_polygon_with_a_bridge():
    """A foreign via-sized pad wholly inside the grown ring, joined to nothing, cuts a hole; the pour is one
    polygon whose outline goes in to the hole and back, and keeps the clearance from the pad."""
    other = _part("B0", "B", 8.8, 8.2, 0.4, 0.4)
    plan = _node([other], reach=1.6).resolve()
    (p,) = _pours(plan)
    gap = poly_distance(_copper(p), other.pads[0].outlines[0])
    assert CLEARANCE - 1e-6 <= gap <= CLEARANCE + SAG + 1e-3, gap
    assert not point_in_polygon((8.8, 8.2), p.points)
    assert len(p.points) > len(set(p.points))                  # the bridge to the hole is walked twice
    assert not declared_findings(plan), plan.findings


def test_copper_planned_after_a_reach_keeps_clear_of_it():
    """A pad searched for later is kept out of the grown copper, which it was not kept out of the bare hull."""
    mover = _part("B0", "B", 20.0, 20.0, 0.8, 0.8)
    board = _node([mover], reach=1.0)
    from placemat.values import OnEdge, Edge
    board.place(Part("b0"), at=OnEdge(Edge.NORTH))
    plan = board.resolve()
    (p,) = _pours(plan)
    for fp_ref in ("B0",):
        pad = plan.occupancy.items[fp_ref].shapes
        for sh in pad:
            if sh.kind == "pad":
                assert poly_distance(_copper(p), sh.poly) >= CLEARANCE - 1e-6


@pytest.mark.parametrize("kw,match", [
    ({"reach": 0.0}, "reach= is a distance in mm greater than 0"),
    ({"reach": -1.0}, "reach= is a distance in mm greater than 0"),
    ({"reach": True}, "reach= is a distance in mm greater than 0"),
    ({"reach": "1mm"}, "reach= is a distance in mm greater than 0"),
])
def test_a_reach_that_is_not_a_positive_distance_is_refused(kw, match):
    board = _board([_part("S0", "SW", 10.0, 10.0), _part("S1", "SW", 14.0, 10.0)])
    with pytest.raises(ValueError, match=match):
        board.pour(Net("SW"), _refs("s", 2), layer=F, swallow_pads=True, **kw)


def test_reach_on_a_pour_that_is_not_fitted_is_refused():
    board = _board([_part("S0", "SW", 10.0, 10.0), _part("S1", "SW", 14.0, 10.0)])
    with pytest.raises(ValueError, match="reach= grows a fitted pour"):
        board.pour(Net("SW"), _refs("s", 2), layer=F, reach=0.5)
    with pytest.raises(ValueError, match="reach= grows a fitted pour"):
        board.pour(Net("SW"), _refs("s", 2), layer=F, swallow_pads=True, width=1.0, reach=0.5)


def test_a_declaration_without_reach_digests_as_before_and_one_with_it_does_not():
    from placemat import reuse
    a, b, c = _node(), _node(), _node(reach=0.4)
    da, db, dc = (reuse.canonical(x._copper) for x in (a, b, c))
    assert da == db and "reach" not in da
    assert dc != da and "reach=0.4" in dc


# ---------------------------------------------------------------- written boards


def _vec(x, y):
    return pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6)))


def _footprint(board, ref, nets, pads, fields=None):
    fp = pcbnew.FOOTPRINT(board)
    fp.SetReference(ref)
    fp.SetPosition(_vec(20, 20))
    board.Add(fp)
    for k, v in (fields or {}).items():
        fp.SetField(k, v)
    for number, net, x, y, w, h in pads:
        p = pcbnew.PAD(fp)
        p.SetNumber(number)
        p.SetShape(pcbnew.PAD_SHAPE_RECTANGLE)
        p.SetSize(_vec(w, h))
        p.SetPosition(_vec(x, y))
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetLayerSet(pcbnew.PAD.SMDMask())
        p.SetNet(nets[net])
        fp.Add(p)
    return fp


def _written_node(tmp_path, clearance=0.16, foreign=()):
    """The switch node of two parts, Q1 and L1, each carrying 3.6 A (1.758 mm of copper at a 10 C rise),
    on a 40 mm board: two pads offset diagonally, whose hull is 1.43 mm across at its narrowest; `foreign`
    (number, net, x, y, w, h) are pads of U9."""
    b = pcbnew.CreateEmptyBoard()
    b.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(pcbnew.FromMM(clearance))
    for a, c in (((0, 0), (40, 0)), ((40, 0), (40, 40)), ((40, 40), (0, 40)), ((0, 40), (0, 0))):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(_vec(*a))
        s.SetEnd(_vec(*c))
        b.Add(s)
    nets = {}
    for name in ("SW", "GND", "BOOT", "PROBE"):
        nets[name] = pcbnew.NETINFO_ITEM(b, name)
        b.Add(nets[name])
    _footprint(b, "Q1", nets, [("1", "SW", 10.0, 10.0, 1.0, 0.8)], {"Pm.I": "3.6A"})
    _footprint(b, "L1", nets, [("1", "SW", 12.5, 11.5, 1.4, 0.8)], {"Pm.I": "3.6A"})
    if foreign:
        _footprint(b, "U9", nets, list(foreign))
    path = tmp_path / "reach.kicad_pcb"
    b.Save(str(path))
    return path


def _declared(pcb, reach):
    board = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    board.size(width=40.0, height=40.0)
    board.pour(Net("SW"), [PadRef(Part("Q1"), 1), PadRef(Part("L1"), 1)], layer=F, swallow_pads=True, reach=reach)
    return board


def _sw(pcb):
    v = {x.subject: x for x in current_paths(read_board(pcb))}
    return v["SW"]


@needs_kicad
def test_a_pour_over_two_offset_pads_is_narrow_for_current_path_and_widens_with_reach(tmp_path):
    from placemat.kicad.drc import run_drc
    (tmp_path / "bare").mkdir()
    (tmp_path / "reached").mkdir()
    pcb = _written_node(tmp_path / "bare")
    plan = _declared(pcb, None).resolve()
    apply_plan(pcb, plan)
    narrow = _sw(pcb)
    # narrower than the need, and short enough to be credited: width alone is what reach grows
    assert narrow.value < narrow.limit and "credited as short" in narrow.note, narrow
    pcb2 = _written_node(tmp_path / "reached")
    plan = _declared(pcb2, 0.8).resolve()
    assert not [f for f in declared_findings(plan) if f.startswith("pour")], plan.findings
    apply_plan(pcb2, plan)
    raw = pcbnew.LoadBoard(str(pcb2))
    assert not list(raw.Zones())
    wide = _sw(pcb2)
    assert wide.ok is True and wide.value > narrow.value, (narrow, wide)
    report = run_drc(pcb2, tmp_path / "reached" / "drc.json")
    assert report.by_type.get("clearance", 0) == 0 and report.by_type.get("shorting_items", 0) == 0, report.by_type


@needs_kicad
def test_reach_clipped_by_another_nets_pad_keeps_its_clearance_on_the_written_board(tmp_path):
    from placemat.kicad.drc import run_drc
    pcb = _written_node(tmp_path, foreign=[("1", "PROBE", 11.0, 8.6, 0.8, 0.8), ("2", "PROBE", 14.4, 11.0, 0.6, 0.6)])
    plan = _declared(pcb, 0.8).resolve()
    assert not [f for f in declared_findings(plan) if f.startswith("pour")], plan.findings
    apply_plan(pcb, plan)
    after = read_board(pcb)
    u9 = after.footprint("U9")
    polys = [c for c in after.copper if c.kind == "poly" and c.net == "SW"]
    assert polys
    for number in (1, 2):
        gap = min(poly_distance(o, u9.pad(number).outlines[0]) for p in polys for o in p.outlines)
        assert CLEARANCE - ARC_ERROR <= gap <= CLEARANCE + SAG + 1e-3, (number, gap)
    report = run_drc(pcb, tmp_path / "drc.json")
    assert report.by_type.get("clearance", 0) == 0 and report.by_type.get("shorting_items", 0) == 0, report.by_type


@needs_kicad
def test_a_pocket_of_foreign_copper_in_the_reach_is_kept_clear_of_on_the_written_board(tmp_path):
    from placemat.kicad.drc import run_drc
    pcb = _written_node(tmp_path, foreign=[("1", "PROBE", 9.2, 8.95, 0.4, 0.4)])
    plan = _declared(pcb, 1.6).resolve()
    (p,) = _pours(plan)
    assert len(p.points) > len(set(p.points))                  # one polygon, the hole joined to the outside
    assert not [f for f in declared_findings(plan) if f.startswith("pour")], plan.findings
    apply_plan(pcb, plan)
    after = read_board(pcb)
    polys = [c for c in after.copper if c.kind == "poly" and c.net == "SW"]
    assert len(polys) == 1
    assert min(poly_distance(o, after.footprint("U9").pad(1).outlines[0]) for o in polys[0].outlines) \
        >= CLEARANCE - ARC_ERROR
    report = run_drc(pcb, tmp_path / "drc.json")
    assert report.by_type.get("clearance", 0) == 0 and report.by_type.get("shorting_items", 0) == 0, report.by_type
    assert _sw(pcb).ok is True


# ---------------------------------------------------------------- pads nearer than the clearance


def _fine_pitch(extra=()):
    """Pads 25 (net PROBE) and 26, 27, 28 (net VBUS) of a part at 0.4 mm pitch, 0.25 mm wide: 0.15 mm apart,
    under the 0.2 mm clearance, as the footprint draws them."""
    pads = [_part("U1%d" % i, "PROBE" if i == 25 else "VBUS", 10.0 + 0.4 * (i - 25), 10.0, 0.25, 1.0)
            for i in (25, 26, 27, 28)]
    return pads + list(extra)


def test_a_pour_over_pads_whose_footprint_gap_is_under_the_clearance_holds_the_pad_clear_of_its_neighbour():
    """The neighbour's clearance outline reaches past pad 26's centre, so the pour holds the part of the pad
    that is clear of it: the outline's nearest edge to pad 25 stays a clearance and the stroke off."""
    pads = _fine_pitch()
    board = _board(pads, clearance=0.2)
    board.pour(Net("VBUS"), [PadRef(Part("u126"), 1), PadRef(Part("u127"), 1), PadRef(Part("u128"), 1)],
               layer=F, swallow_pads=True)
    plan = board.resolve()
    (p,) = _pours(plan)
    assert not declared_findings(plan), plan.findings
    gap = poly_distance(_copper(p), pads[0].pads[0].outlines[0])
    assert 0.2 - 1e-6 <= gap <= 0.2 + SAG + 1e-3, gap
    # it still holds pad 26: copper of the pour lies over the part of the pad that is clear
    assert poly_distance(_copper(p), pads[1].pads[0].outlines[0]) == 0.0


def test_a_pad_wholly_inside_its_neighbours_clearance_is_still_a_finding():
    pads = [_part("U125", "PROBE", 10.0, 10.0, 0.25, 1.0), _part("U126", "VBUS", 10.3, 10.0, 0.1, 1.0),
            _part("U127", "VBUS", 12.0, 10.0, 0.25, 1.0)]
    board = _board(pads, clearance=0.2)
    board.pour(Net("VBUS"), [PadRef(Part("u126"), 1), PadRef(Part("u127"), 1)], layer=F, swallow_pads=True)
    plan = board.resolve()
    assert not _pours(plan)
    assert any("pad U125" in f or "U125 pad 1 (PROBE) is within its clearance of pad U126.1" in f
               for f in declared_findings(plan)), plan.findings


def _fine_board(tmp_path, pads):
    tmp_path.mkdir(exist_ok=True)
    b = pcbnew.CreateEmptyBoard()
    b.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(pcbnew.FromMM(0.2))
    for a, c in (((0, 0), (40, 0)), ((40, 0), (40, 40)), ((40, 40), (0, 40)), ((0, 40), (0, 0))):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(_vec(*a))
        s.SetEnd(_vec(*c))
        b.Add(s)
    nets = {n: pcbnew.NETINFO_ITEM(b, n) for n in ("PROBE", "VBUS")}
    for n in nets.values():
        b.Add(n)
    _footprint(b, "U1", nets, pads)
    path = tmp_path / "fine.kicad_pcb"
    b.Save(str(path))
    return path


@needs_kicad
def test_kicad_flags_a_polygon_edge_on_a_pads_edge_but_not_a_pour_held_clear(tmp_path):
    """KiCad has no exemption for a graphic polygon that stands where the pad's own copper does:
    drc_test_provider_copper_clearance.cpp's testSingleLayerItemAgainstItem (a board graphic against a
    pad) waives only the same net and a net tie, so a polygon whose edge is the pad's edge is a clearance
    violation to the neighbour, as the pad is. The pour held clear adds none; the pad pair's one is the
    footprint's."""
    import json
    from placemat.kicad.drc import run_drc
    pads = [("25", "PROBE", 10.0, 10.0, 0.25, 1.0), ("26", "VBUS", 10.4, 10.0, 0.25, 1.0),
            ("27", "VBUS", 10.8, 10.0, 0.25, 1.0), ("28", "VBUS", 11.2, 10.0, 0.25, 1.0)]

    def described(path):
        return [i["description"] for v in json.load(open(path))["violations"] for i in v["items"]]
    pcb = _fine_board(tmp_path / "held", pads)
    board = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    board.size(width=40.0, height=40.0)
    board.pour(Net("VBUS"), [PadRef(Part("U1"), n) for n in (26, 27, 28)], layer=F, swallow_pads=True)
    plan = board.resolve()
    assert not [f for f in declared_findings(plan) if f.startswith("pour")], plan.findings
    assert _pours(plan)
    apply_plan(pcb, plan)
    held = run_drc(pcb, tmp_path / "held" / "drc.json")
    assert held.by_type.get("clearance", 0) == 1, held.by_type            # pad 25 to pad 26, the footprint's own
    assert not any("Polygon" in d for d in described(tmp_path / "held" / "drc.json"))
    # a polygon over pad 26 whose copper edge is the pad's edge on pad 25's side
    pcb = _fine_board(tmp_path / "edge", pads)
    b = pcbnew.LoadBoard(str(pcb))
    one = pcbnew.SHAPE_POLY_SET()
    one.NewOutline()
    for x, y in ((10.275, 9.5), (11.325, 9.5), (11.325, 10.5), (10.275, 10.5)):
        one.Append(int(round(x * 1e6)), int(round(y * 1e6)))
    sh = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_POLY)
    sh.SetLayer(pcbnew.F_Cu)
    sh.SetFilled(True)
    sh.SetWidth(0)
    sh.SetPolyShape(one)
    sh.SetNetCode(b.FindNet("VBUS").GetNetCode())
    b.Add(sh)
    b.Save(str(pcb))
    edge = run_drc(pcb, tmp_path / "edge" / "drc.json")
    assert edge.by_type.get("clearance", 0) == 2 and any("Polygon" in d for d in described(tmp_path / "edge" / "drc.json"))
