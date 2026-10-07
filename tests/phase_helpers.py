"""Phases for tests that route: the rest phase alone, which routes what the old main pass did; and the capability
listing a stand-in router gives so a route takes it for the placemat fork."""
import json

from placemat.route_phase import parse_phases

SIGNALS = ({"name": "signals"},)
CAPABILITIES = {"modules": {"route.py": True}, "flags": {"route.py": ["--connections", "--bus-nets"]}}


def phases(*raw):
    return parse_phases(raw or SIGNALS)


def fake_capabilities(krt) -> None:
    """A stand-in router checkout's krt_capabilities.py: it lists every flag a phase route needs (route.REQUIRES)."""
    (krt / "krt_capabilities.py").write_text("print(%r)\n" % json.dumps(CAPABILITIES))


def write_sidecar(folder, nets, **over):
    from tests.test_capture_nets import write
    return write(folder, nets=nets, **over)


def board_with_power_and_rf(tmp_path):
    from tests.test_net_clearance import _two_part_board, _project
    pcb = _two_part_board(tmp_path)
    text = pcb.read_text().replace('(property "Reference"', '(property "Pm.I" "4A") (property "Reference"')
    pcb.write_text(text)
    _project(pcb, [{"name": "Default", "clearance": 0.15, "track_width": 0.2},
                   {"name": "RF", "clearance": 0.3, "track_width": 0.2}], assignments={"VIN": ["RF"]})
    return pcb
