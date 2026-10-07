"""A decided part is judged at the outline - a disc's rim and bore, a shaped outline, a cutout - by its real shapes, not
its box: its copper at the keep-in, its courtyard and body where it draws them. A part that draws no courtyard and no
body is its copper. The reported part: 12 copper sectors (fp_poly on F.Cu, no pads, courtyard or fab) between r 21.2
and r 24.75 on a 49.9 mm disc with a 42 mm bore and a 0.2 mm keep-in. Pure: synthetic boards."""
import math

import pytest

from placemat.board_geometry import Footprint
from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Cutout, Face, Location, Part
from tests.fixtures import board_geometry, footprint

D, BORE, KEEP = 49.9, 42.0, 0.2
C = D / 2.0


def _sector(r0, r1, a0, a1, n=30):
    out = [(C + r1 * math.cos(math.radians(a0 + (a1 - a0) * k / n)), C + r1 * math.sin(math.radians(a0 + (a1 - a0) * k / n)))
           for k in range(n + 1)]
    inner = [(C + r0 * math.cos(math.radians(a1 - (a1 - a0) * k / n)), C + r0 * math.sin(math.radians(a1 - (a1 - a0) * k / n)))
             for k in range(n + 1)]
    return tuple((round(x, 4), round(y, 4)) for x, y in out + inner)


def _ring(r0, r1):
    """12 sectors of 15 degrees, centred on 0, 30, ... 330; the footprint's origin at the disc centre."""
    polys = tuple((CopperLayer.F, _sector(r0, r1, a - 7.5, a + 7.5)) for a in range(0, 360, 30))
    box = Box.union([Box.of_points(p) for _, p in polys])
    return Footprint("TG1", "target", None, "RingTarget", Location(C, C), 0.0, Face.FRONT, box, box, box, (),
                     copper=polys, board_only=True, courtyard_drawn=False)


def _place_ring(r0, r1, how="disc"):
    b = Board(board_geometry([_ring(r0, r1)], width=D, height=D, edge_clearance=KEEP), edge_margin=KEEP,
              keep_going=True)
    if how == "disc":
        b.disc(D, hole=BORE)
    else:                               # the same board drawn as an outline with a cutout
        b.outline(Circle(D), holes=[Cutout(Circle(BORE), "bore", at=Location(C, C))])
    b.place(Part("target"), at=Location(C, C), rotation=0)
    return b.resolve()


def _edge(plan):
    return [str(f) for f in plan.findings if " edge" in str(f) or "keep-in" in str(f) or "bore" in str(f)
            or "rim" in str(f) or "outside" in str(f) or "cutout" in str(f)]


@pytest.mark.parametrize("how", ["disc", "outline"])
def test_an_annulus_of_copper_sectors_inside_a_disc_with_a_bore_is_placed(how):
    plan = _place_ring(21.2, 24.75, how)
    assert _edge(plan) == [], _edge(plan)


@pytest.mark.parametrize("how, word", [("disc", "past the rim"), ("outline", "outside the board")])
def test_the_annulus_half_a_millimetre_too_large_is_refused_at_the_rim(how, word):
    found = _edge(_place_ring(21.2, 25.25, how))
    assert found and word in found[0], found


@pytest.mark.parametrize("how, word", [("disc", "into the bore"), ("outline", "cutout")])
def test_an_annulus_reaching_into_the_bore_is_refused_at_the_bore(how, word):
    found = _edge(_place_ring(20.9, 24.75, how))
    assert found and word in found[0], found


def _rect(x):
    b = Board(board_geometry([footprint("R1", 10, 10, w=4, h=2, inst="r1", excess=0.0)], width=20, height=20),
              edge_margin=0.5, keep_going=True)
    b.place(Part("r1"), at=Location(x, 10.0))
    return b.resolve()


def test_a_rectangular_part_on_a_rectangular_board_is_judged_as_before():
    # 4 wide, its pads reaching 1.9 west of its centre; the keep-in is 0.5
    assert _edge(_rect(2.6)) == []
    found = _edge(_rect(2.2))
    assert found and "copper to edge: box 0.30," in found[0], found
