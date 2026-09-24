"""Design checks: the board is read with the `Pm.*` facts its parts carry
(written by the capture as footprint fields), and each check reports a
number, the limit it is judged against and a verdict."""
from tests.conftest import needs_kicad
import json
import math

import pytest

from placemat.checks import (AMBIENT_C, facts, hot_loops, switch_nodes, keep_out, crossings_under,
                             current_paths, heat, ipc2221_width_mm, run_checks)
from placemat.values import CopperLayer
from tests.fixtures import board_geometry, footprint, track

F, B = CopperLayer.F, CopperLayer.B


def buck():
    """A buck in two-pad parts: cin and the switcher close the hot loop on
    VIN/GND, the switcher and the inductor own SW, the divider senses FB."""
    cin = footprint("C1", 10, 10, nets=("VIN", "GND"), fields={"Pm.Role": "bypass", "Pm.Loop": "hot"})
    u = footprint("U1", 14, 13, nets=("VIN", "SW"),
                  fields={"Pm.Role": "switcher", "Pm.Loop": "hot", "Pm.Aggressor": "true",
                          "Pm.I": "3A", "Pm.Pd": "0.6W", "Pm.Tjmax": "125C"})
    l = footprint("L1", 20, 13, nets=("SW", "VOUT"), fields={"Pm.Role": "inductor", "Pm.Aggressor": "true"})
    cout = footprint("C2", 26, 13, nets=("VOUT", "GND"), fields={"Pm.Role": "output"})
    rfb = footprint("R1", 20, 20, nets=("VOUT", "FB"), fields={"Pm.Role": "sense", "Pm.Sensitive": "fb"})
    return cin, u, l, cout, rfb


def test_a_parts_fields_are_read_as_typed_facts():
    cin, u, l, cout, rfb = buck()
    f = facts(board_geometry([cin, u, l, cout, rfb]))
    assert f["U1"].role == "switcher" and f["U1"].loop == "hot" and f["U1"].aggressor
    assert f["U1"].current_a == pytest.approx(3.0) and f["U1"].dissipation_w == pytest.approx(0.6)
    assert f["U1"].tj_max_c == pytest.approx(125.0)
    assert f["R1"].sensitive == "fb" and not f["R1"].aggressor and f["R1"].current_a is None
    assert facts(board_geometry([footprint("X1", 1, 1, fields={"Pm.I": "250mA"})]))["X1"].current_a == pytest.approx(0.25)


def test_a_hot_loop_is_the_hull_of_its_parts_pads_on_the_nets_they_share():
    cin, u, l, cout, rfb = buck()
    (loop,) = hot_loops(board_geometry([cin, u, l, cout, rfb]))
    assert loop.name == "hot" and set(loop.parts) == {"C1", "U1"} and set(loop.nets) == {"VIN"}
    # C1's VIN pad (8.6, 10) and U1's VIN pad (12.6, 13): the loop is VIN out and back through the parts
    assert loop.longest_leg_mm == pytest.approx(5.0)
    assert loop.area_mm2 == pytest.approx(0.0)      # two points enclose nothing; C1's GND pad is not on a shared net


def test_a_hot_loop_with_a_return_encloses_an_area():
    cin = footprint("C1", 10, 10, nets=("VIN", "GND"), fields={"Pm.Loop": "hot"})
    u = footprint("U1", 14, 13, nets=("VIN", "GND"), fields={"Pm.Loop": "hot"})
    (loop,) = hot_loops(board_geometry([cin, u]))
    assert set(loop.nets) == {"VIN", "GND"}
    assert loop.area_mm2 == pytest.approx(8.4)      # the parallelogram (8.6,10) (11.4,10) (15.4,13) (12.6,13)


def test_the_switch_node_is_a_net_owned_entirely_by_aggressors_and_its_copper_is_measured():
    cin, u, l, cout, rfb = buck()
    sw = track("SW", 15.4, 13, 18.6, 13, w=0.3)     # U1's SW pad to L1's SW pad
    (node,) = switch_nodes(board_geometry([cin, u, l, cout, rfb], copper=[sw]))
    assert node.net == "SW" and set(node.parts) == {"U1", "L1"}
    assert node.area_mm2 == pytest.approx(2 * 1.0 + (3.2 + 0.3) * 0.3)     # two 1 mm pads and the track
    assert node.extent_mm == pytest.approx(18.6 + 0.5 - (15.4 - 0.5))        # pad edge to pad edge


def test_keep_out_reports_the_nearest_sensitive_copper_to_each_switch_node():
    cin, u, l, cout, rfb = buck()
    (v,) = keep_out(board_geometry([cin, u, l, cout, rfb]), limit_mm=2.0)
    # R1's FB pad box spans x 20.9..21.9, y 19.5..20.5; L1's SW pad box spans x 18.1..19.1, y 12.5..13.5
    assert v.subject == "SW" and v.value == pytest.approx(math.hypot(20.9 - 19.1, 19.5 - 13.5))
    assert v.ok and v.limit == 2.0
    far = footprint("R1", 20, 40, nets=("VOUT", "FB"), fields={"Pm.Sensitive": "fb"})
    near = footprint("R1", 19, 15, nets=("VOUT", "FB"), fields={"Pm.Sensitive": "fb"})
    assert keep_out(board_geometry([cin, u, l, cout, far]), limit_mm=2.0)[0].ok
    assert not keep_out(board_geometry([cin, u, l, cout, near]), limit_mm=2.0)[0].ok


