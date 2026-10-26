"""Board._ride_turn: riders that move with their host at a turn are laid once for it, though positions rounded to
1e-6 mm can put the two probes' offsets one rounding step apart."""
from placemat import layout
from placemat.layout import Board
from placemat.placement import Placement
from placemat.values import Location
from tests.fixtures import board_geometry, footprint


def _board():
    return Board(board_geometry([footprint("U1", 10, 10, w=4, h=4, inst="u1", nets=("A", "B"))], width=50, height=50))


def _probes(step):
    """A _ride whose rider sits at (host + 1.25, host - 0.5), the shifted probe's off by `step` on x."""
    def ride(occ, plan, i, at, others, board=False):
        x = at.location.x + 1.25 + (step if at.location.x != 20.0 else 0.0)
        return [("r", Placement(Location(x, at.location.y - 0.5), 0.0, at.face), None, None, None)]
    return ride


def test_offsets_one_rounding_step_apart_still_move_with_the_host(monkeypatch):
    b = _board()
    monkeypatch.setattr(b, "_ride", _probes(-1.0000000001e-06))
    at = Placement(Location(20.0, 20.0), 0.0, None)
    got = b._ride_turn(None, None, None, at)
    assert got is not None and got[0] == at and got[1][0][1].location.x == 21.25


def test_a_rider_that_does_not_move_with_the_host_is_laid_per_candidate(monkeypatch):
    b = _board()
    monkeypatch.setattr(b, "_ride", _probes(0.05))
    assert b._ride_turn(None, None, None, Placement(Location(20.0, 20.0), 0.0, None)) is None
    assert layout._RIDE_EXACT < 0.05
