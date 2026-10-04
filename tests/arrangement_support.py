"""Synthetic modules for the arrangement tests: a regulator-like part with a bypass west of it and a pull-up east. Pure: no KiCad
until `kicad_cell_board`."""
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Beside, Edge, Location, Part
from tests.fixtures import board_geometry, footprint


def parts():
    return [footprint("U1", 20, 15, w=6, h=4, nets=("VIN", "OUT"), inst="u1"),
            footprint("C1", 8, 15, w=3, h=1.6, nets=("VIN", "GND"), inst="c_in"),
            footprint("R1", 33, 25, w=3, h=1.6, nets=("OUT", "GND"), inst="r_pull"),
            footprint("R2", 45, 8, w=3, h=1.6, nets=("OUT", "GND"), inst="r_free")]


def module(settings=None) -> Board:
    """u1 on its place, c_in west of it and r_pull east: the module as its script says it (r_free is not placed)."""
    b = Board(board_geometry(parts(), width=60, height=40), edge_margin=1.0, settings=settings or Settings())
    b.place(Part("u1"), at=Location(20, 15), why="the regulator")
    b.place(Part("c_in"), at=Beside(Part("u1"), Edge.WEST), why="bypass at VIN")
    b.place(Part("r_pull"), at=Beside(Part("u1"), Edge.EAST), why="pull-up at OUT")
    return b
