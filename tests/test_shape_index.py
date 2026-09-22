"""The grid over a scan's obstacles answers what the linear filter did."""
import random

from placemat.occupancy import Shape, ShapeIndex
from placemat.values import Box


def _shape(i, box):
    return Shape("o%d" % i, "pad", frozenset(), frozenset(), "", (), box)


def _boxes(rng, n):
    out = []
    for i in range(n):
        x, y = rng.uniform(-5, 60), rng.uniform(-5, 60)
        w, h = rng.choice([rng.uniform(0.1, 3), rng.uniform(0.1, 3), rng.uniform(10, 70)]), rng.uniform(0.1, 4)
        out.append(_shape(i, Box(x, y, x + w, y + h)))
    return out


def test_near_is_the_linear_filter_in_the_same_order():
    rng = random.Random(7)
    shapes = _boxes(rng, 400)
    index = ShapeIndex(shapes)
    for _ in range(500):
        x, y = rng.uniform(-10, 70), rng.uniform(-10, 70)
        box = Box(x, y, x + rng.uniform(0, 8), y + rng.uniform(0, 8))
        gap = rng.choice([0.0, 0.2, 1.0])
        assert index.near(box, gap) == [o for o in shapes if o.box.overlaps(box, gap=gap)]


def test_boxes_that_only_touch_are_not_near():
    a = _shape(0, Box(0, 0, 2, 2))
    index = ShapeIndex([a] * 1 + [_shape(i, Box(50 + i, 50, 51 + i, 51)) for i in range(1, 80)])
    assert index.near(Box(2, 0, 4, 2), 0.0) == []
    assert index.near(Box(1.9, 0, 4, 2), 0.0) == [a]


def test_an_index_is_still_the_list_it_was_built_from():
    shapes = _boxes(random.Random(1), 10)
    assert list(ShapeIndex(shapes)) == shapes and len(ShapeIndex(shapes)) == 10
