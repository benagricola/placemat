"""A pour over pads (`swallow_pads=True`) is fitted round other nets' copper:
the shortest closed outline holding the pads' copper that keeps each other
net's clearance outline (its clearance plus half the pour's stroke) out of
itself, every edge straight, written as a graphic copper polygon and never a
zone. Nothing is cut from a pour afterwards: copper declared after one, or
inside a pour drawn as declared, is a copper finding.

The plan tests are pure (synthetic boards, as test_pour_plan_time_obstacle.py
builds them); the written-board tests build a from-scratch pcbnew board (as
test_layers.py's _board_with does) so the clearance and the pad positions are
exact."""
import os
from pathlib import Path

import pcbnew
import pytest

from placemat import pourfit
from placemat.board_geometry import Footprint
from placemat.copper import Pour, Track
from placemat.geometry import point_in_polygon, poly_distance
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Cover, Edge, Face, Location, Net, OnEdge, PadRef, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, declared_findings, pad

CLEARANCE = 0.16
SAG = 0.02                  # [geometry] arc_sag, the default
F = CopperLayer.F


def _part(ref, net, cx, cy, w=1.0, h=1.0):
    """One pad, `net`, centred at (cx, cy), on a part of its own named `ref`."""
    p = pad(ref, ref.lower(), 1, net, cx, cy, w, h)
    body = Box(cx - w / 2 - 0.5, cy - h / 2 - 0.5, cx + w / 2 + 0.5, cy + h / 2 + 0.5)
    return Footprint(ref, ref.lower(), None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _refs(prefix, n):
    return [PadRef(Part("%s%d" % (prefix.lower(), i)), 1) for i in range(n)]


def _board(parts, clearance=CLEARANCE, edge_margin=1.0, **kw):
    return Board(board_geometry(parts, width=60, height=60, clearance=clearance, **kw), edge_margin=edge_margin)


def _pours(plan):
    return [c for c in plan.copper if isinstance(c, Pour)]


def _outline(plan):
    (p,) = _pours(plan)
    assert p.fitted
    return p


def _copper(p):
    """The pour's copper as the occupancy holds it: its outline and half its stroke."""
    return pourfit.offset(p.points, p.stroke / 2.0)


def _gap(p, poly):
    return poly_distance(_copper(p), poly)


def _holds(p, parts):
    """Every corner of every pad of `parts` lies in the pour's copper, to the stroke and the arc sag."""
    copper = pourfit.offset(p.points, p.stroke / 2.0 + SAG)
    for fp in parts:
        for pd in fp.pads:
            for x, y in pd.outlines[0]:
                assert point_in_polygon((x, y), copper) or poly_distance(copper, ((x, y), (x + 1e-6, y), (x, y + 1e-6))) < 1e-6, (fp.ref, x, y)


def _row(extra=()):
    """Three pads of net A in a row, 4 mm apart; `extra` more parts."""
    return [_part("A%d" % i, "A", 10 + 4 * i, 10) for i in range(3)] + list(extra)


def _a_pads():
    return _refs("a", 3)


def test_a_fitted_pour_with_nothing_in_the_way_is_the_hull_of_its_pads():
    parts = _row()
    b = _board(parts)
    b.pour(Net("A"), _a_pads(), layer=F, swallow_pads=True)
    p = _outline(b.resolve())
    box = Box.of_points(p.points)
    assert (box.left, box.top, box.right, box.bottom) == pytest.approx((9.5, 9.5, 18.5, 10.5))
    _holds(p, parts)


def test_a_fitted_pour_keeps_clear_of_a_pad_standing_inside_the_hull():
    """Another net's pad between two of the three, inside their hull and
    reaching the hull's north edge: the outline goes under it, its edges
    straight, at the clearance and no more than the arc sag past it."""
    blocker = _part("B0", "B", 12.0, 9.4, 0.6, 0.6)
    parts = _row([blocker])
    b = _board(parts)
    b.pour(Net("A"), _a_pads(), layer=F, swallow_pads=True)
    plan = b.resolve()
    p = _outline(plan)
    gap = _gap(p, blocker.pads[0].outlines[0])
    assert CLEARANCE - 1e-6 <= gap <= CLEARANCE + SAG + 1e-6, gap
    _holds(p, parts[:3])
    assert not declared_findings(plan), plan.findings
    # it dips under the pad and rises again: a vertex lies below the pad, beyond the hull's north edge
    assert any(y > 9.9 for _, y in p.points)


def test_four_pads_round_a_pin_and_its_track_reach_both_at_the_clearance():
    """A switch node's four pads round another net's pin, with a track
    running from the pin deep into their hull."""
    pads = [_part("S%d" % i, "SW", x, y) for i, (x, y) in enumerate(((10, 10), (16, 10), (16, 15), (10, 15)))]
    pin = _part("P0", "BOOT", 12.8, 9.0, 4.0, 1.0)
    b = _board(pads + [pin])
    b.track(Net("BOOT"), [PadRef(Part("p0"), 1), Location(12.8, 11.0)], layer=F, width=0.2, chamfer=0)
    b.pour(Net("SW"), _refs("s", 4), layer=F, swallow_pads=True)
    plan = b.resolve()
    p = _outline(plan)
    (trk,) = [c for c in plan.copper if isinstance(c, Track)]
    for poly in (pin.pads[0].outlines[0], trk.polygon):
        gap = _gap(p, poly)
        assert CLEARANCE - 1e-6 <= gap <= CLEARANCE + 6e-3, gap
    _holds(p, pads)
    assert not declared_findings(plan), plan.findings
    # every vertex not at a pad's corner is a corner of a tangent edge: no further than the arc sag past
    # the clearance outline of the pin or the track
    r = CLEARANCE + p.stroke / 2.0
    for v in p.points:
        if any(poly_distance(((v[0], v[1]), (v[0] + 1e-6, v[1]), (v[0], v[1] + 1e-6)), fp.pads[0].outlines[0]) < 0.3
               for fp in pads):
            continue
        d = min(poly_distance(((v[0], v[1]), (v[0] + 1e-6, v[1]), (v[0], v[1] + 1e-6)), poly)
                for poly in (pin.pads[0].outlines[0], trk.polygon))
        assert r - 1e-3 <= d <= r + SAG + 1e-3, (v, d)


def test_a_track_declared_across_a_fitted_pour_is_a_finding_and_the_pour_stays():
    def plan_with(track):
        pads = [_part("A%d" % i, "A", x, y) for i, (x, y) in enumerate(((10, 10), (16, 10), (13, 14)))]
        far = _part("C0", "C", 30.0, 12.0)
        b = _board(pads + [far])
        b.place(Part("c0"), at=OnEdge(Edge.EAST))           # searched: planned after the pour's fixed batch
        b.pour(Net("A"), _refs("a", 3), layer=F, swallow_pads=True)
        if track:
            b.track(Net("C"), [PadRef(Part("c0"), 1), Location(13.0, 11.0)], layer=F, chamfer=0)
        return b.resolve()
    bare, crossed = plan_with(False), plan_with(True)
    assert _outline(crossed).points == _outline(bare).points
    assert any("copper C" in f for f in declared_findings(crossed)), crossed.findings
    assert not any("copper C" in f for f in declared_findings(bare))


def test_a_via_with_no_way_round_leaves_the_pour_undrawn_and_is_named():
    pads = [_part("A%d" % i, "A", x, y) for i, (x, y) in enumerate(((10, 10), (16, 10), (13, 15)))]
    b = _board(pads, extra_nets=["V"])
    b.via(Net("V"), Location(13.0, 11.5), why="stands in the middle of the pads")
    b.pour(Net("A"), _refs("a", 3), layer=F, swallow_pads=True)
    plan = b.resolve()
    assert not _pours(plan)
    (f,) = [f for f in declared_findings(plan) if f.startswith("pour A")]
    assert "via V at (13.00, 11.50)" in f and "no way round" in f, f
    assert all(label in f for label in ("A0.1", "A1.1", "A2.1")[:2]), f


def test_a_wall_between_two_pads_leaves_no_way_and_names_the_wall_and_the_pads():
    pads = _row()
    wall = _part("W0", "WALL", 12.0, 10.0, 1.0, 4.0)
    b = _board(pads + [wall])
    b.pour(Net("A"), _a_pads(), layer=F, swallow_pads=True)
    plan = b.resolve()
    assert not _pours(plan)
    (f,) = [f for f in declared_findings(plan) if f.startswith("pour A")]
    assert "W0 pad 1 (WALL)" in f and "A0.1" in f and "A1.1" in f and "A2.1" not in f, f


def test_a_clearance_rule_between_the_nets_is_kept():
    blocker = _part("B0", "B", 12.0, 9.4, 0.6, 0.6)
    b = _board(_row([blocker]))
    b.rule(clearance=0.4, between=("A", "B"), why="a wider gap")
    b.pour(Net("A"), _a_pads(), layer=F, swallow_pads=True)
    p = _outline(b.resolve())
    gap = _gap(p, blocker.pads[0].outlines[0])
    assert 0.4 - 1e-6 <= gap <= 0.4 + SAG + 1e-6, gap


def test_a_pad_without_a_net_keeps_the_default_clearance():
    blocker = _part("B0", "", 12.0, 9.4, 0.6, 0.6)
    b = _board(_row([blocker]), clearance=0.3)
    b.pour(Net("A"), _a_pads(), layer=F, swallow_pads=True)
    p = _outline(b.resolve())
    gap = _gap(p, blocker.pads[0].outlines[0])
    assert 0.3 - 1e-6 <= gap <= 0.3 + SAG + 1e-6, gap


def test_a_cutout_in_the_board_is_kept_clear_by_the_edge_clearance():
    """A window in the board pokes into the pads' hull from the north."""
    parts = _row()
    b = _board(parts, edge_margin=0.3)
    b.size(width=60.0, height=60.0, holes=[[(12.0, 8.0), (13.0, 8.0), (13.0, 9.8), (12.0, 9.8)]])
    b.pour(Net("A"), _a_pads(), layer=F, swallow_pads=True)
    p = _outline(b.resolve())
    gap = poly_distance(_copper(p), ((12.0, 8.0), (13.0, 8.0), (13.0, 9.8), (12.0, 9.8)))
    assert 0.3 - 1e-6 <= gap <= 0.3 + SAG + 1e-6, gap
    _holds(p, parts)


def test_a_thin_neck_is_a_finding_and_the_pour_is_still_drawn():
    """Two foreign pads leave 0.07 mm between their clearance outlines across
    the pour (0.08 less the 0.005 mm each is held off by): the copper there is
    0.12 mm wide with a 0.05 mm stroke, under the net's 0.2 mm track."""
    above = _part("B0", "B", 12.0, 9.45, 0.6, 0.9)
    below = _part("B1", "B", 12.0, 10.93, 0.6, 1.0)
    b = _board(_row([above, below]), clearance=0.2)
    b.pour(Net("A"), _a_pads(), layer=F, swallow_pads=True, stroke=0.05)
    plan = b.resolve()
    (p,) = _pours(plan)
    (f,) = [f for f in declared_findings(plan) if "narrows" in f]
    assert f.startswith("pour A: narrows to 0.12 mm at (1") and "0.20 mm track" in f, f


@pytest.mark.parametrize("extra", [{"cover": Cover.HULL}, {"cover": Cover.BOX}, {"cover": Cover.CENTRES}])
def test_cover_with_swallow_pads_is_refused_naming_the_fitted_pour(extra):
    b = _board(_row())
    with pytest.raises(ValueError, match="fits the pour round other nets' copper from its pads alone.*no cover="):
        b.pour(Net("A"), _a_pads(), layer=F, swallow_pads=True, **extra)


def test_a_plain_point_with_swallow_pads_is_refused_naming_the_fitted_pour():
    b = _board(_row())
    with pytest.raises(ValueError, match="fits the pour round other nets' copper from its pads alone.*every point is a pad"):
        b.pour(Net("A"), _a_pads() + [Location(14.0, 20.0)], layer=F, swallow_pads=True)
    with pytest.raises(ValueError, match="every point is a pad"):
        b.pour(Net("A"), [Location(0, 0), Location(10, 0), Location(10, 4), Location(0, 4)], layer=F, swallow_pads=True)


def test_a_fitted_pour_over_another_nets_pad_is_a_finding_and_is_not_drawn():
    parts = _row([_part("B0", "B", 14.0, 14.0)])
    b = _board(parts)
    b.pour(Net("A"), _a_pads()[:2] + [PadRef(Part("b0"), 1)], layer=F, swallow_pads=True)
    plan = b.resolve()
    assert not _pours(plan)
    assert any("pad B0.1 is on net B" in f for f in declared_findings(plan)), plan.findings


def test_a_pour_without_swallow_pads_is_drawn_as_declared_and_foreign_copper_in_it_is_a_finding():
    blocker = _part("B0", "B", 12.0, 9.4, 0.6, 0.6)
    b = _board(_row([blocker]))
    pts = [Location(9.0, 9.4), Location(15.0, 9.4), Location(15.0, 10.6), Location(9.0, 10.6)]
    b.pour(Net("A"), pts, layer=F)
    plan = b.resolve()
    (p,) = _pours(plan)
    assert not p.fitted and p.points == ((9.0, 9.4), (15.0, 9.4), (15.0, 10.6), (9.0, 10.6))
    assert any("copper A" in f and "from B copper" in f for f in declared_findings(plan)), plan.findings


def test_a_neck_between_two_pads_is_drawn_as_declared():
    pa, pb = _part("A0", "A", 10.0, 10.0), _part("A1", "A", 16.0, 10.0)
    blocker = _part("B0", "B", 13.0, 10.0, 0.4, 0.4)
    b = _board([pa, pb, blocker])
    b.pour(Net("A"), _refs("a", 2), layer=F, swallow_pads=True)
    plan = b.resolve()
    (p,) = _pours(plan)
    assert not p.fitted and p.points == ((10.0, 10.5), (16.0, 10.5), (16.0, 9.5), (10.0, 9.5))
    assert any("copper A" in f and "from B copper" in f for f in declared_findings(plan)), plan.findings


def test_copper_planned_after_a_fitted_pour_keeps_clear_of_its_stroke():
    """The pour is held as copper at its outline plus half its stroke."""
    pads = _row()
    b = _board(pads)
    b.pour(Net("A"), _a_pads(), layer=F, swallow_pads=True, stroke=0.3)
    plan = b.resolve()
    (shape,) = [s for s in plan.occupancy.copper if s.kind == "copper" and s.net == "A"]
    assert Box.of_points(shape.poly).top == pytest.approx(9.5 - 0.15, abs=1e-6)


# ---------------------------------------------------------------- written boards


def _vec(x, y):
    return pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6)))


