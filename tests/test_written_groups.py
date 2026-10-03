"""The written board's KiCad groups: a group whose members the plan placed
apart is dissolved (its cells left whole at the top level), and
board.group() writes a group of the parts and cells a script names, so a
hand placement in pcbnew moves each set as one."""
import shutil

import pytest

pytest.importorskip("pcbnew")

from placemat.kicad.read import read_board  # noqa: E402
from placemat.kicad.write import apply_plan  # noqa: E402
from placemat.layout import Board  # noqa: E402
from placemat.settings import Settings  # noqa: E402
from placemat.values import Cell, Location, Part  # noqa: E402
from tests.conftest import needs_breakout, needs_kicad  # noqa: E402

pytestmark = [needs_kicad, needs_breakout]


def _module(breakout_pcb, tmp_path):
    """The breakout with a module sheet's group, as the generator nests one:
    'mod' holding the power_drop0 cell and two loose parts. Returns the
    board and the loose parts' instances."""
    import pcbnew
    pcb = tmp_path / "layout.kicad_pcb"
    shutil.copy(breakout_pcb, pcb)
    if breakout_pcb.with_suffix(".kicad_pro").exists():
        shutil.copy(breakout_pcb.with_suffix(".kicad_pro"), tmp_path / "layout.kicad_pro")
    loose = [fp for fp in read_board(pcb).footprints if fp.cell is None][:2]
    brd = pcbnew.LoadBoard(str(pcb))
    by_ref = {f.GetReference(): f for f in brd.GetFootprints()}
    mod = pcbnew.PCB_GROUP(brd)
    mod.SetName("mod")
    brd.Add(mod)
    mod.AddItem(next(g for g in brd.Groups() if g.GetName() == "power_drop0"))
    for fp in loose:
        mod.AddItem(by_ref[fp.ref])
    brd.Save(str(pcb))
    return pcb, [fp.inst for fp in loose]


def _groups(pcb):
    import pcbnew
    out = {}
    for g in pcbnew.LoadBoard(str(pcb)).Groups():
        items = list(g.GetItems())
        out[g.GetName()] = (sorted(i.GetReference() for i in items if isinstance(i, pcbnew.FOOTPRINT)),
                            sorted(i.GetName() for i in items if isinstance(i, pcbnew.PCB_GROUP)),
                            g.GetParentGroup().GetName() if g.GetParentGroup() else None)
    return out


def _write(pcb, script, settings=None):
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True, settings=settings)
    script(b)
    plan = b.resolve()
    apply_plan(pcb, plan)
    return plan


def test_a_cell_is_lifted_out_of_its_module_and_the_module_keeps_its_parts(breakout_pcb, tmp_path):
    pcb, loose = _module(breakout_pcb, tmp_path)
    cell_parts = _groups(pcb)["power_drop0"][0]
    plan = _write(pcb, lambda b: b.place(Part(loose[0]), at=Location(20, 20)))
    groups = _groups(pcb)
    both = sorted(fp.ref for fp in read_board(pcb).footprints if fp.inst in loose)
    assert groups["mod"] == (both, [], None) and groups["power_drop0"] == (cell_parts, [], None)
    assert "mod: cell(s) power_drop0 lifted to the top level" in plan.group_notes, plan.group_notes


def test_split_takes_the_members_placed_apart_out_of_their_group(breakout_pcb, tmp_path):
    pcb, loose = _module(breakout_pcb, tmp_path)
    plan = _write(pcb, lambda b: b.place(Part(loose[0]), at=Location(20, 20)), Settings(write_split_groups="split"))
    groups = _groups(pcb)
    rest = sorted(fp.ref for fp in read_board(pcb).footprints if fp.inst == loose[1])
    assert groups["mod"] == (rest, [], None)
    assert any(n.startswith("mod: 1 part(s) placed apart, taken out") for n in plan.group_notes), plan.group_notes


def test_split_removes_a_module_group_whose_members_all_went(breakout_pcb, tmp_path):
    pcb, loose = _module(breakout_pcb, tmp_path)
    cell_parts = _groups(pcb)["power_drop0"][0]

    def script(b):
        b.place(Part(loose[0]), at=Location(20, 20))
        b.place(Part(loose[1]), at=Location(20, 40))
        b.place(Cell("power_drop0"), at=Location(30, 80))
    plan = _write(pcb, script, Settings(write_split_groups="split"))
    groups = _groups(pcb)
    assert "mod" not in groups and groups["power_drop0"] == (cell_parts, [], None)
    assert any(n.startswith("mod:") and "removed" in n for n in plan.group_notes), plan.group_notes
    cells = read_board(pcb).cells
    assert "mod" not in cells and sorted(fp.ref for fp in cells["power_drop0"].members) == cell_parts


