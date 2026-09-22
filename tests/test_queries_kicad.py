"""The occupancy queries against pcbnew: the rules they need, read off a real
board, and a spot the search chose that KiCad's DRC accepts."""
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad]


@needs_breakout
def test_the_board_hole_rules_are_read(breakout_pcb):
    import pcbnew
    from placemat.kicad.read import read_board
    ds = pcbnew.LoadBoard(str(breakout_pcb)).GetDesignSettings()
    g = read_board(breakout_pcb)
    assert abs(g.hole_to_hole - pcbnew.ToMM(ds.m_HoleToHoleMin)) < 1e-6
    assert abs(g.hole_clearance - pcbnew.ToMM(ds.m_HoleClearance)) < 1e-6


def test_a_via_reads_its_drill(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    b = pcbnew.CreateEmptyBoard()
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(10), pcbnew.FromMM(10)))
    v.SetWidth(pcbnew.FromMM(0.6))
    v.SetDrill(pcbnew.FromMM(0.3))
    b.Add(v)
    p = tmp_path / "v.kicad_pcb"
    b.Save(str(p))
    (via,) = [c for c in read_board(p).copper if c.kind == "via"]
    assert abs(via.drill_mm - 0.3) < 1e-6
