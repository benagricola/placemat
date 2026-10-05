"""The pin map study on a real laid board with an MCU (fixtures/pinmap/reference.json, its annotations given there): the
best map beats the present one, every pose searched inside `pins.budget_ms` on the native core, and no board item
moves. On the Python fallback a study may run out of its budget part way; only the best map is asserted there."""
import hashlib
import importlib.util
from pathlib import Path

from placemat.settings import Settings
from tests.conftest import needs_kicad

BENCH = Path(__file__).resolve().parents[1] / "fixtures" / "pinmap_bench.py"


def bench():
    spec = importlib.util.spec_from_file_location("pinmap_bench", BENCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@needs_kicad
def test_on_a_real_board_the_best_map_beats_the_present_one_inside_its_budget_and_nothing_moves():
    from placemat.kicad.read import read_board
    from placemat.pinmap_core import native_core, study
    b = bench()
    case = b.cases()[0]
    pcb = b.HERE / case["board"]
    digest = hashlib.sha256(pcb.read_bytes()).hexdigest()
    inp = b.input_of(case)
    (ref,) = case["parts"]
    (g,) = [g for g in study(inp, Settings()) if ref in g.refs]
    best = min(g.results, key=lambda r: r.breakdown.total)
    assert best.breakdown.total < g.present.total
    if native_core() is not None:
        assert g.budget_out is False and g.searched == g.of
    assert hashlib.sha256(pcb.read_bytes()).hexdigest() == digest
    where = lambda geometry: [(fp.ref, fp.location, fp.rotation, fp.face) for fp in geometry.footprints]
    assert where(read_board(pcb)) == where(b.board_of(case))
