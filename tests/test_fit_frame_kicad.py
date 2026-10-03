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
