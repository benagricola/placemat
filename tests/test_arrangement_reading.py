# tests/test_arrangement_reading.py
import pytest

from placemat import arrangement_note as N
from placemat.kicad.read import read_board
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Location
from tests.arrangement_support import east_doc, kicad_cell_board
from tests.conftest import needs_kicad

pytestmark = needs_kicad


def test_a_cells_notes_are_read_into_its_arrangements(tmp_path):
    pcb = kicad_cell_board(tmp_path / "layout.kicad_pcb", notes={"mod": N.encode(east_doc(), 4000)})
    cell = read_board(pcb).cell("mod")
    assert cell.offered() == ("c_in.east",) and cell.arrangement_problems == ()
    arr = cell.arrangements[0]
    assert abs(arr.geom.box.center.x - cell.box.center.x) > 1.0
    assert {m.inst for m in arr.members} == {"c_in", "u1"}


def test_a_cell_with_no_note_reads_as_it_always_did(tmp_path):
    pcb = kicad_cell_board(tmp_path / "layout.kicad_pcb")
    cell = read_board(pcb).cell("mod")
    assert cell.arrangements == () and cell.arrangement_problems == ()


def test_a_note_that_cannot_stand_is_a_finding_and_the_cell_places_as_its_default(tmp_path):
    """Review focus 2: a newer note version and a truncated numbered note, through KiCad's save and load."""
    texts = N.encode(dict(east_doc(), v=2), 4000) + N.encode(east_doc("c_in.t"), 40)[:-1]
    pcb = kicad_cell_board(tmp_path / "layout.kicad_pcb", notes={"mod": texts})
    g = read_board(pcb)
    assert g.cell("mod").offered() == () and sorted(p["reason"] for p in g.cell("mod").arrangement_problems) == ["text", "version"]
    from placemat.values import Cell
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.place(Cell("mod"), at=Location(40.0, 30.0))
    plan = b.resolve()
    stale = [f for f in plan.findings if f.cause == "arrangement.stale"]
    assert sorted(f.facts["reason"] for f in stale) == ["text", "version"] and all(f.facts["cell"] == "mod" for f in stale)
    assert plan.placement("mod") is not None and plan.placement("mod").arrangement == ""
