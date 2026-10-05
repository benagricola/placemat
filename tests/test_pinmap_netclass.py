"""A net class's tuning profile, KiCad 10's controlled impedance, is read with the class: the pin map study weighs a
crossing of such a net at `pins.impedance_weight`."""
import json
import shutil
from pathlib import Path

from tests.conftest import needs_kicad

GENERATED = Path(__file__).resolve().parents[1] / "fixtures" / "fairing" / "core" / "generated"


@needs_kicad
def test_a_class_that_names_a_tuning_profile_carries_it_to_its_nets(tmp_path):
    from placemat.kicad.read import read_board
    for f in GENERATED.glob("layout.kicad_p*"):
        shutil.copy(f, tmp_path / f.name)
    pro = tmp_path / "layout.kicad_pro"
    doc = json.loads(pro.read_text())
    for c in doc["net_settings"]["classes"]:
        if c["name"] == "50Ohm SE":
            c["tuning_profile"] = "SE50"
    pro.write_text(json.dumps(doc, indent=2))
    g = read_board(tmp_path / "layout.kicad_pcb")
    profiled = {n for n, nc in g.netclasses.items() if nc.tuning_profile}
    assert profiled and all(g.netclasses[n].tuning_profile == "SE50" for n in profiled)
    assert all("50Ohm SE" in g.netclasses[n].name for n in profiled)
