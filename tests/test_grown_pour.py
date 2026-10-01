"""board.pour(net, pads, layer=, grow=, within=): a pour grown from its pads
as a KiCad zone. Declarations and plans are pure; the fill is KiCad's, so
those tests write a board and read it back."""
import pcbnew
import pytest

from placemat.copper import Via, Zone
from placemat.cutouts import Circle
from placemat.geometry import point_in_polygon
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Edge, Location, Net, OnEdge, PadRef, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, declared_findings, footprint

F = CopperLayer.F


# ------------------------------------------------------------ pure: declarations
def _pure(width=60, height=60):
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("U2", 30, 20, w=4, h=2, inst="u2", nets=("A", "C"))]
    b = Board(board_geometry(fps, width=width, height=height), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("u2"), at=Location(30, 20))
    return b


def _pads():
    return [PadRef(Part("u1"), 1), PadRef(Part("u2"), 1)]


@pytest.mark.parametrize("grow", [0, -1.0])
def test_grow_of_nothing_or_less_is_refused(grow):
    with pytest.raises(ValueError, match="grow="):
        _pure().pour(Net("A"), _pads(), layer=F, grow=grow)


@pytest.mark.parametrize("extra, word", [({"swallow_pads": True}, "swallow_pads="),
                                         ({"cover": __import__("placemat.values", fromlist=["Cover"]).Cover.BOX}, "cover="),
                                         ({"width": 1.0}, "width=")])
def test_grow_takes_no_swallow_pads_cover_or_width(extra, word):
    with pytest.raises(ValueError, match=word):
        _pure().pour(Net("A"), _pads(), layer=F, grow=1.0, **extra)


def test_a_grown_pour_needs_a_pad():
    with pytest.raises(ValueError, match="at least one pad"):
        _pure().pour(Net("A"), [], layer=F, grow=1.0)


def test_a_point_that_is_not_a_pad_is_refused():
    with pytest.raises(TypeError, match="pads"):
        _pure().pour(Net("A"), [PadRef(Part("u1"), 1), Location(25, 20)], layer=F, grow=1.0)


def test_within_without_grow_is_refused():
    with pytest.raises(ValueError, match="grow="):
        _pure().pour(Net("A"), _pads(), layer=F, within=Part("u1"))


def test_within_is_a_keepout_part_or_cell_not_a_point():
    b = _pure()
    with pytest.raises(KeyError):
        b.pour(Net("A"), _pads(), layer=F, grow=1.0, within="nowhere")
    with pytest.raises(TypeError, match="within="):
        b.pour(Net("A"), _pads(), layer=F, grow=1.0, within=[Location(0, 0)])


# ---------------------------------------------------------------- pure: the plan
def _zone(plan):
    (z,) = [c for c in plan.copper if isinstance(c, Zone)]
    return z


def test_the_outline_is_the_pads_hull_grown_and_the_zone_sits_above_the_planes():
    b = _pure()
    b.pour(Net("A"), _pads(), layer=F, grow=1.5)
    plan = b.resolve()
    z = _zone(plan)
    assert z.grown and z.priority >= 1 and z.net == "A" and z.layer is F
    box = Box.of_points(z.points)
    # u1 pad 1 spans x 18.1-19.1 and u2 pad 1 x 28.1-29.1, both y 19.5-20.5
    assert (box.left, box.right) == pytest.approx((18.1 - 1.5, 29.1 + 1.5))
    assert (box.top, box.bottom) == pytest.approx((19.5 - 1.5, 20.5 + 1.5))
    assert z.min_thickness == b.settings.copper_plane_min_thickness
    assert z.solid_pads
    assert Box.of_points(z.hull) == Box(18.1, 19.5, 29.1, 20.5)


def test_no_point_of_the_outline_is_further_than_grow_from_a_pad():
    b = _pure()
    b.pour(Net("A"), [PadRef(Part("u1"), 1)], layer=F, grow=1.5)
    z = _zone(b.resolve())
    for x, y in z.points:
        dx = max(18.1 - x, 0.0, x - 19.1)
        dy = max(19.5 - y, 0.0, y - 20.5)
        assert (dx * dx + dy * dy) ** 0.5 <= 1.5 + 1e-6, (x, y)


