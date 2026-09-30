"""A part's body under the physical envelope is its fab outline. A fab
layer holding one closed shape (a circle, a polygon, a rectangle) is that
shape; several graphics (four lines round a body) are the box round them,
as before. A round body is not claimed as its square."""
from tests.conftest import needs_kicad


def _board(path, shapes):
    import pcbnew
    b = pcbnew.CreateEmptyBoard()
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference("M1")
    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(20), pcbnew.FromMM(20)))
    mm = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
    for kind, a, b2 in shapes:
        sh = pcbnew.PCB_SHAPE(fp, kind)
        sh.SetLayer(pcbnew.F_Fab)
        sh.SetWidth(pcbnew.FromMM(0.1))
        sh.SetStart(mm(*a))
        sh.SetEnd(mm(*b2))
        fp.Add(sh)
    b.Add(fp)
    b.Save(str(path))


@needs_kicad
def test_one_fab_circle_is_claimed_as_the_circle():
    import pcbnew
    from placemat.geometry import point_in_polygon
    from placemat.kicad.read import read_board
    pcb = __import__("pathlib").Path(__import__("tempfile").mkdtemp()) / "layout.kicad_pcb"
    _board(pcb, [(pcbnew.SHAPE_T_CIRCLE, (20, 20), (26.2, 20))])        # r 6.2 round the origin
    [(face, poly)] = read_board(pcb).footprint("M1").fab
    assert len(poly) > 8
    assert point_in_polygon((20.0, 25.9), poly)                           # inside the disc
    assert not point_in_polygon((25.5, 25.5), poly)                       # a corner of its square


@needs_kicad
def test_four_fab_lines_are_still_the_box_round_them():
    import pcbnew
    from placemat.kicad.read import read_board
    pcb = __import__("pathlib").Path(__import__("tempfile").mkdtemp()) / "layout.kicad_pcb"
    lines = [((18, 19), (22, 19)), ((22, 19), (22, 21)), ((22, 21), (18, 21)), ((18, 21), (18, 19))]
    _board(pcb, [(pcbnew.SHAPE_T_SEGMENT, a, b) for a, b in lines])
    [(face, poly)] = read_board(pcb).footprint("M1").fab
    assert len(poly) == 4
