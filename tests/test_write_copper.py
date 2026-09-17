"""Copper ops written through pcbnew come back when the board file is read again, and DRC on the
result is readable as numbers."""
import math
import shutil

import pytest

from placemat.cutouts import Circle, Slot
from placemat.values import Cutout
from placemat.layout import Board
from placemat.kicad.drc import run_drc
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.values import CopperLayer, Edge, Location, Net, Part, PadRef
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]


def _copy(breakout_pcb, tmp_path):
    for ext in (".kicad_pcb", ".kicad_pro"):
        src = breakout_pcb.with_suffix(ext)
        if src.exists():
            shutil.copy(src, tmp_path / ("layout" + ext))
    return tmp_path / "layout.kicad_pcb"


def test_tracks_vias_pours_and_a_plane_round_trip(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    b = Board(before, edge_margin=0.0)
    b.size(width=before.outline_box.width, height=before.outline_box.height, chamfer=2.0)
    b.track(Net("TERM_NEAR_MID"), [PadRef(Part("term_near_ra"), "TERM_NEAR_MID"), PadRef(Part("term_near_rb"), "TERM_NEAR_MID")],
            layer=CopperLayer.F, width=0.3)
    b.via(Net("GND"), Location(5.0, 100.0))
    b.pour(Net("V48P"), [Location(50, 100), Location(60, 100), Location(60, 105), Location(50, 105)],
           layer=CopperLayer.F)
    b.plane(Net("GND"), layers=(CopperLayer.B,), inset=0.4, chamfer=2.0)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    n_tracks = len([c for c in after.copper if c.kind == "track"])
    n_vias = len([c for c in after.copper if c.kind == "via"])
    assert n_tracks == len([c for c in before.copper if c.kind == "track"]) + 1
    assert n_vias == len([c for c in before.copper if c.kind == "via"]) + 1
    assert any(c.kind == "poly" and c.net == "V48P" and abs(c.box.left - 50.0) <= 0.11 for c in after.copper)   # the 0.2 stroke rounds the outline outward
    zones = [c for c in after.copper if c.kind == "zone" and c.net == "GND" and CopperLayer.B in c.layers]
    assert zones                                                    # the one this plan added (the board may carry its own)
    assert zones[0].box.width > after.outline_box.width * 0.9     # filled across the board, not an empty outline


def test_drc_on_the_committed_board_reads_as_numbers(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    report = run_drc(pcb, tmp_path / "drc.json")
    assert report.real == {}                       # the committed board is DRC clean
    assert report.unconnected == 0
    assert set(report.outstanding) <= {"via_dangling", "track_dangling", "isolated_copper"}
    assert report.violations >= 0 and report.path.exists()


def test_a_declared_clearance_is_written_beside_the_board_and_its_drc_reads_it(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    b = Board(before, edge_margin=0.0)
    b.size(width=before.outline_box.width, height=before.outline_box.height, chamfer=2.0)
    b.rule(clearance=5.0, on=Net("GND"), why="an impossible clearance, to prove the rule is read")
    apply_plan(pcb, b.resolve())
    assert (tmp_path / "layout.kicad_dru").read_text().startswith("(version 1)")
    report = run_drc(pcb, tmp_path / "drc.json")
    assert report.by_type.get("clearance", 0) > 0            # the committed board is clean without the rule


def test_the_boards_copper_to_edge_clearance_is_read(breakout):
    assert breakout.edge_clearance == pytest.approx(0.4)
    assert Board(breakout).keep_in == pytest.approx(0.4)


def test_a_knockout_label_is_written_as_silk_text_beside_its_part(breakout_pcb, tmp_path):
    import pcbnew
    from placemat.values import Edge
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    b = Board(before, edge_margin=0.0, keep_going=True)
    b.size(width=before.outline_box.width, height=before.outline_box.height, chamfer=2.0)
    b.label(Part("trunk_pwr"), "TRUNK IN", side=Edge.SOUTH, gap=0.5, knockout=True, size=1.2)
    plan = b.resolve()
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    texts = [d for d in board.GetDrawings() if d.GetClass() == "PCB_TEXT" and d.GetText() == "TRUNK IN"]
    assert len(texts) == 1
    t = texts[0]
    assert t.IsKnockout() and t.GetLayer() == pcbnew.F_SilkS
    part = before.footprint("trunk_pwr").phys_box                 # undeclared: it stays where the board has it
    bb = t.GetEffectiveShape().BBox()                                 # what is drawn: the knockout frame
    assert abs(bb.GetTop() / 1e6 - (part.bottom + 0.5)) < 0.02       # its frame starts exactly one gap below the part
    assert abs((bb.GetLeft() + bb.GetRight()) / 2e6 - part.center.x) < 0.3


def test_faces_written_into_a_cells_group_are_read_back_as_the_cells_faces(breakout_pcb, tmp_path):
    """The fact rides inside the group, which is what pcb layout stamps."""
    import pcbnew
    pcb = _copy(breakout_pcb, tmp_path)
    board = pcbnew.LoadBoard(str(pcb))
    group = [g for g in board.Groups() if g.GetName() == "bus_drop0"][0]
    t = pcbnew.PCB_TEXT(board)
    t.SetText("placemat faces outward=N handoff=W")
    t.SetLayer(pcbnew.Cmts_User)
    t.SetPosition(pcbnew.VECTOR2I(int(20e6), int(20e6)))
    board.Add(t)
    group.AddItem(t)
    board.Save(str(pcb))
    after = read_board(pcb)
    assert after.cell("bus_drop0").faces == {"outward": "N", "handoff": "W"}
    assert after.cell("bus_drop1").faces == {}


def test_show_renders_one_cell_on_its_own_with_a_pad_map(breakout_pcb, tmp_path, capsys):
    from placemat import cli
    pcb = _copy(breakout_pcb, tmp_path)
    assert cli.main(["show", str(pcb), "bus_drop0"]) == 0
    out = capsys.readouterr().out
    assert "bus_drop0" in out and "CAN_S0_P" in out
    pngs = sorted((tmp_path / ".placemat" / "show").glob("bus_drop0-*.png"))
    assert [p.name for p in pngs] == ["bus_drop0-bottom.png", "bus_drop0-iso-bottom.png", "bus_drop0-iso.png", "bus_drop0-top.png"]
    assert all(p.stat().st_size > 1000 for p in pngs)


def test_the_faces_command_writes_the_fact_into_a_fragment_and_replaces_an_old_one(breakout_pcb, tmp_path):
    from placemat import cli
    pcb = _copy(breakout_pcb, tmp_path)
    assert cli.main(["faces", str(pcb), "outward=n", "handoff=E"]) == 0
    assert cli.main(["faces", str(pcb), "outward=S"]) == 0
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb))
    texts = [d for d in board.GetDrawings() if d.GetClass() == "PCB_TEXT" and d.GetText().startswith("placemat faces")]
    assert [t.GetText() for t in texts] == ["placemat faces outward=S"]
    # the note sits clear of the module: below everything it draws, labels included, not over its origin
    lowest = max([fp.GetBoundingBox(True, True).GetBottom() for fp in board.GetFootprints()] +
                 [d.GetBoundingBox().GetBottom() for d in board.GetDrawings()
                  if not (d.GetClass() == "PCB_TEXT" and d.GetText().startswith("placemat faces"))] +
                 [t.GetBoundingBox().GetBottom() for t in board.GetTracks()])
    assert texts[0].GetBoundingBox().GetTop() > lowest


def test_the_faces_note_clears_a_label_drawn_below_the_parts(breakout_pcb, tmp_path):
    from placemat import cli
    import pcbnew
    pcb = _copy(breakout_pcb, tmp_path)
    board = pcbnew.LoadBoard(str(pcb))
    lowest = max(fp.GetBoundingBox(True, True).GetBottom() for fp in board.GetFootprints())
    label = pcbnew.PCB_TEXT(board)
    label.SetText("TERM")
    label.SetLayer(pcbnew.F_SilkS)
    label.SetTextSize(pcbnew.VECTOR2I(int(1e6), int(1e6)))
    label.SetPosition(pcbnew.VECTOR2I(int(30e6), lowest + int(2e6)))      # a label 2 mm below the lowest part
    board.Add(label)
    board.Save(str(pcb))
    assert cli.main(["faces", str(pcb), "outward=N"]) == 0
    board = pcbnew.LoadBoard(str(pcb))
    note = [d for d in board.GetDrawings() if d.GetClass() == "PCB_TEXT" and d.GetText().startswith("placemat faces")][0]
    term = [d for d in board.GetDrawings() if d.GetClass() == "PCB_TEXT" and d.GetText() == "TERM"][0]
    assert note.GetBoundingBox().GetTop() > term.GetBoundingBox().GetBottom()


def test_an_undrawn_frame_writes_no_outline(breakout_pcb, tmp_path):
    import pcbnew
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    b = Board(before, edge_margin=0.0, keep_going=True)
    b.size(width=before.outline_box.width + 5.0, height=before.outline_box.height, chamfer=2.0, draw=False)
    n_before = len([d for d in pcbnew.LoadBoard(str(pcb)).GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts])
    apply_plan(pcb, b.resolve())
    board = pcbnew.LoadBoard(str(pcb))
    edges = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    assert len(edges) == n_before and n_before > 0            # Edge.Cuts untouched: the frame is for placement only


def test_a_round_board_writes_its_rim_and_bore_as_circles(breakout_pcb, tmp_path):
    """A disc's Edge.Cuts is a circle, not a polygon: KiCad mills the arc and
    clips the fills to it, and a bore is a second circle inside the first."""
    import pcbnew
    pcb = _copy(breakout_pcb, tmp_path)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.disc(diameter=42.0, hole=8.0)
    apply_plan(pcb, b.resolve())
    board = pcbnew.LoadBoard(str(pcb))
    edges = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    assert len(edges) == 2 and all(e.GetShapeStr() == "Circle" for e in edges)
    radii = sorted(round(pcbnew.ToMM(e.GetRadius()), 3) for e in edges)
    assert radii == [4.0, 21.0]
    centres = {(round(pcbnew.ToMM(e.GetCenter().x), 3), round(pcbnew.ToMM(e.GetCenter().y), 3)) for e in edges}
    assert centres == {(21.0, 21.0)}


def test_a_shaped_board_writes_its_legs_as_segments_and_its_arcs_as_arcs(breakout_pcb, tmp_path):
    """The fab gets the real curve: the outline is flattened for the
    arithmetic, never for Edge.Cuts."""
    import pcbnew
    from placemat.outline import Arc
    pcb = _copy(breakout_pcb, tmp_path)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.outline([(0.0, 40.0), (0.0, 20.0), Arc(to=(40.0, 20.0), via=(20.0, 0.0)), (40.0, 40.0)])
    apply_plan(pcb, b.resolve())
    board = pcbnew.LoadBoard(str(pcb))
    edges = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    kinds = sorted(e.GetShapeStr() for e in edges)
    assert kinds == ["Arc", "Line", "Line", "Line"]
    (arc,) = [e for e in edges if e.GetShapeStr() == "Arc"]
    assert round(pcbnew.ToMM(arc.GetRadius()), 3) == 20.0
    mid = arc.GetArcMid()
    assert (round(pcbnew.ToMM(mid.x), 2), round(pcbnew.ToMM(mid.y), 2)) == (20.0, 0.0)


def _edge_cuts(pcb):
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb))
    return board, [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]


