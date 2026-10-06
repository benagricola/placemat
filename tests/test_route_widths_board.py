"""The island nets' copper judged on the routed board (kicad/route_widths.py `board_widths`): each track against the width the
net was asked and the width its stated current needs on that track's layer (IPC-2221, the inner constant on an inner layer, as
`check current-path` sizes it), with the router's pad neck-down (KRT `--neckdown-length` plus its taper) not counted.

Synthetic geometry: two pads 35 mm apart on the front, joined by tracks; an inner layer reached through vias."""
from placemat.board_geometry import CopperItem
from placemat.checks import ipc2221_width_mm
from placemat.findings import FindingCause as C
from placemat.kicad.route_widths import KRT_NECKDOWN_LENGTH_MM, KRT_NECKDOWN_TAPER_MM, board_widths, findings_of, judged_on_board, neck_allowance
from placemat.values import Box, CopperLayer
from tests.fixtures import board_geometry, footprint

import dataclasses

F, IN2, B = CopperLayer.F, CopperLayer.IN2, CopperLayer.B
NECK = KRT_NECKDOWN_LENGTH_MM + KRT_NECKDOWN_TAPER_MM


def _track(a, b, width, layer=F, net="V"):
    (x0, y0), (x1, y1) = a, b
    outline = ((min(x0, x1), min(y0, y1) - width / 2), (max(x0, x1), min(y0, y1) - width / 2),
               (max(x0, x1), max(y0, y1) + width / 2), (min(x0, x1), max(y0, y1) + width / 2))
    return CopperItem("track", net, frozenset([layer]), (outline,), Box.of_points(outline), None, width,
                      anchors=(a, b), length_mm=((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)


def _via(at, net="V"):
    x, y = at
    outline = ((x - 0.3, y - 0.3), (x + 0.3, y - 0.3), (x + 0.3, y + 0.3), (x - 0.3, y + 0.3))
    return CopperItem("via", net, frozenset([F, IN2, B]), (outline,), Box.of_points(outline), None, 0.6, 0.3, anchors=(at,))


def _board(*copper, amps=None):
    """U1 pad 1 at (5, 10), U2 pad 1 at (40, 10), both on net V; each part states `amps` when given."""
    fields = {"Pm.I": "%gA" % amps} if amps else None
    parts = [footprint("U1", 5.6 + 1.0, 10.0, nets=("V", "X1"), fields=fields),
             footprint("U2", 40.0 + 1.4, 10.0, nets=("V", "X2"), fields=fields)]
    g = board_geometry(parts, copper=copper, width=60, height=30)
    return dataclasses.replace(g, layers=(F, IN2, B))


def test_an_outer_track_under_the_asked_width_is_counted_and_a_short_pad_neck_is_not():
    g = _board(_track((5, 10), (7, 10), 0.2),               # the neck-down out of U1's pad: 2 mm
               _track((7, 10), (20, 10), 1.0),
               _track((20, 10), (30, 10), 0.3),             # a mid-route pinch: 10 mm
               _track((30, 10), (40, 10), 1.0))
    (r,) = board_widths(g, {"V": 1.0}, neck_mm=NECK)
    assert (r["net"], r["requested_mm"], r["delivered_min_mm"], r["length_under_mm"], r["length_mm"]) == ("V", 1.0, 0.3, 10.0, 35.0)
    assert r["declared"] and r["necks_mm"] == 2.0
    assert r["layers"] == [{"layer": "F.Cu", "need_mm": 1.0, "by": "asked", "under_mm": 10.0, "min_mm": 0.3}]
    (f,) = findings_of([r])
    assert f.cause is C.ROUTE_WIDTH and f.severity == "critical"
    assert f == ("net V: 10.0 of 35.0 mm (29%) of its routed copper is under what it needs: F.Cu 10.0 mm under the 1 mm it was "
                 "asked, narrowest 0.3 mm; 2.0 mm of pad neck-down within 3 mm of a pad not counted")


def test_an_island_is_judged_by_its_asked_width_not_the_nets_stated_current():
    """An island the script gave a width is a tap or a leg whose width the script chose: its copper is judged against that width
    on every layer. The net's highest stated current may flow elsewhere (a declared track), and the paths that carry it are
    `check current-path`'s to judge."""
    g = _board(_track((5, 10), (20, 10), 0.31), _via((20, 10)),
               _track((20, 10), (35, 10), 0.31, IN2), _via((35, 10)),
               _track((35, 10), (40, 10), 0.31), amps=3.0)
    assert board_widths(g, {"V": 0.3}, neck_mm=NECK) == []
    pinched = _board(_track((5, 10), (20, 10), 0.31), _track((20, 10), (30, 10), 0.127, IN2),
                     _track((30, 10), (40, 10), 0.31), amps=3.0)
    (r,) = board_widths(pinched, {"V": 0.3}, neck_mm=NECK)
    assert r["layers"] == [{"layer": "In2.Cu", "need_mm": 0.3, "by": "asked", "under_mm": 10.0, "min_mm": 0.127}]
    assert r["amps"] is None
    (f,) = findings_of([r], {"V": 3.0})
    assert f.severity == "critical" and f.facts["stated_a"] is None
    assert "In2.Cu 10.0 mm under the 0.3 mm it was asked, narrowest 0.127 mm" in f and "design states" not in f


def test_only_an_island_given_a_width_is_judged_and_a_thin_decoupling_branch_elsewhere_is_left_to_current_path():
    trunk = _track((5, 10), (40, 10), 1.37)
    branch = _track((20, 10), (20, 20), 0.127)          # to a decoupling capacitor: never carries the stated 3 A
    g = _board(trunk, branch, amps=3.0)
    assert board_widths(g, {"OTHER": 1.0}, neck_mm=NECK) == []      # V has a Pm.I but is no island
    assert board_widths(g, {"V": None}, neck_mm=NECK) == []         # an island given no width
    assert judged_on_board({"V": None, "W": 1.0}) == {"W"}
    (r,) = board_widths(g, {"V": 1.37}, neck_mm=NECK)               # a width island: the branch counts
    assert r["length_under_mm"] == 10.0 and r["declared"]


def test_the_neck_bound_is_krt_s_and_neck_down_off_counts_every_neck():
    short = _board(_track((5, 10), (7, 10), 0.2), _track((7, 10), (7.5, 10), 0.6),   # neck and taper: 2.5 mm
                   _track((7.5, 10), (40, 10), 1.0))
    assert board_widths(short, {"V": 1.0}, neck_mm=NECK) == []
    (off,) = board_widths(short, {"V": 1.0}, neck_mm=0.0)
    assert off["length_under_mm"] == 2.5 and off["necks_mm"] == 0.0
    long = _board(_track((5, 10), (9, 10), 0.2), _track((9, 10), (40, 10), 1.0))      # 4 mm: past 3 mm
    (r,) = board_widths(long, {"V": 1.0}, neck_mm=NECK)
    assert r["length_under_mm"] == 4.0
    both = _board(_track((5, 10), (40, 10), 0.2), )                                     # narrow from pad to pad: no neck
    assert board_widths(both, {"V": 1.0}, neck_mm=NECK)[0]["length_under_mm"] == 35.0
    pinch = _board(_track((5, 10), (20, 10), 1.0), _track((20, 10), (21, 10), 0.2),    # a 1 mm pinch away from any pad
                   _track((21, 10), (40, 10), 1.0))
    assert board_widths(pinch, {"V": 1.0}, neck_mm=NECK)[0]["length_under_mm"] == 1.0


def test_neck_allowance_reads_the_router_arguments():
    assert neck_allowance([]) == NECK == 3.0
    assert neck_allowance(["--no-power-tap-neckdown"]) == 0.0
    assert neck_allowance(["--neckdown-length", "1.5", "--neckdown-taper-length=0"]) == 1.5
