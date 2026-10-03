"""The router neither sees a footprint's copper graphics nor keeps its
outer-layer ones (its writer moves them to silk): placemat guards them in
the router's input copy and puts them back in the routed copy."""
import pytest

pytest.importorskip("pcbnew")

import shutil

from placemat.kicad.route import guard_footprint_copper, remove_guards
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]

NET = "TERM_NEAR_MID"


def _copy(breakout_pcb, dest):
    dest.mkdir()
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), dest / ("layout" + ext))
    return dest / "layout.kicad_pcb"


def _free_square(pcb, side=2.0):
    """A side x side mm square on the board clear of every item by 1 mm."""
    from placemat.kicad.read import read_board
    from placemat.values import Box
    g = read_board(pcb)
    taken = [c.box for c in g.copper if c.kind != "zone"] + [fp.courtyard_box for fp in g.footprints]
    ob = g.outline_box
    y = ob.top + 3
    while y < ob.bottom - 3:
        x = ob.left + 3
        while x < ob.right - 3:
            b = Box(x, y, x + side, y + side)
            if not any(b.overlaps(t, gap=1.0) for t in taken):
                return b
            x += 0.5
        y += 0.5
    raise AssertionError("no free square")


def _with_art(breakout_pcb, tmp_path):
    """The breakout with a net-less F.Cu square drawn by its first footprint."""
    import pcbnew
    pcb = _copy(breakout_pcb, tmp_path / "in")
    sq = _free_square(pcb)
    brd = pcbnew.LoadBoard(str(pcb))
    fp = brd.GetFootprints()[0]
    art = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_RECT)
    art.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(sq.left), pcbnew.FromMM(sq.top)))
    art.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(sq.right), pcbnew.FromMM(sq.bottom)))
    art.SetFilled(True)
    art.SetWidth(pcbnew.FromMM(0.1))
    art.SetLayer(pcbnew.F_Cu)
    fp.Add(art)
    brd.Save(str(pcb))
    return pcb, fp.GetReference(), sq



def _guards(pcb):
    import pcbnew
    return [z for z in pcbnew.LoadBoard(str(pcb)).Zones() if z.GetZoneName().startswith("placemat footprint copper")]


def test_footprint_copper_is_guarded_from_the_router(breakout_pcb, tmp_path):
    import pcbnew
    pcb, ref, _ = _with_art(breakout_pcb, tmp_path)
    assert guard_footprint_copper(str(pcb)) == 1
    (z,) = _guards(pcb)
    assert z.GetIsRuleArea() and z.GetDoNotAllowTracks() and z.GetDoNotAllowVias()
    assert ref in z.GetZoneName() and z.GetLayerSet().Contains(pcbnew.F_Cu) and not z.GetLayerSet().Contains(pcbnew.B_Cu)





def test_a_guard_leaves_the_footprints_own_pads_reachable(breakout_pcb, tmp_path):
    """A winding ending on its own pad: the guard over it must not cover the
    pad, or the router, which keeps every net off a rule area, cannot reach it."""
    import pcbnew
    pcb = _copy(breakout_pcb, tmp_path / "in")
    brd = pcbnew.LoadBoard(str(pcb))
    fp = next(f for f in brd.GetFootprints() if any(p.GetNetname() == NET for p in f.Pads()))
    pad = next(p for p in fp.Pads() if p.GetNetname() == NET)
    c = pad.GetPosition()
    art = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_SEGMENT)
    art.SetStart(c)
    art.SetEnd(pcbnew.VECTOR2I(c.x, c.y - pcbnew.FromMM(2.0)))
    art.SetWidth(pcbnew.FromMM(0.25))
    art.SetLayer(pad.GetLayer() if pad.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu) else pcbnew.F_Cu)
    fp.Add(art)
    brd.Save(str(pcb))
    assert guard_footprint_copper(str(pcb)) == 1
    (z,) = _guards(pcb)
    assert not z.Outline().Contains(c)                               # the pad's centre is outside it
    assert z.Outline().Contains(pcbnew.VECTOR2I(c.x, c.y - pcbnew.FromMM(1.5)))   # the winding is inside