def test_within_parts_clips_the_outline():
    b = _pure()
    b.pour(Net("A"), [PadRef(Part("u1"), 1)], layer=F, grow=3.0, within=[Part("u1")])
    plan = b.resolve()
    body = plan.box("u1")
    got = Box.of_points(_zone(plan).points)
    assert got.left >= body.left - 1e-6 and got.right <= body.right + 1e-6
    assert got.top >= body.top - 1e-6 and got.bottom <= body.bottom + 1e-6
    assert got.right == pytest.approx(21.9)          # the part's drawn envelope ends at its far pad


def test_within_a_keepout_clips_the_outline_to_its_shape():
    b = _pure()
    b.keepout(Circle(4.0), "zone", at=Location(20.0, 20.0), excludes=("parts",), why="a region")
    b.pour(Net("A"), [PadRef(Part("u1"), 1)], layer=F, grow=6.0, within="zone")
    plan = b.resolve()
    poly = plan.keepouts["zone"].poly
    z = _zone(plan)
    assert z.points
    assert all(point_in_polygon(p, poly) or min(abs(p[0] - q[0]) + abs(p[1] - q[1]) for q in poly) < 0.05
               for p in z.points)
    assert Box.of_points(z.points).right < 19.1 + 6.0 - 1.0


def test_a_pour_whose_reach_lies_outside_what_it_is_within_is_not_drawn_and_says_so():
    b = _pure()
    b.pour(Net("A"), [PadRef(Part("u1"), 1)], layer=F, grow=1.0, within=[Part("u2")])
    plan = b.resolve()
    assert not [c for c in plan.copper if isinstance(c, Zone)]
    assert any("outside what it is within" in str(f) for f in plan.findings), plan.findings


def test_it_is_planned_after_every_other_copper_of_its_batch():
    b = _pure()
    b.pour(Net("A"), _pads(), layer=F, grow=1.5)            # declared first
    b.track(Net("A"), [PadRef(Part("u1"), 1), PadRef(Part("u2"), 1)], layer=CopperLayer.B)
    b.via(Net("B"), Location(40, 40))
    plan = b.resolve()
    kinds = [type(op).__name__ for op in plan.copper]
    assert kinds.index("Zone") > max(i for i, k in enumerate(kinds) if k in ("Track", "Via"))


def test_the_plan_holds_the_pads_hull_for_copper_planned_after_it():
    """A part left to the search lands after the pour's batch; its track of
    another net is judged against the hull the pour holds."""
    fps = [footprint("U1", 10, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("U2", 30, 20, w=4, h=2, inst="u2", nets=("A", "B")),
           footprint("U3", 20, 5, w=2, h=1, inst="u3", nets=("C", "D"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(10, 20))
    b.place(Part("u2"), at=Location(30, 20))
    b.place(Part("u3"), at=OnEdge(Edge.NORTH))
    b.pour(Net("A"), _pads(), layer=F, grow=2.0)
    b.track(Net("D"), [PadRef(Part("u3"), 2), Location(20, 20)], layer=F, width=0.2, why="late, into the hull")
    plan = b.resolve()
    assert any("copper D" in str(f) and "from A copper" in str(f) for f in declared_findings(plan)), plan.findings


def test_a_stitch_over_a_grown_pour_places_vias_inside_its_outline():
    b = _pure()
    pour = b.pour(Net("A"), _pads(), layer=F, grow=2.0)
    b.stitch(Net("A"), pour, pitch=1.5)
    plan = b.resolve()
    z = _zone(plan)
    vias = [op for op in plan.copper if isinstance(op, Via) and op.net == "A"]
    assert vias
    assert all(point_in_polygon((v.at.x, v.at.y), z.points) for v in vias)
    assert set(z.stitched) == {(v.at.x, v.at.y, v.size) for v in vias}


# ----------------------------------------------------------------- KiCad: the fill
def _vec(x, y):
    return pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6)))


