"""What a phase selects on a board (kicad/phase_select.py)."""
from dataclasses import replace

import pytest

from placemat.board_geometry import NetClass
from placemat.kicad.phase_select import current_tasks, layer_widths, net_matches, select
from placemat.route_phase import PhaseError, parse_phases
from tests.fixtures import board_geometry, footprint

LAYERS = ["F.Cu", "B.Cu"]


def board():
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"), fields={"Pm.I": "4A"})
    q1 = footprint("Q1", 20, 10, nets=("VB", "VOUT"), fields={"Pm.I": "4A"})
    u1 = footprint("U1", 30, 20, nets=("VB", "SDA"), fields={"Pm.I": "1mA"})
    r1 = footprint("R1", 30, 30, nets=("SDA", "SCL"))
    r2 = footprint("R2", 35, 30, nets=("SCL", "!RST"))
    g = board_geometry([j1, q1, u1, r1, r2])
    classes = dict(g.netclasses)
    classes["VOUT"] = NetClass("Wide", 0.4, 0.3, 0.6, 0.3)
    return replace(g, netclasses=classes)


def one(raw, capture=None, **kw):
    g = board()
    args = dict(open_nets=set(g.nets), excluded=set(), pour_nets=set(), route_layers=LAYERS, rise_c=10.0, copper_oz=1.0)
    args.update(kw)
    return select(parse_phases([raw])[0], g, capture, **args)


def test_nets_by_name_and_glob_with_an_exclusion():
    s = one({"name": "p", "nets": ["S*", "!SCL"], "width": 0.3})
    assert s.nets == ("SDA",) and s.width == 0.3 and s.layers == ("F.Cu", "B.Cu")


def test_an_active_low_net_is_named_with_its_escape():
    assert net_matches("!RST", "\\!RST") and not net_matches("RST", "\\!RST")
    assert one({"name": "p", "nets": ["\\!RST"]}).nets == ("!RST",)


def test_a_class_selects_its_nets():
    assert one({"name": "p", "net_classes": ["Wide"]}).nets == ("VOUT",)


def test_only_open_nets_are_selected():
    assert one({"name": "p", "nets": ["S*"]}, open_nets={"SCL"}).nets == ("SCL",)


def test_the_rest_takes_every_open_net_not_excluded_nor_a_pour():
    s = one({"name": "signals"}, excluded={"GND"}, pour_nets={"VB"})
    assert s.rest and "GND" not in s.nets and "VB" not in s.nets and "SDA" in s.nets


def test_a_named_pour_net_is_routed_as_one():
    s = one({"name": "p", "nets": ["VB"]}, pour_nets={"VB"})
    assert s.pour_nets == ("VB",) and s.nets == ()


def test_buses_keep_their_groups():
    assert one({"name": "p", "buses": [["SDA", "SCL"]]}).buses == (("SDA", "SCL"),)


def test_a_connection_resolves_by_pad_number_or_net():
    s = one({"name": "p", "width": 1.0, "connections": [{"from": {"part": "j1", "pad": "1"}, "to": {"part": "Q1", "pad": "VB"}}]})
    (t,) = s.tasks
    assert (t.net, t.start, t.end) == ("VB", ("J1", "1"), ("Q1", "1")) and dict(t.widths) == {"F.Cu": 1.0, "B.Cu": 1.0}


def test_current_paths_size_each_pair_at_the_lesser_current_per_layer():
    s = one({"name": "p", "current_paths": True, "width": "current"})
    by_pair = {(t.start[0], t.end[0]): t for t in s.tasks}
    assert by_pair[("J1", "Q1")].amps == 4.0 and by_pair[("J1", "U1")].amps == pytest.approx(0.001)
    assert dict(by_pair[("J1", "Q1")].widths)["F.Cu"] > dict(by_pair[("J1", "U1")].widths)["F.Cu"]


