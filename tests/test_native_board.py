"""The native keep-in and reservations judge a body box as
`Occupancy._edge_or_reservation_conflict` does: the same refusal, word for
word once Python formats it, on boxes drawn on fab grids so the boundary
cases are common."""
import random

import pytest

native = pytest.importorskip("placemat_native")

from tests.conftest import needs_native  # noqa: E402

pytestmark = [needs_native]

from placemat.cutouts import Arc, Circle, Cutouts, Slot  # noqa: E402
from placemat.occupancy import Occupancy  # noqa: E402
from placemat.outline import Outline  # noqa: E402
from placemat.placement import Placement  # noqa: E402
from placemat.values import Box, CopperLayer, Disc, Face, Location  # noqa: E402
from tests.fixtures import board_geometry, footprint  # noqa: E402

N = 20_000


def _occ(margin, **kw):
    g = board_geometry([footprint("R1", 5, 5, inst="r1")], width=60, height=60)
    return Occupancy(g, margin, **kw), g.footprint("R1")


def _boxes(rng, lo, hi, n=N):
    grid = rng.choice((0.05, 0.1, 0.25))
    out = []
    for _ in range(n):
        x = round(rng.uniform(lo, hi) / grid) * grid
        y = round(rng.uniform(lo, hi) / grid) * grid
        w = round(rng.uniform(0.2, 6.0) / grid) * grid or grid
        h = round(rng.uniform(0.2, 6.0) / grid) * grid or grid
        out.append(Box(x, y, x + w, y + h))
    return out


def _python(occ, fp, body):
    geom = occ._geometry(fp)
    return occ._edge_or_reservation_conflict(geom, body, Placement(Location(0, 0), 0.0, Face.FRONT), False, None)


def _native(occ, board, body):
    from placemat.occupancy import edge_sentence
    code = board.edge((body.left, body.top, body.right, body.bottom))
    return None if code == 0 else edge_sentence(code, body, occ.edge_margin)


SLOT = Slot(12.0, 3.0).path_at(Location(30.0, 20.0))
HOLE = Circle(6.0).path_at(Location(20.0, 40.0))
ROUNDED = [(0.0, 60.0), (0.0, 20.0), Arc(to=(60.0, 20.0), via=(30.0, 0.0)), (60.0, 60.0)]


@pytest.mark.parametrize("name, margin, kw", [
    ("rect", 1.0, dict(board_box=Box(0, 0, 60, 60))),
    ("rect with cutouts", 0.5, dict(board_box=Box(0, 0, 60, 60), board_cutouts=Cutouts([SLOT, HOLE]))),
    ("disc", 0.3, dict(board_shape=Disc(Location(30, 30), 58.0))),
    ("disc with a bore and cutouts", 1.0, dict(board_shape=Disc(Location(30, 30), 58.0, hole=10.0, holes=(SLOT,)))),
    ("outline with arcs and cutouts", 0.3, dict(board_shape=Outline.of(ROUNDED, [HOLE, SLOT]))),
    ("outline, no margin", 0.0, dict(board_shape=Outline.of(ROUNDED))),
])
def test_the_edge_refuses_what_python_refuses_in_the_same_words(name, margin, kw):
    from placemat.occupancy import native_board
    occ, fp = _occ(margin, **kw)
    board = native_board(occ)
    rng = random.Random(hash(name) & 0xffff)
    for body in _boxes(rng, -3, 63):
        assert _native(occ, board, body) == _python(occ, fp, body), (name, body)


def test_a_reservation_refuses_what_python_refuses():
    from placemat.occupancy import native_board
    occ, fp = _occ(0.0, board_box=Box(0, 0, 60, 60))
    rng = random.Random(9)
    import math
    polys = [((10, 10), (20, 10), (20, 20), (10, 20)),                                  # a box
             tuple((30 + 8 * math.cos(2 * math.pi * k / 23), 30 + 8 * math.sin(2 * math.pi * k / 23)) for k in range(23)),
             tuple((30 + 8 * math.cos(2 * math.pi * k / 24), 30 + 8 * math.sin(2 * math.pi * k / 24)) for k in range(24)),
             tuple((20 + 15 * math.cos(2 * math.pi * k / 200), 40 + 9 * math.sin(2 * math.pi * k / 200)) for k in range(200)),
             ((40, 5), (55, 5), (55, 25), (48, 12))]                                     # not convex
    for poly in polys:
        occ.reserve(poly, "test")
    board = native_board(occ)
    assert board.reservation_count() == len(polys)
    for body in _boxes(rng, 0, 60):
        for i, r in enumerate(occ.reservations):
            assert board.reservation_overlaps(i, (body.left, body.top, body.right, body.bottom)) == r.overlaps(body), (i, body)


def test_the_native_board_follows_reservations_and_cutouts():
    from placemat.occupancy import native_board
    occ, fp = _occ(0.5, board_box=Box(0, 0, 60, 60))
    first = native_board(occ)
    assert native_board(occ) is first                           # nothing changed: the same
    occ.reserve(((1, 1), (2, 1), (2, 2)), "a")
    again = native_board(occ)
    assert again.reservation_count() == 1
    occ.board_cutouts = Cutouts([SLOT])                         # a settled cutout replaces the object
    assert native_board(occ) is not again