SLOT_SHAPE = Slot(17.0, 3.0)          # 17 tip to tip: a 14 mm centre line, 3 across
SLOT_AT = Location(21.0, 30.0)


@pytest.mark.parametrize("name,declare", [
    ("a rectangle", lambda b, holes: b.size(width=42.0, height=42.0, holes=holes)),
    ("a disc", lambda b, holes: b.disc(diameter=42.0, hole=8.0, holes=holes)),
    ("a shaped board", lambda b, holes: b.outline(Circle(42.0).path_at(Location(21.0, 21.0)), holes=holes)),
])
def test_a_slot_is_milled_as_two_legs_and_two_half_circles(breakout_pcb, tmp_path, name, declare):
    """Whatever the board is declared as, the cutout reaches Edge.Cuts as the
    arcs it was drawn with, and KiCad reads the result as one board with a
    hole in it."""
    import pcbnew
    pcb = _copy(breakout_pcb, tmp_path)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    declare(b, [Cutout(SLOT_SHAPE, "ffc", at=SLOT_AT, why="the cable passes through")])
    apply_plan(pcb, b.resolve())
    board, edges = _edge_cuts(pcb)

    caps = [e for e in edges if e.GetShapeStr() == "Arc"
            and round(pcbnew.ToMM(e.GetRadius()), 3) == SLOT_SHAPE.width / 2.0]
    assert len(caps) == 2                                     # both ends fully rounded
    assert all(round(abs(e.GetArcAngle().AsDegrees()), 1) == 180.0 for e in caps)

    # nothing of zero length: a path that closes on itself is not closed twice
    assert not [e for e in edges if e.GetShapeStr() == "Line" and e.GetStart() == e.GetEnd()]

    ps = pcbnew.SHAPE_POLY_SET()
    assert board.GetBoardPolygonOutlines(ps, False)
    assert ps.OutlineCount() == 1
    cut = SLOT_SHAPE.area
    whole = 42.0 ** 2 if name != "a disc" else math.pi * (21.0 ** 2 - 4.0 ** 2)
    if name == "a shaped board":
        whole = math.pi * 21.0 ** 2
    assert ps.Area() / 1e12 == pytest.approx(whole - cut, rel=0.01)


