"""pourfit.py: the geometry behind a fitted pour. Pure."""
import math
import random

import pytest

from placemat import pourfit

SAG = 0.02


def _rect(cx, cy, w, h):
    return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]


@pytest.mark.parametrize("r", [0.1, 0.5, 2.0])
@pytest.mark.parametrize("pts", [[(0.0, 0.0)], [(0.0, 0.0), (3.0, 1.0)], [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)]])
def test_a_grown_outline_circumscribes_its_arcs_within_the_sag(r, pts):
    """No edge comes nearer the points than `r`, and no corner stands further than `r` plus the sag."""
    poly = pourfit.grown(pts, r, SAG)
    n = len(poly)
    assert pourfit.convex(poly)
    assert all(min(pourfit._seg_gap(p, poly[i], poly[(i + 1) % n]) for i in range(n)) >= r - 1e-9 for p in pts)
    hull = pourfit.hull(pts)

    def reach(q):
        if len(hull) == 1:
            return math.hypot(q[0] - hull[0][0], q[1] - hull[0][1])
        return pourfit._seg_gap(q, *hull) if len(hull) == 2 else pourfit._edge_gap(hull, q)
    assert max(reach(q) for q in poly) <= r + SAG + 1e-9


def test_a_pad_cut_by_a_piece_is_held_inside_its_edges_by_the_margin():
    pad = pourfit.hull(_rect(0.0, 0.0, 1.0, 1.0))
    other = pourfit.pieces_of(_rect(0.0, 1.2, 1.0, 1.0), 0.26, SAG, "other")        # 0.2 mm off: its clearance outline reaches 0.06 into the pad
    held = pourfit.inset(pad, 0.12)
    assert _box_of(held) == pytest.approx((-0.38, -0.38, 0.38, 0.38))
    assert all(not pc.contains(p) for p in held for pc in other)
    assert any(pc.contains(p) for p in pad for pc in other) or any(
        pc.blocks(pad[i], pad[(i + 1) % 4]) for i in range(4) for pc in other)


def _box_of(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def _trial(seed):
    rnd = random.Random(seed)
    holds = [("P%d" % i, pourfit.hull(_rect(rnd.uniform(0, 12), rnd.uniform(0, 12), rnd.uniform(0.4, 1.5),
                                            rnd.uniform(0.4, 1.5)))) for i in range(rnd.randint(3, 5))]
    pieces = []
    for k in range(rnd.randint(1, 8)):
        cx, cy = rnd.uniform(-1, 13), rnd.uniform(-1, 13)
        kind = rnd.choice(["pad", "via", "track"])
        if kind == "pad":
            pieces += pourfit.pieces_of(_rect(cx, cy, rnd.uniform(.3, 1.5), rnd.uniform(.3, 1.5)), 0.265, 0.015, "pad%d" % k)
        elif kind == "via":
            pieces += pourfit.pieces_of((), 0.265, 0.015, "via%d" % k, circle=(cx, cy, rnd.uniform(.2, .5)))
        else:
            a, length = rnd.uniform(0, 6.28), rnd.uniform(1, 6)
            pieces += pourfit.pieces_of(_rect(cx, cy, .2, .2), 0.265, 0.015, "trk%d" % k,
                                        ends=((cx, cy), (cx + length * math.cos(a), cy + length * math.sin(a))))
    return holds, pieces, pourfit.fit(holds, pieces, 0.12)


def test_a_fit_holds_its_pads_enters_no_piece_and_does_not_cross_itself():
    """Random pads and clearance outlines: whatever is fitted keeps every pad's centre inside it, no edge
    reaches into a piece (to a rounding), no piece stands inside it and it is a simple polygon; the
    rest are refused with the copper in the way named."""
    fitted = 0
    for seed in range(400):
        holds, pieces, res = _trial(seed)
        if res.problem:
            assert res.problem in ("too close", "enclosed", "no way"), (seed, res.problem)
            assert res.piece is not None or res.problem == "no way", seed
            continue
        fitted += 1
        o, n = res.outline, len(res.outline)
        for label, poly in holds:
            c = (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
            assert pourfit._inside(o, c) or pourfit._edge_gap(o, c) < 1e-5, (seed, label)
        for i in range(n):
            a, b = o[i], o[(i + 1) % n]
            for pc in pieces:
                if pc.blocks(a, b):
                    depth = max(min(c - (nx * (a[0] + t / 50 * (b[0] - a[0])) + ny * (a[1] + t / 50 * (b[1] - a[1])))
                                    for nx, ny, c in pc.edges) for t in range(51))
                    assert depth <= 2e-6, (seed, pc.what, depth)
        for pc in pieces:
            c = pc.centre()
            assert not (pourfit._inside(o, c) and pourfit._edge_gap(o, c) > 1e-6), (seed, pc.what)
        for i in range(n):
            for j in range(i + 2, n):
                if not (i == 0 and j == n - 1):
                    assert not pourfit._crossing(o[i], o[(i + 1) % n], o[j], o[(j + 1) % n]), seed
    assert fitted > 100


def test_a_fit_round_thirty_pieces_that_intrude_on_every_side_is_fast():
    import time
    holds = [(n, pourfit.hull(_rect(x, y, 1, 1))) for n, (x, y) in zip("ABCD", ((0, 0), (8, 0), (8, 8), (0, 8)))]
    pieces = []
    for k in range(8):
        x = 1.8 + k * 0.6
        for cx, cy in ((x, -0.1), (x, 8.1), (-0.1, x), (8.1, x)):
            w, h = (0.6, 0.8) if cy in (-0.1, 8.1) else (0.8, 0.6)
            pieces += pourfit.pieces_of(_rect(cx, cy, w, h), 0.265, 0.015, "p%.1f,%.1f" % (cx, cy))
    start = time.perf_counter()
    res = pourfit.fit(holds, pieces, 0.12)
    assert not res.problem and time.perf_counter() - start < 1.0
