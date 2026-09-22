"""The PDF readers, against PDFs the tests build with mutool, so nothing here
depends on a datasheet that happens to be on this machine."""
import shutil

import pytest

from placemat.pdf import read
from tests.fixtures import make_pdf

needs_mupdf = pytest.mark.skipif(shutil.which("mutool") is None, reason="mutool is not here")
needs_poppler = pytest.mark.skipif(shutil.which("pdftotext") is None, reason="poppler is not here")
pytestmark = [needs_mupdf, needs_poppler]

LAND = """%%MediaBox 0 0 300 300
%%Font Helv Helvetica
BT /Helv 12 Tf 20 250 Td (RECOMMENDED LAND PATTERN) Tj ET
BT /Helv 10 Tf 20 230 Td ([ Unit : mm ]) Tj ET
10 10 40 20 re f
60 10 40 20 re f
110 10 40 20 re f
"""


def test_a_built_pdf_reads_back_its_page_count_and_text(tmp_path):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert read.page_count(p) == 1
    assert "RECOMMENDED LAND PATTERN" in read.plain_text(p)


def test_a_file_that_is_not_a_pdf_says_so(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("this is not a pdf")
    with pytest.raises(read.PdfError) as e:
        read.page_count(bad)
    assert "notes.txt" in str(e.value)
