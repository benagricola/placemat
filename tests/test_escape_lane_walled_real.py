"""A real board (fixtures/fairing/lane_walled, as one run wrote it, a board's session of 2026-10-03): an MCU's south fan runs
west to stubs that end 0.4 mm short of another cell's through-hole pad (a round 2 mm pad on every copper layer). The
stub of one pin has no way on, and neither track nor via fits round the pad; the stubs of its neighbours have a spot beside
the pad a via fits at, so they are not walled. The run reported none of this: a pad that copper of its own net leaves
counted as having its way out."""
import dataclasses
import pathlib

import pytest

from tests.conftest import needs_kicad

pytestmark = needs_kicad

BOARD = pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/lane_walled/layout.kicad_pcb"


@pytest.fixture(scope="module")
def walled():
    from placemat.escapes import Escapes
    from placemat.kicad.read import read_board
    from placemat.occupancy import Occupancy
    from placemat.settings import Settings
    occ = Occupancy(read_board(str(BOARD)), 1.0, settings=dataclasses.replace(Settings(), place_escape_depth=1.5))
    return Escapes(occ, mirror=False, depth=1.5).confirmed()[1]


def test_the_stub_that_ends_at_the_through_hole_pad_is_walled_off_by_the_part_that_has_it(walled):
    (found,) = [w for w in walled if (w[0], w[1]) == ("U21", "13")]
    assert found[2] == "SDA" and "U19" in {o.name for o in found[3]}


def test_the_stubs_with_a_via_spot_beside_the_pad_are_not_walled(walled):
    assert not [w for w in walled if w[0] == "U21" and w[1] in ("9", "10", "11", "12", "14")]
