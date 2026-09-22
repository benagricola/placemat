"""A module knows which of its sides faces the board edge, which is quiet
and which hands signals off. The module's script says so once; the fact
rides in the fragment and reaches every board that stamps the cell, so a
row or an edge placement turns the cell the right way by itself."""
import pytest

from placemat.copper import Text
from placemat.layout import Board
from placemat.values import OnEdge, Cell, Edge, Face, Location, Part
from tests.fixtures import board_geometry, footprint


def test_a_module_script_declares_its_faces_and_they_are_written_into_the_fragment():
    fps = [footprint("SW1", 10, 10, w=5, h=3, cell="ui", inst="ui.sw", nets=("A", "B"))]
    b = Board(board_geometry(fps, cells=["ui"], width=30, height=30))
    b.faces(outward=Edge.NORTH, quiet=Edge.SOUTH, handoff=Edge.EAST, why="the plungers are pressed from the north")
    plan = b.resolve()
    (t,) = [op for op in plan.copper if isinstance(op, Text)]
    assert t.text == "placemat faces outward=N quiet=S handoff=E" and t.layer == "User.Comments"
    assert t.box.top > plan.geometry.cell("ui").courtyard_box.bottom            # below the cell, not over it


def test_a_cell_whose_outward_side_is_local_north_turns_that_side_to_every_edge():
    fps = [footprint("SW1", 10, 4, w=5, h=3, cell="ui", inst="ui.sw", nets=("A", "B")),
           footprint("R1", 10, 8, w=2, h=1, cell="ui", inst="ui.r", nets=("B", "C"))]     # the switch is the cell's north
    g = board_geometry(fps, cells=["ui"], width=60, height=60, faces={"ui": {"outward": "N"}})
    assert g.cell("ui").faces["outward"] == "N"
    for edge, expect in ((Edge.NORTH, 0.0), (Edge.SOUTH, 180.0)):
        b = Board(g, edge_margin=1.0)
        b.place(Cell("ui"), at=OnEdge(edge))
        plan = b.resolve()
        assert plan.placement("ui").rotation == expect, edge
        sw, r = plan.box("ui.sw") if False else plan.occupancy.items["SW1"].body, plan.occupancy.items["R1"].body
        outer = sw.top if edge is Edge.NORTH else sw.bottom
        inner = r.top if edge is Edge.NORTH else r.bottom
        assert (outer < inner) if edge is Edge.NORTH else (outer > inner)      # the switch is the outboard member
    b = Board(g, edge_margin=1.0)
    b.place(Cell("ui"), at=OnEdge(Edge.EAST))
    plan = b.resolve()
    assert plan.occupancy.items["SW1"].body.right > plan.occupancy.items["R1"].body.right
    b = Board(g, edge_margin=1.0)
    b.place(Cell("ui"), at=OnEdge(Edge.WEST))
    plan = b.resolve()
    assert plan.occupancy.items["SW1"].body.left < plan.occupancy.items["R1"].body.left


def test_a_cell_with_no_declared_faces_uses_the_generic_rule_and_the_step_says_so():
    fps = [footprint("J1", 10, 4, w=5, h=3, cell="pd", inst="pd.j", nets=("A", "B"))]
    b = Board(board_geometry(fps, cells=["pd"], width=60, height=60), edge_margin=1.0)
    b.place(Cell("pd"), at=OnEdge(Edge.NORTH))
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


import math


def _turned(fp, degrees):
    """The same footprint with its pads actually rotated to match a generated
    rotation. `tests.fixtures.footprint` writes the rotation into the
    Footprint field but lays its pads out at rotation 0 whatever it is given,
    which is fine for tests that never ask what the rotation MEANS - and no
    use at all here, where the whole question is whether the transform undoes
    the generator's rotation correctly."""
    import dataclasses
    from placemat.values import Box
    r = math.radians(degrees)
    cos, sin = math.cos(r), math.sin(r)
    o = fp.location

    def turn(x, y):
        dx, dy = x - o.x, y - o.y
        return (o.x + dx * cos + dy * sin, o.y - dx * sin + dy * cos)

    pads = []
    for p in fp.pads:
        outs = tuple(tuple(turn(x, y) for x, y in poly) for poly in p.outlines)
        pads.append(dataclasses.replace(p, outlines=outs,
                                        box=Box.of_points([q for po in outs for q in po])))
    return dataclasses.replace(fp, rotation=float(degrees), pads=tuple(pads))


def _pad_after_flip(generated_rotation, target_rotation):
    """Where the occupancy model puts an asymmetric pad when the part is
    flipped to the back, with the part's origin left where it was."""
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.values import Face, Location
    from tests.fixtures import board_geometry, footprint
    fp = _turned(footprint("U1", 20.0, 20.0, w=6, h=2, inst="u1", nets=("A", "B")),
                 generated_rotation)
    occ = Occupancy(board_geometry([fp], width=60, height=60), edge_margin=0.0)
    occ.commit(fp, Placement(Location(20.0, 20.0), target_rotation, Face.BACK))
    return occ.pad_location("U1", "1")


def test_a_flip_does_not_depend_on_the_rotation_the_generator_left():
    """The same declaration must mean the same physical orientation whatever
    the generator happened to do, or a script cannot say what it means."""
    at_zero = _pad_after_flip(0.0, 0.0)
    for r in (90.0, 180.0, 270.0):
        moved = _pad_after_flip(r, 0.0)
        assert abs(moved.x - at_zero.x) < 1e-6 and abs(moved.y - at_zero.y) < 1e-6, r


def test_a_flip_mirrors_about_the_vertical_axis():
    """KiCad's F key, and what a cell already does. Pad 1 is on the west end
    at rotation 0, so after a left-right mirror about the origin it is east."""
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.values import Face, Location
    from tests.fixtures import board_geometry, footprint
    fp = footprint("U1", 20.0, 20.0, w=6, h=2, inst="u1", nets=("A", "B"))
    occ = Occupancy(board_geometry([fp], width=60, height=60), edge_margin=0.0)
    front = occ.pad_location("U1", "1")
    assert front.x < 20.0                                   # west of the origin
    occ.commit(fp, Placement(Location(20.0, 20.0), 0.0, Face.BACK))
    back = occ.pad_location("U1", "1")
    assert back.x > 20.0                                    # mirrored to the east
    assert abs(back.y - front.y) < 1e-6                     # and not in y


def test_an_unflipped_placement_is_unchanged_at_every_generated_rotation():
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.values import Face, Location
    from tests.fixtures import board_geometry, footprint
    for r in (0.0, 90.0, 180.0, 270.0):
        fp = _turned(footprint("U1", 20.0, 20.0, w=6, h=2, inst="u1", nets=("A", "B")), r)
        occ = Occupancy(board_geometry([fp], width=60, height=60), edge_margin=0.0)
        before = occ.pad_location("U1", "1")
        occ.commit(fp, Placement(Location(20.0, 20.0), r, Face.FRONT))    # same place, same face
        after = occ.pad_location("U1", "1")
        assert abs(after.x - before.x) < 1e-6 and abs(after.y - before.y) < 1e-6, r


def test_the_docs_say_what_a_flip_means():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "vertical axis" in api and "rotation + 180" in api
    skill = Path("skills/placemat/SKILL.md").read_text()
    assert "vertical axis" in skill
    assert "_transform" in skill                      # the detection grep
    mig = Path("skills/placemat/references/migration.md").read_text()
    assert "0.8" in mig and "flip" in mig.lower()
