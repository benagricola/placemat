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


def test_text_comes_back_with_the_box_it_sits_in(tmp_path):
    """A number is only useful when its position is known: that is what ties
    a dimension to the feature it labels."""
    p = make_pdf(tmp_path / "land.pdf", LAND)
    runs = read.text_runs(p, 1)
    hit = [r for r in runs if "RECOMMENDED" in r.text]
    assert len(hit) == 1
    r = hit[0]
    assert r.page == 1
    assert r.box.left == pytest.approx(20, abs=1.0)
    assert r.box.width > 100 and 0 < r.box.height < 30


def test_an_escaped_character_comes_back_decoded(tmp_path):
    p = make_pdf(tmp_path / "dia.pdf", """%%MediaBox 0 0 200 200
%%Font Helv Helvetica
BT /Helv 10 Tf 20 100 Td (VIA 0.2mm) Tj ET
""")
    assert any("VIA" in r.text for r in read.text_runs(p, 1))


def test_a_drawn_rectangle_comes_back_at_its_real_size(tmp_path):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    rects = [d for d in read.draw_paths(p, 1) if d.rect]
    assert len(rects) == 3
    assert all(d.box.width == pytest.approx(40, abs=0.5) for d in rects)
    assert all(d.box.height == pytest.approx(20, abs=0.5) for d in rects)


def test_a_scaled_path_is_measured_after_its_transform(tmp_path):
    """mutool emits pre-transform coordinates. A real datasheet scales by 0.12
    and rotates, so a path measured before its matrix is applied is wrong by
    almost an order of magnitude."""
    p = make_pdf(tmp_path / "scaled.pdf", """%%MediaBox 0 0 300 300
q 0.5 0 0 0.5 0 0 cm
10 10 40 20 re f
Q
""")
    (rect,) = [d for d in read.draw_paths(p, 1) if d.rect]
    assert rect.box.width == pytest.approx(20, abs=0.5)     # 40 * 0.5
    assert rect.box.height == pytest.approx(10, abs=0.5)


def test_a_page_renders_to_a_png(tmp_path):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    png = read.render(p, 1, tmp_path / "out")
    assert png.exists() and png.suffix == ".png" and png.stat().st_size > 0


def test_a_tool_that_warns_and_still_works_is_not_an_error():
    """mutool exits 1 for `warning: ICC support is not available` while
    producing the whole trace, so a non-zero exit is only fatal when nothing
    came back with it."""
    out = read._run(["sh", "-c", "echo produced; echo 'warning: noise' >&2; exit 1"],
                    "testing", "x.pdf")
    assert out.strip() == "produced"


def test_a_tool_that_fails_with_nothing_to_show_is_an_error():
    with pytest.raises(read.PdfError):
        read._run(["sh", "-c", "echo 'error: no such page' >&2; exit 1"], "testing", "x.pdf")


def test_the_complaint_is_the_error_not_the_last_warning():
    said = read._complaint(b"error: cannot find page 9\nwarning: ICC support is not available\n")
    assert "cannot find page 9" in said
