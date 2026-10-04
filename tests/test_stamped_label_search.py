"""A stamped cell's own labels - the silk texts in its group - are judged
while the cell is searched, as its parts' silk is: under the physical
envelope a spot where a label lies over a placed part's mask opening (silk
over copper to KiCad) or within the silk clearance of its silk is refused,
on the face the cell lands on. Pure: synthetic boards."""
import dataclasses

from placemat.board_geometry import RuleArea
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import CopperLayer, Face, Location
from tests.fixtures import board_geometry, footprint

SILK = 0.2


def _board(label_layer=CopperLayer.F):
    """The panel cell: U1 at (10, 10), its label 'BOOT' a 2 x 1 box from
    (9, 12) to (11, 13), just south of it. R1 stands alone at (30, 30) with
    its pads' mask openings and a silk outline."""
    fps = [footprint("U1", 10, 10, w=4, h=2, cell="panel", inst="panel.u", nets=("A", "B")),
           footprint("R1", 30, 30, w=2, h=1, inst="r1", nets=("B", "C"), mask_grow=0.05,
                     silk_boxes=((28.8, 29.3, 31.2, 29.35),))]
    g = board_geometry(fps, cells=["panel"], width=60, height=60, silk_clearance=SILK)
    g = dataclasses.replace(g, rule_areas=(
        RuleArea("label BOOT", "panel", ((9.0, 12.0), (11.0, 12.0), (11.0, 13.0), (9.0, 13.0)),
                 frozenset([label_layer]), frozenset(["parts"])),))
    occ = Occupancy(g, edge_margin=0.0, settings=dataclasses.replace(Settings(), place_envelope="physical"))
    occ.commit(g.footprint("R1"), Placement(Location(30.0, 30.0), 0.0, Face.FRONT))
    return g, occ


def _at_label(g, x, y, face=Face.FRONT):
    """The cell's placement that puts its label's centre at (x, y), unturned."""
    cell = g.cell("panel")
    c = cell.box.center
    return Placement(Location(x - 10.0 + c.x, y - 12.5 + c.y), 0.0, face)


def test_a_cell_whose_label_lies_on_a_placed_pad_is_refused_there():
    g, occ = _board()
    pad = g.footprint("R1").pads[0].box.center          # R1's west pad
    assert occ.legal(g.cell("panel"), _at_label(g, pad.x, pad.y)) is not None


def test_a_cell_whose_label_is_within_the_silk_clearance_of_a_placed_part_s_silk_is_refused():
    g, occ = _board()
    # the label's north edge 0.1 mm under R1's silk line, clear of its pads
    assert occ.legal(g.cell("panel"), _at_label(g, 30.0, 28.75 - 0.1)) is not None


def test_the_same_cell_clear_of_the_part_is_legal():
    g, occ = _board()
    assert occ.legal(g.cell("panel"), _at_label(g, 30.0, 26.0)) is None


def test_a_label_is_judged_on_the_face_the_cell_lands_on():
    """On the back, the front part's pads and silk are not under the label;
    a back label on a front cell turns to the front with the cell."""
    g, occ = _board()
    pad = g.footprint("R1").pads[0].box.center
    cell = g.cell("panel")
    c = cell.box.center
    # flipped, the cell mirrors about its centre's vertical line: the label's centre lands on the pad
    back = Placement(Location(pad.x + (10.0 - c.x), pad.y - 12.5 + c.y), 0.0, Face.BACK)
    why = occ.legal(cell, back)
    assert why is None or "BOOT" not in str(why) and "silk" not in str(why), why
    g2, occ2 = _board(label_layer=CopperLayer.B)
    assert occ2.legal(g2.cell("panel"), back) is not None
