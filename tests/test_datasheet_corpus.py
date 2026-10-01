"""Against real datasheets, when they are on this machine: set
PLACEMAT_TEST_ANTENNA_PDF (a chip antenna) and PLACEMAT_TEST_CONNECTOR_PDF (a
connector whose sheet is drawn in outlined curves). These are the two
measurements the spec argues from, so they are checked rather than quoted."""
import os
import pathlib
import shutil

import pytest

from placemat import datasheet as ds
from placemat.pdf import read

pytestmark = [pytest.mark.skipif(shutil.which("mutool") is None, reason="mutool is not here")]

ANTENNA = pathlib.Path(os.environ.get("PLACEMAT_TEST_ANTENNA_PDF", "/nonexistent.pdf"))
CONNECTOR = pathlib.Path(os.environ.get("PLACEMAT_TEST_CONNECTOR_PDF", "/nonexistent.pdf"))


@pytest.mark.skipif(not ANTENNA.exists(), reason="no antenna datasheet")
def test_the_antennas_land_pattern_is_found_on_page_7():
    by_page = {n: (read.text_runs(ANTENNA, n), read.draw_paths(ANTENNA, n))
               for n in range(1, read.page_count(ANTENNA) + 1)}
    land = [c for c in ds.index(by_page) if c.topic == "land"][0]
    assert land.page == 7 and land.band == "strong"


@pytest.mark.skipif(not CONNECTOR.exists(), reason="no connector datasheet")
def test_a_datasheet_with_no_text_still_yields_its_rectangles():
    """55 characters of text on the whole page; every dimension is an outlined
    curve. The geometry is still there, and it is what makes this part
    tractable at all."""
    runs = read.text_runs(CONNECTOR, 1)
    assert sum(len(r.text) for r in runs) < 200
    groups = ds.clusters(ds.rectangles(read.draw_paths(CONNECTOR, 1)))
    assert groups and groups[0][1] >= 10


@pytest.mark.skipif(not CONNECTOR.exists(), reason="no connector datasheet")
@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract is not here")
def test_ocr_turns_the_text_free_connector_into_a_strong_land_pattern(tmp_path):
    """Its own text is six runs. Read off the render it yields the heading,
    the dimension stack and the unit."""
    runs = read.ocr_runs(CONNECTOR, 1, tmp_path)
    assert len(runs) > 50
    assert any("LAYOUT" in r.text.upper() for r in runs)
    assert ds.unit_of(runs) == "mm"
    ev = ds.page_evidence("land", runs, read.draw_paths(CONNECTOR, 1))
    assert ds.band_of(ev) == "strong"


@pytest.mark.skipif(not CONNECTOR.exists(), reason="no connector datasheet")
@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract is not here")
def test_the_connectors_dimension_stack_is_sourced_with_confidence(tmp_path):
    """0.50 1.50 2.50 3.50 5.05 6.15 6.65 are on the sheet and readable only
    off the render. 4.55 is there too and tesseract reads it as 4.95, which is
    why a sourced number carries its confidence."""
    runs = read.ocr_runs(CONNECTOR, 1, tmp_path)
    found = ds.facts({1: (runs, ())})
    dims = {f.value: f for f in found if f.name == "dimension"}
    stack = {0.5, 1.5, 2.5, 3.5, 5.05, 6.15, 6.65}
    assert stack <= set(dims)
    # a dimension standing on its own line is read well; a line's reported
    # confidence is its WEAKEST word, so a mixed line like `UNIT: mm SCALE:`
    # sits low on the strength of the `mm` tesseract scores at 23
    assert all(dims[v].confidence >= 80 for v in stack)
    assert all(f.source == "ocr" and 0 < f.confidence <= 100 for f in found)