def _kicad_board(tmp_path, pads, tracks=(), vias=(), clearance=0.2, rules=None, size=40.0):
    """A `size` mm square board with one footprint U1 carrying `pads`
    (number, net, x, y, w, h), `tracks` (net, x1, y1, x2, y2, width) and
    `vias` (net, x, y)."""
    b = pcbnew.CreateEmptyBoard()
    b.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(pcbnew.FromMM(clearance))
    for a, c in (((0, 0), (size, 0)), ((size, 0), (size, size)), ((size, size), (0, size)), ((0, size), (0, 0))):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(_vec(*a))
        s.SetEnd(_vec(*c))
        b.Add(s)
    nets = {}

    def net(name):
        if name not in nets:
            nets[name] = pcbnew.NETINFO_ITEM(b, name)
            b.Add(nets[name])
        return nets[name]
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference("U1")
    fp.SetPosition(_vec(size / 2, size / 2))
    b.Add(fp)
    for number, name, x, y, w, h in pads:
        pad = pcbnew.PAD(fp)
        pad.SetNumber(number)
        pad.SetShape(pcbnew.PAD_SHAPE_RECTANGLE)
        pad.SetSize(_vec(w, h))
        pad.SetPosition(_vec(x, y))
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetLayerSet(pcbnew.PAD.SMDMask())
        pad.SetNet(net(name))
        fp.Add(pad)
    for name, x1, y1, x2, y2, w in tracks:
        t = pcbnew.PCB_TRACK(b)
        t.SetLayer(pcbnew.F_Cu)
        t.SetStart(_vec(x1, y1))
        t.SetEnd(_vec(x2, y2))
        t.SetWidth(int(round(w * 1e6)))
        t.SetNet(net(name))
        b.Add(t)
    for name, x, y in vias:
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(_vec(x, y))
        v.SetWidth(600000)
        v.SetDrill(300000)
        v.SetNet(net(name))
        b.Add(v)
    path = tmp_path / "grown.kicad_pcb"
    b.Save(str(path))
    if rules:
        (tmp_path / "grown.kicad_dru").write_text(rules)
    return path


def _plan(pcb, declare):
    from placemat.kicad.read import read_board
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    declare(b)
    return b.resolve()


def _written(tmp_path, pads, declare, **board):
    """The plan `declare(board)` makes over the KiCad board, written; the
    board read back, and the plan."""
    from placemat.kicad.write import apply_plan
    pcb = _kicad_board(tmp_path, pads, **board)
    plan = _plan(pcb, declare)
    apply_plan(pcb, plan)
    return pcbnew.LoadBoard(str(pcb)), plan, pcb


def _fills(board, net, layer=pcbnew.F_Cu):
    """The outlines of `net`'s zone fill on `layer`, as (SHAPE_LINE_CHAIN, box in mm)."""
    out = []
    for z in board.Zones():
        if z.GetNetname() != net or z.GetIsRuleArea() or not z.IsOnLayer(layer):
            continue
        ps = z.GetFilledPolysList(layer)
        for i in range(ps.OutlineCount()):
            bb = ps.Outline(i).BBox()
            out.append((ps.Outline(i), (bb.GetLeft() / 1e6, bb.GetTop() / 1e6, bb.GetRight() / 1e6, bb.GetBottom() / 1e6)))
    return out


def _polys(board, net):
    ps = pcbnew.SHAPE_POLY_SET()
    for z in board.Zones():
        if z.GetNetname() == net and not z.GetIsRuleArea():
            fill = z.GetFilledPolysList(pcbnew.F_Cu)
            for i in range(fill.OutlineCount()):
                ps.AddOutline(fill.COutline(i))
    return ps


def _covers(board, net, x, y):
    return _polys(board, net).Contains(_vec(x, y))


def _gap(board, net, x, y):
    """How far (x, y) lies from the net's fill, in mm; 0 inside it."""
    ps = _polys(board, net)
    if ps.Contains(_vec(x, y)):
        return 0.0
    return ps.SquaredDistanceToPolygon(pcbnew.VECTOR2I(int(x * 1e6), int(y * 1e6))) ** 0.5 / 1e6 \
        if hasattr(ps, "SquaredDistanceToPolygon") else ps.Distance(_vec(x, y)) / 1e6


TWO_PADS = [("1", "A", 10, 10, 1, 1), ("2", "A", 14, 10, 1, 1)]


