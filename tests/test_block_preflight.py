"""A block that cannot be laid out even on an empty board, at any rotation it
may take, is refused before the board is searched for it: a run spent a
quarter of an hour scanning for a block whose coil had nowhere to go.
Pure: synthetic boards."""
import time

from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint, pad
from placemat.board_geometry import Footprint
from placemat.values import Box, Face


def _chip():
    """Two pins 0.5 mm apart on nets SW1, SW2, both on the west end of a long
    body, so both face west: a satellite on each has one direction to go."""
    pads = (pad("U1", "u1", 1, "SW1", 18.0, 20.0, 0.25, 0.8), pad("U1", "u1", 2, "SW2", 18.5, 20.0, 0.25, 0.8),
            pad("U1", "u1", 3, "GND", 22.5, 20.0, 0.25, 0.8))
    body = Box(17.5, 19.0, 23.0, 21.0)
    return Footprint("U1", "u1", None, "U1", Location(20.25, 20), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)


def test_a_block_that_fits_nowhere_is_refused_before_the_search():
    fps = [_chip(),
           footprint("L1", 30, 30, w=6, h=6, inst="l1", nets=("SW1", "V1")),
           footprint("L2", 40, 40, w=6, h=6, inst="l2", nets=("SW2", "V2"))]
    b = Board(board_geometry(fps, width=80, height=80), edge_margin=0.5, keep_going=True)
    b.place(b.block(Part("u1"), satellites=[(Part("l1"), "SW1"), (Part("l2"), "SW2")]))
    t0 = time.time()
    plan = b.resolve()
    hits = [f for f in plan.findings if "u1" in f and "on its own" in f]
    assert hits, plan.findings
    assert time.time() - t0 < 10.0
