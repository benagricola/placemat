"""A module knows which of its sides faces the board edge, which is quiet
and which hands signals off. The module's script says so once; the fact
rides in the fragment and reaches every board that stamps the cell, so a
row or an edge placement turns the cell the right way by itself."""
import pytest

from placemat.copper import Text
from placemat.layout import Board
from placemat.values import Cell, Edge, Face, Location, Part
from tests.fixtures import board_geometry, footprint


def test_a_module_script_declares_its_faces_and_they_are_written_into_the_fragment():
    fps = [footprint("SW1", 10, 10, w=5, h=3, cell="ui", inst="ui.sw", nets=("A", "B"))]
    b = Board(board_geometry(fps, cells=["ui"], width=30, height=30))
    b.faces(outward=Edge.NORTH, quiet=Edge.SOUTH, handoff=Edge.EAST, why="the plungers are pressed from the north")
    plan = b.resolve()
    (t,) = [op for op in plan.copper if isinstance(op, Text)]
    assert t.text == "placemat faces outward=N quiet=S handoff=E" and t.layer == "Cmts.User"


def test_a_cell_whose_outward_side_is_local_north_turns_that_side_to_every_edge():
    fps = [footprint("SW1", 10, 4, w=5, h=3, cell="ui", inst="ui.sw", nets=("A", "B")),
           footprint("R1", 10, 8, w=2, h=1, cell="ui", inst="ui.r", nets=("B", "C"))]     # the switch is the cell's north
    g = board_geometry(fps, cells=["ui"], width=60, height=60, faces={"ui": {"outward": "N"}})
    assert g.cell("ui").faces["outward"] == "N"
    for edge, expect in ((Edge.NORTH, 0.0), (Edge.SOUTH, 180.0)):
        b = Board(g, edge_margin=1.0)
        b.place(Cell("ui"), edge=edge)
        plan = b.resolve()
        assert plan.placement("ui").rotation == expect, edge
        sw, r = plan.box("ui.sw") if False else plan.occupancy.items["SW1"].body, plan.occupancy.items["R1"].body
        outer = sw.top if edge is Edge.NORTH else sw.bottom
        inner = r.top if edge is Edge.NORTH else r.bottom
        assert (outer < inner) if edge is Edge.NORTH else (outer > inner)      # the switch is the outboard member
    b = Board(g, edge_margin=1.0)
    b.place(Cell("ui"), edge=Edge.EAST)
    plan = b.resolve()
    assert plan.occupancy.items["SW1"].body.right > plan.occupancy.items["R1"].body.right
    b = Board(g, edge_margin=1.0)
    b.place(Cell("ui"), edge=Edge.WEST)
    plan = b.resolve()
    assert plan.occupancy.items["SW1"].body.left < plan.occupancy.items["R1"].body.left


def test_a_cell_with_no_declared_faces_uses_the_generic_rule_and_the_step_says_so():
    fps = [footprint("J1", 10, 4, w=5, h=3, cell="pd", inst="pd.j", nets=("A", "B"))]
    b = Board(board_geometry(fps, cells=["pd"], width=60, height=60), edge_margin=1.0)
    b.place(Cell("pd"), edge=Edge.NORTH)
    plan = b.resolve()
    assert plan.placement("pd").rotation == 180.0
    assert "no faces declared" in plan.step("pd").note


def test_a_row_turns_each_cell_by_its_own_faces():
    fps = [footprint("SW1", 10, 4, w=5, h=3, cell="ui", inst="ui.sw", nets=("A", "B")),
           footprint("J1", 30, 4, w=5, h=3, cell="pd", inst="pd.j", nets=("C", "D"))]
    g = board_geometry(fps, cells=["ui", "pd"], width=60, height=60, faces={"ui": {"outward": "N"}})
    b = Board(g, edge_margin=1.0)
    b.row([Cell("ui"), Cell("pd")], Edge.NORTH, gap=2.0, align="center")
    plan = b.resolve()
    assert plan.placement("ui").rotation == 0.0 and plan.placement("pd").rotation == 180.0