def _declare(grow=2.0, **kw):
    return lambda b: b.pour(Net("A"), [PadRef(Part("U1"), 1), PadRef(Part("U1"), 2)], layer=F, grow=grow, **kw)


@needs_kicad
def test_the_fill_covers_both_pads_and_stops_a_clearance_off_the_track_between_them(tmp_path):
    board, plan, _ = _written(tmp_path, TWO_PADS, _declare(2.0), tracks=[("B", 12, 6, 12, 14, 0.3)])
    assert _covers(board, "A", 10, 10) and _covers(board, "A", 14, 10)
    track_edge = 12 - 0.15
    for left, top, right, bottom in (b for _, b in _fills(board, "A")):
        assert right <= track_edge - 0.2 + 1e-3 or left >= 12 + 0.15 + 0.2 - 1e-3, (left, right)
    # nothing of it lies past grow from the pads
    box = Box.union([Box(*b) for _, b in _fills(board, "A")])
    assert (box.left, box.top, box.right, box.bottom) == pytest.approx((7.5, 7.5, 16.5, 12.5), abs=0.01)


@needs_kicad
def test_a_piece_cut_off_from_every_pad_is_removed(tmp_path):
    board, plan, _ = _written(tmp_path, [("1", "A", 10, 10, 1, 1)],
                              lambda b: b.pour(Net("A"), [PadRef(Part("U1"), 1)], layer=F, grow=4.0),
                              tracks=[("B", 12, 2, 12, 18, 0.3)])
    assert _covers(board, "A", 10, 10)
    assert not _covers(board, "A", 13.5, 10)                # across the track: joined to no pad
    assert max(r for _, (l, t, r, b) in _fills(board, "A")) < 12.0


@needs_kicad
def test_a_piece_joined_only_to_a_pad_of_the_net_the_pour_does_not_name_is_kept(tmp_path):
    pads = [("1", "A", 10, 10, 1, 1), ("2", "A", 14, 10, 1, 1)]
    board, plan, _ = _written(tmp_path, pads,
                              lambda b: b.pour(Net("A"), [PadRef(Part("U1"), 1)], layer=F, grow=5.0),
                              tracks=[("B", 12, 2, 12, 18, 0.3)])
    assert _covers(board, "A", 14, 10)                      # pad 2 is of the net, not named: its piece stays


@needs_kicad
def test_within_a_keepout_the_fill_stays_inside_it(tmp_path):
    from placemat.cutouts import Circle

    def declare(b):
        b.keepout(Circle(3.0), "zone", at=Location(10.0, 10.0), excludes=("parts",), why="a region")
        b.pour(Net("A"), [PadRef(Part("U1"), 1)], layer=F, grow=6.0, within="zone")
    board, plan, _ = _written(tmp_path, [("1", "A", 10, 10, 1, 1)], declare)
    fills = _fills(board, "A")
    assert fills
    for left, top, right, bottom in (b for _, b in fills):
        assert left >= 10 - 1.5 - 0.01 and right <= 10 + 1.5 + 0.01
        assert top >= 10 - 1.5 - 0.01 and bottom <= 10 + 1.5 + 0.01


@needs_kicad
def test_a_plane_of_another_net_on_the_layer_pulls_back_from_the_pour(tmp_path):
    def declare(b):
        b.plane(Net("C"), [F], outline=[Location(1, 1), Location(39, 1), Location(39, 39), Location(1, 39)])
        b.pour(Net("A"), [PadRef(Part("U1"), 1), PadRef(Part("U1"), 2)], layer=F, grow=2.0)
    board, plan, _ = _written(tmp_path, TWO_PADS + [("3", "C", 30, 30, 1, 1)], declare)
    assert _covers(board, "A", 10, 10) and _covers(board, "A", 14, 10)
    a, c = _polys(board, "A"), _polys(board, "C")
    assert a.OutlineCount() and c.OutlineCount()
    assert a.BBox().GetLeft() / 1e6 == pytest.approx(7.5, abs=0.01)     # not cut back by the plane
    # a point just outside the pour's reach is the plane's, and one inside it is not
    assert c.Contains(_vec(20, 20))
    assert not c.Contains(_vec(12, 10))