def _add_pad(fp, number, net, x, y, w=1.0, h=1.0):
    p = pcbnew.PAD(fp)
    p.SetNumber(number)
    p.SetShape(pcbnew.PAD_SHAPE_RECTANGLE)
    p.SetSize(pcbnew.VECTOR2I(int(round(w * 1e6)), int(round(h * 1e6))))
    p.SetPosition(_vec(x, y))
    p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    p.SetLayerSet(pcbnew.PAD.SMDMask())
    if net is not None:            # None: no net at all (GetNetCode() <= 0), same as a fiducial or a locating pad
        p.SetNet(net)
    fp.Add(p)
    return p


def _written_board(tmp_path, pads, clearance=0.16, track=None):
    """A 40x40 board with one footprint U1 carrying `pads` (number, net_name,
    x, y, w, h), at the netclass clearance given; `track` (net, x0, y0, x1,
    y1, width) is a track of the board's own."""
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
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference("U1")
    fp.SetPosition(_vec(20, 20))
    b.Add(fp)
    for number, net_name, x, y, w, h in pads:
        if net_name is not None and net_name not in nets:
            n = pcbnew.NETINFO_ITEM(b, net_name)
            b.Add(n)
            nets[net_name] = n
        _add_pad(fp, number, nets[net_name] if net_name is not None else None, x, y, w, h)
    if track:
        net, x0, y0, x1, y1, width = track
        if net not in nets:
            nets[net] = pcbnew.NETINFO_ITEM(b, net)
            b.Add(nets[net])
        t = pcbnew.PCB_TRACK(b)
        t.SetLayer(pcbnew.F_Cu)
        t.SetWidth(pcbnew.FromMM(width))
        t.SetStart(_vec(x0, y0))
        t.SetEnd(_vec(x1, y1))
        t.SetNet(nets[net])
        b.Add(t)
    path = tmp_path / "fitted.kicad_pcb"
    b.Save(str(path))
    return path


