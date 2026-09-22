"""polys_overlap skips what its bounding boxes rule out, and answers as the
full edge-by-edge test does."""
import math
import random

from placemat import geometry
from placemat.geometry import _edges, point_in_polygon, segments_intersect, _strictly_inside


def reference(a, b):
    """polys_overlap as it was before the box tests, verbatim."""
    if point_in_polygon(a[0], b) or point_in_polygon(b[0], a):
        return True
    for p1, p2 in _edges(a):
        for q1, q2 in _edges(b):
            if segments_intersect(p1, p2, q1, q2):
                return True
    return any(_strictly_inside(p, b) for p in a[1:]) or any(_strictly_inside(q, a) for q in b[1:])


def _poly(rng, cx, cy, r, n, concave):
    pts = []
    for k in range(n):
        t = 2 * math.pi * k / n
        rr = r * (rng.uniform(0.4, 1.0) if concave else 1.0)
        pts.append((round(cx + rr * math.cos(t), 3), round(cy + rr * math.sin(t), 3)))
    return tuple(pts)


def _rect(x0, y0, x1, y1):
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def test_random_polygons_answer_as_the_full_test_does():
    rng = random.Random(3)
    for _ in range(4000):
        a = _poly(rng, rng.uniform(0, 10), rng.uniform(0, 10), rng.uniform(0.2, 4), rng.choice([4, 6, 16, 60]), rng.random() < 0.5)
        if rng.random() < 0.5:
            x, y = rng.uniform(0, 10), rng.uniform(0, 10)
            b = _rect(x, y, x + rng.uniform(0.1, 3), y + rng.uniform(0.1, 3))
        else:
            b = _poly(rng, rng.uniform(0, 10), rng.uniform(0, 10), rng.uniform(0.2, 4), rng.choice([4, 12, 200]), rng.random() < 0.5)
        assert geometry.polys_overlap(a, b) == reference(a, b), (a, b)
        assert geometry.polys_overlap(b, a) == reference(b, a), (a, b)


def test_edge_cases_of_touching_and_containment():
    big = _rect(0, 0, 10, 10)
    cases = [
        (_rect(10, 0, 12, 2), big),                    # sharing an edge
        (_rect(10, 10, 12, 12), big),                  # sharing a corner
        (_rect(2, 2, 3, 3), big),                      # inside
        (_rect(-1, -1, 11, 11), big),                  # around
        (((0.0, 5.0), (1.0, 4.0), (2.0, 5.0), (1.0, 6.0)), big),   # inside, a vertex on the edge
        (_rect(0, 0, 10, 10), big),                    # the same
        (_rect(10.000001, 0, 12, 2), big),             # just apart
        (_rect(-2, 3, 0, 5), big), (_rect(3, -2, 5, 0), big), (_rect(3, 10, 5, 12), big),   # touching each side
        (_rect(-2, -2, 0, 0), big), (_rect(10, -2, 12, 0), big), (_rect(-2, 10, 0, 12), big),  # and each corner
        (((10.0, 5.0), (12.0, 3.0), (12.0, 7.0)), big),                                   # a vertex on the edge, outside
    ]
    for a, b in cases:
        assert geometry.polys_overlap(a, b) == reference(a, b), a
        assert geometry.polys_overlap(b, a) == reference(b, a), a
