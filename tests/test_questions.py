"""What a script may ask about the generated board's parts before placing
anything: sizes, pads, and a connector's pin pitch, so no number that the
footprint already knows is typed into a script."""
import pytest

from placemat.layout import Board
from placemat.values import Part
from placemat.board_geometry import Footprint
from tests.fixtures import board_geometry, footprint, pad
from placemat.values import Box, Face, Location


def connector(ref, inst, pitch, n=4):
    pads = tuple(pad(ref, inst, i + 1, "N%d" % i, 10 + i * pitch, 10, 1.5, 1.5, True) for i in range(n))
    body = Box(8.0, 5.0, 10 + (n - 1) * pitch + 2, 15.0)
    return Footprint(ref, inst, None, ref, Location(10, 10), 0.0, Face.FRONT, body, body, body, pads)


def test_a_connectors_pin_pitch_is_read_from_its_pads():
    b = Board(board_geometry([connector("J1", "j1", 5.08), footprint("R1", 30, 30, inst="r1")]), edge_margin=1.0)
    assert b.pitch(Part("j1")) == pytest.approx(5.08)


def test_a_two_pad_part_has_a_pitch_too_and_one_pad_has_none():
    b = Board(board_geometry([footprint("R1", 30, 30, w=4, inst="r1")]), edge_margin=1.0)
    assert b.pitch(Part("r1")) == pytest.approx(2.8)      # pads 0.6 in from each end of a 4 mm body
    single = Footprint("M1", "m1", None, "M1", Location(5, 5), 0.0, Face.FRONT, Box(4, 4, 6, 6), Box(4, 4, 6, 6), Box(4, 4, 6, 6),
                       (pad("M1", "m1", 1, "GND", 5, 5, 1, 1, True),))
    b = Board(board_geometry([single]), edge_margin=1.0)
    with pytest.raises(ValueError):
        b.pitch(Part("m1"))


def test_a_pad_answers_its_size():
    b = Board(board_geometry([connector("J1", "j1", 5.08)]), edge_margin=1.0)
    p = b.pad(Part("j1"), 1)
    assert p.box.width == pytest.approx(1.5) and p.through