def _fitted(pcb, nets=("PROBE_A",), numbers=(1, 2, 3), **pour):
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    for net in nets:
        b.pour(Net(net), [PadRef(Part("U1"), n) for n in numbers], layer=F, swallow_pads=True, **pour)
    return b


# pads 1, 2, 3 on PROBE_A in a row; pad 4 on PROBE_B 0.2 mm north of pad 1
_THREE_AND_A_NEIGHBOUR = [
    ("1", "PROBE_A", 10.0, 10.0, 1.0, 1.0),
    ("2", "PROBE_A", 12.0, 10.0, 1.0, 1.0),
    ("3", "PROBE_A", 14.0, 10.0, 1.0, 1.0),
    ("4", "PROBE_B", 10.0, 8.8, 1.0, 1.0),
]


def _drawn(after, net):
    return [c for c in after.copper if c.kind == "poly" and c.net == net]


@needs_kicad
def test_a_fitted_pour_is_written_as_a_graphic_polygon_not_a_zone(tmp_path):
    pcb = _written_board(tmp_path, _THREE_AND_A_NEIGHBOUR)
    plan = _fitted(pcb).resolve()
    apply_plan(pcb, plan)
    raw = pcbnew.LoadBoard(str(pcb))
    assert not list(raw.Zones())
    shapes = [d for d in raw.GetDrawings() if isinstance(d, pcbnew.PCB_SHAPE) and d.GetShape() == pcbnew.SHAPE_T_POLY
              and d.GetLayer() == pcbnew.F_Cu]
    assert len(shapes) == 1 and shapes[0].IsSolidFill() and shapes[0].GetNetname() == "PROBE_A"
    assert [tuple(round(pcbnew.ToMM(v), 6) for v in (p.x, p.y)) for p in shapes[0].GetPolyShape().Outline(0).CPoints()] \
        == [tuple(round(v, 6) for v in pt) for pt in _outline(plan).points]


