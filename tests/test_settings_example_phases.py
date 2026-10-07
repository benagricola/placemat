"""`placemat settings --example` writes the default routing phases: for a board, from what it has."""
import tomllib

from placemat.cli import board_default_phases
from placemat.settings import example_toml, load
from tests.conftest import needs_kicad
from tests.phase_helpers import board_with_power_and_rf, write_sidecar


def test_without_a_board_the_example_has_the_rest_phase(tmp_path):
    text = example_toml()
    assert [p["name"] for p in tomllib.loads(text)["route"]["phase"]] == ["signals"]
    (tmp_path / "placemat.toml").write_text(text)
    assert [p["name"] for p in load(tmp_path).route_phase] == ["signals"]


@needs_kicad
def test_a_board_with_pairs_currents_a_wide_class_and_a_capture_gets_their_phases(tmp_path):
    pcb = board_with_power_and_rf(tmp_path)          # U1/J1 carry VIN and FB at4A; VIN is in a0.3mm class
    write_sidecar(pcb.parent, {"VIN": {"type": "Power", "fields": {}}}, exports=["types", "fields", "interfaces"],
                  interfaces={"S": {"type": "Spi", "members": {"CLK": "VIN", "MOSI": "FB"}}},
                  pairs=[{"instance": "USB.D", "p": "VIN", "n": "FB"}])
    got = board_default_phases(pcb)
    assert [p["name"] for p in got] == ["diff-pairs", "buses", "wide-clearance", "current", "signals"]
    assert got[0] == {"name": "diff-pairs", "pairs": True}


@needs_kicad
def test_a_board_whose_capture_has_no_pair_gets_no_pair_phase(tmp_path):
    pcb = board_with_power_and_rf(tmp_path)
    write_sidecar(pcb.parent, {"VIN": {"type": "Power", "fields": {}}}, exports=["types", "fields", "interfaces"],
                  interfaces={"S": {"type": "Spi", "members": {"CLK": "VIN", "MOSI": "FB"}}}, pairs=[])
    assert [p["name"] for p in board_default_phases(pcb)] == ["buses", "wide-clearance", "current", "signals"]


def test_explicit_user_phases_replace_example_defaults(tmp_path):
    text = example_toml()
    assert text.count('[[route.phase]]') == 1
    (tmp_path / "placemat.toml").write_text('[route]\n[[route.phase]]\nname = "power"\nnets = ["V"]\nwidth = 0.8\n')
    phases = load(tmp_path).route_phase
    assert len(phases) == 1 and phases[0]["name"] == "power"
    assert phases[0]["width"] == 0.8


def test_default_interfaces_deduplicate_types_and_keep_diffpair_in_its_phase():
    from placemat.route_phase import default_phases
    result = default_phases(pairs=True, interface_types=["Spi", "DiffPair", "Spi"], wide_classes=[], currents=False)
    assert result == [{"name": "diff-pairs", "pairs": True}, {"name": "buses", "interfaces": ["Spi"]}, {"name": "signals"}]
