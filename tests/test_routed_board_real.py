"""A routed real board (fixtures/fairing/routed: a whole board after its route, KiCad's DRC clean on copper), read
as placemat reads it: its current paths, its stamped cells' labels and the gaps of its copper."""
import dataclasses
import math
from pathlib import Path

import pytest

from tests.conftest import needs_kicad

pytestmark = needs_kicad

BOARD = Path(__file__).resolve().parent.parent / "fixtures" / "fairing" / "routed" / "layout.kicad_pcb"
_read = {}


@pytest.fixture
def geometry():
    if not _read:
        from placemat.kicad.read import read_board
        _read["g"] = read_board(str(BOARD))
    return _read["g"]


def test_the_ground_net_is_judged_on_its_planes_not_a_sliver(geometry):
    """Through-hole carriers joined by inner planes on every layer: the
    widest route between them is the planes', not a sliver where two fills
    of the front layer meet (0.05 mm, one step, before)."""
    from placemat.checks import ZONE_STEP, current_paths
    v = {x.subject: x for x in current_paths(geometry)}["GND"]
    assert v.value > 1.0, v.note
    assert "one %g mm step or less" % ZONE_STEP not in v.note, v.note