@needs_kicad
def test_a_fitted_pour_keeps_the_clearance_from_a_foreign_pad_beside_it_on_the_written_board(tmp_path):
    pcb = _written_board(tmp_path, _THREE_AND_A_NEIGHBOUR)
    plan = _fitted(pcb).resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    u1 = after.footprint("U1")
    polys = _drawn(after, "PROBE_A")
    assert polys
    gap = min(poly_distance(o, u1.pad(4).outlines[0]) for p in polys for o in p.outlines)
    assert CLEARANCE - 1e-6 <= gap <= CLEARANCE + SAG + 1e-3, gap
    for number in (1, 2, 3):
        c = u1.pad(number).box.center
        assert any(point_in_polygon((c.x, c.y), o) for p in polys for o in p.outlines), number


@needs_kicad
def test_kicads_drc_finds_no_clearance_violation_from_a_fitted_pour(tmp_path):
    from placemat.kicad.drc import run_drc
    pcb = _written_board(tmp_path, _THREE_AND_A_NEIGHBOUR + [("5", "PROBE_B", 11.0, 8.7, 0.6, 0.6)],
                         track=("PROBE_B", 11.0, 8.7, 11.0, 9.9, 0.2))
    plan = _fitted(pcb).resolve()
    assert not [f for f in declared_findings(plan) if f.startswith("pour")], plan.findings
    apply_plan(pcb, plan)
    report = run_drc(pcb, tmp_path / "drc.json")
    assert report.by_type.get("clearance", 0) == 0 and report.by_type.get("shorting_items", 0) == 0, report.by_type


