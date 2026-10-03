"""A fitted pour (`swallow_pads=True`) may join vias as well as pads: what
`board.via()` and `board.vias()` return, and an escape lane's `.via`. A via
counts on the pour's layer when its span includes it, as its copper ring
there. The pour is planned after the vias it joins. The plan tests are pure
(synthetic four-layer boards); the DRC test writes a board and has KiCad
check it."""
import dataclasses

import pcbnew
import pytest

from placemat import pourfit, reuse
from placemat.copper import Pour, Track, Via
from placemat.geometry import point_in_polygon, poly_distance
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.values import CopperLayer, Edge, FreeSpot, Location, Net, OnEdge, PadRef, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, declared_findings
from tests.test_pour_fitted import CLEARANCE, SAG, _add_pad, _gap, _part, _vec

F, IN1, IN2, B = CopperLayer.F, CopperLayer.IN1, CopperLayer.IN2, CopperLayer.B
FOUR = (F, IN1, IN2, B)


@pytest.fixture(autouse=True)
def _fab_makes_every_via(monkeypatch):
    monkeypatch.setattr(Board, "fab_via_tiers", {"micro": "yes", "blind": "yes", "buried": "yes"})


def _board(parts=(), **kw):
    geometry = dataclasses.replace(board_geometry(list(parts), width=60, height=60, clearance=CLEARANCE, **kw),
                                   layers=FOUR)
    return Board(geometry, edge_margin=1.0)


def _pour(plan):
    (p,) = [c for c in plan.copper if isinstance(c, Pour)]
    assert p.fitted
    return p


def _vias(plan, net="A"):
    return [c for c in plan.copper if isinstance(c, Via) and c.net == net]


def _holds_vias(p, vias):
    """Every corner of every via's ring lies in the pour's copper, to the arc sag."""
    copper = pourfit.offset(p.points, p.stroke / 2.0 + SAG)
    for v in vias:
        for x, y in v.polygon:
            assert point_in_polygon((x, y), copper) or poly_distance(
                copper, ((x, y), (x + 1e-6, y), (x, y + 1e-6))) < 1e-6, (v.at, x, y)


def _via(b, x, y, net="A", **kw):
    return b.via(Net(net), Location(x, y), size=0.6, drill=0.3, **kw)


def test_three_vias_on_an_inner_layer_are_held_round_a_track_between_two_of_them():
    b = _board(extra_nets=["A", "B"])
    drops = [_via(b, x, y) for x, y in ((10.0, 10.0), (18.0, 10.0), (14.0, 16.0))]
    b.track(Net("B"), [Location(14.0, 5.0), Location(14.0, 12.0)], layer=IN2, width=0.2, chamfer=0)
    b.pour(Net("A"), drops, layer=IN2, swallow_pads=True)
    plan = b.resolve()
    p = _pour(plan)
    assert p.layer is IN2
    _holds_vias(p, _vias(plan))
    (track,) = [c for c in plan.copper if isinstance(c, Track)]
    gap = _gap(p, track.polygon)
    assert CLEARANCE - 1e-6 <= gap <= CLEARANCE + SAG + 1e-6, gap
    assert not declared_findings(plan), plan.findings


def test_a_pad_and_a_via_are_held_on_the_front_layer():
    b = _board([_part("A0", "A", 10.0, 10.0)], extra_nets=["A"])
    v = _via(b, 14.0, 10.0)
    b.pour(Net("A"), [PadRef(Part("a0"), 1), v], layer=F, swallow_pads=True)
    plan = b.resolve()
    p = _pour(plan)
    _holds_vias(p, _vias(plan))
    assert min(x for x, _ in p.points) <= 9.6                   # the pad's west edge is held too
    assert not declared_findings(plan), plan.findings


