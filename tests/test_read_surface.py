"""The read surface against real boards: the standalone footprint reader, the
board's true outline, and the promise that this reader and the placer's agree."""
import glob
import hashlib
import os
import pathlib

import pytest

from placemat.kicad.read import read_board
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad]

FAIRING = "/home/ben/Documents/Hardware/fairing-instrument/electronics/boards/main/kicad/layout.kicad_pcb"
PARTS = "/home/ben/Documents/Hardware/fairing-instrument/electronics/parts"
needs_fairing = pytest.mark.skipif(not pathlib.Path(FAIRING).exists(),
                                   reason="the fairing main board is not here")
needs_parts = pytest.mark.skipif(not os.path.isdir(PARTS), reason="the fairing parts are not here")


def _one(pattern):
    hits = glob.glob(os.path.join(PARTS, pattern, "*.kicad_mod"))
    if not hits:
        pytest.skip("no footprint matching %s" % pattern)
    return hits[0]


@needs_breakout
def test_a_rectangular_board_reads_as_one_outline_with_no_holes(breakout_pcb):
    g = read_board(breakout_pcb)
    assert len(g.board_polygon) == 1
    assert len(g.board_polygon[0]) >= 4


@needs_breakout
def test_the_outline_box_agrees_with_the_polygon(breakout_pcb):
    """board_polygon is added beside outline, not instead of it; they must
    describe the same board."""
    from placemat.values import Box
    g = read_board(breakout_pcb)
    poly_box = Box.of_points(g.board_polygon[0])
    assert poly_box.width == pytest.approx(g.outline_box.width, abs=0.2)
    assert poly_box.height == pytest.approx(g.outline_box.height, abs=0.2)


@needs_fairing
def test_a_disc_with_a_bore_reads_as_a_curve_and_a_hole():
    """The case outline gets wrong: it holds one bounding box per Edge.Cuts
    drawing, so a disc reads as a square."""
    g = read_board(FAIRING)
    assert len(g.board_polygon) >= 2                 # the rim, and at least one hole
    assert len(g.board_polygon[0]) > 100             # a flattened curve, not a rectangle
