"""Against real datasheets, when they are on this machine. These are the two
measurements the spec argues from, so they are checked rather than quoted."""
import pathlib
import shutil

import pytest

from placemat import datasheet as ds
from placemat.pdf import read

CORPUS = pathlib.Path("/home/ben/Documents/Hardware/fairing-instrument/electronics/datasheets")
pytestmark = [pytest.mark.skipif(shutil.which("mutool") is None, reason="mutool is not here"),
              pytest.mark.skipif(not CORPUS.is_dir(), reason="the datasheet corpus is not here")]

TDK = CORPUS / "TDK-ANT016008LCS2442MA1_C76585.pdf"
TYPEC = CORPUS / "Korean_Hroparts_Elec-TYPE_C_31_M_12_C165948.pdf"


@pytest.mark.skipif(not TDK.exists(), reason="no TDK antenna datasheet")
def test_the_antennas_land_pattern_is_found_on_page_7():
    by_page = {n: (read.text_runs(TDK, n), read.draw_paths(TDK, n))
               for n in range(1, read.page_count(TDK) + 1)}
    land = [c for c in ds.index(by_page) if c.topic == "land"][0]
    assert land.page == 7 and land.band == "strong"


@pytest.mark.skipif(not TYPEC.exists(), reason="no TYPE-C datasheet")
def test_a_datasheet_with_no_text_still_yields_its_rectangles():
    """55 characters of text on the whole page; every dimension is an outlined
    curve. The geometry is still there, and it is what makes this part
    tractable at all."""
    runs = read.text_runs(TYPEC, 1)
    assert sum(len(r.text) for r in runs) < 200
    groups = ds.clusters(ds.rectangles(read.draw_paths(TYPEC, 1)))
    assert groups and groups[0][1] >= 10


@pytest.mark.skipif(not TYPEC.exists(), reason="no TYPE-C datasheet")
@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract is not here")
def test_ocr_turns_the_text_free_connector_into_a_strong_land_pattern(tmp_path):
    """Its own text is six runs. Read off the render it yields the heading,
    the dimension stack and the unit."""
    runs = read.ocr_runs(TYPEC, 1, tmp_path)
    assert len(runs) > 50
    assert any("LAYOUT" in r.text.upper() for r in runs)
    assert ds.unit_of(runs) == "mm"
    ev = ds.page_evidence("land", runs, read.draw_paths(TYPEC, 1))
    assert ds.band_of(ev) == "strong"