def test_a_pad_without_copper_on_the_layer_is_refused_beside_a_via():
    b = _board([_part("A0", "A", 10.0, 10.0)], extra_nets=["A"])
    v = _via(b, 14.0, 10.0)
    b.pour(Net("A"), [PadRef(Part("a0"), 1), v], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    assert not [c for c in plan.copper if isinstance(c, Pour)]
    assert any("pad A0.1 has no copper on In2.Cu" in f for f in declared_findings(plan)), plan.findings


def test_a_via_that_does_not_span_the_pours_layer_is_refused_and_named():
    b = _board(extra_nets=["A"])
    a = _via(b, 10.0, 10.0)
    c = _via(b, 14.0, 10.0, layers=(F, IN1))
    b.pour(Net("A"), [a, c], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    assert not [x for x in plan.copper if isinstance(x, Pour)]
    hits = [f for f in declared_findings(plan) if "does not span In2.Cu" in f]
    assert len(hits) == 1 and "via at (14.00, 10.00)" in hits[0] and "F.Cu-In1.Cu" in hits[0], plan.findings


def test_a_via_that_spans_the_layer_without_being_a_through_via_counts():
    b = _board(extra_nets=["A"])
    a = _via(b, 10.0, 10.0, layers=(IN1, IN2))
    c = _via(b, 14.0, 10.0, layers=(IN2, B))
    b.pour(Net("A"), [a, c], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    _holds_vias(_pour(plan), _vias(plan))


def test_a_vias_result_is_every_one_of_its_vias():
    b = _board([_part("A0", "A", 20.0, 20.0, 2.0, 1.0)], extra_nets=["A"])
    b.place(Part("a0"), at=Location(20.0, 20.0))
    drops = b.vias(Net("A"), along=PadRef(Part("a0"), 1), count=3, size=0.6, drill=0.3)
    b.pour(Net("A"), [drops], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    vias = _vias(plan)
    assert len(vias) == 3
    _holds_vias(_pour(plan), vias)


def test_an_escape_lanes_via_is_a_member():
    from tests.escape_fixtures import board_with, qfn
    nets = {32: "V", 31: "V", 30: "PGOOD"}
    b = board_with([qfn(nets=nets)])
    b.geometry = dataclasses.replace(b.geometry, layers=FOUR)
    b.place(Part("pd"), at=Location(30, 30))
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[32, 31], why="north row")
    b.pour(Net("V"), [esc[32].via, esc[31].via], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    vias = _vias(plan, "V")
    assert len(vias) == 2
    _holds_vias(_pour(plan), vias)


def test_a_pour_of_only_vias_is_drawn():
    b = _board(extra_nets=["A"])
    members = [_via(b, x, 10.0) for x in (10.0, 13.0)]
    b.pour(Net("A"), members, layer=IN2, swallow_pads=True)
    plan = b.resolve()
    _holds_vias(_pour(plan), _vias(plan))


@pytest.mark.parametrize("pour_before_place", [False, True])
def test_the_pour_waits_for_a_free_spot_via_and_the_part_it_is_found_from(pour_before_place):
    """The via is found from a pad of a searched part; the pour, naming the via, is planned after it
    whichever of the pour and the part's place() is declared first."""
    b = _board([_part("A0", "A", 20.0, 20.0)], extra_nets=["A"])
    far = _part("A1", "A", 10.0, 10.0)
    b.geometry = dataclasses.replace(b.geometry, footprints=b.geometry.footprints + (far,))
    v = b.via(Net("A"), FreeSpot(PadRef(Part("a0"), 1), tail=False), size=0.6, drill=0.3)
    place = lambda: b.place(Part("a0"), at=OnEdge(Edge.EAST))           # searched
    if not pour_before_place:
        place()
    b.pour(Net("A"), [v, PadRef(Part("a1"), 1)], layer=F, swallow_pads=True)
    if pour_before_place:
        place()
    plan = b.resolve()
    vias = _vias(plan)
    assert len(vias) == 1
    _holds_vias(_pour(plan), vias)
    kinds = [type(c) for c in plan.copper if isinstance(c, (Via, Pour))]
    assert kinds == [Via, Pour]


def test_a_via_member_without_swallow_pads_is_refused():
    b = _board(extra_nets=["A"])
    members = [_via(b, x, 10.0) for x in (10.0, 13.0, 16.0)]
    with pytest.raises(TypeError, match="swallow_pads"):
        b.pour(Net("A"), members, layer=IN2)


def test_a_track_is_not_a_member():
    b = _board(extra_nets=["A"])
    t = b.track(Net("A"), [Location(10.0, 10.0), Location(12.0, 10.0)], layer=IN2, chamfer=0)
    with pytest.raises(TypeError, match="track"):
        b.pour(Net("A"), [t, _via(b, 14.0, 10.0)], layer=IN2, swallow_pads=True)


def test_a_via_of_another_net_is_a_finding():
    b = _board(extra_nets=["A", "B"])
    b.pour(Net("A"), [_via(b, 10.0, 10.0), _via(b, 14.0, 10.0, net="B")], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    assert not [c for c in plan.copper if isinstance(c, Pour)]
    assert any("via at (14.00, 10.00) is on net B" in f for f in declared_findings(plan)), plan.findings


def test_a_pour_without_via_members_digests_as_before():
    def intent(members):
        b = _board([_part("A%d" % i, "A", 10 + 4 * i, 10) for i in range(3)], extra_nets=["A"])
        pads = [PadRef(Part("a%d" % i), 1) for i in range(3)]
        b.pour(Net("A"), pads + members(b), layer=F, swallow_pads=True)
        return reuse.canonical(b._copper)
    plain = intent(lambda b: [])
    assert "members" not in plain
    assert intent(lambda b: [_via(b, 12.0, 12.0)]) != plain


@needs_kicad
def test_kicads_drc_finds_no_clearance_violation_from_a_pour_on_an_inner_layer_joining_vias(tmp_path):
    from placemat.kicad.drc import run_drc
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(4)
    b.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(pcbnew.FromMM(CLEARANCE))
    for a, c in (((0, 0), (40, 0)), ((40, 0), (40, 40)), ((40, 40), (0, 40)), ((0, 40), (0, 0))):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(_vec(*a))
        s.SetEnd(_vec(*c))
        b.Add(s)
    nets = {}
    for name in ("VOUT", "SW"):
        nets[name] = pcbnew.NETINFO_ITEM(b, name)
        b.Add(nets[name])
    fp = pcbnew.FOOTPRINT(b)            # a pad of the vias' net, so the board knows it
    fp.SetReference("U1")
    fp.SetPosition(_vec(30, 30))
    b.Add(fp)
    _add_pad(fp, "1", nets["VOUT"], 30.0, 30.0)
    t = pcbnew.PCB_TRACK(b)             # another net's track on In2, between the vias
    t.SetLayer(pcbnew.In2_Cu)
    t.SetWidth(pcbnew.FromMM(0.2))
    t.SetStart(_vec(14.0, 5.0))
    t.SetEnd(_vec(14.0, 12.0))
    t.SetNet(nets["SW"])
    b.Add(t)
    pcb = tmp_path / "vias.kicad_pcb"
    b.Save(str(pcb))
    board = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    board.rect(width=40.0, height=40.0)
    drops = [board.via(Net("VOUT"), Location(x, y), size=0.6, drill=0.3)
             for x, y in ((10.0, 10.0), (18.0, 10.0), (14.0, 16.0))]
    board.pour(Net("VOUT"), drops, layer=IN2, swallow_pads=True)
    plan = board.resolve()
    assert [c for c in plan.copper if isinstance(c, Pour)], plan.findings
    apply_plan(pcb, plan)
    report = run_drc(pcb, tmp_path / "drc.json")
    assert report.by_type.get("clearance", 0) == 0 and report.by_type.get("shorting_items", 0) == 0, report.by_type
