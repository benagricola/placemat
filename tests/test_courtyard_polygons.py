"""A courtyard that is not a rectangle is claimed by the polygon KiCad
draws and tests, not the box round it."""
import dataclasses
import math

import pytest

from placemat.values import Box, Location
from tests.conftest import needs_breakout, needs_kicad


@needs_kicad
@needs_breakout
def test_a_triangular_courtyard_reads_back_as_its_triangle(breakout_pcb, tmp_path):
    import shutil
    import pcbnew
    from placemat.kicad.read import read_board
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), tmp_path / ("layout" + ext))
    pcb = tmp_path / "layout.kicad_pcb"
    brd = pcbnew.LoadBoard(str(pcb))
    fp = next(f for f in brd.GetFootprints() if f.GetLayer() == pcbnew.F_Cu)
    ref = fp.GetReference()
    for d in list(fp.GraphicalItems()):
        if d.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            fp.Delete(d)
    bb = fp.GetBoundingBox(False, False)
    x0, y0, x1, y1 = bb.GetLeft() - pcbnew.FromMM(1), bb.GetTop() - pcbnew.FromMM(1), \
        bb.GetRight() + pcbnew.FromMM(4), bb.GetBottom() + pcbnew.FromMM(4)
    tri = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_POLY)
    tri.SetPolyPoints([pcbnew.VECTOR2I(x0, y0), pcbnew.VECTOR2I(x1, y0), pcbnew.VECTOR2I(x0, y1)])
    tri.SetLayer(pcbnew.F_CrtYd)
    tri.SetWidth(pcbnew.FromMM(0.05))
    fp.Add(tri)
    brd.Save(str(pcb))
    part = next(f for f in read_board(pcb).footprints if f.ref == ref)
    assert len(part.courtyard_poly) == 3
    xs, ys = [p[0] for p in part.courtyard_poly], [p[1] for p in part.courtyard_poly]
    assert min(xs) == pytest.approx(pcbnew.ToMM(x0), abs=0.05) and max(ys) == pytest.approx(pcbnew.ToMM(y1), abs=0.05)


@needs_kicad
@needs_breakout
def test_a_rectangular_courtyard_reads_back_as_a_rectangle(breakout):
    fp = next(f for f in breakout.footprints if f.courtyard_poly)
    assert len(fp.courtyard_poly) == 4


def _sector(ref, inst, centre=(20.0, 20.0), radius=6.0, span=30.0):
    """A part shaped like a slice of a disc, its origin at the disc's centre
    and its courtyard the slice (0 to `span` degrees); its box is much more."""
    from tests.fixtures import footprint
    cx, cy = centre
    wedge = ((cx, cy),) + tuple((cx + radius * math.cos(math.radians(a)), cy + radius * math.sin(math.radians(a)))
                                for a in range(0, int(span) + 1, 5))
    fp = footprint(ref, cx + 4.0, cy + 0.9, w=2.4, h=1.0, inst=inst, nets=("N%s1" % ref, "N%s2" % ref))
    return dataclasses.replace(fp, location=Location(cx, cy), courtyard_box=Box.of_points(wedge),
                               body_box=Box.of_points(wedge), courtyard_poly=wedge)


def _occupancy(*fps):
    from placemat.occupancy import Occupancy
    from tests.fixtures import board_geometry
    return Occupancy(board_geometry(list(fps), width=60, height=60), edge_margin=0.0)


def test_two_slices_of_a_disc_apart_may_stand_though_their_boxes_overlap():
    from placemat.placement import Placement
    from placemat.values import Face
    a, b = _sector("L1", "l1"), _sector("L2", "l2")
    occ = _occupancy(a, b)
    assert occ.legal(b, Placement(Location(20, 20), 35.0, Face.FRONT)) is None


def test_two_slices_of_a_disc_that_overlap_are_refused():
    from placemat.placement import Placement
    from placemat.values import Face
    a, b = _sector("L1", "l1"), _sector("L2", "l2")
    occ = _occupancy(a, b)
    why = occ.legal(b, Placement(Location(20, 20), 20.0, Face.FRONT))
    assert why is not None and "courtyard" in str(why)


def test_a_rectangular_courtyard_keeps_its_box():
    from tests.fixtures import footprint
    fp = footprint("R1", 10, 10, w=2, h=1)
    square = dataclasses.replace(fp, courtyard_poly=((8.9, 9.4), (11.1, 9.4), (11.1, 10.6), (8.9, 10.6)))
    occ = _occupancy(square)
    (court,) = [s for s in occ.items["R1"].shapes if s.kind == "courtyard"]
    assert Box.of_points(court.poly) == square.courtyard_box


def test_a_slice_at_a_round_boards_centre_is_judged_by_its_polygon_at_the_edge():
    from placemat.layout import Board
    from placemat.values import Part
    from tests.fixtures import board_geometry
    fp = _sector("L1", "l1", centre=(7.0, 7.0))
    b = Board(board_geometry([fp], width=14, height=14), edge_margin=0.5)
    b.disc(diameter=14.0)
    b.place(Part("l1"), at=Location(7.0, 7.0), rotation=45)           # the box's far corner 6.7 out, past 6.5
    plan = b.resolve()
    assert not [f for f in plan.findings if f.kind == "fixed"], list(plan.findings)


@pytest.mark.parametrize("turn", [35.0, 90.0, 180.0, 270.0, 300.0, 325.0])
def test_two_slices_sharing_only_their_apex_may_stand_whichever_way_turned(turn):
    """KiCad does not count a shared vertex as an overlap; whether placemat
    did depended on which way the part was turned."""
    from placemat.placement import Placement
    from placemat.values import Face
    a, b = _sector("L1", "l1"), _sector("L2", "l2")
    occ = _occupancy(a, b)
    assert occ.legal(b, Placement(Location(20, 20), turn, Face.FRONT)) is None


def test_polygons_sharing_one_vertex_do_not_overlap_in_either_order():
    from placemat.geometry import polys_overlap
    tri = ((0.0, 0.0), (4.0, 0.0), (0.0, 3.0))
    other = ((0.0, 0.0), (-4.0, 0.0), (0.0, -3.0))
    assert not polys_overlap(tri, other) and not polys_overlap(other, tri)
    assert not polys_overlap(tri[::-1], other) and not polys_overlap(other[::-1], tri)
