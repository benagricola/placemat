"""A scan's lattice made in Rust (`NativeSweepSeen.expand_grid`) is the points `placer._grid` makes and `expand` takes:
the same triples in the same order, the seen-set shared between the two ways of handing points over."""
import math
import random

import pytest

native = pytest.importorskip("placemat_native")

from placemat import placer  # noqa: E402
from placemat.values import Location  # noqa: E402


def _python(centre, radius, step, n_rots, seen, around=None):
    """What a pass did before: the points of `_grid`, filtered, expanded."""
    pts = [(x, y) for _, x, y in placer._grid(centre, radius, step)]
    if around is not None:
        pts = [(x, y) for x, y in pts if math.hypot(x - around[0], y - around[1]) <= around[2] + 1e-9]
    return seen.expand(pts, n_rots)


def test_the_lattice_made_natively_is_the_one_python_makes():
    rnd = random.Random(20261004)
    steps = (0.05, 0.1, 0.25, 0.2, 0.127, 0.5, 1.0, 0.3)
    points = 0
    for case in range(120):
        step = rnd.choice(steps)
        radius = round(rnd.uniform(0.0, 14.0), rnd.choice((1, 2, 6)))
        if case % 7 == 0:
            radius = step * rnd.randrange(0, 40)
        centre = Location(round(rnd.uniform(-60, 60), rnd.choice((1, 3, 6))), round(rnd.uniform(-40, 40), rnd.choice((1, 3, 6))))
        rots = rnd.choice((1, 2, 4, 8))
        py_seen, rs_seen = native.NativeSweepSeen(), native.NativeSweepSeen()
        for second in range(3):                     # repeated passes on one scan: what the first made is not made again
            c2 = Location(centre.x + rnd.choice((0.0, step, 0.5 * step)), centre.y) if second else centre
            around = (centre.x, centre.y, radius) if second == 2 else None
            r2 = radius if not second else radius / rnd.choice((1.0, 2.0, 3.0))
            want = _python(c2, r2, step, rots, py_seen, around)
            got = rs_seen.expand_grid(c2.x, c2.y, r2, step, rots, around)
            assert got == want, (case, second, len(got), len(want))
            points += len(got)
    assert points > 100000, points
