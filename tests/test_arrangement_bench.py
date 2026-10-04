"""The arrangement bench set (fixtures/bench.py --arrangements), run on a tiny board of two stamped cells: every cell gets a
synthetic note, the note stands, and the board is resolved free and firm with arrangements off and on."""
import importlib.util
import pathlib

from tests.arrangement_support import kicad_cell_board
from tests.conftest import needs_kicad

pytestmark = needs_kicad
BENCH = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "bench.py"


def load():
    spec = importlib.util.spec_from_file_location("bench", BENCH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_arrangement_bench_resolves_a_board_of_noted_cells_with_arrangements_off_and_on(tmp_path):
    pcb = kicad_cell_board(tmp_path / "cells.kicad_pcb", cells=(("ma", (10.0, 10.0)), ("mb", (40.0, 30.0))))
    out = load().bench_arrangements(module=None, board=pcb, outline=[(0.0, 0.0), (80.0, 0.0), (80.0, 60.0), (0.0, 60.0)], repeats=1)
    assert set(out) == {"board", "firm"}
    for case in ("board", "firm"):
        row = out[case]
        assert row["cells"] == 2 and row["offered"] == 2, case          # each cell's note stands
        assert row["off_placed"] == row["on_placed"] == 2, case
        assert row["off_taken"] == 0 and 0 <= row["on_taken"] <= 2, case  # off lays every cell's default
        assert row["off_s"] > 0 and row["on_s"] > 0, case
        assert isinstance(row["off_score"], float) and isinstance(row["on_score"], float), case
    assert out["board"]["plain_s"] > 0                                  # the same board without notes
    assert "--arrangements" in BENCH.read_text()
