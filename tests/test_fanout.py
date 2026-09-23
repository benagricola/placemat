"""A fanout band: the strip outside a part's pad rows that only its own
satellites and the parts linked SHORT to its pins may enter."""
import pytest

from placemat.layout import Board
from placemat.values import Edge, Face, LinkWeight, Location, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board():
    # U1: 10 wide, pads at its west and east ends (pad 1 x 5.5..6.5, pad 2 x 13.5..14.5 when at 10,30)
    fps = [footprint("U1", 10, 30, w=10, h=4, inst="mcu", nets=("GPIO", "VDD")),
           footprint("R1", 60, 60, w=2, h=1, inst="pull", nets=("GPIO", "X")),
           footprint("C1", 60, 65, w=2, h=1, inst="bypass", nets=("VDD", "GND")),
           footprint("R2", 60, 70, w=2, h=1, inst="far", nets=("GPIO", "Z"), face=Face.BACK)]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)


def _band_edges(plan):
    return [r for r in plan.occupancy.reservations if r.why.startswith("fanout")]


def test_a_part_linked_to_a_pin_lands_across_the_band():
    b = _board()
    b.place(Part("mcu"), at=Location(30, 30))
    b.fanout(Part("mcu"), depth=2.0, why="the GPIO escape")
    b.link(PadRef(Part("pull"), 1), PadRef(Part("mcu"), 1))
    b.place(Part("pull"))
    plan = b.resolve()
    (west,) = [r for r in _band_edges(plan) if "west" in r.why]
    assert not plan.box("pull").overlaps(west.box)
    assert "fanout of mcu (west side)" in plan.step("pull").note     # it was turned away from its seed


def test_a_part_linked_short_may_sit_in_the_band():
    b = _board()
    b.place(Part("mcu"), at=Location(30, 30))
    b.fanout(Part("mcu"), depth=2.0)
    b.link(PadRef(Part("bypass"), 1), PadRef(Part("mcu"), 2), weight=LinkWeight.SHORT)
    b.place(Part("bypass"))
    plan = b.resolve()
    east = plan.occupancy.pad_location("U1", "2").x + 0.5
    assert east <= plan.box("bypass").center.x <= east + 2.0 + 1.0


def test_the_band_is_on_the_part_s_face_only_and_sides_limit_it():
    b = _board()
    b.place(Part("mcu"), at=Location(30, 30))
    b.fanout(Part("mcu"), depth=2.0, sides=[Edge.WEST])
    plan = b.resolve()
    (band,) = _band_edges(plan)
    assert band.layer is not None and band.layer.face is Face.FRONT
    assert band.box.right <= plan.occupancy.pad_location("U1", "1").x - 0.5 + 1e-6


def test_a_fanout_names_a_part_placed_by_the_script():
    b = _board()
    with pytest.raises(KeyError):
        b.fanout(Part("nothing"), depth=2.0)
