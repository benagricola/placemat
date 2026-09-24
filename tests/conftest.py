import os
from pathlib import Path

import pytest

ECOSYSTEM = Path(os.environ.get("MNB_ECOSYSTEM", Path.home() / "Documents/Hardware/mnb-ecosystem"))
BREAKOUT_PCB = ECOSYSTEM / "breakout/layout/Breakout/layout.kicad_pcb"


def _has_pcbnew():
    try:
        import pcbnew  # noqa: F401
        return True
    except ImportError:
        return False


needs_kicad = pytest.mark.skipif(not _has_pcbnew(), reason="pcbnew not importable")


def _placemat_native() -> bool:
    from placemat import geometry
    return geometry._native is not None


# placemat's own native path: the module built, of this release, and not
# switched off with PLACEMAT_NATIVE=0
needs_native = pytest.mark.skipif(not _placemat_native(), reason="placemat's native path is off or not built")
needs_breakout = pytest.mark.skipif(not BREAKOUT_PCB.exists(), reason="committed Breakout board not found")


@pytest.fixture(scope="session")
def breakout_pcb():
    return BREAKOUT_PCB


@pytest.fixture(scope="session")
def breakout(breakout_pcb):
    from placemat.kicad.read import read_board
    return read_board(breakout_pcb, courtyard_excess_mm=0.10)
