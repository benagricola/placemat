"""SideOf(pad, along=True): the side of a part where a pad lies along its row,
the end of the row it is nearer; for Beside's side and Facing's toward=. Pure:
synthetic boards."""
import pytest

from placemat.values import Beside, Edge, Facing, Location, PadRef, Part, SideOf
from tests.fixtures import footprint
from tests.test_facing_grids_rows_sides import _TURNS, _board, _centre_of, _dist, _part


def _dual(n_pins, ref="U", inst="u"):
    """A dual-row package: pins 1..n/2 down the west column, n/2+1..n up the east
    column, at (40, 40); pads run across their row (long in x)."""
    per = n_pins // 2
    pads = []
    for k in range(per):
        pads.append((k + 1, "P%d" % (k + 1), -3.0, (k - (per - 1) / 2.0) * 1.0, 1.0, 0.4))
    for k in range(per):
        pads.append((per + k + 1, "P%d" % (per + k + 1), 3.0, ((per - 1) / 2.0 - k) * 1.0, 1.0, 0.4))
    return _part(ref, pads, 40.0, 40.0)


def _cap():
    return footprint("C", 0, 0, w=2, h=1, inst="c", nets=("SUPPLY", "GND"))


def _row_end(plan, ref, number, row):
    """The side, along its row, a pad lies at: the pad's offset from the centroid of its
    row's pads, snapped to an axis (measured off the placed part)."""
    c = _centre_of(plan, ref, [number])
    mates = [_centre_of(plan, ref, [m]) for m in row]
    mx = sum(m.x for m in mates) / len(mates)
    my = sum(m.y for m in mates) / len(mates)
    dx, dy = c.x - mx, c.y - my
    if abs(dx) > abs(dy):
        return Edge.EAST if dx > 0 else Edge.WEST
    return Edge.SOUTH if dy > 0 else Edge.NORTH


def _stands_on(plan, side):
    ub, rb = plan.box("u"), plan.box("c")
    got = {Edge.EAST: rb.center.x > ub.right, Edge.WEST: rb.center.x < ub.left,
           Edge.SOUTH: rb.center.y > ub.bottom, Edge.NORTH: rb.center.y < ub.top}
    assert sum(got.values()) == 1, (ub, rb)
    return got[side]


_PACKAGES = [
    (10, [(1, range(1, 6)), (5, range(1, 6)), (6, range(6, 11)), (10, range(6, 11))]),
    (8, [(1, range(1, 5)), (4, range(1, 5)), (5, range(5, 9)), (8, range(5, 9))]),
]
_CASES = [(n, pin, list(row)) for n, pins in _PACKAGES for pin, row in pins]


@pytest.mark.parametrize("rot, face", _TURNS)
@pytest.mark.parametrize("n_pins, pin, row", _CASES)
def test_a_part_stands_beside_the_end_of_the_row_where_a_pad_lies(n_pins, pin, row, rot, face):
    b = _board([_dual(n_pins), _cap()])
    b.place(Part("u"), at=Location(40, 40), rotation=rot, face=face)
    b.place(Part("c"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), pin), along=True)), rotation=0)
    plan = b.resolve()
    want = _row_end(plan, "U", pin, row)
    assert _stands_on(plan, want), (pin, rot, face, want)


@pytest.mark.parametrize("rot, face", _TURNS)
@pytest.mark.parametrize("n_pins, pin, row", _CASES)
def test_a_pad_faces_the_part_from_the_end_where_a_pad_lies(n_pins, pin, row, rot, face):
    b = _board([_dual(n_pins), _cap()])
    b.place(Part("u"), at=Location(40, 40), rotation=rot, face=face)
    side = SideOf(PadRef(Part("u"), pin), along=True)
    b.place(Part("c"), at=Beside(Part("u"), side),
            rotation=Facing(PadRef(Part("c"), "SUPPLY"), toward=side))
    plan = b.resolve()
    assert _stands_on(plan, _row_end(plan, "U", pin, row))
    centre = plan.box("u").center
    assert _dist(_centre_of(plan, "C", [1]), centre) < _dist(_centre_of(plan, "C", [2]), centre)


def test_the_end_follows_a_part_placed_after_it():
    b = _board([_dual(10), _cap()])
    b.place(Part("c"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), 1), along=True)), rotation=0)
    b.place(Part("u"), at=Location(40, 40), rotation=180)
    plan = b.resolve()
    assert _stands_on(plan, _row_end(plan, "U", 1, range(1, 6)))


def test_a_pad_exactly_mid_row_is_refused_saying_why():
    b = _board([_dual(10), _cap()])
    b.place(Part("u"), at=Location(40, 40))
    with pytest.raises(ValueError, match=r"SideOf\(pad 3\).*(middle|mid).*row"):
        b.place(Part("c"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), 3), along=True)), rotation=0)
        b.resolve()


def test_along_names_one_pad():
    with pytest.raises(TypeError, match="one pad"):
        SideOf([PadRef(Part("u"), 1), PadRef(Part("u"), 2)], along=True)


def test_a_pad_with_no_row_is_refused():
    from tests.test_facing_grids_rows_sides import _grid
    b = _board([_grid("U", n=3), _cap()])
    b.place(Part("u"), at=Location(30, 30))
    with pytest.raises(ValueError, match="row"):
        b.place(Part("c"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), 1), along=True)), rotation=0)
        b.resolve()


def test_along_is_part_of_the_digest_only_when_set():
    from placemat.reuse import canonical as digest_of
    plain = SideOf(PadRef(Part("u"), 1))
    assert digest_of(plain) == digest_of(SideOf(PadRef(Part("u"), 1), along=False))
    assert digest_of(plain) != digest_of(SideOf(PadRef(Part("u"), 1), along=True))
