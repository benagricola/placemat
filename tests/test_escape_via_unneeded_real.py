"""A real module (fixtures/fairing/lane_vias, the run board of a module whose chip fans its pin rows out in escapes, nets
renamed after the chip pin each is on, and the module's fit frame drawn on Edge.Cuts). Five vias stand on lanes there: the
lanes of pins 44 and 45 end in vias through `vias=` on the west fan, the pair on pins 25 and 26 ends in vias at its lanes'
ends, and pin 50's lane goes on as a track into a `board.via`. Each lane reaches the frame's edge on F.Cu without its
via. The chip's exposed pad is filled with ground vias and its supply pins drop into planes: none of those is a lane's."""
import dataclasses
import pathlib

import pytest

from tests.conftest import needs_kicad

pytestmark = needs_kicad

BOARD = pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/lane_vias/layout.kicad_pcb"
FRAME = (-9.7695, -5.1825, 6.287719, 9.217501)
PLANES = frozenset(("GND", "VDD"))


@pytest.fixture(scope="module")
def found():
    from placemat.escapes import Escapes
    from placemat.kicad.read import read_board
    from placemat.occupancy import Occupancy
    from placemat.settings import Settings
    occ = Occupancy(read_board(str(BOARD)), 1.0, settings=Settings())
    occ.quiet_nets = PLANES
    pins = sorted({(s.owner, s.label) for s in occ.items["U1"].shapes if s.kind == "pad" and s.owner == "U1"})
    return occ, Escapes(occ, mirror=False).vias_unneeded(pins, occ.board_box)


def test_the_frame_is_the_modules_fit_frame(found):
    occ, _ = found
    b = occ.board_box
    assert (b.left, b.top, b.right, b.bottom) == pytest.approx(FRAME, abs=0.026)      # the line's half width round it


def test_the_five_vias_on_lanes_with_a_way_out_are_found_and_no_other(found):
    _, out = found
    assert sorted((ref, number, net) for ref, number, net, _, _ in out) == [
        ("U1", "25", "P25"), ("U1", "26", "P26"), ("U1", "44", "P44"), ("U1", "45", "P45"), ("U1", "50", "P50")]


def test_each_finding_names_its_via_on_the_component_face(found):
    from placemat.values import CopperLayer
    _, out = found
    at = {number: sorted((round(v.circle[0], 2), round(v.circle[1], 2)) for v in vias)
          for _, number, _, _, vias in out}
    assert at == {"25": [(5.47, -2.7)], "26": [(4.84, -2.7)], "44": [(-4.43, -2.7)], "45": [(-5.02, -2.7)],
                  "50": [(-7.45, -2.24)]}
    assert all(layers == frozenset([CopperLayer.F]) for _, _, _, layers, _ in out)


def test_a_wall_of_another_nets_copper_round_the_chip_keeps_the_vias():
    """The same board with a ring of copper of another net round the chip, inside the frame: every lane is walled in
    within the module, so each via is needed."""
    from placemat.escapes import Escapes
    from placemat.kicad.read import read_board
    from placemat.occupancy import Occupancy, Shape
    from placemat.settings import Settings
    from placemat.values import Box, CopperLayer, Face
    occ = Occupancy(read_board(str(BOARD)), 1.0, settings=Settings())
    occ.quiet_nets = PLANES
    left, top, right, bottom = FRAME
    ring = []
    for box in (Box(left + 0.1, top + 0.1, right - 0.1, top + 0.3), Box(left + 0.1, bottom - 0.3, right - 0.1, bottom - 0.1),
                Box(left + 0.1, top + 0.1, left + 0.3, bottom - 0.1), Box(right - 0.3, top + 0.1, right - 0.1, bottom - 0.1)):
        poly = ((box.left, box.top), (box.right, box.top), (box.right, box.bottom), (box.left, box.bottom))
        ring.append(Shape("", "copper", frozenset([Face.FRONT]), frozenset([CopperLayer.F]), "WALL", poly, box))
    occ.add_copper(ring)
    pins = [("U1", n) for n in ("25", "26", "44", "45", "50")]
    assert Escapes(occ, mirror=False).vias_unneeded(pins, occ.board_box) == []
