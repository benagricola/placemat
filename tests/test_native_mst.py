"""The native minimum spanning tree is `ratsnest.mst`'s: the same airwires
in the same order, ties broken by KiCad's order key, copper-joined pads
pre-united."""
import random

import pytest

native = pytest.importorskip("placemat_native")

from placemat.ratsnest import Anchor  # noqa: E402


def _python_mst(net, anchors, joined):
    from placemat import geometry, ratsnest
    was = geometry._native
    geometry._native = None
    try:
        return ratsnest.mst(net, anchors, joined)
    finally:
        geometry._native = was


@pytest.mark.parametrize("seed", range(30))
def test_the_tree_is_the_pythons(seed):
    rng = random.Random(seed)
    grid = rng.choice((0.1, 0.25, 0.5, 1.0))
    n = rng.randint(2, 60)
    anchors = [Anchor(rng.choice(("A", "B", "C", "")), str(rng.randint(1, 9)),
                      round(rng.uniform(0, 20) / grid) * grid, round(rng.uniform(0, 20) / grid) * grid) for _ in range(n)]
    joined = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < 0.02]
    pairs = native.mst([(a.x, a.y, a.ref, a.number) for a in anchors], joined)
    want = [(anchors.index(e.a), anchors.index(e.b)) for e in _python_mst("N", anchors, joined)]
    got = [(i, j) for i, j in pairs]
    # anchors may repeat by value; compare the edges' anchors themselves
    assert [(anchors[i], anchors[j]) for i, j in got] == [(anchors[i], anchors[j]) for i, j in want]
