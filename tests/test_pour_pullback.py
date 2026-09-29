"""A pour with swallow_pads pulls back from every other net's copper to the
netclass clearance, as a zone fill does, dropping any piece the pull-back
cuts off that touches no named or swallowed pad. Real case: a pour over a
clamp's pad and three capacitor ends came 0.15 mm from a 100 nF's other-net
pad against a 0.16 mm rule (kicad reported 3 clearance errors) - the pour's
own shape already ran that close, before any growing over same-net pads.

Built on a from-scratch synthetic board (as test_layers.py's _board_with
does) so the clearance and the pad positions are exact, not whatever a real
board's parts happen to leave."""
import pcbnew
import pytest

from placemat.geometry import point_in_polygon, poly_distance
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net
from tests.conftest import needs_kicad

pytestmark = needs_kicad


def _vec(x, y):
    return pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6)))


def _add_pad(fp, number, net, x, y, w=1.0, h=1.0):
    pad = pcbnew.PAD(fp)
    pad.SetNumber(number)
    pad.SetShape(pcbnew.PAD_SHAPE_RECTANGLE)
    pad.SetSize(pcbnew.VECTOR2I(int(round(w * 1e6)), int(round(h * 1e6))))
    pad.SetPosition(_vec(x, y))
    pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    pad.SetLayerSet(pcbnew.PAD.SMDMask())
    pad.SetNet(net)
    fp.Add(pad)
    return pad


def _board(tmp_path, pads, clearance=0.16):
    """A 40x40 board with one footprint U1 carrying `pads`
    (number, net_name, x, y, w, h), at the netclass clearance given."""
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
        if net_name not in nets:
            n = pcbnew.NETINFO_ITEM(b, net_name)
            b.Add(n)
            nets[net_name] = n
        _add_pad(fp, number, nets[net_name], x, y, w, h)
    path = tmp_path / "pullback.kicad_pcb"
    b.Save(str(path))
    return path


# pad 1, 2, 3 on PROBE_A in a row; pad 4 on PROBE_B 0.2 mm north of pad 1
_THREE_AND_A_NEIGHBOUR = [
    ("1", "PROBE_A", 10.0, 10.0, 1.0, 1.0),
    ("2", "PROBE_A", 12.0, 10.0, 1.0, 1.0),
    ("3", "PROBE_A", 14.0, 10.0, 1.0, 1.0),
    ("4", "PROBE_B", 10.0, 8.8, 1.0, 1.0),
]


def test_a_swallow_pour_keeps_the_clearance_from_a_foreign_pad_beside_it(tmp_path):
    pcb = _board(tmp_path, _THREE_AND_A_NEIGHBOUR, clearance=0.16)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    # a band across the row that runs right up near pad 4, as the real board did
    pts = [Location(9.0, 9.4), Location(15.0, 9.4), Location(15.0, 10.6), Location(9.0, 10.6)]
    b.pour(Net("PROBE_A"), pts, layer=CopperLayer.F, swallow_pads=True)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    u1 = after.footprint("U1")
    pad4 = u1.pad(4)
    polys = [c for c in after.copper if c.kind == "poly" and c.net == "PROBE_A"]
    assert polys
    gap = min(poly_distance(o, pad4.outlines[0]) for p in polys for o in p.outlines)
    assert gap >= 0.16 - 1e-6, gap
    # still covers the three pads it was declared over
    for number in (1, 2, 3):
        c = u1.pad(number).box.center
        assert any(point_in_polygon((c.x, c.y), o) for p in polys for o in p.outlines), number


def test_a_pour_without_swallow_pads_keeps_its_given_shape_exactly(tmp_path):
    """Documented and unchanged: no pull-back at all without swallow_pads."""
    pcb = _board(tmp_path, _THREE_AND_A_NEIGHBOUR, clearance=0.16)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    pts = [Location(9.0, 9.4), Location(15.0, 9.4), Location(15.0, 10.6), Location(9.0, 10.6)]
    b.pour(Net("PROBE_A"), pts, layer=CopperLayer.F, swallow_pads=False, stroke=0.0)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    polys = [c for c in after.copper if c.kind == "poly" and c.net == "PROBE_A"]
    assert len(polys) == 1
    box = polys[0].box
    assert (round(box.left, 2), round(box.top, 2), round(box.right, 2), round(box.bottom, 2)) == (9.0, 9.4, 15.0, 10.6)


def test_a_named_pad_isolated_by_the_pull_back_is_a_finding(tmp_path):
    """A pour small enough that pulling back from a touching foreign pad
    cuts it off entirely: reported, not silently dropped."""
    pads = [
        ("1", "PROBE_A", 10.0, 10.0, 1.0, 1.0),
        ("4", "PROBE_B", 10.0, 10.0, 1.0, 1.0),      # right over pad 1: no room anywhere near it
    ]
    pcb = _board(tmp_path, pads, clearance=0.16)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    pts = [Location(9.45, 9.45), Location(10.55, 9.45), Location(10.55, 10.55), Location(9.45, 10.55)]
    b.pour(Net("PROBE_A"), pts, layer=CopperLayer.F, swallow_pads=True)
    plan = b.resolve()
    apply_plan(pcb, plan)
    assert any("joined to nothing" in f and "U1.1" in f for f in plan.findings), plan.findings
