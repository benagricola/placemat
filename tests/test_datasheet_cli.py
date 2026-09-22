"""placemat datasheet, end to end on a PDF the test builds."""
import shutil

import pytest

from placemat.cli import main
from tests.fixtures import make_pdf
from tests.test_pdf_read import LAND

pytestmark = [pytest.mark.skipif(shutil.which("mutool") is None, reason="mutool is not here"),
              pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler is not here")]

BARE = """%%MediaBox 0 0 200 200
%%Font Helv Helvetica
BT /Helv 10 Tf 20 100 Td (Ordering information) Tj ET
"""


def test_the_index_prints_the_land_pattern_page(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p)]) == 0
    out = capsys.readouterr().out
    assert "land pattern" in out and "p1" in out


def test_show_renders_a_page_and_names_the_file(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--show", "p1", "--out", str(tmp_path / "o")]) == 0
    assert ".png" in capsys.readouterr().out
    assert list((tmp_path / "o").glob("*.png"))


def test_show_resolves_a_topic_to_its_best_page(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--show", "land", "--out", str(tmp_path / "o")]) == 0
    assert ".png" in capsys.readouterr().out


def test_show_for_a_topic_with_no_candidate_says_so(tmp_path, capsys):
    p = make_pdf(tmp_path / "bare.pdf", BARE)
    assert main(["datasheet", str(p), "--show", "pins", "--out", str(tmp_path / "o")]) == 1
    assert "no candidate" in capsys.readouterr().out


def test_a_file_that_is_not_a_pdf_exits_one(tmp_path, capsys):
    bad = tmp_path / "notes.txt"
    bad.write_text("not a pdf")
    assert main(["datasheet", str(bad)]) == 1
    assert "notes.txt" in capsys.readouterr().out


def test_json_carries_the_same_rows(tmp_path, capsys):
    import json
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["pages"] == 1
    assert any(r["topic"] == "land" and r["page"] == 1 for r in doc["index"])
