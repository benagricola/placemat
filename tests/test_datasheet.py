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


def test_a_keyword_and_geometry_together_are_strong():
    runs = [_run("RECOMMENDED LAND PATTERN"), _run("0.50"), _run("1.30"), _run("[ Unit : mm ]")]
    rects = [_rect(2, 1) for _ in range(6)]
    ev = ds.page_evidence("land", runs, rects)
    assert any(e.kind == "keyword" for e in ev)
    assert any(e.kind == "rects" for e in ev)
    assert ds.band_of(ev) == "strong"


def test_geometry_with_no_keyword_is_fair():
    """The text-free connectors: 36 equal rectangles and nothing said."""
    rects = [_rect(2, 1) for _ in range(36)]
    ev = ds.page_evidence("land", [], rects)
    assert ds.band_of(ev) == "fair"


def test_a_page_with_nothing_earns_no_evidence():
    assert ds.page_evidence("land", [_run("Ordering information")], []) == ()
    assert ds.band_of(()) == "none"


def test_every_topic_has_a_keyword_table():
    for topic in ds.TOPICS:
        assert ds.KEYWORDS[topic], topic


def _page(page, words=(), rects=0, size=(2.0, 1.0)):
    runs = [_run(w, page=page) for w in words]
    paths = [_rect(size[0], size[1], page=page) for _ in range(rects)]
    return runs, paths


def test_the_index_puts_the_best_candidate_for_a_topic_first():
    by_page = {
        1: _page(1, ("Ordering information",)),
        6: _page(6, ("MECHANICAL DIMENSIONS (mm)", "1.20", "3.40", "5.60"), rects=20),
        7: _page(7, ("RECOMMENDED LAND PATTERN", "[ Unit : mm ]", "0.50", "1.30", "2.10"), rects=8),
    }
    land = [c for c in ds.index(by_page) if c.topic == "land"]
    assert land[0].page == 7 and land[0].band == "strong"


def test_a_topic_with_no_candidate_still_appears():
    by_page = {1: _page(1, ("Ordering information",))}
    got = {c.topic: c for c in ds.index(by_page)}
    assert set(got) == set(ds.TOPICS)
    assert got["pins"].band == "none" and got["pins"].page == 0


def test_the_index_lines_name_the_page_the_band_and_the_evidence():
    by_page = {7: _page(7, ("RECOMMENDED LAND PATTERN", "0.50", "1.30", "2.10"), rects=8)}
    text = "\n".join(ds.index_lines("TDK-ANT016008", 11, ds.index(by_page)))
    assert "p7" in text and "land" in text and "strong" in text
    assert "RECOMMENDED LAND PATTERN" in text


def test_index_rows_carry_the_same_facts_as_the_lines():
    by_page = {7: _page(7, ("RECOMMENDED LAND PATTERN", "0.50", "1.30", "2.10"), rects=8)}
    rows = ds.index_rows(ds.index(by_page))
    land = [r for r in rows if r["topic"] == "land"][0]
    assert land["page"] == 7 and land["band"] == "strong" and land["evidence"]


def test_geometry_argues_for_a_drawing_topic_and_not_a_textual_one():
    """A row of identical rectangles says "a land pattern or a package
    drawing". It says nothing whatever about a pin table, and offering it as
    evidence for one made a text-free connector rank `pins` as high as
    everything else."""
    rects = [_rect(2, 1) for _ in range(36)]
    assert any(e.kind == "rects" for e in ds.page_evidence("land", [], rects))
    assert any(e.kind == "rects" for e in ds.page_evidence("package", [], rects))
    assert ds.page_evidence("pins", [], rects) == ()
    assert ds.page_evidence("rules", [], rects) == ()


def test_a_rule_line_is_not_a_pad():
    """A table's rules are rectangles too: 9 of 1 x 42 on the antenna's
    terminal-function page. A pad is not 42 times longer than it is wide."""
    lines = [_rect(42.0, 1.0) for _ in range(9)]
    assert ds.rectangles(lines) == ()
    assert ds.page_evidence("land", [], lines) == ()


def test_a_contents_line_is_not_the_page_that_covers_it():
    """TI's contents says "Layout Guidelines ....... 30". It names the topic
    and it is on page 2, so it beat the page that actually covers it."""
    assert ds.is_contents("Layout Guidelines ........................ 30")
    assert ds.is_contents("Pin Configuration and Functions......... 3")
    assert not ds.is_contents("Layout Guidelines")
    assert not ds.is_contents("RECOMMENDED LAND PATTERN")


def test_a_contents_page_does_not_win_a_topic():
    by_page = {
        2: _page(2, ("Layout Guidelines ................ 30", "1.20", "3.40", "5.60")),
        30: _page(30, ("Layout Guidelines", "0.50", "1.30", "2.10")),
    }
    rules = [c for c in ds.index(by_page) if c.topic == "rules"][0]
    assert rules.page == 30


def test_a_hairline_is_not_a_pad():
    """A cluster of paths too small to size is a hatch or a border, and
    printing it as "16 of 0 x 0" told a reader nothing."""
    hairs = [_rect(0.02, 0.02) for _ in range(16)]
    assert ds.rectangles(hairs) == ()
