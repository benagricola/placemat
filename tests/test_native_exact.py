"""The native module's arithmetic lands on CPython's bits: `math.hypot` (its
own algorithm, not the C library's) and `round(v, 9)` (geometry._clean), on
ten million values each, the hard cases included."""
import math
import os
import random
import struct

import pytest

native = pytest.importorskip("placemat_native")

# Ten million each was run when the port was made; the suite runs one million
# (PLACEMAT_EXACT_N=10000000 for the full count).
N = int(os.environ.get("PLACEMAT_EXACT_N", 1_000_000))


def _floats(n, rng):
    """Values like placemat's: millimetres on fab grids, sums and products
    of them, random magnitudes, and every tie class at the ninth decimal."""
    out = []
    grids = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.127, 0.2, 0.25, 0.5, 1.0, 2.54)
    while len(out) < n:
        k = rng.randrange(8)
        if k == 0:
            out.append(rng.uniform(-300, 300))
        elif k == 1:
            out.append(rng.randrange(-30000, 30000) * rng.choice(grids))
        elif k == 2:
            out.append(rng.randrange(-30000, 30000) * rng.choice(grids) + rng.randrange(-3000, 3000) * rng.choice(grids))
        elif k == 3:
            out.append(rng.randrange(-10 ** 12, 10 ** 12) / 1e9 + rng.choice((5e-10, -5e-10)))  # a half at the ninth place
        elif k == 4:
            out.append(rng.uniform(-1, 1) * 10 ** rng.randrange(-12, 7))
        elif k == 5:
            out.append(struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0])
        elif k == 6:
            out.append(math.cos(rng.uniform(0, 7)) * rng.uniform(-50, 50) + rng.uniform(-100, 100))
        else:
            out.append(rng.choice((0.0, -0.0, 1e-10, -1e-10, 5e-10, -5e-10, 1.5e-9, 2.5e-9, 1e300, -1e-300)))
    return out[:n]


def _clean(v):
    r = round(v, 9)
    return 0.0 if r == 0 else r


def test_clean9_is_rounds_to_nine_places_bit_for_bit():
    rng = random.Random(1)
    vs = [v for v in _floats(N, rng) if math.isfinite(v)]
    got = native.clean9_many(vs)
    bad = [(v, a) for v, a in zip(vs, got) if struct.pack("<d", a) != struct.pack("<d", _clean(v))]
    assert not bad, bad[:5]


def test_hypot_is_cpythons_bit_for_bit():
    rng = random.Random(2)
    xs = _floats(N, rng)
    ys = _floats(N, rng)
    pairs = [(x, y) for x, y in zip(xs, ys) if math.isfinite(x) and math.isfinite(y)]
    pairs += [(3.0, 4.0), (1e-310, 1e-310), (5e-324, 0.0), (1e308, 1e308), (0.0, 0.0), (1.0, 1.0),
              (2.0 ** -1074, 2.0 ** -1073), (1.7976931348623157e308, 1.0)]
    got = native.hypot_many([p[0] for p in pairs], [p[1] for p in pairs])
    bad = [(x, y, g) for (x, y), g in zip(pairs, got) if struct.pack("<d", g) != struct.pack("<d", math.hypot(x, y))]
    assert not bad, bad[:5]
