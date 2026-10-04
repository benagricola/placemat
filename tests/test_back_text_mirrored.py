"""Every text placemat writes on a back layer is mirrored, and one on a front layer is not, as KiCad's DRC expects
(drc_test_provider_text_mirroring.cpp: a text on B.Cu, B.SilkS, B.Mask or B.Fab that is not mirrored is
nonmirrored_text_on_back_layer; one on their front twins that is, mirrored_text_on_front_layer). That covers a
keepout's name on B.Fab, a text op given a back layer by name, and a stamped cell's text the writer moves."""
import json
import shutil
import subprocess

import pytest

from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import CopperLayer, Face, Location, Part
from tests.conftest import needs_breakout, needs_kicad
from tests.fixtures import board_geometry, footprint

pytestmark = needs_kicad


def _keepout_plan(layer):
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"), fields={"Pm.Height": "1.1mm"})]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5,
              settings=Settings(write_keepout_drawings="admitting"))
    b.keepout(Circle(8.0), "tray", at=Location(20, 20), excludes=("parts",), max_height=1.9, layers=[layer],
              why="the case leaves 1.9 mm here")
    b.place(Part("c1"), at=Location(20, 20), face=Face.BACK if layer is CopperLayer.B else Face.FRONT)
    return b.resolve()


def _texts(board):
    import pcbnew
    return [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)]


@pytest.mark.parametrize("layer,mirrored", [(CopperLayer.B, True), (CopperLayer.F, False)], ids=["back", "front"])
def test_a_keepouts_name_is_mirrored_on_the_back_fab(layer, mirrored):
    import pcbnew
    from placemat.kicad.write import _draw_keepout_drawings
    board = pcbnew.CreateEmptyBoard()
    _draw_keepout_drawings(board, _keepout_plan(layer))
    (text,) = _texts(board)
    assert text.GetLayer() == (pcbnew.B_Fab if mirrored else pcbnew.F_Fab)
    assert text.IsMirrored() is mirrored


@pytest.mark.parametrize("layer,mirrored", [("B.Fab", True), ("B.Silkscreen", True), ("F.Fab", False),
                                            ("User.Comments", False)])
def test_a_text_op_on_a_named_layer_is_mirrored_by_that_layers_face(layer, mirrored):
    import pcbnew
    from placemat.copper import Text
    from placemat.kicad.write import _draw_text
    board = pcbnew.CreateEmptyBoard()
    _draw_text(board, Text("note", Location(10, 10), Face.FRONT, 1.0, 0.15, layer=layer))
    (text,) = _texts(board)
    assert text.IsMirrored() is mirrored


def test_a_text_op_on_the_back_silk_by_its_face_is_mirrored():
    import pcbnew
    from placemat.copper import Text
    from placemat.kicad.write import _draw_text
    board = pcbnew.CreateEmptyBoard()
    _draw_text(board, Text("note", Location(10, 10), Face.BACK, 1.0, 0.15))
    (text,) = _texts(board)
    assert text.GetLayer() == pcbnew.B_SilkS and text.IsMirrored()


def test_a_stamped_cells_text_on_a_back_layer_is_mirrored_when_the_cell_is_moved():
    """A fragment written before this fix carries its keepout name on B.Fab unmirrored; moving the cell puts it right.
    A back text the cell carries mirrored, and a front one, keep theirs."""
    import pcbnew
    from placemat.board_geometry import CellGeom
    from placemat.kicad.write import _move_cell
    from placemat.placement import Placement
    from placemat.values import Box
    board = pcbnew.CreateEmptyBoard()
    group = pcbnew.PCB_GROUP(board)
    group.SetName("cell")
    board.Add(group)
    made = {}
    for name, layer, mirror in (("plain_back", pcbnew.B_Fab, False), ("mirrored_back", pcbnew.B_SilkS, True),
                                ("front", pcbnew.F_Fab, False)):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(name)
        t.SetLayer(layer)
        t.SetMirrored(mirror)
        t.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(10), pcbnew.FromMM(10)))
        board.Add(t)
        group.AddItem(t)
        made[name] = t
    cell = CellGeom("cell", (), Box(9, 9, 11, 11), Box(9, 9, 11, 11), Box(9, 9, 11, 11), Box(0, 0, 0, 0), {})
    _move_cell(board, cell, Placement(Location(20, 20), 30.0, Face.FRONT), {"cell": group})
    assert made["plain_back"].IsMirrored() and made["mirrored_back"].IsMirrored()
    assert not made["front"].IsMirrored()


@needs_breakout
@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="no kicad-cli")
def test_kicad_finds_no_unmirrored_text_on_a_written_back_keepout(tmp_path, breakout_pcb):
    """The whole writer, judged by KiCad: a back keepout's name, a label on a back-face part."""
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    for ext in (".kicad_pcb", ".kicad_pro"):
        src = breakout_pcb.with_suffix(ext)
        if src.exists():
            shutil.copy(src, tmp_path / ("layout" + ext))
    pcb = tmp_path / "layout.kicad_pcb"
    g = read_board(pcb)
    b = Board(g, edge_margin=0.0, keep_going=True, settings=Settings(write_keepout_drawings="all"))
    b.rect(width=g.outline_box.width, height=g.outline_box.height)
    box = g.outline_box
    b.keepout(Circle(4.0), "back_tray", at=Location(box.left + 5.0, box.top + 5.0), layers=[CopperLayer.B],
              why="a tray under the board")
    plan = b.resolve()
    apply_plan(pcb, plan)
    out = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(out), str(pcb)],
                   check=True, capture_output=True, cwd=str(tmp_path))
    found = [v for v in json.loads(out.read_text())["violations"]
             if v["type"] in ("nonmirrored_text_on_back_layer", "mirrored_text_on_front_layer")]
    assert found == [], [v["items"][0]["description"] for v in found]
