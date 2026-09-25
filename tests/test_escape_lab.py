"""The escape lab builds the same board from the same case every time: KiCad
writes a board's items in UUID order, and the router's outcome depends on the
order it reads them in, so random UUIDs made one case route differently from
build to build."""
import sys
from pathlib import Path

import pytest

from tests.conftest import needs_kicad

pytestmark = [needs_kicad]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fixtures"))
CHIP = Path.home() / "Documents/Hardware/mnb-ecosystem/parts/Raspberry_Pi_RP2350B/QFN-80_L10.0-W10.0-P0.40-TL-EP3.4.kicad_mod"


@pytest.mark.skipif(not CHIP.exists(), reason="the chip footprint is not on this machine")
def test_the_same_case_builds_the_same_board(tmp_path):
    import subprocess
    code = ("import sys, pathlib; sys.path.insert(0, %r); sys.path.insert(0, %r); import escape_lab as L;"
            "c = [c for c in L.cap_cases(%r, '11') if c.name == 'cap-0402-radial-s0.4-g0.5'][0];"
            "L.build(c, 'two', %r, pathlib.Path(sys.argv[1]))") % (str(ROOT / "fixtures"), str(ROOT / "src"), str(CHIP), str(CHIP))
    for k in (1, 2):
        subprocess.run([sys.executable, "-c", code, str(tmp_path / str(k))], check=True, capture_output=True)
    assert (tmp_path / "1" / "board.kicad_pcb").read_text() == (tmp_path / "2" / "board.kicad_pcb").read_text()
