"""The native escape mirror answers `Escapes.closed` as the Python one does:
on real module boards, for every part at many spots and turns, and still
after parts are lifted, moved and put back and copper is planned."""
import random
import sys
from pathlib import Path

import pytest

native = pytest.importorskip("placemat_native")

from tests.conftest import needs_native  # noqa: E402

pytestmark = [needs_native]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fixtures"))
import bench  # noqa: E402

MODULES = [p for p in bench.boards() if bench._name(p) in ("fairing/SlotControl", "fairing/Mcu", "mnb/MCU_RP2350B")]


def _both(occ, item, placement):
    from placemat.escapes import Escapes
    py = occ.__dict__.setdefault("_py_escapes", Escapes(occ, mirror=False))
    return occ.escapes().closed(item, placement, 0), py.closed(item, placement, 0)


@pytest.mark.parametrize("pcb", MODULES, ids=bench._name)
def test_closed_is_the_pythons_on_a_real_board(pcb):
    from placemat.kicad.read import read_board
    from placemat.placement import Placement
    from placemat.values import Location
    g = read_board(pcb)
    plan = bench.ModuleBoard(g, {}, bench._planes(g), bench._size(g, True))().resolve()
    occ = plan.occupancy
    rng = random.Random(len(g.footprints))
    fps = [fp for fp in g.footprints if fp.ref in occ.items and fp.ref not in occ.pending]
    nonzero = 0
    for trial in range(1500):
        if trial % 300 == 299:                          # a part lifted and put back elsewhere
            fp = rng.choice(fps)
            occ.lift([fp.ref])
            was = occ.items[fp.ref].reference
            occ.commit(fp, Placement(Location(was.location.x + rng.uniform(-2, 2), was.location.y + rng.uniform(-2, 2)),
                                     was.rotation, was.face))
            py = occ.__dict__.get("_py_escapes")
            if py is not None:
                py.refresh({fp.ref})
        fp = rng.choice(fps)
        at = occ.items[fp.ref].reference
        pl = Placement(Location(at.location.x + rng.uniform(-3, 3), at.location.y + rng.uniform(-3, 3)),
                       rng.choice((0.0, 90.0, 180.0, 270.0)), at.face)
        got, want = _both(occ, fp, pl)
        assert got == want, (trial, fp.ref, pl)
        nonzero += got != (0, 0, 0)
    assert nonzero > 50                                 # the question was a real one
