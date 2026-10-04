"""A fixture module run with alternatives, stamped by a board, and written with one of its arrangements: the arrangement offered
passes the module's real DRC, the board run places the cell, and the module run and the board run agree on what was written. The
note's split texts survive the stamp and KiCad; two arranged stamps of one module name their rule areas apart; and arranging cells
on the largest real board leaves pcbnew's bindings and the board's groups whole (CLAUDE.md: board.Delete, not board.Remove)."""
import gc
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from placemat.arrangement_note import ARRANGEMENT_PREFIX
from tests import real_modules
from tests.arrangement_support import stamp_fragment, stamp_fragment_as_cell, stamp_fragment_as_cells, synthetic_notes_for
from tests.conftest import needs_kicad
from tests.test_arrangement_run import ALTERNATIVES, with_alternatives

pytestmark = needs_kicad

ROUTED = Path(__file__).resolve().parents[1] / "fixtures" / "fairing" / "routed"     # the largest real board of the fixtures

# A label on r_rt, which r_rt.apart stands 0.4 mm further south, and a keepout over r_rt's places that lets RT_5V and EN_5V's tracks
# through (an AllowRule names its area). The keepout's place is r_rt's in the fragment's frame.
MARKS = '''
from placemat import Location, Path
board.label(Part("r_rt"), "RT", side=Edge.SOUTH, why="the RT resistor, marked")
board.keepout(Path([(-1.0, -0.8), (1.0, -0.8), (1.0, 0.8), (-1.0, 0.8)]), "rt", at=Location(-1.36, 3.1), excludes=("tracks",),
              allow=(Net("RT_5V"), Net("EN_5V")), why="RT's run kept to its own nets")
'''


def with_marks(text: str) -> str:
    marker = "frame_planes(FILLET, supply=None)"
    return text.replace(marker, ALTERNATIVES + MARKS + marker, 1)


def module_run(tmp_path_factory, edit):
    """(RunResult, run.json, the fragment's board, the ids offered other than the default)."""
    result, _, frag = real_modules.run(tmp_path_factory.mktemp("module"), "usb5v", edit=edit)
    rec = json.loads((result.run_dir / "run.json").read_text())
    return result, rec, frag, [a["id"] for a in rec["arrangements"][1:] if a["offered"]]


@pytest.fixture(scope="module")
def usb5v(tmp_path_factory):
    return module_run(tmp_path_factory, with_alternatives)


@pytest.fixture(scope="module")
def usb5v_marked(tmp_path_factory):
    run = module_run(tmp_path_factory, with_marks)
    assert run[3] == ["r_rt.apart"], "the marks must leave r_rt.apart offered"
    return run


def poses(geometry, member_filter):
    return {fp.inst: (fp.location, fp.rotation % 360.0, fp.face) for fp in geometry.footprints if member_filter(fp)}


def note_texts(board) -> list:
    import pcbnew
    return sorted(d.GetText() for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(ARRANGEMENT_PREFIX))


def test_an_offered_arrangement_is_what_the_board_writes(tmp_path, usb5v):
    from placemat.findings import FindingCause
    from placemat.kicad.drc import run_drc
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    from placemat.layout import Board
    from placemat.values import Cell, Location
    result, rec, frag, offered = usb5v
    assert offered
    arr = read_board(result.run_dir / "arrangements" / offered[0] / "layout.kicad_pcb")        # the module run's own board of it
    errors = {v["type"] for v in json.loads((result.run_dir / "arrangements" / offered[0] / "drc.json").read_text()).get("violations", [])
              if v.get("severity") == "error"}
    assert errors <= {"invalid_outline"}                    # a fragment draws no outline (DrcReport.is_expected)
    stamped = stamp_fragment_as_cell(frag, tmp_path / "stamped.kicad_pcb", "mod", (40.0, 20.0))
    g = read_board(stamped)
    assert g.cell("mod").offered() == tuple(offered) and g.cell("mod").arrangement_problems == ()
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(width=140, height=120)
    b.place(Cell("mod"), at=Location(70.0, 60.0), arrangements=offered[0])
    plan = b.resolve()
    assert plan.step("mod").placement is not None and plan.placement("mod").arrangement == offered[0]
    assert not [f for f in plan.findings if f.cause is FindingCause.ARRANGEMENT_STALE]
    apply_plan(stamped, plan)
    after = poses(read_board(stamped), lambda fp: fp.cell == "mod")
    want = poses(arr, lambda fp: fp.cell is None)
    mine = next(a for a in rec["arrangements"] if a["id"] == offered[0])["metrics"]["drc"] or 0
    assert sum(run_drc(stamped, tmp_path / "stamped-drc.json", frame_only=True).real.values()) <= mine      # no worse than the module run's own
    assert {k.split(".", 1)[1] for k in after} == set(want)
    first = sorted(want)[0]
    here = after["mod." + first][0]
    for inst, (loc, rot, face) in want.items():                                     # the placement is a translation: relative places agree
        wloc, wrot, wface = after["mod." + inst]
        assert (rot, face) == (wrot, wface), inst
        assert abs((wloc.x - here.x) - (loc.x - want[first][0].x)) < 2e-3 and abs((wloc.y - here.y) - (loc.y - want[first][0].y)) < 2e-3, inst