def test_a_crossing_under_a_sensitive_track_by_another_net_is_counted():
    cin, u, l, cout, rfb = buck()
    fb = track("FB", 21.4, 20, 30, 20, w=0.2, layer=F)
    under = track("SW", 25, 10, 25, 30, w=0.3, layer=B)
    beside = track("GND", 40, 10, 40, 30, w=0.3, layer=B)
    (v,) = crossings_under(board_geometry([cin, u, l, cout, rfb], copper=[fb, under, beside]))
    assert v.subject == "FB" and v.value == 1 and not v.ok
    assert crossings_under(board_geometry([cin, u, l, cout, rfb], copper=[fb, beside]))[0].ok


def test_ipc2221_width_for_an_outer_track():
    # 3 A at a 10 C rise on 1 oz copper: 74 sq mil of cross-section, 54 mil wide
    assert ipc2221_width_mm(3.0, rise_c=10.0, copper_oz=1.0) == pytest.approx(1.37, abs=0.02)
    assert ipc2221_width_mm(1.0, rise_c=10.0, copper_oz=1.0) < ipc2221_width_mm(3.0, rise_c=10.0, copper_oz=1.0)


def test_a_current_path_is_judged_by_its_narrowest_track():
    cin, u, l, cout, rfb = buck()
    vin = track("VIN", 8.6, 10, 12.6, 13, w=0.5)
    sw = track("SW", 15.4, 13, 18.6, 13, w=1.5)
    verdicts = current_paths(board_geometry([cin, u, l, cout, rfb], copper=[vin, sw]))
    by_net = {v.subject: v for v in verdicts}
    assert set(by_net) == {"VIN", "SW"}                 # U1 carries 3 A: the nets on its pads
    assert by_net["VIN"].value == pytest.approx(0.5) and not by_net["VIN"].ok
    assert by_net["SW"].value == pytest.approx(1.5) and by_net["SW"].ok
    assert by_net["VIN"].limit == pytest.approx(ipc2221_width_mm(3.0, 10.0, 1.0))


def test_heat_needs_a_thermal_resistance_and_judges_junction_against_its_maximum():
    cin, u, l, cout, rfb = buck()
    (v,) = heat(board_geometry([cin, u, l, cout, rfb]), ambient_c=AMBIENT_C)
    assert v.subject == "U1" and v.ok is None and "Pm.ThetaJb" in v.note      # unknown: no thermal resistance
    hot = footprint("U1", 14, 13, nets=("VIN", "SW"),
                    fields={"Pm.Pd": "0.6W", "Pm.Tjmax": "125C", "Pm.Thetaja": "80C/W"})
    (v,) = heat(board_geometry([cin, hot, l, cout, rfb]), ambient_c=100.0)
    assert v.value == pytest.approx(148.0) and v.limit == 125.0 and not v.ok
    (v,) = heat(board_geometry([cin, hot, l, cout, rfb]), ambient_c=60.0)
    assert v.value == pytest.approx(108.0) and v.ok


def test_run_checks_reports_every_check_with_its_name():
    cin, u, l, cout, rfb = buck()
    report = run_checks(board_geometry([cin, u, l, cout, rfb]))
    assert {v.check for v in report} >= {"hot-loop", "switch-node", "keep-out", "crossings-under", "current-path", "heat"}
    assert all(v.unit for v in report)


