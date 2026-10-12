"""The crossing counts the one-score search asks often, counted without listing: `Ratsnest.crossed_pairs` is the length of
`crossed_pair_list`, and `count_crossings` is `segments_cross` summed over every pair, on random boards with airwires
on a coarse grid (so many touch, end on each other or run along each other) and with long airwires."""
import random

import pytest

from placemat.ratsnest import Anchor, Ratsnest, count_crossings, mst, nm_segment, segments_cross


def _board(rng, spread):
    rn = Ratsnest()
    parts = ["P%d" % i for i in range(12)] + [""]
    for n in range(rng.randint(5, 30)):
        grid = rng.choice((0.25, 0.5, 1.0))
        rn.set_net("N%d" % n, [Anchor(rng.choice(parts), str(i), round(rng.uniform(0, spread) / grid) * grid,
                                      round(rng.uniform(0, spread) / grid) * grid) for i in range(rng.randint(1, 8))])
    return rn


@pytest.mark.parametrize("seed", range(40))
def test_crossed_pairs_is_the_listed_count(seed):
    rng = random.Random(seed)
    rn = _board(rng, rng.choice((6.0, 20.0, 80.0)))
    for depth in (0.5, 1.0, 3.0, 100.0):
        assert rn.crossed_pairs(depth) == len(rn.crossed_pair_list(depth))


@pytest.mark.parametrize("seed", range(20))
def test_count_crossings_is_segments_cross_summed(seed):
    rng = random.Random(seed)
    nets = []
    for n in range(2):
        grid = rng.choice((0.5, 1.0))
        pts = [Anchor("P", str(i), round(rng.uniform(0, 10) / grid) * grid, round(rng.uniform(0, 10) / grid) * grid)
               for i in range(rng.randint(2, 12))]
        nets.append(mst("N%d" % n, pts))
    a, b = nets
    expected = sum(segments_cross((e.a.x, e.a.y), (e.b.x, e.b.y), (f.a.x, f.a.y), (f.b.x, f.b.y)) for e in a for f in b)
    assert count_crossings([nm_segment(e) for e in a], [nm_segment(f) for f in b]) == expected
