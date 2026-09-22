"""What a datasheet page is about, from what is on it. Pure: no PDF, so these
run anywhere."""
import pytest

from placemat import datasheet as ds
from placemat.values import Box


def _run(text, x=0.0, y=0.0, w=50.0, h=10.0, page=1):
    return ds.TextRun(page, text, Box(x, y, x + w, y + h))


def _rect(w, h, x=0.0, y=0.0, page=1):
    return ds.DrawPath(page, Box(x, y, x + w, y + h), points=4, rect=True, filled=True)


def test_only_four_corner_paths_count_as_rectangles():
    diamond = ds.DrawPath(1, Box(0, 0, 9, 9), points=4, rect=False, filled=False)
    curve = ds.DrawPath(1, Box(0, 0, 9, 9), points=17, rect=False, filled=False)
    assert len(ds.rectangles([_rect(2, 1), _rect(2, 1), diamond, curve])) == 2


def test_rectangles_of_the_same_size_cluster():
    rects = [_rect(2.0, 1.0), _rect(2.0, 1.0), _rect(2.02, 1.01), _rect(5.0, 5.0)]
    top = ds.clusters(rects)[0]
    assert top[1] == 3 and top[0] == (pytest.approx(2.0, abs=0.1), pytest.approx(1.0, abs=0.1))


def test_dimension_numbers_are_the_decimals_on_the_page():
    runs = [_run("0.50"), _run("1.30"), _run("Page 7 of 11"), _run("ANT016008LCS2442MA1")]
    assert sorted(ds.dimension_numbers(runs)) == [0.5, 1.3]


def test_the_unit_is_read_where_the_page_states_it():
    assert ds.unit_of([_run("[ Unit : mm ]")]) == "mm"
    assert ds.unit_of([_run("All dimensions are in mm / inches")]) == "mm"
    assert ds.unit_of([_run("nothing to say")]) is None
