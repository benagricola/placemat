"""A fit frame written through pcbnew: the plane bounded to it is inside it
and KiCad's DRC finds nothing new."""
import pytest

pytest.importorskip("pcbnew")

import shutil

from placemat.kicad.drc import run_drc
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.values import CopperLayer, Net, Part
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]


def test_a_plane_on_a_fit_frame_is_written_inside_it(breakout_pcb, tmp_path):
    pcb = tmp_path / "layout.kicad_pcb"
    shutil.copy(breakout_pcb, pcb)
    shutil.copy(breakout_pcb.with_suffix(".kicad_pro"), tmp_path / "layout.kicad_pro")
    g = read_board(pcb)
    before = run_drc(pcb, tmp_path / "before.json")
    a, c = g.footprint("term_near_ra"), g.footprint("term_near_rb")
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(fit=True, draw=False, margin=0.5)
    b.place(Part(a.inst), at=a.location, rotation=a.rotation)
    b.place(Part(c.inst), at=c.location, rotation=c.rotation)
    b.plane(Net("GND"), layers=(CopperLayer.B,))
    plan = b.resolve()
    apply_plan(pcb, plan)
    zones = [z for z in read_board(pcb).copper if z.kind == "zone" and z.net == "GND" and CopperLayer.B in z.layers
             and plan.outline.inflate(1e-3).contains(z.box)]
    assert zones, "no GND zone inside the fitted frame %s" % (plan.outline,)
    assert run_drc(pcb, tmp_path / "after.json").real == before.real


def test_a_plane_is_written_above_the_same_net_zone_it_overlaps(breakout_pcb, tmp_path):
    """The board's own board-wide GND zone and the plane bounded to a fit frame overlap on B.Cu: at one
    priority KiCad reports zones_intersect, so the plane takes the higher one."""
    pcb = tmp_path / "layout.kicad_pcb"
    shutil.copy(breakout_pcb, pcb)
    shutil.copy(breakout_pcb.with_suffix(".kicad_pro"), tmp_path / "layout.kicad_pro")
    g = read_board(pcb)
    a = g.footprint("term_near_ra")
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(fit=True, draw=False, margin=0.5)
    b.place(Part(a.inst), at=a.location, rotation=a.rotation)
    b.plane(Net("GND"), layers=(CopperLayer.B,))
    apply_plan(pcb, b.resolve())
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb))
    back = [z for z in board.Zones() if z.GetNetname() == "GND" and board.GetLayerID("B.Cu") in z.GetLayerSet().CuStack()]
    assert len(back) == 2
    assert len({z.GetAssignedPriority() for z in back}) == 2
    assert run_drc(pcb, tmp_path / "after.json").by_type.get("zones_intersect", 0) == 0
