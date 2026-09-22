"""The marker against pcbnew: read, written, and widened on a stamped zone."""
import pytest

from placemat.values import CopperLayer
from tests.conftest import needs_kicad

pytestmark = [needs_kicad]
F, B, IN1, IN2 = CopperLayer.F, CopperLayer.B, CopperLayer.IN1, CopperLayer.IN2


def _board(tmp_path, copper, zones, group=None):
    """A board of `copper` layers carrying rule areas (name, layer ids), the
    lot in one group when `group` is given - which is how a stamp looks."""
    import pcbnew
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(copper)
    g = None
    if group:
        g = pcbnew.PCB_GROUP(b)
        g.SetName(group)
        b.Add(g)
    for i, (name, layer_ids) in enumerate(zones):
        z = pcbnew.ZONE(b)
        z.SetIsRuleArea(True)
        ls = pcbnew.LSET()
        for l in layer_ids:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        z.SetDoNotAllowFootprints(False)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowPads(False)
        o = z.Outline()
        o.NewOutline()
        x = 10.0 * i
        for px, py in ((x, 0), (x + 4, 0), (x + 4, 4), (x, 4)):
            o.Append(pcbnew.FromMM(px), pcbnew.FromMM(py))
        z.SetZoneName(name)
        b.Add(z)
        if g is not None:
            g.AddItem(z)
    path = tmp_path / "layout.kicad_pcb"
    b.Save(str(path))
    return path


def test_a_stamped_all_layer_keepout_reads_on_every_layer_of_the_parent(tmp_path):
    """The W3011 case: declared on every layer in a two-layer module, arriving
    in the four-layer parent on F and B only."""
    import pcbnew
    from placemat.kicad.read import read_board
    path = _board(tmp_path, 4, [("keepout antenna [*.Cu]_1", (pcbnew.F_Cu, pcbnew.B_Cu))],
                  group="ant_rf")
    (ra,) = read_board(path).rule_areas
    assert ra.layers == frozenset((F, IN1, IN2, B))
    assert ra.base == "keepout antenna" and ra.cell == "ant_rf" and ra.missing == ()


def test_a_declared_layer_the_board_lacks_is_kept_as_missing(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    path = _board(tmp_path, 2, [("keepout antenna_c [In2.Cu]", (pcbnew.In2_Cu,))])
    (ra,) = read_board(path).rule_areas
    assert ra.layers == frozenset() and ra.missing == (IN2,)


def test_an_unmarked_rule_area_reads_as_it_always_did(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    path = _board(tmp_path, 4, [("keepout vent", (pcbnew.F_Cu,))])
    (ra,) = read_board(path).rule_areas
    assert ra.layers == frozenset((F,)) and ra.missing == ()


def _plan_with(keepout_layers):
    """A resolved plan carrying one keepout, on a synthetic geometry."""
    from placemat.cutouts import Circle
    from placemat.layout import Board
    from placemat.values import Location
    from tests.fixtures import board_geometry
    b = Board(board_geometry([], width=40, height=40), edge_margin=0.0)
    b.keepout(Circle(4.0), "antenna", at=Location(20, 20), layers=keepout_layers,
              why="the antenna clearance")
    return b.resolve()


def test_an_every_layer_keepout_is_written_with_its_marker(tmp_path):
    import pcbnew
    from placemat.kicad.write import _draw_keepouts
    path = _board(tmp_path, 2, [])
    board = pcbnew.LoadBoard(str(path))
    _draw_keepouts(board, _plan_with(None))
    names = [z.GetZoneName() for z in board.Zones() if z.GetIsRuleArea()]
    assert names == ["keepout antenna [*.Cu]"]


def test_writing_widens_a_stamped_zone_to_what_it_declared(tmp_path):
    import pcbnew
    from placemat.kicad.write import _draw_keepouts
    path = _board(tmp_path, 4, [("keepout antenna [*.Cu]_1", (pcbnew.F_Cu, pcbnew.B_Cu)),
                                ("keepout plain_1", (pcbnew.F_Cu,))], group="ant_rf")
    board = pcbnew.LoadBoard(str(path))
    _draw_keepouts(board, _plan_with(None))
    layers = {z.GetZoneName(): sorted(board.GetLayerName(l) for l in z.GetLayerSet().CuStack())
              for z in board.Zones() if z.GetIsRuleArea()}
    assert layers["keepout antenna [*.Cu]_1"] == ["B.Cu", "F.Cu", "In1.Cu", "In2.Cu"]
    assert layers["keepout plain_1"] == ["F.Cu"]            # no marker: left alone
