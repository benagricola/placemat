"""A flip mirrors an item's inner copper through the stack (In2 and In3 swap
on six layers), as KiCad flips it. On a stackup that is not symmetric that
lands copper on a layer of another role - a power pour on a signal or
another net's plane layer - so such a flip is refused, naming the copper and
both layers. Like on like (In1 GND and In4 GND) flips."""
import dataclasses

import pytest

from placemat.board_geometry import CopperItem
from placemat.layout import Board
from placemat.values import Box, Cell, CopperLayer, Face, Location, Net
from tests.fixtures import board_geometry, footprint, rect

F, B = CopperLayer.F, CopperLayer.B
IN1, IN2, IN3, IN4 = CopperLayer.IN1, CopperLayer.IN2, CopperLayer.IN3, CopperLayer.IN4
SIX = (F, IN1, IN2, IN3, IN4, B)
TYPES = {F: "mixed", IN1: "power", IN2: "power", IN3: "mixed", IN4: "power", B: "mixed"}


def _board(layer, net, types=TYPES):
    poly = rect(10, 10, 2, 2)
    pour = CopperItem("poly", net, frozenset({layer}), (poly,), Box.of_points(poly), "k")
    fp = footprint("U1", 10, 13, inst="k.u1", cell="k", nets=(net, "A"))
    g = board_geometry([fp], cells=("k",), copper=[pour], width=40, height=40, extra_nets=("GND", "V3V3", "VBIKE"))
    g = dataclasses.replace(g, layers=SIX, layer_types=dict(types))
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.plane(Net("GND"), layers=(IN1, IN4))
    b.plane(Net("V3V3"), layers=(IN3,))
    return b


def test_a_flip_that_lands_a_power_pour_on_another_nets_plane_layer_is_refused():
    b = _board(IN2, "VBIKE")
    b.place(Cell("k"), at=Location(20, 20), face=Face.BACK)
    with pytest.raises(ValueError, match=r"In2\.Cu.*In3\.Cu"):
        b.resolve()


def test_a_flip_of_like_onto_like_is_placed():
    b = _board(IN1, "GND")
    b.place(Cell("k"), at=Location(20, 20), face=Face.BACK)
    b.resolve()


def test_a_flip_onto_a_layer_of_another_type_is_refused_with_no_planes():
    b = _board(IN2, "VBIKE", types={**TYPES, IN3: "signal"})
    b.place(Cell("k"), at=Location(20, 20), face=Face.BACK)
    with pytest.raises(ValueError, match="power.*signal|signal.*power"):
        b.resolve()


def test_the_same_cell_on_its_own_face_is_not_a_flip():
    b = _board(IN2, "VBIKE")
    b.place(Cell("k"), at=Location(20, 20), face=Face.FRONT)
    b.resolve()
