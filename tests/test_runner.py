"""Runner behaviour that needs no KiCad: what a rerun keeps, and what the
DRC wrapper refuses to measure."""
import json
from pathlib import Path

import pytest


def test_a_rerun_carries_the_previous_run_s_route_into_the_new_one(tmp_path):
    """A matching run id means the same script, generated board, tool version
    and settings, so the board this run writes is byte-identical to the one
    the route was taken on. Losing the route costs minutes and nothing says
    it has gone."""
    from placemat.runner import keep_route
    final, staging = tmp_path / "1cbe69ce", tmp_path / ".staging"
    (final / "route").mkdir(parents=True)
    (final / "route" / "routed.kicad_pcb").write_text("the routed board")
    staging.mkdir()
    keep_route(final, staging)
    assert (staging / "route" / "routed.kicad_pcb").read_text() == "the routed board"


def test_a_rerun_with_no_previous_route_is_untroubled(tmp_path):
    from placemat.runner import keep_route
    final, staging = tmp_path / "id", tmp_path / ".staging"
    final.mkdir()
    staging.mkdir()
    keep_route(final, staging)                       # no raise
    assert not (staging / "route").exists()


def test_a_route_this_run_already_produced_is_not_overwritten(tmp_path):
    """The routing path writes into the run directory itself; a preserved
    older route must never displace a fresher one."""
    from placemat.runner import keep_route
    final, staging = tmp_path / "id", tmp_path / ".staging"
    (final / "route").mkdir(parents=True)
    (final / "route" / "routed.kicad_pcb").write_text("old")
    (staging / "route").mkdir(parents=True)
    (staging / "route" / "routed.kicad_pcb").write_text("new")
    keep_route(final, staging)
    assert (staging / "route" / "routed.kicad_pcb").read_text() == "new"


def test_drc_refuses_a_board_with_no_project_file_beside_it(tmp_path):
    """kicad-cli substitutes its own defaults when the project file is not
    there, and the report then measures KiCad rather than the board: on the
    fairing main board that is 1263 violations against a true 313, including
    199 track_width that do not exist."""
    from placemat.kicad.drc import run_drc
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    with pytest.raises(FileNotFoundError) as e:
        run_drc(pcb, tmp_path / "drc.json")
    assert "layout.kicad_pro" in str(e.value)


def test_drc_is_content_when_the_project_file_is_there(tmp_path, monkeypatch):
    """The guard is about the project file, not about the board: with one
    present the call proceeds to kicad-cli as before."""
    from placemat.kicad import drc as drc_mod
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    (tmp_path / "layout.kicad_pro").write_text("{}")
    out = tmp_path / "drc.json"

    class _Proc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kw):
        out.write_text(json.dumps({"violations": [], "unconnected_items": []}))
        return _Proc()

    monkeypatch.setattr(drc_mod.subprocess, "run", fake_run)
    report = drc_mod.run_drc(pcb, out)
    assert report.violations == 0