def test_a_split_note_survives_the_stamp_and_kicad(tmp_path, usb5v):
    """The offered arrangement's note is about 21k characters in several texts: stamped as pcb stamps (each text duplicated into the
    cell's group), saved and read back, every text is there unchanged and the arrangement attaches, not stale."""
    import pcbnew
    from placemat.kicad.read import read_board
    from placemat.settings import Settings
    _, _, frag, offered = usb5v
    written = note_texts(pcbnew.LoadBoard(str(frag)))
    assert len(written) > 1 and all(len(t) <= Settings().place_arrangement_note_chars for t in written)
    stamped = stamp_fragment_as_cell(frag, tmp_path / "stamped.kicad_pcb", "mod", (40.0, 20.0))
    board = pcbnew.LoadBoard(str(stamped))
    assert note_texts(board) == written
    assert {d.GetParentGroup().GetName() for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)
            and d.GetText().startswith(ARRANGEMENT_PREFIX)} == {"mod"}
    cell = read_board(stamped).cell("mod")
    assert cell.offered() == tuple(offered) and cell.arrangement_problems == ()
    print("note characters:", sum(len(t) for t in written), "in", len(written), "texts")


def _arranged_pair(tmp_path, frag):
    """The marked fragment stamped twice (u5a, u5b), both placed in r_rt.apart on a 140 x 120 board: (board path, plan)."""
    from placemat.kicad.read import read_board
    from placemat.layout import Board
    from placemat.values import Cell, Location
    pcb = stamp_fragment_as_cells(frag, tmp_path / "pair.kicad_pcb", {"u5a": (40.0, 20.0), "u5b": (70.0, 20.0)})
    g = read_board(pcb)
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(width=140, height=120)
    b.place(Cell("u5a"), at=Location(40.0, 40.0), arrangements="r_rt.apart")
    b.place(Cell("u5b"), at=Location(90.0, 40.0), arrangements="r_rt.apart")
    return pcb, b.resolve()


def test_two_arranged_stamps_of_one_module_name_their_rule_areas_apart(tmp_path, usb5v_marked):
    """pcb names the module's keepout `<name>_1` in both stamps. Written in an arrangement, each cell's area has a name of its own and
    each AllowRule names its own cell's: KiCad's DRC lets each cell's RT and EN tracks through its own area only."""
    import pcbnew
    from placemat.kicad.drc import run_drc
    from placemat.kicad.write import apply_plan
    _, _, frag, _ = usb5v_marked
    pcb, plan = _arranged_pair(tmp_path, frag)
    assert [plan.placement(c).arrangement for c in ("u5a", "u5b")] == ["r_rt.apart", "r_rt.apart"]
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    areas = {z.GetParentGroup().GetName(): z.GetZoneName() for z in board.Zones() if z.GetIsRuleArea()}
    assert sorted(areas) == ["u5a", "u5b"] and areas["u5a"] != areas["u5b"]
    rules = pcb.with_suffix(".kicad_dru").read_text()
    for cell, name in areas.items():
        assert "A.intersectsArea('%s') && A.NetName != '%s.EN_5V' && A.NetName != '%s.RT_5V'" % (name, cell, cell) in rules
    report = run_drc(pcb, tmp_path / "pair-drc.json", frame_only=True)
    assert "items_not_allowed" not in report.by_type, report.by_type


def _silk_boxes(board, keep) -> list:
    """(left, top, right, bottom) of each silk text `keep(text)` takes, to 0.01 mm."""
    import pcbnew
    out = []
    for d in board.GetDrawings():
        if isinstance(d, pcbnew.PCB_TEXT) and d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and keep(d):
            bb = d.GetEffectiveShape().BBox()
            out.append(tuple(round(pcbnew.ToMM(v), 2) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())))
    return sorted(out)


