"""placemat datasheet, end to end on a PDF the test builds."""
import pathlib
import shutil

import pytest

from placemat.cli import main
from tests.fixtures import make_pdf
from tests.conftest import needs_kicad
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


def _tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_show_without_an_output_request_writes_no_file_and_prints_the_text(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    before = _tree(tmp_path)
    assert main(["datasheet", str(p), "--show", "p1"]) == 0
    out = capsys.readouterr().out
    assert _tree(tmp_path) == before
    assert ".png" not in out and "page 1" in out and "RECOMMENDED LAND PATTERN" in out


def test_show_on_a_page_with_no_text_says_so(tmp_path, capsys):
    p = make_pdf(tmp_path / "blank.pdf", "%%MediaBox 0 0 200 200\n")
    assert main(["datasheet", str(p), "--show", "p1", "--no-ocr"]) == 0
    assert "no text on this page (outlined curves)" in capsys.readouterr().out
    assert not list(tmp_path.rglob("*.png")) and not (tmp_path / ".placemat").exists()


def test_png_writes_under_the_projects_views_folder_with_a_gitignore(tmp_path, capsys):
    (tmp_path / "placemat.toml").write_text("")
    docs = tmp_path / "docs"
    docs.mkdir()
    p = make_pdf(docs / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--show", "p1", "--png"]) == 0
    views = tmp_path / ".placemat" / "views"
    assert (views / "datasheet" / "land-p1.png").exists()
    assert (views / ".gitignore").read_text() == "*\n"
    assert str(views / "datasheet" / "land-p1.png") in capsys.readouterr().out
    assert not list(docs.glob("*.png")) and not (docs / ".placemat").exists()


def test_png_with_no_project_uses_the_pdfs_own_directory(tmp_path):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--show", "land", "--png"]) == 0
    assert (tmp_path / ".placemat/views/datasheet/land-p1.png").exists()
    assert not list(tmp_path.glob("*.png"))


def test_out_writes_exactly_there_and_nowhere_else(tmp_path, capsys):
    import json
    p = make_pdf(tmp_path / "land.pdf", LAND)
    target = tmp_path / "o" / "page.png"
    before = _tree(tmp_path)
    assert main(["datasheet", str(p), "--show", "p1", "--out", str(target), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["png"] == str(target) and doc["text"]
    assert _tree(tmp_path) == sorted(before + ["o", "o/page.png"])


def test_json_without_a_render_has_text_and_no_png(tmp_path, capsys):
    import json
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--show", "p1", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["text"] and "png" not in doc


def test_png_without_show_is_refused(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--png"]) == 1
    assert "--show" in capsys.readouterr().out
    assert not list(tmp_path.rglob("*.png")) and not (tmp_path / ".placemat").exists()


def test_show_resolves_a_topic_to_its_best_page(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--show", "land"]) == 0
    assert "page 1" in capsys.readouterr().out


def test_show_for_a_topic_with_no_candidate_says_so(tmp_path, capsys):
    p = make_pdf(tmp_path / "bare.pdf", BARE)
    assert main(["datasheet", str(p), "--show", "pins"]) == 1
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


def test_read_prints_the_facts_with_their_provenance(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--read"]) == 0
    out = capsys.readouterr().out
    assert "unit" in out and "mm" in out and "p1" in out


def test_read_json_carries_the_same_facts(tmp_path, capsys):
    import json
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--read", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert any(f["name"] == "unit" and f["value"] == "mm" for f in doc["facts"])


def test_read_on_a_sheet_that_yields_nothing_says_so(tmp_path, capsys):
    p = make_pdf(tmp_path / "bare.pdf", """%%MediaBox 0 0 200 200
%%Font Helv Helvetica
BT /Helv 10 Tf 20 100 Td (Ordering) Tj ET
""")
    assert main(["datasheet", str(p), "--read", "--no-ocr"]) == 0
    assert "nothing could be sourced" in capsys.readouterr().out


PARTS = pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/parts"
needs_parts = pytest.mark.skipif(not PARTS.is_dir(), reason="the fixture parts are not here")


@needs_kicad
@needs_parts
def test_check_names_a_disagreement_and_exits_one(tmp_path, capsys):
    mods = sorted(PARTS.glob("*/*.kicad_mod"))
    assert mods, "no footprints to check"
    p = make_pdf(tmp_path / "land.pdf", LAND)
    code = main(["datasheet", "check", str(p), str(mods[0]), "--pads", "999"])
    out = capsys.readouterr().out
    assert code == 1 and "MISMATCH" in out and "pads" in out


@needs_kicad
@needs_parts
def test_check_with_nothing_supplied_still_reports_every_measurement(tmp_path, capsys):
    mods = sorted(PARTS.glob("*/*.kicad_mod"))
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", "check", str(p), str(mods[0])]) == 0
    out = capsys.readouterr().out
    for name in ("pitch", "pad", "pads", "span"):
        assert name in out
    assert "unchecked" in out


@needs_kicad
@needs_parts
def test_check_json_carries_the_footprints_digest(tmp_path, capsys):
    import json
    mods = sorted(PARTS.glob("*/*.kicad_mod"))
    p = make_pdf(tmp_path / "land.pdf", LAND)
    main(["datasheet", "check", str(p), str(mods[0]), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert len(doc["sha256"]) == 64
    assert {c["name"] for c in doc["checks"]} == {"pitch", "pad", "pads", "span"}


def test_check_without_two_paths_says_what_it_takes(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", "check", str(p)]) == 1
    assert "check takes a datasheet and a footprint" in capsys.readouterr().out