def test_a_cell_with_a_member_placed_alone_keeps_its_group_and_its_copper(breakout_pcb, tmp_path):
    import pcbnew
    pcb, loose = _module(breakout_pcb, tmp_path)
    member = next(fp for fp in read_board(pcb).footprints if fp.cell == "power_drop1")

    def items(path):
        g = next(g for g in pcbnew.LoadBoard(str(path)).Groups() if g.GetName() == "power_drop1")
        return [i for i in g.GetItems() if not isinstance(i, pcbnew.FOOTPRINT)]
    copper = len(items(pcb))
    _write(pcb, lambda b: b.place(Part(member.inst), at=Location(20, 20)), Settings(write_split_groups="split"))
    assert member.ref not in _groups(pcb)["power_drop1"][0] and len(items(pcb)) == copper


def test_groups_nested_two_deep_each_stand_at_the_top_level(breakout_pcb, tmp_path):
    import pcbnew
    pcb, loose = _module(breakout_pcb, tmp_path)
    brd = pcbnew.LoadBoard(str(pcb))
    top = pcbnew.PCB_GROUP(brd)
    top.SetName("top")
    brd.Add(top)
    top.AddItem(next(g for g in brd.Groups() if g.GetName() == "mod"))
    brd.Save(str(pcb))

    def script(b):
        b.place(Part(loose[0]), at=Location(20, 20))
        b.place(Part(loose[1]), at=Location(20, 40))
        b.place(Cell("power_drop0"), at=Location(30, 80))
    _write(pcb, script)
    groups = _groups(pcb)
    assert groups["mod"][2] is None and groups["mod"][1] == [] and groups["power_drop0"][2] is None
    assert "top" not in groups                     # it held only mod: left empty


def test_a_module_the_plan_left_alone_keeps_its_parts(breakout_pcb, tmp_path):
    pcb, loose = _module(breakout_pcb, tmp_path)
    _write(pcb, lambda b: None)
    assert len(_groups(pcb)["mod"][0]) == 2


def test_the_setting_keeps_every_group(breakout_pcb, tmp_path):
    pcb, loose = _module(breakout_pcb, tmp_path)
    _write(pcb, lambda b: b.place(Part(loose[0]), at=Location(20, 20)), Settings(write_split_groups="keep"))
    assert len(_groups(pcb)["mod"][0]) == 2 and _groups(pcb)["mod"][1] == ["power_drop0"]


def test_a_declared_group_holds_the_parts_it_names_at_the_top_level(breakout_pcb, tmp_path):
    pcb, loose = _module(breakout_pcb, tmp_path)

    def script(b):
        b.place(Part(loose[0]), at=Location(20, 20))
        b.group("working", [Part(loose[0]), Part(loose[1])], why="moved as one")
    plan = _write(pcb, script)
    groups = _groups(pcb)
    refs = sorted(fp.ref for fp in read_board(pcb).footprints if fp.inst in loose)
    assert groups["working"] == (refs, [], None)
    assert "mod" not in groups                      # it held only these two and its cell: left empty
    assert "working written: 2 part(s) (moved as one)" in plan.group_notes, plan.group_notes
    working = read_board(pcb).cells["working"]
    assert sorted(fp.ref for fp in working.members) == refs


def test_no_group_is_written_inside_another(breakout_pcb, tmp_path):
    """Groups on the board are one level: KiCad makes a nested one entered
    before anything in it can be moved."""
    pcb, loose = _module(breakout_pcb, tmp_path)
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    with pytest.raises(ValueError, match="one level"):
        b.group("working", [Part(loose[0]), Cell("power_drop1")])


def test_a_declared_group_may_not_take_a_cells_name_or_an_item_twice(breakout_pcb, tmp_path):
    pcb, loose = _module(breakout_pcb, tmp_path)
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    with pytest.raises(ValueError, match="power_drop2"):
        b.group("power_drop2", [Part(loose[0])])
    b.group("one", [Part(loose[0])])
    with pytest.raises(ValueError, match="already in group 'one'"):
        b.group("two", [Part(loose[0])])


def test_a_member_of_a_cell_placed_whole_may_not_be_grouped_apart(breakout_pcb, tmp_path):
    pcb, loose = _module(breakout_pcb, tmp_path)
    member = next(fp.inst for fp in read_board(pcb).footprints if fp.cell == "power_drop2")
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    b.place(Cell("power_drop2"), at=Location(30, 30))
    b.group("stray", [Part(member)])
    with pytest.raises(ValueError, match="group the cell"):
        b.resolve()


