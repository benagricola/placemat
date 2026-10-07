"""The search compares a candidate as (pads walled off, cost) (D13): one that walls a pad loses to any that walls none,
whatever the costs; a candidate the scorer did not weigh (pruned) ranks below every one weighed in full."""
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.placer import UNWEIGHED, scan
from placemat.values import Face, Location
from tests.fixtures import board_geometry, footprint


def _scan(score):
    fps = [footprint("R1", 30, 30, w=2, h=1, inst="r1")]
    occ = Occupancy(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    return scan(occ, fps[0], Placement(Location(30, 30), 0, Face.FRONT), 2.0, 0.5, (0,), score=score)


def test_a_spot_that_walls_a_pad_loses_to_any_that_walls_none_whatever_the_cost():
    near = lambda p: abs(p.location.x - 30) + abs(p.location.y - 30)
    r = _scan(lambda p: (1, near(p)) if p.location.x < 31.5 else (0, 1000.0 + near(p)))
    assert r.chosen.location == Location(31.5, 30) and r.walled == 0 and r.score == 1001.5


def test_among_spots_that_wall_pads_the_fewest_wins():
    r = _scan(lambda p: (2, 0.0) if p.location.x < 31.5 else (1, 50.0 + abs(p.location.y - 30)))
    assert r.chosen.location == Location(31.5, 30) and r.walled == 1


def test_an_unweighed_spot_ranks_below_one_that_walls_a_pad():
    r = _scan(lambda p: (UNWEIGHED, 1e6) if p.location.x < 31.5 else (3, 500.0 + abs(p.location.y - 30)))
    assert r.chosen.location.x >= 31.5 and r.walled == 3