def test_an_inner_layer_needs_more_width_for_the_same_current():
    g = board()
    outer = dict(layer_widths(4.0, ["F.Cu"], g, 10.0, 1.0))["F.Cu"]
    inner = dict(layer_widths(4.0, ["In1.Cu"], g, 10.0, 1.0))["In1.Cu"]
    assert inner > outer


def test_a_width_is_never_under_the_boards_minimum():
    g = replace(board(), min_track_width=0.2)
    assert dict(layer_widths(0.001, ["F.Cu"], g, 10.0, 1.0))["F.Cu"] == 0.2


def test_current_width_on_a_net_with_one_carrier_is_refused_naming_it():
    with pytest.raises(PhaseError) as e:
        one({"name": "p", "nets": ["SDA"], "width": "current"})
    assert e.value.code == "no_current" and e.value.facts["nets"] == ["SDA"]


@pytest.mark.parametrize("selector", [{"pairs": True}, {"interfaces": ["Spi"]}, {"net_types": ["Power"]}])
def test_capture_selectors_without_a_sidecar_are_refused(selector):
    with pytest.raises(PhaseError) as e:
        one(dict({"name": "p"}, **selector))
    assert e.value.code == "needs_capture"


@pytest.mark.parametrize("raw, kind", [
    ({"name": "p", "nets": ["NOPE"]}, "net"), ({"name": "p", "nets": ["Z*"]}, "net"),
    ({"name": "p", "net_classes": ["Gone"]}, "class"),
    ({"name": "p", "connections": [{"from": {"part": "X9", "pad": "1"}, "to": {"part": "Q1", "pad": "1"}}]}, "part"),
])
def test_a_selector_that_names_nothing_on_the_board_is_refused(raw, kind):
    with pytest.raises(PhaseError) as e:
        one(raw)
    assert e.value.code == "not_on_board" and e.value.facts["kind"] == kind


def test_layers_the_board_lacks_are_refused_naming_its_layers():
    with pytest.raises(PhaseError) as e:
        one({"name": "p", "nets": ["SDA"], "layers": ["In2"]})
    assert e.value.code == "layer_missing" and e.value.facts["board_layers"] == ["F.Cu", "B.Cu"]


def test_current_tasks_span_every_pad_of_both_parts():
    two = footprint("Q2", 20, 10, nets=("VB", "VB"), fields={"Pm.I": "4A"})
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"), fields={"Pm.I": "4A"})
    tasks, missing = current_tasks(board_geometry([j1, two]), ["VB"], LAYERS, 10.0, 1.0)
    assert {(t.start, t.end) for t in tasks} == {(("J1", "1"), ("Q2", "1")), (("J1", "1"), ("Q2", "2"))} and not missing


def test_a_pairs_selection_from_the_capture_lists_each_physical_pair_once():
    from placemat.capture_nets import Capture
    cap = Capture("x", "d", {"name": "g"}, frozenset({"interfaces"}), {}, {},
                  (("a.usb", "SDA", "SCL"), ("b.usb", "SDA", "SCL")))
    assert one({"name": "p", "pairs": True}, cap).pairs == (("SDA", "SCL"),)
    assert one({"name": "p", "pairs": True}, cap, open_nets={"SDA"}).pairs == ()


def test_every_new_refusal_renders_its_text():
    from placemat.route_phase import phase_error_text
    for code, facts in [("needs_capture", {"name": "p", "selector": "pairs", "generator": None}),
                        ("not_on_board", {"name": "p", "kind": "net", "value": "X"}),
                        ("layer_missing", {"name": "p", "layers": ["In2.Cu"], "board_layers": LAYERS}),
                        ("no_current", {"name": "p", "nets": ["SDA"]}),
                        ("no_current", {"name": "p", "connections": [{"net": "N", "from": "J1", "to": "Q1"}]}),
                        ("ends_on_two_nets", {"name": "p", "index": 0, "nets": ["A", "B"]})]:
        assert "route.phase 'p'" in phase_error_text(code, facts)