@needs_kicad
def test_a_clearance_rule_between_the_nets_is_kept_by_the_fill(tmp_path):
    rules = '(version 1)\n(rule "wide" (condition "A.NetName == \'A\' && B.NetName == \'B\'")' \
            ' (constraint clearance (min 1.0mm)))\n'
    from placemat.kicad.write import apply_plan
    pcb = _kicad_board(tmp_path, TWO_PADS, tracks=[("B", 12, 6, 12, 14, 0.3)])
    plan = _plan(pcb, lambda b: (b.rule(clearance=1.0, between=(Net("A"), Net("B")), why="wide"),
                                 _declare(2.0)(b)))
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    for left, top, right, bottom in (b for _, b in _fills(board, "A")):
        assert right <= 12 - 0.15 - 1.0 + 1e-3 or left >= 12 + 0.15 + 1.0 - 1e-3, (left, right)


@needs_kicad
def test_kicads_drc_finds_no_clearance_violation_from_the_pour(tmp_path):
    import json
    import subprocess
    board, plan, pcb = _written(tmp_path, TWO_PADS + [("3", "B", 12, 12.5, 1, 1)], _declare(2.0),
                                tracks=[("B", 12, 6, 12, 9, 0.3)])
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=180)
    data = json.loads(report.read_text())
    bad = [v for v in data.get("violations", []) if v.get("type") in ("clearance", "shorting_items", "hole_clearance")]
    assert not bad, bad


@needs_kicad
def test_the_pours_pads_connect_solid_and_its_priority_is_above_a_planes(tmp_path):
    def declare(b):
        b.plane(Net("C"), [F], outline=[Location(1, 1), Location(39, 1), Location(39, 39), Location(1, 39)])
        _declare(2.0)(b)
    board, plan, _ = _written(tmp_path, TWO_PADS + [("3", "C", 30, 30, 1, 1)], declare)
    zones = {z.GetNetname(): z for z in board.Zones()}
    assert zones["A"].GetPadConnection() == pcbnew.ZONE_CONNECTION_FULL
    assert zones["A"].GetAssignedPriority() > zones["C"].GetAssignedPriority()
    assert zones["A"].GetMinThickness() == pcbnew.FromMM(Settings().copper_plane_min_thickness)


@needs_kicad
def test_a_stitching_via_the_fill_does_not_reach_is_a_finding(tmp_path):
    """A foreign track cuts the outline in two; the piece with no pad is dropped, and the
    stitching vias placed in it lie outside the fill."""
    def declare(b):
        p = b.pour(Net("A"), [PadRef(Part("U1"), 1)], layer=F, grow=4.0)
        b.stitch(Net("A"), p, pitch=1.5)
    board, plan, _ = _written(tmp_path, [("1", "A", 10, 10, 1, 1)], declare, tracks=[("B", 12, 2, 12, 18, 0.3)])
    vias = [op for op in plan.copper if isinstance(op, Via)]
    beyond = [v for v in vias if v.at.x > 12.5]
    assert vias and beyond
    said = [str(f) for f in plan.findings if "stitching via" in str(f)]
    assert len(said) == len(beyond), plan.findings
    assert all("outside its fill" in f for f in said)


@needs_kicad
def test_a_pour_whose_fill_joins_none_of_its_pads_is_a_finding(tmp_path):
    """A pad of another net sits on the pour's only pad, so the fill pulls back from the pad it
    was grown from and joins nothing."""
    board, plan, _ = _written(tmp_path, [("1", "A", 10, 10, 1, 1), ("2", "B", 10, 10.0, 1, 1)],
                              lambda b: b.pour(Net("A"), [PadRef(Part("U1"), 1)], layer=F, grow=1.0))
    said = [str(f) for f in plan.findings if "joins none of its pads" in str(f)]
    assert said and "pour A" in said[0] and "U1.1" in said[0], plan.findings