@needs_kicad
def test_a_board_track_in_the_way_is_kept_clear_of(tmp_path):
    """Copper the board already carries (a stamped cell's own track, read with the board) stands in
    the plan's way like any planned copper."""
    pads = [("1", "PROBE_A", 10.0, 10.0, 1.0, 1.0), ("2", "PROBE_A", 16.0, 10.0, 1.0, 1.0),
            ("3", "PROBE_A", 13.0, 14.0, 1.0, 1.0), ("4", "PROBE_B", 13.0, 7.0, 1.0, 1.0)]
    pcb = _written_board(tmp_path, pads, track=("PROBE_B", 13.0, 7.0, 13.0, 11.0, 0.3))
    plan = _fitted(pcb).resolve()
    p = _outline(plan)
    track = Track("PROBE_B", F, width=0.3, start=Location(13.0, 7.0), end=Location(13.0, 11.0))
    gap = poly_distance(pourfit.offset(p.points, p.stroke / 2.0), track.polygon)
    assert CLEARANCE - 1e-6 <= gap <= CLEARANCE + SAG + 1e-3, gap


@needs_kicad
def test_a_pad_with_no_net_is_kept_clear_of_at_the_default_clearance(tmp_path):
    pads = _THREE_AND_A_NEIGHBOUR[:3] + [("4", None, 10.0, 8.8, 1.0, 1.0)]
    pcb = _written_board(tmp_path, pads)
    plan = _fitted(pcb).resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    gap = min(poly_distance(o, after.footprint("U1").pad(4).outlines[0])
              for p in _drawn(after, "PROBE_A") for o in p.outlines)
    assert gap >= after.default_clearance - 1e-6, gap