def test_every_placed_cutout_reaches_edge_cuts(breakout_pcb, tmp_path):
    """The plan's shape grows as holes are cut, so what the fab gets is the
    board the placer actually used - not the one declared before the holes
    had anywhere to go."""
    import pcbnew
    from placemat.values import Centre
    pcb = _copy(breakout_pcb, tmp_path)
    base = read_board(pcb)
    box = base.outline_box
    b = Board(base, edge_margin=0.5, keep_going=True)
    # A freedom, so the hole goes through the placement queue and slides to
    # board the generated parts left clear. That is the path on which the
    # plan's shape has to grow as each hole is cut.
    b.size(width=box.width, height=box.height,
           holes=[Cutout(Slot(13.0, 3.0), "ffc", at=Centre(None, 20.0), why="the cable")])
    plan = b.resolve()
    assert set(plan.cutouts_placed) == {"ffc"}, plan.findings
    apply_plan(pcb, plan)
    board, edges = _edge_cuts(pcb)
    caps = [e for e in edges if e.GetShapeStr() == "Arc"
            and round(abs(e.GetArcAngle().AsDegrees()), 1) == 180.0]
    assert len(caps) == 2                                  # both ends of the slot
    assert not [e for e in edges if e.GetShapeStr() == "Line" and e.GetStart() == e.GetEnd()]
    ps = pcbnew.SHAPE_POLY_SET()
    assert board.GetBoardPolygonOutlines(ps, False)
    assert ps.OutlineCount() == 1 and ps.HoleCount(0) == 1
    assert ps.Area() / 1e12 == pytest.approx(
        box.width * box.height - Slot(13.0, 3.0).area, rel=0.01)