@needs_kicad
def test_current_path_measures_the_written_fill_of_a_grown_pour(tmp_path):
    """The checks read the filled board: the pour's fill is a zone there, and the load's route
    through it is measured as through any zone fill (a 1 mm neck of the fill, here)."""
    from placemat.checks import current_paths
    from placemat.kicad.read import read_board
    pads = [("1", "SW", 11.4, 10, 1, 1), ("2", "SW", 18.6, 10, 1, 1)]
    board, plan, pcb = _written(tmp_path, pads, lambda b: b.pour(Net("SW"), [PadRef(Part("U1"), 1), PadRef(Part("U1"), 2)],
                                                                 layer=F, grow=1.0),
                                tracks=[("OTHER", 15, 2, 15, 8.9, 0.3)])
    read = read_board(pcb)
    zones = [c for c in read.copper if c.kind == "zone" and c.net == "SW"]
    assert zones
    parts = [footprint("Q1", 10, 10, nets=("GND", "SW"), fields={"Pm.I": "1A"}),
             footprint("L1", 20, 10, nets=("SW", "VOUT"), fields={"Pm.I": "1A"})]
    got = {v.subject: v for v in current_paths(board_geometry(parts, copper=zones))}["SW"]
    assert got.ok is True, got.note
    assert "not measured" not in got.note and "fill" in got.note, got.note


@needs_kicad
def test_a_pour_over_two_pins_and_a_capacitor_joins_them_and_keeps_off_a_neighbours_lane_and_via(tmp_path):
    """The shape a hand layout draws as a polygon: a column over two pins, widening into a
    capacitor's pad, its edge a clearance off a neighbour pin's lane and via."""
    pads = [("28", "PP5V", 10, 10, 0.5, 1.0), ("29", "PP5V", 10, 11.0, 0.5, 1.0), ("5", "PP5V", 14, 8, 1, 1),
            ("7", "GPIO", 8.5, 10, 0.5, 1.0)]
    lane = ("GPIO", 8.5, 10, 8.5, 16, 0.2)
    via = ("GPIO", 12.5, 14)

    def declare(b):
        b.pour(Net("PP5V"), [PadRef(Part("U1"), 28), PadRef(Part("U1"), 29), PadRef(Part("U1"), 5)],
               layer=F, grow=2.0)
    board, plan, _ = _written(tmp_path, pads, declare, tracks=[lane], vias=[via])
    for x, y in ((10, 10), (10, 11), (14, 8)):
        assert _covers(board, "PP5V", x, y), (x, y)
    ps = _polys(board, "PP5V")
    clearance = pcbnew.FromMM(0.2)
    for y in (10.0, 11.0, 12.0, 14.0, 16.0):                       # along the lane, off its copper
        assert not ps.Collide(_vec(8.5, y), pcbnew.FromMM(0.1) + clearance - 1000), y
    assert not ps.Collide(_vec(12.5, 14), pcbnew.FromMM(0.3) + clearance - 1000)


def test_a_polygon_is_clipped_to_a_convex_one():
    from placemat.geometry import clip_to_convex
    box = ((0, 0), (4, 0), (4, 4), (0, 4))
    got = clip_to_convex(box, ((2, -1), (6, -1), (6, 5), (2, 5)))
    assert Box.of_points(got) == Box(2, 0, 4, 4)
    assert clip_to_convex(box, ((10, 10), (12, 10), (12, 12), (10, 12))) == ()
    assert Box.of_points(clip_to_convex(box, ((4, 4), (0, 4), (0, 0), (4, 0)))) == Box(0, 0, 4, 4)     # either winding


@needs_kicad
def test_a_planes_fill_keeps_a_clearance_rule_too(tmp_path):
    """KiCad reads the rules file beside a board as it loads it: a plane's
    fill keeps the script's rule only when the file is there before the
    load, not only after the save."""
    from placemat.kicad.write import apply_plan
    pcb = _kicad_board(tmp_path, TWO_PADS, tracks=[("B", 12, 6, 12, 14, 0.3)])
    plan = _plan(pcb, lambda b: (b.rule(clearance=1.0, between=(Net("A"), Net("B")), why="wide"),
                                 b.plane(Net("A"), [F], outline=[Location(4, 4), Location(20, 4),
                                                                 Location(20, 16), Location(4, 16)])))
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    assert _covers(board, "A", 6, 12)                          # the plane is filled
    for x in (12 - 0.15 - 0.6, 12 + 0.15 + 0.6):               # inside the rule's 1.0, outside the 0.2 netclass
        assert not _covers(board, "A", x, 12), x
