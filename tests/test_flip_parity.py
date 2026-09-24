"""The planner and the writer must agree about a back-face part.

The occupancy model decides legality, clearance and copper endpoints from one
answer and KiCad gets another, so a disagreement here is not a cosmetic one:
every via-in-pad, every Pin() placement and every clearance the model judged
inherits it. These tests write a real board and read it back, because the only
authority on what KiCad did is KiCad."""
import pytest

pytest.importorskip("pcbnew")        # the module imports placemat.kicad, which needs KiCad's pcbnew

import shutil

import pytest

from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.values import Cell, Centre, Face, Location, Part
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]

ROTATIONS = (0.0, 90.0, 180.0, 270.0)


def _copy(src, tmp_path):
    dst = tmp_path / "layout.kicad_pcb"
    shutil.copy(src, dst)
    pro = src.with_suffix(".kicad_pro")
    if pro.exists():
        shutil.copy(pro, tmp_path / "layout.kicad_pro")
    return dst


def _by_generated_rotation(geometry):
    """One multi-pad front footprint at each generated rotation. On the
    committed Breakout these are U7 at 0, U2 at 90, U8 at 180 and U5 at 270."""
    out = {}
    for fp in geometry.footprints:
        if len(fp.pads) >= 3 and fp.face is Face.FRONT:
            out.setdefault(fp.rotation % 360, fp)
    return out


def _parity(pcb, inst, rotation, face):
    """Place one part, write, read back, and return the worst disagreement in
    mm between what the occupancy model planned and what the file holds."""
    before = read_board(pcb)
    fp = before.footprint(inst)
    b = Board(before, edge_margin=0.0, keep_going=True)
    b.place(Part(inst), at=Location(fp.location.x, fp.location.y), rotation=rotation, face=face)
    plan = b.resolve()
    planned = {p.number: plan.occupancy.pad_location(fp.ref, p.number) for p in fp.pads}
    apply_plan(pcb, plan)
    after = read_board(pcb).footprint(inst)
    return max(abs(p.box.center.x - planned[p.number].x) + abs(p.box.center.y - planned[p.number].y)
               for p in after.pads)


@pytest.mark.parametrize("generated", ROTATIONS)
@pytest.mark.parametrize("target", ROTATIONS)
def test_a_back_face_part_lands_where_the_planner_said(breakout_pcb, tmp_path, generated, target):
    pcb = _copy(breakout_pcb, tmp_path)
    cands = _by_generated_rotation(read_board(pcb))
    if generated not in cands:
        pytest.skip("the Breakout has no multi-pad front part at rotation %g" % generated)
    worst = _parity(pcb, cands[generated].inst, target, Face.BACK)
    assert worst < 1e-5, "generated %g, target %g: worst pad error %.6f mm" % (generated, target, worst)


@pytest.mark.parametrize("generated", ROTATIONS)
@pytest.mark.parametrize("target", ROTATIONS)
def test_a_front_face_part_is_undisturbed(breakout_pcb, tmp_path, generated, target):
    pcb = _copy(breakout_pcb, tmp_path)
    cands = _by_generated_rotation(read_board(pcb))
    if generated not in cands:
        pytest.skip("the Breakout has no multi-pad front part at rotation %g" % generated)
    worst = _parity(pcb, cands[generated].inst, target, Face.FRONT)
    assert worst < 1e-5, "generated %g, target %g: worst pad error %.6f mm" % (generated, target, worst)


@pytest.mark.parametrize("target", ROTATIONS)
def test_a_cell_flipped_to_the_back_lands_where_the_planner_said(breakout_pcb, tmp_path, target):
    """Cells were already right. This is here so that is checked, not assumed:
    if it fails, the cell path needs its own fix."""
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    cell = before.cell("power_drop0")
    b = Board(before, edge_margin=0.0, keep_going=True)
    b.place(Cell("power_drop0"), at=Centre(cell.box.center.x, cell.box.center.y),
            rotation=target, face=Face.BACK)
    plan = b.resolve()
    planned = {(fp.ref, p.number): plan.occupancy.pad_location(fp.ref, p.number)
               for fp in cell.members for p in fp.pads}
    apply_plan(pcb, plan)
    after = read_board(pcb).cell("power_drop0")
    worst = max(abs(p.box.center.x - planned[(fp.ref, p.number)].x)
                + abs(p.box.center.y - planned[(fp.ref, p.number)].y)
                for fp in after.members for p in fp.pads)
    assert worst < 1e-5, "target %g: worst pad error %.6f mm" % (target, worst)


def test_a_part_and_a_cell_holding_it_flip_the_same_way(breakout_pcb, tmp_path):
    """The asymmetry this work removed: a lone part mirrored top-to-bottom and
    the same part inside a cell mirrored left-to-right, so the two differed by
    half a turn and nothing said so.

    Measured through the WRITER, because that is where the two paths differ:
    `_place_footprint` and `_move_cell` are separate code, and comparing the
    planner against itself would prove nothing.

    Flipping a cell turns nothing: each member keeps the rotation it had, so
    the member's own geometry comes out as `mirror . R(its own rotation)`. To
    put the lone part in the same orientation it must be asked for
    `-its own rotation`. With that accounted for, the two answers are equal if
    and only if both paths mirror about the same axis - which is the whole
    question."""
    member = "power_drop0.conn"
    r_m = read_board(breakout_pcb).footprint(member).rotation

    def offsets_of(pcb):
        """Each pad's offset from its part's origin, KEYED BY PAD NUMBER.

        Not a set of positions: a connector's pads sit in a symmetric row, so
        a half turn maps the set onto itself and a comparison that ignored
        which pad was which would pass against exactly the error this test
        exists to catch."""
        fp = read_board(pcb).footprint(member)
        return {p.number: (round(p.box.center.x - fp.location.x, 4),
                           round(p.box.center.y - fp.location.y, 4)) for p in fp.pads}

    alone_dir = tmp_path / "alone"
    alone_dir.mkdir()
    pcb_a = _copy(breakout_pcb, alone_dir)
    fp0 = read_board(pcb_a).footprint(member)
    b = Board(read_board(pcb_a), edge_margin=0.0, keep_going=True)
    b.place(Part(member), at=Location(fp0.location.x, fp0.location.y),
            rotation=(-r_m) % 360, face=Face.BACK)
    apply_plan(pcb_a, b.resolve())

    in_cell_dir = tmp_path / "in_cell"
    in_cell_dir.mkdir()
    pcb_c = _copy(breakout_pcb, in_cell_dir)
    before = read_board(pcb_c)
    cell = before.cell("power_drop0")
    b = Board(before, edge_margin=0.0, keep_going=True)
    b.place(Cell("power_drop0"), at=Centre(cell.box.center.x, cell.box.center.y),
            rotation=0.0, face=Face.BACK)
    apply_plan(pcb_c, b.resolve())

    alone_offsets, cell_offsets = offsets_of(pcb_a), offsets_of(pcb_c)
    assert alone_offsets == cell_offsets, (
        "a part flipped alone and the same part flipped inside a cell mirror "
        "about different axes: pad 1 at %s against %s"
        % (alone_offsets.get("1"), cell_offsets.get("1")))