@needs_kicad
def test_two_fitted_pours_of_different_nets_keep_clear_of_each_other(tmp_path):
    """The second pour is fitted round the first as planned: its hull
    reaches across the first's corner."""
    pads = [("1", "PROBE_A", 10.0, 10.0, 0.5, 0.5), ("2", "PROBE_A", 10.0, 13.0, 0.5, 0.5),
            ("3", "PROBE_A", 13.0, 10.0, 0.5, 0.5),
            ("4", "PROBE_B", 8.0, 11.5, 0.5, 0.5), ("5", "PROBE_B", 15.0, 11.5, 0.5, 0.5),
            ("6", "PROBE_B", 11.5, 16.0, 0.5, 0.5)]
    pcb = _written_board(tmp_path, pads, clearance=0.2)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    b.pour(Net("PROBE_A"), [PadRef(Part("U1"), n) for n in (1, 2, 3)], layer=F, swallow_pads=True)
    b.pour(Net("PROBE_B"), [PadRef(Part("U1"), n) for n in (4, 5, 6)], layer=F, swallow_pads=True)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    a = [o for c in _drawn(after, "PROBE_A") for o in c.outlines]
    bb = [o for c in _drawn(after, "PROBE_B") for o in c.outlines]
    assert a and bb
    assert min(poly_distance(p, q) for p in a for q in bb) >= 0.2 - 1e-6
    u1 = after.footprint("U1")
    for number, outlines in ((1, a), (2, a), (3, a), (4, bb), (5, bb), (6, bb)):
        c = u1.pad(number).box.center
        assert any(point_in_polygon((c.x, c.y), o) for o in outlines), number


@needs_kicad
def test_a_pour_without_swallow_pads_is_written_exactly_as_declared(tmp_path):
    """Another net's pad inside it is a copper finding, and the pour is not cut."""
    pcb = _written_board(tmp_path, _THREE_AND_A_NEIGHBOUR)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    pts = [Location(9.0, 9.4), Location(15.0, 9.4), Location(15.0, 10.6), Location(9.0, 10.6)]
    b.pour(Net("PROBE_A"), pts, layer=F, stroke=0.0)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    polys = _drawn(after, "PROBE_A")
    assert len(polys) == 1
    box = polys[0].box
    assert (round(box.left, 2), round(box.top, 2), round(box.right, 2), round(box.bottom, 2)) == (9.0, 9.4, 15.0, 10.6)
    assert any("copper PROBE_A" in f and "from PROBE_B copper" in f for f in plan.findings), plan.findings


