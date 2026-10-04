"""Which rotations a searched part is scanned at: all four unless the script
gave `rotation=` or `rotations=`, or `[place] rotations = "declared"`."""
import pytest

from placemat.layout import Board
from placemat.settings import Settings, SettingsError
from placemat.values import Cell, Centre, Edge, Face, Location, Near, OnEdge, Part
from tests.fixtures import board_geometry, footprint


def _pulled(settings=None):
    """R1's pad 1 (A) is west and pad 2 (B) east at rotation 0, but the pad
    on A sits east of it and the pad on B west: turned 180 it faces both."""
    fps = [footprint("J1", 10, 20, inst="west", nets=("X", "B")),     # pad 2, on B, at its east end
           footprint("J2", 30, 20, inst="east", nets=("A", "Y")),     # pad 1, on A, at its west end
           footprint("R1", 50, 50, inst="r", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0,
              **({"settings": settings} if settings else {}))
    b.place(Part("west"), at=Location(10, 20))
    b.place(Part("east"), at=Location(30, 20))
    return b


def test_a_searched_part_turns_to_face_what_it_connects_to():
    b = _pulled()
    b.place(Part("r"))
    assert b.resolve().placement("r").rotation == 180


@pytest.mark.parametrize("kw", [{"rotation": 0}, {"rotations": (0,)}])
def test_a_rotation_the_script_gave_is_kept(kw):
    b = _pulled()
    b.place(Part("r"), **kw)
    assert b.resolve().placement("r").rotation == 0


def test_declared_scans_only_the_declared_rotation():
    b = _pulled(Settings(place_rotations="declared"))
    b.place(Part("r"))
    assert b.resolve().placement("r").rotation == 0


def _slot(settings=None):
    """Two walls 3 mm apart: R1's 4.2 x 2.2 courtyard fits between them only on end."""
    fps = [footprint("W1", 10, 20, w=8, h=20, inst="w1", excess=0.0),
           footprint("W2", 21, 20, w=8, h=20, inst="w2", excess=0.0),
           footprint("R1", 50, 50, inst="r", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=1.0,
              **({"settings": settings} if settings else {}))
    b.place(Part("w1"), at=Location(10, 20))
    b.place(Part("w2"), at=Location(21, 20))
    return b


def test_a_part_that_fits_only_on_end_is_placed_on_end():
    b = _slot()
    b.place(Part("r"), at=Near(Location(15.5, 20), radius=1.0))
    p = b.resolve().placement("r")
    assert p is not None and p.rotation in (90, 270)


def test_with_declared_the_same_part_is_refused():
    b = _slot(Settings(place_rotations="declared"))
    b.place(Part("r"), at=Near(Location(15.5, 20), radius=1.0))
    assert b.resolve().placement("r") is None


def test_an_edge_part_and_a_line_part_keep_the_rotation_their_place_gives():
    fps = [footprint("J1", 50, 50, inst="j", nets=("A", "B")),
           footprint("R1", 50, 50, inst="r", nets=("A", "C")),
           footprint("J2", 5, 30, inst="far", nets=("C", "B"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("far"), at=Location(5, 30))
    b.place(Part("j"), at=OnEdge(Edge.NORTH))
    b.place(Part("r"), at=Centre(40, None, coordinates=True))
    plan = b.resolve()
    assert plan.placement("j").rotation == b.outward_rotation(Part("j"), Edge.NORTH)[0]
    assert plan.placement("r").rotation == 0


def test_a_cell_keeps_its_rotation():
    """A cell's sides are declared: turning it is the script's decision."""
    fps = [footprint("U2", 50, 50, cell="c", inst="c.u", nets=("A", "B")),
           footprint("J2", 30, 20, inst="east", nets=("A", "Y"))]
    b = Board(board_geometry(fps, cells=["c"], width=60, height=60), edge_margin=1.0)
    b.place(Part("east"), at=Location(30, 20))
    b.place(Cell("c"))
    assert b.resolve().placement("c").rotation == 0


def test_an_unknown_rotations_setting_is_a_settings_error(tmp_path):
    from placemat import settings
    (tmp_path / "placemat.toml").write_text('[place]\nrotations = "some"\n')
    with pytest.raises(SettingsError, match="all or declared"):
        settings.load(tmp_path)


def _east_facing_cell():
    """Cell c, its outward side declared east: U2 at its east end, U1 at its
    west end."""
    import dataclasses
    fps = [footprint("U1", 40, 30, cell="c", inst="c.u1", nets=("A", "B")),
           footprint("U2", 48, 30, cell="c", inst="c.u2", nets=("C", "D"))]
    g = board_geometry(fps, cells=["c"], width=80, height=80)
    cells = dict(g.cells)
    cells["c"] = dataclasses.replace(cells["c"], faces={"outward": Edge.EAST.value})
    return dataclasses.replace(g, cells=cells)


@pytest.mark.parametrize("face", [Face.FRONT, Face.BACK])
@pytest.mark.parametrize("edge", [Edge.NORTH, Edge.EAST, Edge.SOUTH, Edge.WEST])
def test_outward_rotation_turns_the_declared_side_to_the_edge_on_either_face(face, edge):
    """On the back a cell is mirrored before it turns, so its east side is
    its west until turned: the rotation for the back is the one that takes
    the mirrored side to the edge."""
    b = Board(_east_facing_cell(), edge_margin=1.0)
    turn, _ = b.outward_rotation(Cell("c"), edge, face=face)
    b.place(Cell("c"), at=Location(40, 40), rotation=turn, face=face)
    occ = b.resolve().occupancy
    east_end, west_end = occ.items["U2"].reference.location, occ.items["U1"].reference.location
    dx, dy = east_end.x - west_end.x, east_end.y - west_end.y
    want = {Edge.NORTH: (0, -1), Edge.SOUTH: (0, 1), Edge.EAST: (1, 0), Edge.WEST: (-1, 0)}[edge]
    assert (round(dx / 8.0), round(dy / 8.0)) == want, (face, edge, turn, dx, dy)


def test_a_cell_on_an_edge_on_the_back_turns_its_declared_side_outward():
    """place() turns a cell to the edge on its own: on the back, from the
    mirrored side."""
    b = Board(_east_facing_cell(), edge_margin=1.0)
    b.place(Cell("c"), at=OnEdge(Edge.NORTH), face=Face.BACK)
    occ = b.resolve().occupancy
    east_end, west_end = occ.items["U2"].reference.location, occ.items["U1"].reference.location
    assert east_end.y < west_end.y - 4.0, (east_end, west_end)