def _plain(**kw):
    j1 = footprint("J1", 5, 10, nets=("VB", ""), fields={"Pm.I": "4A"})
    q1 = footprint("Q1", 20, 10, nets=("VB", ""), fields={"Pm.I": "4A"})
    nc = footprint("J2", 30, 10, nets=("unconnected-(J2-Pad1)", "unconnected-(J2-Pad1)"))
    g = board_geometry([j1, q1, nc])
    return g


def _sel(g, raw, **kw):
    args = dict(open_nets=set(g.nets), excluded=set(), pour_nets=set(), route_layers=LAYERS, rise_c=10.0, copper_oz=1.0)
    args.update(kw)
    return select(parse_phases([raw])[0], g, None, **args)


def test_current_paths_skip_pads_on_no_net():
    s = _sel(_plain(), {"name": "p", "current_paths": True})
    assert {t.net for t in s.tasks} == {"VB"}


def test_the_wildcard_leaves_out_unconnected_nets_a_literal_takes_them():
    g = _plain()
    assert _sel(g, {"name": "p", "nets": ["*"]}).nets == ("VB",)
    assert _sel(g, {"name": "p", "nets": ["unconnected-(J2-Pad1)"]}).nets == ("unconnected-(J2-Pad1)",)


@pytest.mark.parametrize("patterns", [["*", "!GDN"], ["*", "!ZZ*"], ["!GDN"]])
def test_an_exclusion_naming_no_net_is_refused(patterns):
    with pytest.raises(PhaseError) as e:
        one({"name": "p", "nets": patterns})
    assert e.value.code == "not_on_board" and e.value.facts["kind"] == "net"


def test_an_exclusion_only_list_takes_every_other_net():
    assert "GND" not in one({"name": "p", "nets": ["!GND"]}).nets and "SDA" in one({"name": "p", "nets": ["!GND"]}).nets


def test_a_connection_on_no_net_is_refused():
    with pytest.raises(PhaseError) as e:
        _sel(_plain(), {"name": "p", "connections": [{"from": {"part": "J1", "pad": "2"}, "to": {"part": "Q1", "pad": "2"}}]})
    assert e.value.code == "not_on_board" and e.value.facts["kind"] == "pad"


def test_a_connection_without_a_width_takes_the_default_class_width():
    s = one({"name": "p", "connections": [{"from": {"part": "R1", "pad": "1"}, "to": {"part": "U1", "pad": "2"}}]})
    assert dict(s.tasks[0].widths) == {"F.Cu": 0.2, "B.Cu": 0.2}


def test_capture_pairs_the_board_lacks_or_none_are_refused():
    from placemat.capture_nets import Capture
    def cap(pairs):
        return Capture("x", "d", {"name": "g"}, frozenset({"interfaces"}), {}, {}, pairs)
    with pytest.raises(PhaseError) as e:
        one({"name": "p", "pairs": True}, cap((("a", "SDA", "NOPE"),)))
    assert e.value.facts["kind"] == "net" and e.value.facts["value"] == "NOPE"
    with pytest.raises(PhaseError) as e:
        one({"name": "p", "pairs": True}, cap(()))
    assert e.value.facts["kind"] == "pair"


def test_the_pour_nets_of_a_task_set_are_named():
    s = one({"name": "p", "current_paths": True}, pour_nets={"VB"})
    assert s.pour_nets == ("VB",) and s.tasks


def test_pairs_by_name_need_no_capture_and_keep_p_first():
    assert one({"name": "p", "pairs": [["SDA", "SCL"]]}).pairs == (("SDA", "SCL"),)


def test_a_named_pair_with_a_net_already_joined_is_not_routed():
    assert one({"name": "p", "pairs": [["SDA", "SCL"]]}, open_nets={"SDA"}).pairs == ()


def test_a_named_pair_net_the_board_lacks_is_refused():
    with pytest.raises(PhaseError) as e:
        one({"name": "p", "pairs": [["SDA", "NOPE"]]})
    assert e.value.code == "not_on_board" and e.value.facts == {"name": "p", "kind": "net", "value": "NOPE"}