def test_an_item_named_twice_in_one_group_is_refused(breakout_pcb, tmp_path):
    pcb, loose = _module(breakout_pcb, tmp_path)
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    with pytest.raises(ValueError, match="named twice"):
        b.group("dup", [Part(loose[0]), Part(loose[0])])


def test_a_nested_cell_placed_apart_from_its_parent_is_written_where_the_plan_put_it(breakout_pcb, tmp_path):
    """Placing the parent's group must not carry a nested cell the plan
    placed on its own: the plan's parent holds only its own parts, so the
    writer moves only those, not the child group inside it."""
    pcb, loose = _module(breakout_pcb, tmp_path)

    def script(b):
        b.place(Cell("mod"), at=Location(15, 15))
        b.place(Cell("power_drop0"), at=Location(35, 25))
    plan = _write(pcb, script)
    after = {fp.ref: fp.location for fp in read_board(pcb).footprints}
    for ref in {m.ref for m in plan.geometry.cells["power_drop0"].members}:
        want = plan.occupancy.items[ref].reference.location
        assert (after[ref].x, after[ref].y) == pytest.approx((want.x, want.y), abs=0.01), ref


def _copy_breakout(breakout_pcb, tmp_path):
    pcb = tmp_path / "layout.kicad_pcb"
    shutil.copy(breakout_pcb, pcb)
    if breakout_pcb.with_suffix(".kicad_pro").exists():
        shutil.copy(breakout_pcb.with_suffix(".kicad_pro"), tmp_path / "layout.kicad_pro")
    return pcb


def _faces_note(brd, x=0.0, y=0.0):
    import pcbnew
    t = pcbnew.PCB_TEXT(brd)
    t.SetText("placemat faces outward=N quiet=S")
    t.SetLayer(pcbnew.Cmts_User)
    t.SetPosition(pcbnew.VECTOR2I(int(x * 1e6), int(y * 1e6)))
    brd.Add(t)
    return t


def test_a_stamped_cells_faces_note_is_read_then_left_out_of_the_written_board(breakout_pcb, tmp_path):
    import pcbnew
    pcb = _copy_breakout(breakout_pcb, tmp_path)
    brd = pcbnew.LoadBoard(str(pcb))
    next(g for g in brd.Groups() if g.GetName() == "power_drop0").AddItem(_faces_note(brd, 400.0, 400.0))
    brd.Save(str(pcb))
    geometry = read_board(pcb)
    assert geometry.cells["power_drop0"].faces == {"outward": "N", "quiet": "S"}
    before = geometry.cells["power_drop0"].box
    _write(pcb, lambda b: b.place(Cell("power_drop0"), at=Location(30, 80)))
    brd = pcbnew.LoadBoard(str(pcb))
    assert not [d for d in brd.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith("placemat faces")]
    g = next(g for g in brd.Groups() if g.GetName() == "power_drop0")
    assert not [i for i in g.GetItems() if isinstance(i, pcbnew.PCB_TEXT)]
    after = read_board(pcb).cells["power_drop0"].box
    assert after.width == pytest.approx(before.width, abs=0.01) and after.height == pytest.approx(before.height, abs=0.01)
    assert g.GetBoundingBox().GetWidth() / 1e6 < before.width + 10      # no 400 mm reach to the note


def test_a_fragment_opened_on_its_own_keeps_its_faces_note(breakout_pcb, tmp_path):
    import pcbnew
    pcb = _copy_breakout(breakout_pcb, tmp_path)
    brd = pcbnew.LoadBoard(str(pcb))
    _faces_note(brd)
    brd.Save(str(pcb))

    def fragment(b):
        b.rect(fit=True)                                     # a fragment: its frame is for placement only
        b.place(Cell("power_drop0"), at=Location(30, 80))
    _write(pcb, fragment)
    texts = [d.GetText() for d in pcbnew.LoadBoard(str(pcb)).GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)]
    assert "placemat faces outward=N quiet=S" in texts


def test_a_note_loose_on_a_board_that_stamps_is_not_kept(breakout_pcb, tmp_path):
    import pcbnew
    pcb = _copy_breakout(breakout_pcb, tmp_path)
    brd = pcbnew.LoadBoard(str(pcb))
    _faces_note(brd)
    brd.Save(str(pcb))
    _write(pcb, lambda b: b.place(Cell("power_drop0"), at=Location(30, 80)))
    texts = [d.GetText() for d in pcbnew.LoadBoard(str(pcb)).GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)]
    assert not [t for t in texts if t.startswith("placemat faces")]
