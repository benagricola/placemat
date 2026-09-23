"""A reservation answers "does this box overlap you" from a raster of cells
wholly inside, wholly outside or crossed by its outline, and asks the exact
polygon test only when the box touches a crossed cell."""
import math
import random

from placemat.geometry import box_polygon, polys_overlap
from placemat.occupancy import Reservation
from placemat.values import Box


def _ring(cx, cy, r_in, r_out, n):
    outer = [(cx + r_out * math.cos(2 * math.pi * k / n), cy + r_out * math.sin(2 * math.pi * k / n)) for k in range(n + 1)]
    inner = [(cx + r_in * math.cos(2 * math.pi * k / n), cy + r_in * math.sin(2 * math.pi * k / n)) for k in range(n, -1, -1)]
    return tuple(outer + inner)


def _concave(rng, n):
    return tuple((25 + rng.uniform(8, 20) * math.cos(2 * math.pi * k / n), 25 + rng.uniform(8, 20) * math.sin(2 * math.pi * k / n))
                 for k in range(n))


def test_the_raster_answers_as_the_polygon_test_does():
    rng = random.Random(5)
    polys = [_ring(25, 25, 19, 21, 160), _ring(25, 25, 4, 22, 300), _concave(rng, 80),
             ((5.0, 5.0), (45.0, 5.0), (45.0, 45.0), (5.0, 45.0)), ((10.0, 10.0), (12.0, 10.0), (12.0, 13.0), (10.0, 13.0))]
    for poly in polys:
        r = Reservation(poly, "test", frozenset(), None)
        for _ in range(3000):
            x, y = rng.uniform(-2, 52), rng.uniform(-2, 52)
            body = Box(x, y, x + rng.uniform(0.2, 6), y + rng.uniform(0.2, 6))
            assert r.overlaps(body) == polys_overlap(poly, box_polygon(body)), (poly[:2], body)


def test_boxes_on_the_raster_lines_and_on_the_outline_answer_as_the_polygon_test_does():
    poly = ((5.0, 5.0), (45.0, 5.0), (45.0, 45.0), (5.0, 45.0))
    r = Reservation(poly, "test", frozenset(), None)
    for body in (Box(45.0, 10.0, 47.0, 12.0), Box(3.0, 10.0, 5.0, 12.0), Box(10.0, 10.0, 10.25, 10.25),
                 Box(5.0, 5.0, 45.0, 45.0), Box(44.9, 44.9, 46.0, 46.0), Box(0.0, 0.0, 50.0, 50.0)):
        assert r.overlaps(body) == polys_overlap(poly, box_polygon(body)), body


def test_a_reservations_box_is_worked_out_once():
    r = Reservation(((0.0, 0.0), (2.0, 0.0), (2.0, 1.0)), "t", frozenset(), None)
    assert r.box is r.box
