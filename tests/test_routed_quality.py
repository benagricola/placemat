"""The routed quality key's terms read off a routed board (kicad.route.routed_quality), as KRT's board_score.quality
reads them: vias, routed copper in mm and the track count."""
import pytest

from tests.conftest import needs_kicad

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")


def _vec(x, y):
    return pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6)))


def test_vias_copper_and_segments_are_counted_off_the_routed_board(tmp_path):
    from placemat.kicad.route import routed_quality
    board = pcbnew.CreateEmptyBoard()
    for a, b in (((0, 0), (3, 4)), ((3, 4), (3, 10))):
        t = pcbnew.PCB_TRACK(board)
        t.SetLayer(pcbnew.F_Cu)
        t.SetStart(_vec(*a))
        t.SetEnd(_vec(*b))
        t.SetWidth(pcbnew.FromMM(0.2))
        board.Add(t)
    for at in ((3, 10), (8, 8), (9, 9)):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(_vec(*at))
        v.SetWidth(pcbnew.FromMM(0.6))
        v.SetDrill(pcbnew.FromMM(0.3))
        board.Add(v)
    path = tmp_path / "routed.kicad_pcb"
    board.Save(str(path))
    assert routed_quality(path) == {"vias": 3, "copper_mm": 11.0, "segments": 2}
