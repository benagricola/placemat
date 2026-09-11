"""The copper drawers, proved on geometry alone - no board, no toolchain.

Each test states an INVARIANT, never expected coordinates. A coordinate test
breaks whenever the drawing legitimately changes and gets deleted; an invariant
is the property callers actually rely on, and it is exactly what a hand-rolled
copy of a drawer gets wrong.

The box invariant below is not hypothetical: a board script carried its own
45-degree midpoint,

    (x_dst - (y_dst - y_src), y_src)

which is correct only while the destination lies one particular side of the
source. When a part moved the other way the corner landed 24 mm off the edge of
the board, and the first sign of it was eleven hole-clearance violations in a
DRC run five minutes later.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from conftest import segments                                      # noqa: E402


QUADRANTS = {
    "dst below-right": (10.0, 10.0, 20.0, 25.0),
    "dst above-right": (10.0, 40.0, 20.0, 25.0),
    "dst below-left": (30.0, 10.0, 20.0, 25.0),
    "dst above-left": (30.0, 40.0, 20.0, 25.0),
}


@pytest.mark.parametrize("case", QUADRANTS.keys())
def test_l45_stays_inside_its_endpoints_box(bare, case):
    """A two-segment 45 may not leave the rectangle its endpoints make."""
    x0, y0, x1, y1 = QUADRANTS[case]
    bare.l45("T", x0, y0, x1, y1, w=0.2)
    for sx, sy, ex, ey in segments(bare):
        for px, py in ((sx, sy), (ex, ey)):
            assert min(x0, x1) - 1e-6 <= px <= max(x0, x1) + 1e-6, "escaped in x"
            assert min(y0, y1) - 1e-6 <= py <= max(y0, y1) + 1e-6, "escaped in y"


@pytest.mark.parametrize("case,pts", [
    ("diagonal", (10.0, 10.0, 20.0, 25.0)),
    ("pure horizontal", (10.0, 10.0, 20.0, 10.0)),
    ("pure vertical", (10.0, 10.0, 10.0, 25.0)),
])
def test_l45_reaches_both_endpoints(bare, case, pts):
    x0, y0, x1, y1 = pts
    bare.l45("T", x0, y0, x1, y1, w=0.2)
    ends = [(s[0], s[1]) for s in segments(bare)] + [(s[2], s[3]) for s in segments(bare)]
    assert any(abs(p[0] - x0) < 1e-6 and abs(p[1] - y0) < 1e-6 for p in ends)
    assert any(abs(p[0] - x1) < 1e-6 and abs(p[1] - y1) < 1e-6 for p in ends)


@pytest.mark.parametrize("case,pts", [
    ("wider than tall", (10.0, 10.0, 30.0, 15.0)),
    ("taller than wide", (10.0, 10.0, 15.0, 30.0)),
])
def test_l45_enters_on_the_pads_axis(bare, case, pts):
    """The LAST leg rides the destination's own axis (skill tactic 9): a final
    segment arriving off-axis skims a pad instead of entering it."""
    x0, y0, x1, y1 = pts
    bare.l45("T", x0, y0, x1, y1, w=0.2)
    last = [s for s in segments(bare) if abs(s[2] - x1) < 1e-6 and abs(s[3] - y1) < 1e-6]
    assert last, "nothing arrives at the destination"
    assert abs(last[0][0] - x1) < 1e-6 or abs(last[0][1] - y1) < 1e-6


@pytest.mark.parametrize("case,pts", [
    ("shallow", (10.0, 10.0, 40.0, 13.0)),
    ("steep", (10.0, 10.0, 13.0, 40.0)),
])
def test_l45_draws_only_orthogonal_or_true_45(bare, case, pts):
    bare.l45("T", *pts, w=0.2)
    for sx, sy, ex, ey in segments(bare):
        dx, dy = abs(ex - sx), abs(ey - sy)
        if dx > 1e-6 and dy > 1e-6:
            assert abs(dx - dy) < 1e-6, "segment is neither orthogonal nor a 45"


def test_route45_polyline_stays_inside_each_legs_box(bare):
    """route45 is l45 per leg, so the invariant holds leg by leg - which is what
    makes it safe to use where a hand-written midpoint is not."""
    pts = [(10.0, 10.0), (25.0, 20.0), (15.0, 35.0), (30.0, 30.0)]
    bare.route45("T", pts, w=0.2)
    lo_x = min(p[0] for p in pts) - 1e-6
    hi_x = max(p[0] for p in pts) + 1e-6
    lo_y = min(p[1] for p in pts) - 1e-6
    hi_y = max(p[1] for p in pts) + 1e-6
    for sx, sy, ex, ey in segments(bare):
        assert lo_x <= sx <= hi_x and lo_x <= ex <= hi_x
        assert lo_y <= sy <= hi_y and lo_y <= ey <= hi_y
