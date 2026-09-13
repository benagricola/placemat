"""Slice 3, KiCad side: a resolved plan applied through pcbnew moves parts and
cells exactly, draws the outline, and writes the same bytes twice."""
import shutil

from placemat.layout import Board
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.values import Cell, Location, Part
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
    b = Board(before, edge_margin=0.0)
    b.size(width=before.outline_box.width, height=before.outline_box.height, chamfer=2.0)
    target = pd0.box.center.offset(0, 5.0)
    b.place(Cell("power_drop0"), center=target, rotation=0)
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
    b = Board(before, edge_margin=0.0)
    b.place(Cell("power_drop0"), center=pd0.box.center, rotation=90)
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
    b = Board(before, edge_margin=0.0)
    b.size(width=before.outline_box.width, height=before.outline_box.height, chamfer=2.0)
    b.place(Part("trunk_pwr"), at=Location(30.0, 12.0), rotation=180)
    plan = b.resolve()
    apply_plan(pcb, plan)
    first = pcb.read_bytes()
    plan2 = Board(read_board(pcb), edge_margin=0.0)
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
