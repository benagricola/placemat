"""The native ratsnest mirror answers `leaf_costs` as the Python Ratsnest
does, exactly: the weighted crossings a candidate's leaf airwires add and
the escapes they cross, with quiet nets weighted, own parts left out, and
nets replaced as parts move."""
import random

import pytest

native = pytest.importorskip("placemat_native")

from placemat.ratsnest import Anchor, Ratsnest, mst  # noqa: E402


def _random_board(rng, weights):
    py = Ratsnest(weights)
    nat = Ratsnest(weights, mirror=native.NativeRatsnest(weights))
    nets = {}
    parts = ["P%d" % i for i in range(30)] + [""]
    for n in range(rng.randint(5, 40)):
        net = "N%d" % n
        k = rng.randint(1, 8)
        grid = rng.choice((0.25, 0.5, 1.0))
        pts = [Anchor(rng.choice(parts), str(i), round(rng.uniform(0, 40) / grid) * grid,
                      round(rng.uniform(0, 40) / grid) * grid) for i in range(k)]
        nets[net] = pts
    for net, pts in nets.items():
        py.set_net(net, pts)
        nat.set_net(net, pts)
    return py, nat, nets


@pytest.mark.parametrize("seed", range(12))
def test_leaf_costs_are_the_pythons_exactly(seed):
    rng = random.Random(seed)
    weights = {"N0": 0.0, "N1": 0.25, "N2": 0.0}
    py, nat, nets = _random_board(rng, weights)
    names = sorted(nets)
    for trial in range(400):
        if trial % 50 == 49:                     # a part moves: its nets are worked out again
            net = rng.choice(names)
            pts = [Anchor(a.ref, a.number, round(rng.uniform(0, 40), 3), round(rng.uniform(0, 40), 3))
                   for a in nets[net]]
            nets[net] = pts
            py.set_net(net, pts)
            nat.set_net(net, pts)
        pads = [(rng.choice(names + ["NEW"]), round(rng.uniform(0, 40) / 0.25) * 0.25,
                 round(rng.uniform(0, 40) / 0.25) * 0.25) for _ in range(rng.randint(1, 6))]
        own = frozenset(rng.sample(["P%d" % i for i in range(30)], rng.randint(0, 3)))
        depth = rng.choice((0.5, 1.0, 3.0))
        want = Ratsnest.leaf_costs(py, pads, own, depth)
        got = nat.leaf_costs(pads, own, depth)
        assert got == want, (seed, trial, pads, own, depth)
