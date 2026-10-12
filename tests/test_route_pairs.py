"""Differential pairs in the route step: the router's pair router
(route_diff.py) routes the named pairs first, then route.py routes the rest
with the coupled pairs left out. Pure: command lines and summaries."""
import json

from placemat.kicad.route import pair_command, read_pairs, router_command


def test_the_pair_command_routes_the_patterns_on_the_layers_with_escalation_off():
    cmd = pair_command("py", "route_diff.py", "in.kicad_pcb", "out.kicad_pcb", ("*",), ["F.Cu", "B.Cu"])
    assert cmd[:4] == ["py", "route_diff.py", "in.kicad_pcb", "out.kicad_pcb"]
    assert cmd[cmd.index("--nets") + 1] == "*"
    assert cmd[cmd.index("--layers") + 1:cmd.index("--layers") + 3] == ["F.Cu", "B.Cu"]
    assert cmd[cmd.index("--escalation") + 1] == "off"


def test_width_and_gap_come_from_the_net_class_unless_set():
    cmd = pair_command("py", "route_diff.py", "i", "o", ("*",), ["F.Cu"])
    assert "--diff-pair-gap" not in cmd and "--track-width" not in cmd
    cmd = pair_command("py", "route_diff.py", "i", "o", ("*",), ["F.Cu"], gap=0.45, width=0.2)
    assert cmd[cmd.index("--diff-pair-gap") + 1] == "0.45"
    assert cmd[cmd.index("--track-width") + 1] == "0.2"


def test_an_iteration_cap_reaches_the_pair_router_too():
    cmd = pair_command("py", "route_diff.py", "i", "o", ("*",), ["F.Cu"], iterations=300)
    assert cmd[cmd.index("--max-iterations") + 1] == "300"


def _summary(**kw):
    base = {"routed_diff_pairs": [], "failed_diff_pairs": [], "partial_diff_pairs": [],
            "single_ended_diff_pairs": [], "pair_reports": []}
    base.update(kw)
    return "JSON_SUMMARY: " + json.dumps(base)


def test_the_pairs_are_read_from_the_pair_routers_own_summary():
    reports = [{"pair": "USB", "p_net": "USB_P", "n_net": "USB_N", "outcome": "routed"},
               {"pair": "LVDS", "p_net": "LVDS_P", "n_net": "LVDS_N", "outcome": "failed"},
               {"pair": "CLK", "p_net": "CLK+", "n_net": "CLK-", "outcome": "partial"}]
    log = "\n".join(["Routing...", 'JSON_SUMMARY: {"successful": 1}',     # a nested run's, without the pair keys
                     _summary(routed_diff_pairs=["USB"], failed_diff_pairs=["LVDS"],
                              partial_diff_pairs=["CLK"], pair_reports=reports), "done"])
    pairs = read_pairs(log)
    assert pairs.coupled == ["USB"] and pairs.failed == ["LVDS"] and pairs.partial == ["CLK"]
    # the coupled and partial pairs' copper stays; route.py routes the rest
    assert pairs.routed_nets == {"USB_P", "USB_N", "CLK+", "CLK-"}


def test_a_log_without_a_pair_summary_reads_as_no_pairs():
    pairs = read_pairs("Error: No differential pairs found matching the patterns!\n")
    assert pairs.coupled == [] and pairs.routed_nets == set()


def test_the_coupled_pairs_are_left_out_of_the_single_ended_route():
    cmd = router_command("py", "route.py", "i", "o", {"GND"} | {"USB_P", "USB_N"}, ["F.Cu"], "s.json")
    assert "!USB_P" in cmd and "!USB_N" in cmd and "!GND" in cmd
