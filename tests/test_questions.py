"""What a script may ask about the generated board's parts before placing
anything: sizes, pads, and a connector's pin pitch, so no number that the
footprint already knows is typed into a script."""
import pytest

from placemat.layout import Board
from placemat.values import Location, Part
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


def test_a_pad_number_that_is_not_all_digits_is_still_a_pad_number():
    """Some footprints number a doubled leg 1': PadRef(part, "1'") means
    that pad, not a net called 1'. A string names a net first; when no pad
    of the part is on a net of that name, it is tried as a pad number."""
    from placemat.board_geometry import Footprint
    from placemat.values import Box, Face
    from tests.fixtures import pad
    pads = (pad("SW2", "sw2", "1", "A", 9.4, 10), pad("SW2", "sw2", "1'", "A", 10.6, 10), pad("SW2", "sw2", "2", "B", 12, 10))
    body = Box(8, 9, 13, 11)
    sw = Footprint("SW2", "sw2", None, "SW2", Location(10.5, 10), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)
    b = Board(board_geometry([sw], width=60, height=60), edge_margin=1.0)
    assert b.pad(Part("sw2"), "1'").location == Location(10.6, 10)
    assert b.pad(Part("sw2"), "A").number == "1"                      # a net name still wins
    with pytest.raises(TypeError):
        b.pad(Part("sw2"), "9")                                       # an all-digit string is neither: pass an int
    with pytest.raises(KeyError):
        b.pad(Part("sw2"), "zz")


def _split_row():
    """Four pins at 0.5 mm; pin 1 is drawn as two lands 0.25 mm apart, as an
    L-shaped corner pad is."""
    pads = (pad("U1", "u1", 1, "N0", 10.0, 10.0, 0.2, 0.6), pad("U1", "u1", 1, "N0", 10.0, 9.75, 0.2, 0.2)) + tuple(
        pad("U1", "u1", i + 1, "N%d" % i, 10.0 + i * 0.5, 10.0, 0.25, 0.6) for i in range(1, 4))
    body = Box(9.0, 9.0, 12.0, 11.0)
    return Footprint("U1", "u1", None, "U1", Location(10.5, 10), 0.0, Face.FRONT, body, body, body, pads)


def test_a_pin_drawn_as_two_lands_does_not_set_the_pitch():
    b = Board(board_geometry([_split_row()]), edge_margin=1.0)
    assert b.pitch(Part("u1")) == pytest.approx(0.5)


def test_the_pitch_between_two_named_pins():
    b = Board(board_geometry([_split_row()]), edge_margin=1.0)
    assert b.pitch(Part("u1"), pins=(2, 4)) == pytest.approx(1.0)


def test_the_envelope_is_what_the_placer_keeps_under_the_setting():
    import dataclasses
    from placemat.settings import Settings
    fp = footprint("R1", 30, 30, w=2, h=1, inst="r1", silk_boxes=[(28.8, 29.2, 31.2, 30.8)], excess=0.1)
    court = Board(board_geometry([fp]), edge_margin=1.0).envelope(Part("r1"))
    phys = Board(board_geometry([fp]), edge_margin=1.0,
                 settings=dataclasses.replace(Settings(), place_envelope="physical")).envelope(Part("r1"))
    assert (court.width, court.height) == pytest.approx((2.2, 1.2))       # the courtyard: the body plus its excess
    assert (phys.width, phys.height) == pytest.approx((2.4, 1.6))         # the silk, which reaches past it
    turned = Board(board_geometry([fp]), edge_margin=1.0,
                   settings=dataclasses.replace(Settings(), place_envelope="physical")).envelope(Part("r1"), rotation=90)
    assert (turned.width, turned.height) == pytest.approx((1.6, 2.4))


def test_the_board_lists_its_parts_and_those_on_a_net():
    fps = [footprint("U1", 10, 10, inst="u1", nets=("V3V3", "GND")),
           footprint("C1", 20, 10, inst="c1", nets=("V3V3", "GND")),
           footprint("R1", 30, 10, inst="r1", nets=("SIG", "V3V3")),
           footprint("J1", 40, 10, inst="j1", nets=("SIG", "OUT"))]
    b = Board(board_geometry(fps), edge_margin=1.0)
    assert [p.inst for p in b.parts()] == ["c1", "j1", "r1", "u1"]
    assert [p.inst for p in b.parts(net="GND")] == ["c1", "u1"]
    assert [p.inst for p in b.parts(net="V3V3")] == ["c1", "r1", "u1"]
