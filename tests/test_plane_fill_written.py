"""A plane's KiCad fill, written and read back: it keeps the script's clearance rules, and the checks measure it."""
import pcbnew

from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint

F = CopperLayer.F


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
    b.rect(width=40.0, height=40.0)
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


TWO_PADS = [("1", "A", 10, 10, 1, 1), ("2", "A", 14, 10, 1, 1)]


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


@needs_kicad
def test_current_path_measures_the_written_fill_of_a_plane(tmp_path):
    """The checks read the filled board: a plane's fill is a zone there, and the load's route
    through it is measured as through any zone fill."""
    from placemat.checks import current_paths
    from placemat.kicad.read import read_board
    pads = [("1", "SW", 11.4, 10, 1, 1), ("2", "SW", 18.6, 10, 1, 1)]
    board, plan, pcb = _written(tmp_path, pads, lambda b: b.plane(Net("SW"), [F], outline=[
        Location(9, 8.5), Location(21, 8.5), Location(21, 11.5), Location(9, 11.5)]),
        tracks=[("OTHER", 15, 2, 15, 7.5, 0.3)])
    read = read_board(pcb)
    zones = [c for c in read.copper if c.kind == "zone" and c.net == "SW"]
    assert zones
    parts = [footprint("Q1", 10, 10, nets=("GND", "SW"), fields={"Pm.I": "1A"}),
             footprint("L1", 20, 10, nets=("SW", "VOUT"), fields={"Pm.I": "1A"})]
    got = {v.subject: v for v in current_paths(board_geometry(parts, copper=zones))}["SW"]
    assert got.ok is True, got.note
    assert "not measured" not in got.note and "fill" in got.note, got.note
