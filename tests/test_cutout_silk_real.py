"""A real board (fixtures/fairing/vent_silk, a back-face two-pin connector as a run wrote it): a round vent searched by
the connector's pad 2 (`Cutout(Circle(1.5), at=Near(PadRef(...)))`) was cut where its box clears the connector's pads and
silk, 0.1466 mm from the connector's back silk. KiCad's DRC judges silk against Edge.Cuts by the board's silk clearance
(0.2 mm) and reported silk_edge_clearance three times. The search now keeps that clearance from the silk of every part
already placed, on either face."""
import json
import pathlib
import shutil

import pytest

from tests.conftest import needs_kicad

pytestmark = [needs_kicad, pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="no kicad-cli")]

pytest.importorskip("pcbnew")

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/vent_silk"


def _run(tmp_path):
    from placemat.cutouts import Circle
    from placemat.kicad.drc import run_drc
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    from placemat.layout import Board
    from placemat.values import Cutout, Face, Location, Near, PadRef, Part
    shutil.copytree(FIXTURE, tmp_path / "board")
    pcb = tmp_path / "board/layout.kicad_pcb"
    g = read_board(str(pcb))
    b = Board(g)
    b.rect(width=40.0, height=50.0,
           holes=[Cutout(Circle(1.5), "vent", at=Near(PadRef(Part("J1"), 2)), why="airflow by the connector")])
    b.place(Part("J1"), at=Location(17.0, 33.7), rotation=90.0, face=Face.BACK)
    plan = b.resolve()
    apply_plan(pcb, plan)
    report = run_drc(pcb, tmp_path / "drc.json", refill_zones=False)
    found = [v for v in json.loads((tmp_path / "drc.json").read_text())["violations"]
             if v["type"] == "silk_edge_clearance"]
    return plan, report, found


def test_the_vent_keeps_the_silk_clearance_from_the_connectors_back_silk(tmp_path):
    plan, _report, found = _run(tmp_path)
    vent = plan.cutouts_placed["vent"].centre
    assert found == [], (vent, [v["description"] for v in found])
    # still by its pad, whose centre is at (17.0, 31.16): the first spot of the search that clears the silk
    assert ((vent.x - 17.0) ** 2 + (vent.y - 31.16) ** 2) ** 0.5 < 3.0, vent