def test_an_arranged_cells_label_is_silk_and_reserved_where_the_arrangement_writes_it(tmp_path, usb5v_marked):
    """The label on r_rt moves with it in r_rt.apart: the occupancy holds its silk and its parts reservation where the board writes
    it, and the board writes it where the module run's own board of the arrangement has it, relative to r_rt."""
    import pcbnew
    from placemat.kicad.write import apply_plan
    from placemat.values import Box
    result, _, frag, _ = usb5v_marked
    pcb, plan = _arranged_pair(tmp_path, frag)
    occ = plan.occupancy
    rounded = lambda b: tuple(round(v, 2) for v in (b.left, b.top, b.right, b.bottom))
    held = sorted(rounded(s.box) for s in occ.copper if s.kind == "silk" and s.owner == "u5a")
    reserved = sorted(rounded(Box.of_points(r.poly)) for r in occ.reservations if r.why.name == "label 'RT' from the u5a cell")
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    written = _silk_boxes(board, lambda d: d.GetParentGroup() is not None and d.GetParentGroup().GetName() == "u5a")
    assert len(written) == 1 and held == written and reserved == written
    proven = pcbnew.LoadBoard(str(result.run_dir / "arrangements" / "r_rt.apart" / "layout.kicad_pcb"))
    at = lambda b, path: next(fp.GetPosition() for fp in b.GetFootprints() if fp.GetFieldText("Path").startswith(path))
    here, there = at(board, "u5a.r_rt."), at(proven, "r_rt.")
    dx, dy = pcbnew.ToMM(here.x - there.x), pcbnew.ToMM(here.y - there.y)
    [box] = _silk_boxes(proven, lambda d: d.GetText() == "RT")
    assert written == [tuple(round(v + d, 2) for v, d in zip(box, (dx, dy, dx, dy)))]


def test_arranging_cells_on_the_largest_real_board_keeps_pcbnews_bindings_and_its_groups(tmp_path, usb5v, monkeypatch):
    """Every cell of the routed board gets a note that turns its smallest member (its copper then deleted from its group and none
    drawn), and the real module is stamped beside it and placed in its offered arrangement; the board is written. In that one
    process the written board's footprints, groups and zones are still pcbnew's objects, and read back from disk each group holds
    what the write left in it."""
    import pcbnew
    from placemat.kicad import write
    from placemat.kicad.read import read_board
    from placemat.layout import Board
    from placemat.values import Cell
    _, _, frag, offered = usb5v
    work = tmp_path / "routed"
    shutil.copytree(ROUTED, work)
    pcb = work / "layout.kicad_pcb"
    cells = synthetic_notes_for(pcb)
    board = pcbnew.LoadBoard(str(pcb))
    stamp_fragment(board, frag, "u5", (80.0, 30.0))         # beside the board: it has no room inside for one more module
    board.Save(str(pcb))
    del board
    g = read_board(pcb)
    assert len(cells) == 30 and {n: (g.cell(n).offered(), g.cell(n).arrangement_problems) for n in cells} == \
        {n: (("turn",), ()) for n in cells}
    assert g.cell("u5").offered() == tuple(offered)
    b = Board(g, edge_margin=0.0, keep_going=True)
    for name in sorted(cells):
        b.place(Cell(name), at=g.cell(name).arranged("turn").box.center, arrangements="turn")      # where it stands
    b.place(Cell("u5"), at=g.cell("u5").arranged(offered[0]).box.center, arrangements=offered[0])
    plan = b.resolve()
    assert {n: plan.placement(n).arrangement for n in [*cells, "u5"]} == {**cells, "u5": offered[0]}
    held = {}
    save = write.save

    def keep(board, path):
        held["board"] = board
        return save(board, path)
    monkeypatch.setattr(write, "save", keep)
    write.apply_plan(pcb, plan)
    gc.collect()                                            # an item handed to a Python wrapper is freed with it

    def contents(board) -> dict:
        assert all(isinstance(fp, pcbnew.FOOTPRINT) for fp in board.GetFootprints())
        [fp.GetPosition().x for fp in board.GetFootprints()]
        out = {}
        for grp in board.Groups():
            items = list(grp.GetItems())
            assert not [i for i in items if type(i).__name__ == "SwigPyObject"], grp.GetName()
            [i.GetPosition().x for i in items if hasattr(i, "GetPosition")]
            out[grp.GetName()] = Counter(type(i).__name__ for i in items)
        assert all(isinstance(z, pcbnew.ZONE) for z in board.Zones())
        [z.GetZoneName() for z in board.Zones()]
        return out
    in_process = contents(held.pop("board"))
    assert in_process["u5"]["FOOTPRINT"] == len(g.cell("u5").members) and in_process["u5"]["PCB_VIA"] > 0
    assert contents(pcbnew.LoadBoard(str(pcb))) == in_process