def test_copper_inside_a_ring_guards_hole_is_no_breach():
    from placemat.board_geometry import CopperItem, RuleArea, keepout_breaches
    from placemat.geometry import circle_polygon
    from placemat.values import Box, CopperLayer, Location
    ring = RuleArea("placemat footprint copper H5", None, circle_polygon(Location(10, 10), 2.15, n=32),
                    frozenset([CopperLayer.F]), frozenset(["tracks", "vias"]),
                    holes=(circle_polygon(Location(10, 10), 1.85, n=32),))
    via = circle_polygon(Location(10, 10), 0.3)
    inside = CopperItem("via", "A", frozenset([CopperLayer.F, CopperLayer.B]), (via,), Box.of_points(via))
    over = circle_polygon(Location(12, 10), 0.3)
    across = CopperItem("via", "A", frozenset([CopperLayer.F, CopperLayer.B]), (over,), Box.of_points(over))
    assert keepout_breaches([ring], [inside]) == []
    assert len(keepout_breaches([ring], [across])) == 1


def test_a_ring_graphics_guard_is_read_with_its_hole(breakout_pcb, tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    pcb = _copy(breakout_pcb, tmp_path / "in")
    sq = _free_square(pcb, side=4.0)
    brd = pcbnew.LoadBoard(str(pcb))
    fp = brd.GetFootprints()[0]
    ring = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_CIRCLE)
    ring.SetCenter(pcbnew.VECTOR2I(pcbnew.FromMM(sq.center.x), pcbnew.FromMM(sq.center.y)))
    ring.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(sq.center.x + 1.5), pcbnew.FromMM(sq.center.y)))
    ring.SetFilled(False)
    ring.SetWidth(pcbnew.FromMM(0.3))
    ring.SetLayer(pcbnew.F_Cu)
    fp.Add(ring)
    brd.Save(str(pcb))
    guard_footprint_copper(str(pcb))
    (ra,) = [r for r in read_board(pcb).rule_areas if r.name.startswith("placemat footprint copper")]
    assert len(ra.holes) == 1


def test_a_board_without_footprint_copper_is_left_alone(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path / "plain")
    assert guard_footprint_copper(str(pcb)) == 0
    assert remove_guards(str(pcb)) == 0


def test_remove_guards_deletes_what_guard_footprint_copper_added(breakout_pcb, tmp_path):
    pcb, _, _ = _with_art(breakout_pcb, tmp_path)
    assert guard_footprint_copper(str(pcb)) == 1
    assert remove_guards(str(pcb)) == 1
    assert not _guards(pcb)


FIXTURES = __import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures"
COIL = FIXTURES / "fairing/modules/ringsensor/layout/layout.kicad_pcb"           # RingCoil_V3 x2: 366 copper graphics
NET_TIE = FIXTURES / "fairing/keep_out/modules/usbconverter/generated/UsbConverter/layout.kicad_pcb"   # NT1, NT2


def _copper_graphics(pcb) -> dict:
    """{footprint reference: its copper-layer graphic shapes, as (shape, layer, start, end)}."""
    import pcbnew
    from placemat.kicad.quiet import quiet_stderr
    with quiet_stderr():
        brd = pcbnew.LoadBoard(str(pcb))
    return {fp.GetReference(): sorted((d.GetShape(), d.GetLayer(), d.GetStart().x, d.GetStart().y, d.GetEnd().x, d.GetEnd().y)
                                      for d in fp.GraphicalItems()
                                      if isinstance(d, pcbnew.PCB_SHAPE) and pcbnew.IsCopperLayer(d.GetLayer()))
            for fp in brd.GetFootprints()}


def _routed_keeps_footprint_copper(src, tmp_path, strip_tracks):
    import pcbnew
    from pathlib import Path
    from placemat.kicad.route import ROUTER_DEFAULT, route_board
    if not (Path(ROUTER_DEFAULT) / ".venv/bin/python").exists():
        pytest.skip("router not at %s" % ROUTER_DEFAULT)
    pcb = _copy(src, tmp_path / "in")
    if strip_tracks:
        brd = pcbnew.LoadBoard(str(pcb))
        for t in list(brd.GetTracks()):
            brd.Delete(t)
        brd.Save(str(pcb))
    before = _copper_graphics(pcb)
    assert sum(map(len, before.values())) > 0
    report = route_board(pcb, tmp_path / "route", quick=True)
    assert _copper_graphics(report.routed_pcb) == before
    assert not _guards(report.routed_pcb)


def test_a_routed_copy_keeps_a_coil_footprints_copper(tmp_path):
    _routed_keeps_footprint_copper(COIL, tmp_path, strip_tracks=True)


def test_a_routed_copy_keeps_a_net_tie_footprints_copper(tmp_path):
    _routed_keeps_footprint_copper(NET_TIE, tmp_path, strip_tracks=False)
