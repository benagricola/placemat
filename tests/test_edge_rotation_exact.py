"""A part turned to face a curved edge gets its rotation as a clean number:
a trace of float left over (359.99999999999994 for 0) put a receptacle's
pads off the board for the router. Pure."""
from placemat import Arc
from placemat.layout import Board
from placemat.values import Along, Edge, Location, OnEdge, Part
from tests.fixtures import board_geometry, footprint


def test_a_part_facing_an_arc_tip_is_turned_to_a_clean_angle():
    path = [Location(0, 0), Location(20, 0), Location(20, 30), Arc(to=Location(0, 30), via=Location(10, 36)),
            Location(0, 0)]
    b = Board(board_geometry([footprint("J1", 7, 7, w=4, h=2, inst="j1")], width=20, height=40), edge_margin=0.5)
    b.outline(path)
    b.place(Part("j1"), at=OnEdge(b.edge(facing=Edge.SOUTH, outermost=True), along=Along.MID))
    assert b.resolve().placement("j1").rotation == 0.0
