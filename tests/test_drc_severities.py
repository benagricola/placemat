"""`[drc.severities]`: KiCad rule severities placemat writes into the board's
project, so a check the project has decided against (courtyards meeting in
a physical envelope) is set aside by KiCad as by placemat. The generator
rewrites the project on a fresh generation, so a hand edit did not last."""
import json

import pytest

from placemat import settings
from placemat.kicad.drc import patch_rule_severities
from placemat.settings import SettingsError


def test_the_table_is_read(tmp_path):
    (tmp_path / "placemat.toml").write_text('[drc.severities]\ncourtyards_overlap = "ignore"\nsilk_overlap = "warning"\n')
    cfg = settings.load(tmp_path)
    assert cfg.drc_severities == {"courtyards_overlap": "ignore", "silk_overlap": "warning"}


def test_a_severity_kicad_does_not_have_is_refused(tmp_path):
    (tmp_path / "placemat.toml").write_text('[drc.severities]\ncourtyards_overlap = "off"\n')
    with pytest.raises(SettingsError, match="error, warning or ignore"):
        settings.load(tmp_path)


def test_the_project_takes_the_severities_and_keeps_the_rest(tmp_path):
    pcb = tmp_path / "layout.kicad_pcb"
    pro = tmp_path / "layout.kicad_pro"
    pro.write_text(json.dumps({"board": {"design_settings": {"rule_severities": {
        "courtyards_overlap": "error", "clearance": "error"}, "trace_widths": [0.2]}}, "meta": {"version": 1}}))
    patch_rule_severities(pcb, {"courtyards_overlap": "ignore"})
    d = json.loads(pro.read_text())
    assert d["board"]["design_settings"]["rule_severities"] == {"courtyards_overlap": "ignore", "clearance": "error"}
    assert d["board"]["design_settings"]["trace_widths"] == [0.2] and d["meta"] == {"version": 1}


def test_no_table_leaves_the_project_untouched(tmp_path):
    pcb = tmp_path / "layout.kicad_pcb"
    pro = tmp_path / "layout.kicad_pro"
    pro.write_text('{"board": {}}')
    patch_rule_severities(pcb, {})
    assert pro.read_text() == '{"board": {}}'
