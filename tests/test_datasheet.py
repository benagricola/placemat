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


def test_the_shape_evidence_names_its_unit_and_does_not_claim_pads():
    """`183 of 3 x 5` reads as 183 pads of 3 x 5 mm. They are PDF points, and
    on the TYPE-C sheet that cluster is glyph strokes in the notes column
    sitting on 42 evenly spaced text rows, not a contact array. The evidence
    says a shape repeats; it does not say what the shape is."""
    rects = [_rect(3.0, 5.0) for _ in range(183)]
    (ev,) = [e for e in ds.page_evidence("land", [], rects) if e.kind == "rects"]
    assert "pt" in ev.detail
    assert "pad" not in ev.detail.lower()
    assert "183" in ev.detail


def test_a_text_run_says_which_channel_read_it():
    """A number read by OCR is not as good as one read from the PDF's own
    text, and a reader has to be able to tell which they are looking at."""
    plain = ds.TextRun(1, "0.50", Box(0, 0, 10, 5))
    assert plain.source == "text" and plain.confidence == 100.0
    seen = ds.TextRun(1, "0.50", Box(0, 0, 10, 5), source="ocr", confidence=78.0)
    assert seen.source == "ocr" and seen.confidence == 78.0


TSV = "\t".join(["level", "page_num", "block_num", "par_num", "line_num", "word_num",
                 "left", "top", "width", "height", "conf", "text"]) + "\n" + "\n".join([
    "5\t1\t1\t1\t1\t1\t100\t50\t90\t12\t92\tRECOMMEND",
    "5\t1\t1\t1\t1\t2\t200\t50\t40\t12\t88\tP.C.B",
    "5\t1\t1\t1\t1\t3\t250\t50\t80\t12\t73\tLAYOUT(COMPONEN",
    "5\t1\t2\t1\t1\t1\t400\t80\t30\t10\t96\t6.65",
    "5\t1\t3\t1\t1\t1\t500\t90\t30\t10\t16\tYUUUUUUUU",
    "5\t1\t4\t1\t1\t1\t600\t99\t10\t10\t95\t",
])


def test_ocr_words_are_grouped_into_the_line_they_came_from():
    """tesseract's TSV is one row per WORD. Building a run per word split
    "RECOMMEND P.C.B LAYOUT" into three, and no keyword matched any of them."""
    runs = ds.runs_from_tsv(TSV, page=1)
    texts = [r.text for r in runs]
    assert "RECOMMEND P.C.B LAYOUT(COMPONEN" in texts
    assert "6.65" in texts


def test_a_line_of_nothing_but_noise_is_dropped_and_an_empty_word_ignored():
    runs = ds.runs_from_tsv(TSV, page=1)
    assert not any("YUUUUUUUU" in r.text for r in runs)      # alone at conf 16
    assert all(r.text.strip() for r in runs)


def test_a_weak_word_inside_a_good_line_is_kept():
    """tesseract scores `mm` at 23 on the TYPE-C sheet - two identical letters,
    small - while the `SCALE:` beside it scores 96 and the read is right.
    Dropping words below the floor returned `UNIT: | SCALE:` and lost the unit
    of the whole drawing, so a line is judged by its best word and kept
    whole."""
    tsv = TSV + "\n" + "\n".join([
        "5\t1\t9\t1\t1\t1\t700\t10\t30\t10\t79\tUNIT:",
        "5\t1\t9\t1\t1\t2\t735\t10\t20\t10\t23\tmm",
        "5\t1\t9\t1\t1\t3\t760\t10\t40\t10\t96\tSCALE:",
    ])
    (line,) = [r for r in ds.runs_from_tsv(tsv, page=1) if "UNIT" in r.text]
    assert line.text == "UNIT: mm SCALE:"
    assert line.confidence == 23.0        # reported conservatively: its weakest word
    assert ds.unit_of([line]) == "mm"


def test_a_grouped_run_carries_the_box_round_its_words_and_the_lowest_confidence():
    (heading,) = [r for r in ds.runs_from_tsv(TSV, page=1) if "RECOMMEND" in r.text]
    assert heading.box.left == 100 and heading.box.right == 330      # 250 + 80
    assert heading.source == "ocr"
    assert heading.confidence == 73.0        # the weakest word decides the line


def test_a_dotted_pcb_still_matches_the_land_keyword():
    """OCR reads the TYPE-C heading as "RECOMMEND P.C.B LAYOUT(COMPONEN".
    The pattern `pcb layout` does not match it, and that one gap kept the
    only page of a text-free datasheet at `fair`."""
    runs = [_run("RECOMMEND P.C.B LAYOUT(COMPONEN")]
    ev = ds.page_evidence("land", runs, [_rect(2, 1) for _ in range(6)])
    assert any(e.kind == "keyword" for e in ev)
    assert ds.band_of(ev) == "strong"


def test_a_fact_carries_the_page_the_box_and_the_channel():
    by_page = {1: ([_run("[ Unit : mm ]", x=20, y=30)], [])}
    (unit,) = [f for f in ds.facts(by_page) if f.name == "unit"]
    assert unit.value == "mm" and unit.page == 1
    assert unit.box.left == 20 and unit.source == "text"
    assert "Unit" in unit.detail


def test_every_decimal_becomes_a_dimension_fact_with_its_place():
    by_page = {7: ([_run("0.50", x=100, y=200, page=7),
                    _run("Page 7 of 11", page=7)], [])}
    dims = [f for f in ds.facts(by_page) if f.name == "dimension"]
    assert [f.value for f in dims] == [0.5]
    assert dims[0].box.left == 100 and dims[0].page == 7


def test_an_ocr_fact_keeps_the_confidence_that_read_it():
    runs = [ds.TextRun(1, "4.95", Box(0, 0, 10, 5), source="ocr", confidence=78.0)]
    (dim,) = [f for f in ds.facts({1: (runs, [])}) if f.name == "dimension"]
    assert dim.source == "ocr" and dim.confidence == 78.0


def test_a_topic_heading_becomes_a_fact_a_reader_can_check():
    by_page = {7: ([_run("RECOMMENDED LAND PATTERN")], [])}
    found = [f for f in ds.facts(by_page) if f.name == "land"]
    assert found and "RECOMMENDED LAND PATTERN" in found[0].detail


def test_read_lines_name_the_value_and_its_provenance():
    runs = [ds.TextRun(1, "0.50", Box(10, 20, 40, 30), source="ocr", confidence=88.0)]
    text = "\n".join(ds.read_lines("TYPE_C", ds.facts({1: (runs, [])})))
    assert "0.5" in text and "p1" in text and "ocr" in text and "88" in text


def test_read_rows_carry_the_same_facts_as_the_lines():
    runs = [_run("[ Unit : mm ]")]
    rows = ds.read_rows(ds.facts({1: (runs, [])}))
    assert any(r["name"] == "unit" and r["value"] == "mm" and r["source"] == "text"
               for r in rows)


def test_a_sheet_that_yields_nothing_says_so():
    assert "nothing could be sourced" in "\n".join(ds.read_lines("bare", ()))
