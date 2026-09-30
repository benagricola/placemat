"""Slice 3, KiCad side: a resolved plan applied through pcbnew moves parts and
cells exactly, draws the outline, and writes the same bytes twice."""
import pytest

pytest.importorskip("pcbnew")        # the module imports placemat.kicad, which needs KiCad's pcbnew

import shutil

from placemat.layout import Board
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.values import Centre, Cell, Location, Part
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]


def _copy(breakout_pcb, tmp_path):
    dst = tmp_path / "layout.kicad_pcb"
    shutil.copy(breakout_pcb, dst)
    pro = breakout_pcb.with_suffix(".kicad_pro")
    if pro.exists():
        shutil.copy(pro, tmp_path / "layout.kicad_pro")
    return dst


def test_moving_a_cell_and_a_part_lands_them_exactly(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    pd0 = before.cell("power_drop0")
    b = Board(before, edge_margin=0.0, keep_going=True)     # re-placing cells on a board that already carries their copper
    b.size(width=before.outline_box.width, height=before.outline_box.height, chamfer=2.0)
    target = pd0.box.center.offset(0, 5.0)
    b.place(Cell("power_drop0"), at=Centre(target.x, target.y), rotation=0)
    b.place(Part("trunk_pwr"), at=Location(30.0, 12.0), rotation=180)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    moved = after.cell("power_drop0")
    assert abs(moved.box.center.y - target.y) < 1e-5 and abs(moved.box.center.x - target.x) < 1e-5
    assert abs(moved.box.width - pd0.box.width) < 1e-5 and abs(moved.box.height - pd0.box.height) < 1e-5
    # the cell's own copper travelled with it
    assert abs(moved.copper_box.center.y - (pd0.copper_box.center.y + 5.0)) < 1e-5
    cn1 = after.footprint("trunk_pwr")
    assert cn1.location == Location(30.0, 12.0) and cn1.rotation == 180


def test_rotating_a_cell_turns_its_members_and_copper(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    pd0 = before.cell("power_drop0")
    b = Board(before, edge_margin=0.0, keep_going=True)     # re-placing cells on a board that already carries their copper
    b.place(Cell("power_drop0"), at=Centre(pd0.box.center.x, pd0.box.center.y), rotation=90)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    moved = after.cell("power_drop0")
    assert abs(moved.box.width - pd0.box.height) < 1e-5 and abs(moved.box.height - pd0.box.width) < 1e-5
    conn_before = pd0.member("conn")
    conn_after = after.cell("power_drop0").member("conn")
    assert (conn_after.rotation - conn_before.rotation) % 360 == 90


def test_writing_the_same_plan_twice_is_byte_identical(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    b = Board(before, edge_margin=0.0, keep_going=True)     # re-placing cells on a board that already carries their copper
    b.size(width=before.outline_box.width, height=before.outline_box.height, chamfer=2.0)
    b.place(Part("trunk_pwr"), at=Location(30.0, 12.0), rotation=180)
    plan = b.resolve()
    apply_plan(pcb, plan)
    first = pcb.read_bytes()
    plan2 = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    plan2.size(width=before.outline_box.width, height=before.outline_box.height, chamfer=2.0)
    plan2.place(Part("trunk_pwr"), at=Location(30.0, 12.0), rotation=180)
    apply_plan(pcb, plan2.resolve())
    assert pcb.read_bytes() == first


def test_writing_leaves_only_the_boards_own_project_file(breakout_pcb, tmp_path):
    """pcbnew writes a project beside whatever name it saves; saving through a
    temporary name left a layout.kicad_pcb.kicad_pro beside every board."""
    pcb = _copy(breakout_pcb, tmp_path)
    b = Board(read_board(pcb), edge_margin=0.0)
    apply_plan(pcb, b.resolve())
    stray = sorted(p.name for p in tmp_path.iterdir() if p.suffix in (".kicad_pro", ".kicad_prl") and p.stem != "layout")
    assert stray == []


def _add_rule_area(pcb, name, group_name=None):
    """Put a rule area on a board file, optionally inside a group, the way
    `pcb layout` stamps a module fragment's own."""
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb))
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetLayerSet(pcbnew.LSET.AllCuMask(board.GetCopperLayerCount()))
    # every flag explicitly: a fresh ZONE does not default them all to false,
    # so a helper that sets only one is not saying what it means
    z.SetDoNotAllowFootprints(True)
    z.SetDoNotAllowZoneFills(False)
    z.SetDoNotAllowTracks(False)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowPads(False)
    o = z.Outline()
    o.NewOutline()
    for x, y in ((10.0, 10.0), (14.0, 10.0), (14.0, 14.0), (10.0, 14.0)):
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    z.SetZoneName(name)
    board.Add(z)
    if group_name:
        g = pcbnew.PCB_GROUP(board)
        g.SetName(group_name)
        g.AddItem(z)
        board.Add(g)
    board.Save(str(pcb))


def test_a_rule_area_in_a_group_survives_a_write(breakout_pcb, tmp_path):
    """A stamped cell's regions are group members. placemat did not write them
    and must not destroy them."""
    pcb = _copy(breakout_pcb, tmp_path)
    _add_rule_area(pcb, "keepout antenna_1", group_name="ant_rf")
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    apply_plan(pcb, b.resolve())
    assert "keepout antenna_1" in [r.name for r in read_board(pcb).rule_areas]


def test_a_group_less_rule_area_is_replaced_on_a_write(breakout_pcb, tmp_path):
    """placemat's own, from a previous run: deleted and rewritten, so a
    declaration removed from the script does not leak."""
    pcb = _copy(breakout_pcb, tmp_path)
    _add_rule_area(pcb, "keepout stale")
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    apply_plan(pcb, b.resolve())
    assert "keepout stale" not in [r.name for r in read_board(pcb).rule_areas]


def test_reading_a_rule_area_gives_its_name_cell_layers_and_excludes(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    _add_rule_area(pcb, "keepout antenna_1", group_name="ant_rf")
    (ra,) = [r for r in read_board(pcb).rule_areas if r.name == "keepout antenna_1"]
    assert ra.cell == "ant_rf"
    assert ra.excludes == frozenset(["parts"])
    assert len(ra.layers) >= 2 and len(ra.polygon) == 4


def test_the_keepout_drawings_group_does_not_read_back_as_a_cell(breakout_pcb, tmp_path):
    """placemat's own `keepout drawings` group holds a shape and a text, no
    footprints: it is not a stamped cell, and must not become one that
    `placemat measure` (or anything else iterating snap.cells) then trips
    over with no box."""
    from placemat.cutouts import Circle
    from placemat.values import Location as Loc
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    b = Board(before, edge_margin=0.0, keep_going=True)
    b.keepout(Circle(1.0), "probe", at=Loc(12.0, 12.0), excludes=("parts",), max_height=1.0,
              why="a height band for this probe")
    apply_plan(pcb, b.resolve())
    after = read_board(pcb)
    assert "keepout drawings" not in after.cells
    # every remaining cell still answers a real box, the way `placemat measure` reads it
    for name in after.cells:
        c = after.cell(name)
        assert c.box is not None, name


def test_a_second_write_does_not_pull_unrelated_items_into_the_keepout_drawings_group(breakout_pcb, tmp_path):
    """The board's UUID generator is seeded the same way on every write
    (`seed_uuids`), for a reproducible file. A SECOND write, reading back a
    board this project already wrote once, must not let its own freshly
    seeded items land on a UUID an existing, unrelated item (a stamped
    cell's track) already carries: that made the group's own membership
    (keyed by UUID) pick up items nobody drew for it."""
    import pcbnew
    from placemat.cutouts import Circle
    from placemat.values import Location as Loc
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    b = Board(before, edge_margin=0.0, keep_going=True)
    b.keepout(Circle(1.0), "probe", at=Loc(12.0, 12.0), excludes=("parts",), max_height=1.0, why="probe")
    apply_plan(pcb, b.resolve())
    # a second, DIFFERENT script (a different keepout name, so it does not clash with the
    # rule area the first write left on the board) against the board the first write produced -
    # an ordinary "read what placemat last wrote and lay out again" cycle.
    before2 = read_board(pcb)
    b2 = Board(before2, edge_margin=0.0, keep_going=True)
    b2.keepout(Circle(1.0), "probe0", at=Loc(18.0, 12.0), excludes=("parts",), max_height=1.0, why="probe0")
    b2.keepout(Circle(1.0), "probe2", at=Loc(16.0, 12.0), excludes=("parts",), max_height=1.0, why="probe2")
    apply_plan(pcb, b2.resolve())
    board = pcbnew.LoadBoard(str(pcb))
    (group,) = [g for g in board.Groups() if g.GetName() == "keepout drawings"]
    kinds = sorted(type(it).__name__ for it in group.GetItems())
    assert kinds == ["PCB_SHAPE", "PCB_SHAPE", "PCB_TEXT", "PCB_TEXT"], kinds
