"""A real board (fixtures/fairing/lane_walled, as one run wrote it, a board's session of 2026-10-03): an MCU's south fan runs
west to stubs that end 0.4 mm short of another cell's through-hole pad (a round 2 mm pad on every copper layer). Five
stubs have no track on their layer past the pad, and one of them no via spot either; the sixth can run on south. The run reported none of this: a pad that copper of its own net leaves
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


def test_the_stubs_of_the_fan_that_end_at_the_through_hole_pad_are_walled_off_by_the_part_that_has_it(walled):
    for number in ("9", "10", "11", "12", "13"):
        (found,) = [w for w in walled if (w[0], w[1]) == ("U21", number)]
        assert "U19" in found[3], found


def test_the_last_stub_has_a_clear_run_south_past_the_pad_and_is_not_walled(walled):
    """Its end is level with the pad's centre, 0.4 mm off its edge, and a track runs on south to the edge of the window
    (1.5 mm round the stub) with nothing in the way."""
    assert not [w for w in walled if (w[0], w[1]) == ("U21", "14")]


def test_with_a_via_counted_as_a_way_out_only_the_stub_with_no_via_spot_is_walled():
    import dataclasses as dc
    from placemat.escapes import Escapes
    from placemat.kicad.read import read_board
    from placemat.occupancy import Occupancy
    from placemat.settings import Settings
    st = dc.replace(Settings(), place_escape_depth=1.5, place_escape_lane_via_exit=True)
    occ = Occupancy(read_board(str(BOARD)), 1.0, settings=st)
    fan = {w[1] for w in Escapes(occ, mirror=False, depth=1.5).confirmed()[1] if w[0] == "U21"}
    assert {"13"} <= fan and not fan & {"9", "10", "11", "12", "14"}
