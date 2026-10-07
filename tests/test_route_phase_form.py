"""The `[[route.phase]]` form: each selector, the refusals, and the setting as it loads."""
import pytest

from placemat.route_phase import Connection, End, Phase, PhaseError, parse_phases
from placemat.settings import SettingsError, load


def test_each_selector_parses_to_its_phase():
    got = parse_phases([
        {"name": "legs", "current_paths": True, "width": "current", "layers": ["F", "B"], "neckdown": False},
        {"name": "leg", "width": 1.2, "connections": [{"from": {"part": "j1", "pad": "2"}, "to": {"part": "q1", "pad": "VB"}}]},
        {"name": "dp", "pairs": True},
        {"name": "bus", "interfaces": ["Spi", "DISP"], "layers": ["F.Cu"]},
        {"name": "pwr", "net_types": ["Power"], "width": "current"},
        {"name": "rf", "net_classes": ["50Ohm SE"]},
        {"name": "taps", "nets": ["VB*", "!VBX"], "width": 0.3},
        {"name": "grp", "buses": [["D0", "D1"], ["A*"]]},
        {"name": "signals"},
    ])
    assert [p.selector for p in got] == ["current_paths", "connections", "pairs", "interfaces", "net_types",
                                         "net_classes", "nets", "buses", "rest"]
    assert got[0].layers == ("F.Cu", "B.Cu") and got[0].neckdown is False and got[0].width == "current"
    assert got[1].connections == (Connection(End("j1", "2"), End("q1", "VB")),) and got[1].width == 1.2
    assert got[7].buses == (("D0", "D1"), ("A*",))
    assert got[8] == Phase("signals", "rest")


@pytest.mark.parametrize("raw, code", [
    ([{"nets": ["A"]}], "no_name"),
    ([{"name": "a b"}], "bad_name"),
    ([{"name": "x"}, {"name": "x"}], "duplicate_name"),
    ([{"name": "x", "nets": ["A"], "pairs": True}], "two_selectors"),
    ([{"name": "x", "clearance": 0.3}], "clearance_key"),
    ([{"name": "x", "colour": 1}], "unknown_key"),
    ([{"name": "x", "pairs": False}], "flag_true"),
    ([{"name": "x", "width": -1}], "bad_width"),
    ([{"name": "x", "width": "wide"}], "bad_width"),
    ([{"name": "x", "width": float("inf")}], "bad_width"),
    ([{"name": "x", "width": float("nan")}], "bad_width"),
    ([{"name": "x", "router_args": "--bus"}], "bad_router_args"),
    ([{"name": "x", "router_args": ["--bus-nets", "A"]}], "router_owned"),
    ([{"name": "x", "router_args": ["--connections=f"]}], "router_owned"),
    ([{"name": "x", "layers": ["Top"]}], "bad_layers"),
    ([{"name": "x", "neckdown": "no"}], "bad_neckdown"),
    ([{"name": "x", "router_args": ["--nets", "A"]}], "router_owned"),
    ([{"name": "x", "router_args": ["--no-power-tap-neckdown"]}], "router_owned"),
    ([{"name": "x", "connections": [{"from": {"part": "j1"}, "to": {"part": "q1", "pad": "1"}}]}], "bad_connection"),
    ([{"name": "x", "nets": []}], "bad_list"),
    ([{"name": "x", "buses": [["A"], "B"]}], "bad_buses"),
])
def test_a_phase_that_cannot_be_obeyed_is_refused_by_code(raw, code):
    with pytest.raises(PhaseError) as e:
        parse_phases(raw)
    assert e.value.code == code and e.value.facts


def test_the_setting_loads_from_arrays_of_tables(tmp_path):
    (tmp_path / "placemat.toml").write_text(
        '[[route.phase]]\nname = "leg"\nwidth = "current"\n[[route.phase.connections]]\n'
        'from = { part = "j1", pad = "2" }\nto = { part = "q1", pad = "VB" }\n\n[[route.phase]]\nname = "signals"\n')
    cfg = load(tmp_path)
    assert [t["name"] for t in cfg.route_phase] == ["leg", "signals"]


def test_a_bad_phase_fails_the_settings_load_naming_the_file(tmp_path):
    (tmp_path / "placemat.toml").write_text('[[route.phase]]\nname = "x"\nnets = ["A"]\npairs = true\n')
    with pytest.raises(SettingsError, match=r"placemat.toml: route.phase 'x': .*one selector"):
        load(tmp_path)


@pytest.mark.parametrize("flag", ["--connections", "--bus-nets"])
def test_the_new_router_flags_are_placemats_own(tmp_path, flag):
    (tmp_path / "placemat.toml").write_text('[route]\nrouter_args = ["%s", "x"]\n' % flag)
    with pytest.raises(SettingsError, match="is set by placemat itself"):
        load(tmp_path)


def test_a_flag_that_only_starts_like_an_owned_one_is_the_projects(tmp_path):
    assert parse_phases([{"name": "x", "router_args": ["--bus", "A"]}])[0].router_args == ("--bus", "A")
    (tmp_path / "placemat.toml").write_text('[route]\nrouter_args = ["--bus", "A"]\n')
    assert load(tmp_path).route_router_args == ("--bus", "A")


@pytest.mark.parametrize("arg", ["--bus-nets", "--connections=f"])
def test_an_owned_flag_is_refused_in_the_setting_as_well(tmp_path, arg):
    (tmp_path / "placemat.toml").write_text('[route]\npair_router_args = ["%s"]\n' % arg)
    with pytest.raises(SettingsError, match="is set by placemat itself"):
        load(tmp_path)


def test_pairs_take_net_names_p_first():
    (p,) = parse_phases([{"name": "usb", "pairs": [["USB_D+", "USB_D-"], ["TX_P", "TX_N"]]}])
    assert p.selector == "pairs" and p.pairs == (("USB_D+", "USB_D-"), ("TX_P", "TX_N"))
    (q,) = parse_phases([{"name": "dp", "pairs": True}])
    assert q.pairs == ()


@pytest.mark.parametrize("value", [[], [["A"]], [["A", "A"]], [["A", ""]], [["A", "B", "C"]], [[1, 2]]])
def test_a_pair_list_that_is_not_pairs_of_two_nets_is_refused(value):
    with pytest.raises(PhaseError) as e:
        parse_phases([{"name": "x", "pairs": value}])
    assert e.value.code == "bad_pairs" and e.value.facts["value"] == value
