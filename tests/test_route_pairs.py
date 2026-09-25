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


# ---------------------------------------------------------------- routed

import math  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from placemat.kicad.route import router_dir  # noqa: E402
from tests.conftest import needs_kicad  # noqa: E402

_ROUTER = router_dir()
needs_router = pytest.mark.skipif(not (Path(_ROUTER) / "py_router/route_diff.py").exists(),
                                  reason="no router with a pair router at %s" % _ROUTER)

NETS = ("D_P", "D_N", "SIG")


def _board() -> str:
    def part(ref, x, y, pads):
        body = "".join('\t\t(pad "%d" smd rect (at %g %g) (size 0.4 1.2) (layers "F.Cu" "F.Mask") (net "%s"))\n'
                       % (i + 1, px, py, net) for i, (px, py, net) in enumerate(pads))
        return ('\t(footprint "t:conn" (layer "F.Cu") (at %g %g)\n\t\t(property "Reference" "%s" (at 0 -2 0) '
                '(layer "F.SilkS"))\n%s\t)\n' % (x, y, ref, body))
    return ('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
            '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
            '\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n'
            + "".join('\t(net %d "%s")\n' % (i + 1, n) for i, n in enumerate(NETS))
            + part("J1", 110, 110, [(-0.4, 0, "D_P"), (0.4, 0, "D_N"), (3, 0, "SIG")])
            + part("J2", 130, 118, [(-0.4, 0, "D_P"), (0.4, 0, "D_N"), (3, 0, "SIG")])
            + '\t(gr_rect (start 100 100) (end 140 128) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))\n)\n')


def _segments(pcb: Path, net: str) -> list:
    """(x1, y1, x2, y2, width, layer) of every track of `net`, in mm."""
    from placemat.kicad.quiet import import_pcbnew
    p = import_pcbnew()
    board = p.LoadBoard(str(pcb))
    return [(p.ToMM(t.GetStart().x), p.ToMM(t.GetStart().y), p.ToMM(t.GetEnd().x), p.ToMM(t.GetEnd().y),
             p.ToMM(t.GetWidth()), t.GetLayerName())
            for t in board.GetTracks() if t.GetNetname() == net and not isinstance(t, p.PCB_VIA)]


def _route(tmp_path, **settings):
    from placemat.kicad.route import route_board
    from placemat.settings import Settings, bind
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text(_board())
    with bind(Settings(**settings)):
        return route_board(pcb, tmp_path / "route", layers=["F.Cu", "B.Cu"], quick=False)


@needs_kicad
@needs_router
def test_a_named_pair_routes_coupled_at_its_gap_and_the_rest_single_ended(tmp_path):
    report = _route(tmp_path, route_diff_pair_gap=0.2, route_diff_pair_width=0.2)
    assert report.pairs["coupled"] == ["D"], report.pairs
    assert report.open_after == 0, report.open_nets
    p, n = _segments(report.routed_pcb, "D_P"), _segments(report.routed_pcb, "D_N")
    assert p and n and _segments(report.routed_pcb, "SIG")
    # the long runs of P lie beside a run of N at width + gap, centre to centre
    def gap(a, b):
        ax, ay = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
        ux, uy = b[2] - b[0], b[3] - b[1]
        return abs((ax - b[0]) * uy - (ay - b[1]) * ux) / math.hypot(ux, uy)
    long_p = [s for s in p if math.hypot(s[2] - s[0], s[3] - s[1]) > 2.0]
    assert long_p
    for s in long_p:
        side = [t for t in n if t[5] == s[5] and abs((s[2] - s[0]) * (t[3] - t[1]) - (s[3] - s[1]) * (t[2] - t[0])) < 1e-3
                * math.hypot(s[2] - s[0], s[3] - s[1]) * math.hypot(t[2] - t[0], t[3] - t[1]) + 1e-9]
        assert any(abs(gap(s, t) - 0.4) < 0.02 for t in side), (s, side)


@needs_kicad
@needs_router
def test_with_no_pair_patterns_the_pair_router_is_not_run(tmp_path):
    report = _route(tmp_path, route_diff_pairs=())
    assert report.pairs == {"coupled": [], "partial": [], "failed": [], "single_ended": []}
    assert not (report.work / "pairs.log").exists()
    assert report.open_after == 0, report.open_nets
