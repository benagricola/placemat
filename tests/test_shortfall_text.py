"""A finding never prints a shortfall so that it reads as the limit: "is 0.10 mm (needs 0.10)" for a gap of 0.0986."""
import re

import pytest

from placemat.geometry import gap_texts
from placemat.layout import Board, _shape_of
from placemat.copper import Track
from placemat.values import CopperLayer, Location, Net
from tests.fixtures import board_geometry, footprint


@pytest.mark.parametrize("gap, need, want", [
    (0.0986, 0.10, ("0.099", "0.100")),
    (0.0999, 0.10, ("0.0999", "0.1000")),
    (0.05, 0.10, ("0.05", "0.10")),
    (0.1004, 0.1005, ("0.100", "0.101")),
    (0.0, 0.2, ("0.00", "0.20")),
    (-0.3, 0.2, ("0.00", "0.20")),
    (0.2, 0.2, ("0.20", "0.20")),
    (0.1999999999, 0.2, ("0.20", "0.20")),
])
def test_a_gap_under_the_limit_never_reads_as_the_limit(gap, need, want):
    assert gap_texts(gap, need) == want


def test_the_copper_finding_for_a_leg_just_inside_the_clearance_shows_the_shortfall():
    plan = _board(20.0 + 0.225 + 0.127 + 0.1986)
    assert plan.occupancy.copper_conflicts(_leg(plan))
    words = " ".join(plan.occupancy.copper_conflicts(_leg(plan)))
    m = re.search(r"is ([0-9.]+) mm from .*\(needs ([0-9.]+)", words)
    assert m and float(m.group(1)) < float(m.group(2)), words


def _leg(plan):
    return _shape_of(Track("SIG", CopperLayer.F, 0.254, Location(plan.leg_x, 19.0), Location(plan.leg_x, 21.0)))


def _board(x):
    cap = footprint("C1", 30, 30, w=2, h=1, inst="c1", nets=("A", "B"))
    b = Board(board_geometry([cap], width=40, height=40, extra_nets=["GND", "SIG"]), edge_margin=0.5, keep_going=True)
    b.via(Net("GND"), Location(20.0, 20.0), drill=0.2, size=0.45)
    plan = b.resolve()
    plan.leg_x = x
    return plan


def test_a_hole_is_measured_as_its_circle_not_as_a_polygon_inside_it():
    from placemat.geometry import box_polygon, circle_poly_gap
    from placemat.values import Box
    wall = box_polygon(Box(0.3, -1.0, 1.0, 1.0))
    assert circle_poly_gap(Location(0.0, 0.0), 0.1, wall) == pytest.approx(0.2, abs=1e-12)
    assert circle_poly_gap(Location(0.5, 0.0), 0.1, wall) == pytest.approx(-0.1)