@needs_kicad          # it patches placemat.kicad.read, which imports pcbnew
def test_the_check_command_prints_one_line_per_verdict_and_fails_on_a_failed_one(monkeypatch, capsys):
    from placemat import cli
    cin, u, l, cout, rfb = buck()
    near = footprint("R1", 19, 15, nets=("VOUT", "FB"), fields={"Pm.Sensitive": "fb"})
    geometry = board_geometry([cin, u, l, cout, near])
    monkeypatch.setattr("placemat.kicad.read.read_board", lambda path: geometry)
    assert cli.main(["check", "layout.kicad_pcb"]) == 1                 # keep-out fails
    out = capsys.readouterr().out
    assert "keep-out" in out and "FAIL" in out and "hot-loop" in out
    assert cli.main(["check", "layout.kicad_pcb", "--keep-out", "0.5"]) == 0
    capsys.readouterr()
    assert cli.main(["check", "layout.kicad_pcb", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert {d["check"] for d in data} >= {"keep-out", "heat"} and any(d["ok"] is False for d in data)


def test_a_current_may_be_given_per_net_so_a_control_pin_is_not_sized_for_the_power_path():
    u = footprint("U1", 14, 13, nets=("VIN", "FB"), fields={"Pm.I": "vin:3A fb:1mA"})
    f = facts(board_geometry([u]))
    assert f["U1"].current_a is None and f["U1"].currents == {"vin": 3.0, "fb": 0.001}
    vin = track("VIN", 8.6, 10, 12.6, 13, w=0.5)
    fb = track("FB", 15.4, 13, 20, 13, w=0.2)
    by_net = {v.subject: v for v in current_paths(board_geometry([u], copper=[vin, fb]))}
    assert not by_net["VIN"].ok and by_net["FB"].ok
    assert by_net["FB"].limit == pytest.approx(ipc2221_width_mm(0.001, 10.0, 1.0))


def test_a_sensitive_net_named_wrongly_falls_back_to_the_parts_local_node_and_says_so():
    cin, u, l, cout, rfb = buck()
    misnamed = footprint("R1", 20, 20, nets=("VOUT", "VFB"), fields={"Pm.Sensitive": "fb"})
    (v,) = crossings_under(board_geometry([cin, u, l, cout, misnamed]))
    assert v.subject == "VFB" and "no pad of R1 is on a net called fb" in v.note


def test_a_net_carried_by_a_pour_is_judged_by_the_pour_not_its_pin_leads():
    from placemat.board_geometry import CopperItem
    from placemat.values import Box
    from tests.fixtures import rect
    u = footprint("U1", 14, 13, nets=("VIN", "SW"), fields={"Pm.I": "vin:3A"})
    lead = track("VIN", 12.6, 13, 12.6, 11, w=0.2)                       # the pin's lead into the pour
    outline = rect(12.6, 8, 6, 4)
    pour = CopperItem("poly", "VIN", frozenset([F]), (outline,), Box.of_points(outline))
    (v,) = current_paths(board_geometry([u], copper=[lead, pour]))
    assert v.ok and v.value == pytest.approx(4.0) and "pin leads, narrowest 0.20" in v.note


def test_keep_out_ignores_a_parts_own_adjacent_pins():
    """The switcher's FB pin sits next to its own BST pin: package geometry,
    not layout. Only copper of another part, or a track or pour, counts."""
    u = footprint("U1", 14, 13, nets=("FB", "SW"), fields={"Pm.Aggressor": "true", "Pm.Sensitive": "FB"})
    l = footprint("L1", 20, 13, nets=("SW", "VOUT"), fields={"Pm.Aggressor": "true"})
    (v,) = keep_out(board_geometry([u, l]), limit_mm=2.0)
    assert v.value == pytest.approx(5.0) and v.ok                      # L1's SW pad, not U1's own SW pad next door
    sw = track("SW", 15.4, 13, 18.6, 13, w=0.3)
    (v,) = keep_out(board_geometry([u, l], copper=[sw]), limit_mm=2.0)
    assert v.value == pytest.approx(15.4 - 0.15 - (12.6 + 0.5))       # the track's end to U1's FB pad edge


def test_a_pours_narrowest_neck_is_the_current_paths_width():
    from placemat.checks import neck_mm
    from placemat.board_geometry import CopperItem
    from placemat.values import Box
    # two 4 x 4 pads of copper joined by a 1.0 wide, 3 long neck
    dumbbell = ((0, 0), (4, 0), (4, 1.5), (7, 1.5), (7, 0), (11, 0), (11, 4), (7, 4), (7, 2.5), (4, 2.5), (4, 4), (0, 4))
    assert neck_mm(dumbbell) == pytest.approx(1.0)
    u = footprint("U1", 2, 2, nets=("VIN", "SW"), fields={"Pm.I": "vin:3A"})
    pour = CopperItem("poly", "VIN", frozenset([F]), (dumbbell,), Box.of_points(dumbbell))
    (v,) = current_paths(board_geometry([u], copper=[pour]))
    assert v.value == pytest.approx(1.0) and v.ok is False and "neck" in v.note
    wide = CopperItem("poly", "VIN", frozenset([F]), (((0, 0), (11, 0), (11, 4), (0, 4)),), Box(0, 0, 11, 4))
    (v,) = current_paths(board_geometry([u], copper=[wide]))
    assert v.value == pytest.approx(4.0) and v.ok


def test_heat_from_a_board_temperature_uses_junction_to_board_when_the_part_gives_it():
    cin, u, l, cout, rfb = buck()
    both = footprint("U1", 14, 13, nets=("VIN", "SW"),
                     fields={"Pm.Pd": "0.74W", "Pm.Tjmax": "125C", "Pm.Thetaja": "92.6C/W", "Pm.Thetajb": "15.5C/W"})
    (v,) = heat(board_geometry([cin, both, l, cout, rfb]), ambient_c=100.0)
    assert v.value == pytest.approx(100 + 0.74 * 15.5) and v.ok and "board" in v.note
    ja_only = footprint("U1", 14, 13, nets=("VIN", "SW"), fields={"Pm.Pd": "0.74W", "Pm.Tjmax": "125C", "Pm.Thetaja": "92.6C/W"})
    (v,) = heat(board_geometry([cin, ja_only, l, cout, rfb]), ambient_c=100.0)
    assert v.value == pytest.approx(100 + 0.74 * 92.6) and not v.ok and "JEDEC" in v.note
