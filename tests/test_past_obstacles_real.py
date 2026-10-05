"""The reported case on a real board (fixtures/fairing/vent_silk: the connector a 1.5 mm vent is cut beside, as a run
wrote it). A 3 A track on B.Cu drawn straight across the vent gave KiCad's copper_edge_clearance at 0.0 mm and nothing in
the run's own findings. The run now says so itself, as copper.edge, and `Past([vent], Edge.WEST)` takes the track past
the vent at the copper-to-edge clearance, which KiCad's DRC accepts. The vent is cut where `Near(PadRef(J1, 2))` cuts it
on this board (tests/test_cutout_silk_real.py), as a decided place, so the track's ends can be said."""
import json
import pathlib
import shutil

import pytest

from tests.conftest import needs_kicad

pytestmark = [needs_kicad, pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="no kicad-cli")]

pytest.importorskip("pcbnew")

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/vent_silk"
W3A = 1.37                  # 3 A on 1 oz outer copper at a 10 C rise (IPC-2221)
VENT_AT = (14.4, 31.16)     # its box x 13.65..15.15


def _run(tmp_path, past: bool):
    from placemat.cutouts import Circle
    from placemat.kicad.drc import run_drc
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    from placemat.layout import Board
    from placemat.values import CopperLayer, Cutout, Edge, Face, Location, Net, Part, Past
    shutil.copytree(FIXTURE, tmp_path / "board")
    pcb = tmp_path / "board/layout.kicad_pcb"
    b = Board(read_board(str(pcb)))
    vent = Cutout(Circle(1.5), "vent", at=Location(*VENT_AT), why="equalises two sealed chambers")
    b.rect(width=40.0, height=50.0, holes=[vent])
    b.place(Part("J1"), at=Location(17.0, 33.7), rotation=90.0, face=Face.BACK)
    middle = [Past([vent], Edge.WEST)] if past else []
    b.track(Net("GND"), [Location(14.4, 24.0)] + middle + [Location(14.4, 38.0)], layer=CopperLayer.B, width=W3A)
    plan = b.resolve()
    apply_plan(pcb, plan)
    run_drc(pcb, tmp_path / "drc.json", refill_zones=False)
    kicad = [v for v in json.loads((tmp_path / "drc.json").read_text())["violations"]
             if v["type"] == "copper_edge_clearance"]
    return plan, kicad


def test_a_3a_track_drawn_across_the_vent_is_copper_edge_as_kicad_says(tmp_path):
    plan, kicad = _run(tmp_path, past=False)
    found = [f for f in plan.findings if f.cause.value == "copper.edge"]
    assert len(found) == 1, plan.findings
    assert found[0].facts["obstacle"] == {"form": "cutout", "name": "vent"} and found[0].facts["gap_mm"] == 0.0
    assert kicad, "KiCad reports the track across the vent"


def test_past_the_vent_on_its_west_side_kicad_accepts(tmp_path):
    from placemat.copper import Track
    plan, kicad = _run(tmp_path, past=True)
    assert not [f for f in plan.findings if f.cause.value == "copper.edge"], plan.findings
    # 13.65 - 0.02 (the arc's chords) - 0.4 (this board's copper to edge) - 0.685 (half the track) = 12.545
    ends = {(round(p.x, 6), round(p.y, 6)) for t in plan.copper if isinstance(t, Track) for p in (t.start, t.end)}
    assert (12.545, 31.16) in ends, ends
    assert kicad == [], [v["description"] for v in kicad]