# ---------------------------------------------------------------- a drawn reference

# a board with a hand-drawn polygon of a net, and that net: its pads are fitted on the board's other copper
REFERENCE = os.environ.get("PLACEMAT_FIT_REFERENCE")
REFERENCE_NET = os.environ.get("PLACEMAT_FIT_REFERENCE_NET")
needs_reference = pytest.mark.skipif(not REFERENCE or not REFERENCE_NET or not Path(REFERENCE).exists(),
                                     reason="PLACEMAT_FIT_REFERENCE and PLACEMAT_FIT_REFERENCE_NET are not set")


@needs_kicad
@needs_reference
def test_a_pour_fitted_over_a_hand_drawn_boards_pads_keeps_the_clearance_it_was_drawn_to():
    """The pads of a net, fitted on the copper of the board's other nets (the
    board's own polygon of that net is left out as the pour's own copper):
    every edge keeps at least the clearance, and the outline holds the pads."""
    net = REFERENCE_NET
    geometry = read_board(REFERENCE)
    pads = [(fp.ref, pd.number) for fp in geometry.footprints for pd in fp.pads if pd.net == net and F in pd.layers]
    assert len(pads) >= 3
    b = Board(geometry, edge_margin=0.0, keep_going=True)
    b.pour(Net(net), [PadRef(Part(ref), int(number)) for ref, number in pads], layer=F, swallow_pads=True, stroke=0.2)
    plan = b.resolve()
    p = _outline(plan)
    copper = pourfit.offset(p.points, p.stroke / 2.0)
    # a zone is filled round the pour by KiCad; every other copper keeps its clearance from it
    foreign = [(c.net, o) for c in geometry.copper if c.net != net and c.kind != "zone" and F in c.layers
               for o in c.outlines]
    assert foreign
    for other, o in foreign:
        need = geometry.clearance(net, other) if other in geometry.nets else geometry.default_clearance
        assert poly_distance(copper, o) >= need - 1e-6, (other, need)
    held = pourfit.offset(p.points, p.stroke / 2.0 + SAG)
    for fp in geometry.footprints:
        for pd in fp.pads:
            if pd.net == net and F in pd.layers:
                c = pd.box.center
                assert point_in_polygon((c.x, c.y), held), (fp.ref, pd.number)


@needs_kicad
@needs_reference
def test_kicads_drc_finds_no_clearance_violation_from_a_pour_fitted_where_a_hand_drawn_one_had_some(tmp_path):
    """The board's own polygon of the net is taken off a copy and the pour fitted in its place."""
    import shutil
    from placemat.kicad.drc import run_drc
    net = REFERENCE_NET
    pcb = tmp_path / "ref.kicad_pcb"
    shutil.copy(REFERENCE, pcb)
    pro = Path(REFERENCE).with_suffix(".kicad_pro")
    if pro.exists():
        shutil.copy(pro, pcb.with_suffix(".kicad_pro"))
    raw = pcbnew.LoadBoard(str(pcb))
    for d in list(raw.GetDrawings()):
        if isinstance(d, pcbnew.PCB_SHAPE) and d.GetNetname() == net and d.GetLayer() == pcbnew.F_Cu:
            raw.Delete(d)
    raw.Save(str(pcb))
    geometry = read_board(pcb)
    pads = [(fp.ref, pd.number) for fp in geometry.footprints for pd in fp.pads if pd.net == net and F in pd.layers]
    b = Board(geometry, edge_margin=0.0, keep_going=True)
    b.pour(Net(net), [PadRef(Part(ref), int(number)) for ref, number in pads], layer=F, swallow_pads=True, stroke=0.2)
    apply_plan(pcb, b.resolve())
    assert run_drc(pcb, tmp_path / "drc.json").by_type.get("clearance", 0) == 0
