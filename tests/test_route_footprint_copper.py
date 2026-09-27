"""The router neither sees a footprint's copper graphics nor keeps its
outer-layer ones (its writer moves them to silk): placemat guards them in
the router's input copy and puts them back in the routed copy."""
import pytest

pytest.importorskip("pcbnew")

import shutil

from placemat.kicad.drc import run_drc
from placemat.kicad.route import guard_footprint_copper, restore_footprint_graphics
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


def _routed_as_the_router_writes_it(pcb_in, tmp_path, sq):
    """The router's writer moves footprint copper graphics on the outer
    layers to silk; its routing ran through the square."""
    import pcbnew
    out = tmp_path / "routed.kicad_pcb"
    shutil.copy(pcb_in, out)
    brd = pcbnew.LoadBoard(str(out))
    for fp in brd.GetFootprints():
        for d in fp.GraphicalItems():
            if isinstance(d, pcbnew.PCB_SHAPE) and d.GetLayer() == pcbnew.F_Cu:
                d.SetLayer(pcbnew.F_SilkS)
    t = pcbnew.PCB_TRACK(brd)
    y = pcbnew.FromMM((sq.top + sq.bottom) / 2)
    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(sq.left - 1), y))
    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(sq.right + 1), y))
    t.SetWidth(pcbnew.FromMM(0.2))
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(brd.FindNet(NET))
    brd.Add(t)
    brd.Save(str(out))
    return out


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


def test_the_routed_copy_gets_its_footprint_copper_back(breakout_pcb, tmp_path):
    import pcbnew
    pcb, ref, sq = _with_art(breakout_pcb, tmp_path)
    guard_footprint_copper(str(pcb))
    routed = _routed_as_the_router_writes_it(pcb, tmp_path, sq)
    before = run_drc(routed, tmp_path / "drc0.json")
    assert restore_footprint_graphics(str(pcb), str(routed)) == {"footprints": 1, "items": 1}
    brd = pcbnew.LoadBoard(str(routed))
    fp = next(f for f in brd.GetFootprints() if f.GetReference() == ref)
    assert [d.GetLayer() for d in fp.GraphicalItems() if isinstance(d, pcbnew.PCB_SHAPE)
            and pcbnew.IsCopperLayer(d.GetLayer())] == [pcbnew.F_Cu]
    assert not _guards(routed)
    after = run_drc(routed, tmp_path / "drc1.json")
    assert sum(after.real.values()) > sum(before.real.values())      # the track against the square it crossed


def test_a_board_without_footprint_copper_is_left_alone(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path / "plain")
    assert guard_footprint_copper(str(pcb)) == 0
    out = tmp_path / "routed.kicad_pcb"
    shutil.copy(pcb, out)
    assert restore_footprint_graphics(str(pcb), str(out)) == {"footprints": 0, "items": 0}
