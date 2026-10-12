"""pairs = true and interfaces select what the capture's nets.layout.json says (Zener fork stage 2)."""
import pytest

from placemat.capture_nets import read_capture
from placemat.kicad.phase_select import select
from placemat.route_phase import PhaseError, parse_phases
from tests.fixtures import board_geometry, footprint
from tests.phase_helpers import write_sidecar


def board():
    return board_geometry([footprint("U1", 5, 5, nets=("USB_D_P", "USB_D_N")), footprint("J1", 20, 5, nets=("USB_D_P", "USB_D_N")),
                           footprint("U2", 5, 20, nets=("DISP_CLK", "DISP_MOSI")), footprint("J2", 20, 20, nets=("DISP_CLK", "DISP_MOSI"))])


def capture(tmp_path):
    write_sidecar(tmp_path, {n: {"type": "Net", "fields": {}} for n in ("USB_D_P", "USB_D_N", "DISP_CLK", "DISP_MOSI")},
                  exports=["types", "fields", "interfaces"],
                  interfaces={"DISP": {"type": "Spi", "members": {"CLK": "DISP_CLK", "MOSI": "DISP_MOSI"}},
                              "USB.D": {"type": "DiffPair", "members": {"P": "USB_D_P", "N": "USB_D_N"}}},
                  pairs=[{"instance": "USB.D", "p": "USB_D_P", "n": "USB_D_N"}])
    return read_capture(tmp_path / "nets.layout.json")


def one(raw, cap):
    g = board()
    return select(parse_phases([raw])[0], g, cap, open_nets=set(g.nets), excluded=set(), pour_nets=set(),
                  route_layers=["F.Cu", "B.Cu"], rise_c=10.0, copper_oz=1.0)


def test_pairs_are_the_diffpair_instances(tmp_path):
    assert one({"name": "dp", "pairs": True}, capture(tmp_path)).pairs == (("USB_D_P", "USB_D_N"),)


def test_an_interface_type_selects_each_instance_as_a_bus(tmp_path):
    assert one({"name": "b", "interfaces": ["Spi"]}, capture(tmp_path)).buses == (("DISP_CLK", "DISP_MOSI"),)


def test_an_instance_is_selected_by_its_path(tmp_path):
    assert one({"name": "b", "interfaces": ["DISP"]}, capture(tmp_path)).buses == (("DISP_CLK", "DISP_MOSI"),)


def test_an_unknown_instance_is_refused(tmp_path):
    with pytest.raises(PhaseError) as e:
        one({"name": "b", "interfaces": ["CAM"]}, capture(tmp_path))
    assert e.value.code == "not_on_board" and e.value.facts["value"] == "CAM"


def test_a_stage_one_sidecar_refuses_interfaces(tmp_path):
    write_sidecar(tmp_path, {"DISP_CLK": {"type": "Net", "fields": {}}})
    with pytest.raises(PhaseError) as e:
        one({"name": "b", "interfaces": ["Spi"]}, read_capture(tmp_path / "nets.layout.json"))
    assert e.value.code == "needs_capture"
