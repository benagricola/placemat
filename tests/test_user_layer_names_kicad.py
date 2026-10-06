"""A board whose copper layers carry user names reads and writes by the
standard names F.Cu, In1.Cu, B.Cu, not the user's."""
import pytest

pytest.importorskip("pcbnew")

from placemat.kicad.quiet import import_pcbnew
from placemat.kicad.read import read_board
from placemat.values import CopperLayer
from tests.conftest import needs_kicad

pytestmark = [needs_kicad]


def _board(tmp_path):
    pcbnew = import_pcbnew()
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(4)
    board.SetLayerName(pcbnew.F_Cu, "top_layer")
    board.SetLayerName(pcbnew.In1_Cu, "gnd_plane")
    board.SetLayerName(pcbnew.In2_Cu, "power_plane")
    board.SetLayerName(pcbnew.B_Cu, "bottom_layer")
    for i, (a, b) in enumerate([((0, 0), (20, 0)), ((20, 0), (20, 10)), ((20, 10), (0, 10)), ((0, 10), (0, 0))]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[0]), pcbnew.FromMM(a[1])))
        seg.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(b[0]), pcbnew.FromMM(b[1])))
        board.Add(seg)
    path = str(tmp_path / "named.kicad_pcb")
    board.Save(path)
    return path


def test_a_board_with_user_named_copper_layers_reads(tmp_path):
    path = _board(tmp_path)
    g = read_board(path)
    assert g.layers == (CopperLayer.F, CopperLayer.IN1, CopperLayer.IN2, CopperLayer.B)


def test_the_route_layer_list_uses_standard_names(tmp_path):
    from placemat.kicad.route import _copper_layers
    assert _copper_layers(_board(tmp_path)) == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
