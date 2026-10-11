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


@needs_kicad
def test_the_cli_module_run_as_a_script_writes_a_boards_phases(tmp_path):
    import os
    import subprocess
    import sys
    pcb = board_with_power_and_rf(tmp_path)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    out = subprocess.run([sys.executable, "-m", "placemat.cli", "settings", str(pcb), "--example"],
                         capture_output=True, text=True, timeout=120, env=env, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert "[[route.phase]]" in out.stdout


def test_the_default_current_phase_takes_the_outer_layers_it_is_given():
    """The user's decision of 2026-10-11: the default current phase routes on the board's outer copper layers only."""
    from placemat.route_phase import default_phases
    got = default_phases(pairs=False, interface_types=[], wide_classes=[], currents=True, outer_layers=["F.Cu", "B.Cu"])
    assert got == [{"name": "current", "current_paths": True, "width": "current", "layers": ["F.Cu", "B.Cu"]},
                   {"name": "signals"}]
    plain = default_phases(pairs=False, interface_types=[], wide_classes=[], currents=True)
    assert plain[0] == {"name": "current", "current_paths": True, "width": "current"}


def _four_layers(pcb):
    pcb.write_text(pcb.read_text().replace('\t\t(2 "B.Cu" signal)\n',
                                           '\t\t(2 "B.Cu" signal)\n\t\t(4 "In1.Cu" signal)\n\t\t(6 "In2.Cu" signal)\n'))
    return pcb


@needs_kicad
def test_a_board_with_inner_layers_gets_a_current_phase_on_the_outer_layers_of_its_stack(tmp_path):
    from placemat.kicad.read import read_board
    pcb = _four_layers(board_with_power_and_rf(tmp_path))
    stack = [l.value for l in read_board(str(pcb)).layers]
    assert len(stack) > 2 and stack[1].startswith("In")
    (current,) = [p for p in board_default_phases(pcb) if p["name"] == "current"]
    assert current["layers"] == [stack[0], stack[-1]] == ["F.Cu", "B.Cu"]
    text = phases_text(pcb)
    (written,) = [p for p in tomllib.loads(text)["route"]["phase"] if p["name"] == "current"]
    assert written["layers"] == ["F.Cu", "B.Cu"]


@needs_kicad
def test_a_two_layer_boards_current_phase_names_no_layers(tmp_path):
    (current,) = [p for p in board_default_phases(board_with_power_and_rf(tmp_path)) if p["name"] == "current"]
    assert "layers" not in current


def phases_text(pcb):
    from placemat.route_phase import phases_toml
    return "[route]\n" + phases_toml(board_default_phases(pcb))
