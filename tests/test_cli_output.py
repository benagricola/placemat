"""Every command takes --format text|json and --output FILE, the same way."""
import json

import pytest

from placemat.cli import main, parser


def _subcommands():
    sub = next(a for a in parser()._actions if a.dest == "command")
    return sub.choices


def test_every_command_takes_format_and_output():
    for name, sp in _subcommands().items():
        flags = {o for a in sp._actions for o in a.option_strings}
        assert {"--format", "--output"} <= flags, name


def test_output_writes_the_report_to_the_file_and_nothing_to_the_terminal(tmp_path, capsys):
    out = tmp_path / "settings.json"
    assert main(["settings", str(tmp_path), "--format", "json", "--output", str(out)]) == 0
    assert capsys.readouterr().out == ""
    data = json.loads(out.read_text())
    assert "place.step" in json.dumps(data) or "place_step" in json.dumps(data)


def test_format_json_is_the_same_as_json(tmp_path, capsys):
    main(["settings", str(tmp_path), "--json"])
    a = capsys.readouterr().out
    main(["settings", str(tmp_path), "--format", "json"])
    assert capsys.readouterr().out == a


def test_text_to_a_file_has_no_colour(tmp_path, monkeypatch):
    out = tmp_path / "settings.txt"
    assert main(["settings", str(tmp_path), "--output", str(out)]) == 0
    assert "\033[" not in out.read_text() and out.read_text().strip()


def test_impact_gives_json_with_both_runs_metrics(tmp_path, capsys):
    from placemat.report import RunRecord
    a, b = tmp_path / "a", tmp_path / "b"
    for d, rid, placed in ((a, "aaaa1111", 3), (b, "bbbb2222", 4)):
        d.mkdir()
        rec = RunRecord(run_id=rid, board="x", status="ok")
        rec.metrics = {"placed": placed, "findings": 0}
        rec.save(d / "run.json")
    assert main(["impact", str(a), str(b), "--format", "json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["before"]["metrics"]["placed"] == 3 and doc["after"]["metrics"]["placed"] == 4
    assert isinstance(doc["lines"], list)


def test_faces_gives_json(tmp_path, capsys):
    import pathlib, shutil
    from tests.conftest import _has_pcbnew
    if not _has_pcbnew():
        pytest.skip("pcbnew not importable")
    src = pathlib.Path(__file__).resolve().parent.parent / "fixtures/mnb/modules/UsbC/layout"
    shutil.copytree(src, tmp_path / "layout")
    frag = tmp_path / "layout" / "layout.kicad_pcb"
    assert main(["faces", str(frag), "outward=N", "--format", "json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["faces"] == {"outward": "N"} and doc["fragment"] == str(frag)
