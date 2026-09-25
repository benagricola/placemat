"""A scan judged natively (Occupancy.native_sweeper) gives what the
pure-Python sweep gives: every scan's chosen placement, tried count,
refusal tallies, first sentences and blockers, and so the whole plan, on
every benchmark module under each configuration."""
import sys
from pathlib import Path

import pytest

native = pytest.importorskip("placemat_native")

from tests.conftest import needs_kicad, needs_native  # noqa: E402

pytestmark = [needs_native, needs_kicad]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fixtures"))
import bench  # noqa: E402


def _record(monkeypatch):
    from placemat import placer
    seen = []

    class Recorded(placer.ScanResult):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            seen.append(self)
    monkeypatch.setattr(placer, "ScanResult", Recorded)
    return seen


def _summary(results):
    return [(r.chosen, r.tried, list(r.rejected.items()), list(r.reasons.items()), list(r.blockers.items()),
             getattr(r, "score", None)) for r in results]


def _plan(plan):
    return ([(s.item, s.placement, s.note) for s in plan.steps], [(f.kind, str(f)) for f in plan.findings])


MODULES = [p for p in bench.boards()
           if bench._name(p) in ("fairing/SlotControl", "fairing/Mcu", "fairing/UsbPd", "fairing/Environment",
                                 "mnb/MCU_RP2350B", "mnb/CanFrontendDiscrete")]


@pytest.mark.parametrize("config", sorted(bench.CONFIGS))
@pytest.mark.parametrize("pcb", MODULES, ids=bench._name)
def test_a_native_sweep_is_the_python_sweep(pcb, config, monkeypatch):
    from placemat import placer
    from placemat.kicad.read import read_board
    g = read_board(pcb)
    make = bench.ModuleBoard(g, bench.CONFIGS[config], bench._planes(g), bench._size(g, True))
    runs = {}
    for on in (False, True):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", on)
        seen = _record(monkeypatch)
        plan = make().resolve()
        runs[on] = (_summary(seen), _plan(plan))
    assert runs[True][0] == runs[False][0]
    assert runs[True][1] == runs[False][1]
