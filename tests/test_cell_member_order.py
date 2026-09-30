"""A cell's members are read in reference order. KiCad returns a group's
items in no fixed order, so members read in that order made the search's
refusal tallies and the split finding's member lists vary between runs of
the same board."""
from tests.conftest import needs_kicad


def _board(path, order):
    import pcbnew
    b = pcbnew.CreateEmptyBoard()
    g = pcbnew.PCB_GROUP(b)
    g.SetName("m")
    b.Add(g)
    fps = {}
    for k, ref in enumerate(("R10", "C2", "U1", "R2")):
        fp = pcbnew.FOOTPRINT(b)
        fp.SetReference(ref)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(5 + 3 * k), pcbnew.FromMM(5)))
        b.Add(fp)
        fps[ref] = fp
    for ref in order:
        g.AddItem(fps[ref])
    b.Save(str(path))


@needs_kicad
def test_a_cells_members_come_in_reference_order_whatever_the_group_says(tmp_path):
    from placemat.kicad.read import read_board
    seen = set()
    for n, order in enumerate((("R10", "C2", "U1", "R2"), ("U1", "R2", "R10", "C2"))):
        pcb = tmp_path / ("b%d" % n) / "layout.kicad_pcb"
        pcb.parent.mkdir()
        _board(pcb, order)
        seen.add(tuple(fp.ref for fp in read_board(pcb).cells["m"].members))
    assert seen == {("C2", "R2", "R10", "U1")}
