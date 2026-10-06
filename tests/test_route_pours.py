"""The router does not see copper zones when it routes other nets, so it
would lay tracks through a partial inner-layer pour and the refill would
split it. The router's input copy gets a track-forbidding rule area over
each partial inner-layer pour of a net the route leaves out; the routed copy
has it removed."""
import shutil

import pytest

pytest.importorskip("pcbnew")

from placemat.kicad.route import POUR_GUARD, guard_partial_pours, remove_guards  # noqa: E402
from tests.conftest import needs_breakout, needs_kicad  # noqa: E402

pytestmark = [needs_kicad, needs_breakout]

LAYERS = ["F.Cu", "In2.Cu", "B.Cu"]


def _four_layer(breakout_pcb, dest, zones):
    """The breakout as a four-layer board with `zones`: (net, layer names,
    (x0, y0, x1, y1) or None for the board's own box)."""
    import pcbnew
    dest.mkdir()
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), dest / ("layout" + ext))
    pcb = dest / "layout.kicad_pcb"
    brd = pcbnew.LoadBoard(str(pcb))
    brd.SetCopperLayerCount(4)
    bb = brd.GetBoardEdgesBoundingBox()
    for net, layers, box in zones:
        z = pcbnew.ZONE(brd)
        ls = pcbnew.LSET()
        for name in layers:
            ls.AddLayer(brd.GetLayerID(name))
        z.SetLayerSet(ls)
        z.SetNetCode(brd.GetNetcodeFromNetname(net))
        o = z.Outline()
        o.NewOutline()
        if box is None:
            pts = ((bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()), (bb.GetRight(), bb.GetBottom()),
                   (bb.GetLeft(), bb.GetBottom()))
        else:
            x0, y0 = bb.GetLeft() + pcbnew.FromMM(box[0]), bb.GetTop() + pcbnew.FromMM(box[1])
            x1, y1 = bb.GetLeft() + pcbnew.FromMM(box[2]), bb.GetTop() + pcbnew.FromMM(box[3])
            pts = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        for x, y in pts:
            o.Append(x, y)
        brd.Add(z)
    brd.Save(str(pcb))
    return pcb


def _guards(pcb):
    import pcbnew
    brd = pcbnew.LoadBoard(str(pcb))
    return [z for z in brd.Zones() if z.GetIsRuleArea() and z.GetZoneName().startswith(POUR_GUARD)], brd


def test_a_partial_inner_pour_keeps_other_nets_tracks_out(breakout_pcb, tmp_path):
    pcb = _four_layer(breakout_pcb, tmp_path / "in", [("GND", ["In2.Cu"], (5, 5, 15, 15))])
    assert guard_partial_pours(str(pcb), {"GND"}, LAYERS, 0.9) == ["GND on In2.Cu"]
    guards, brd = _guards(pcb)
    assert len(guards) == 1
    g = guards[0]
    assert g.GetZoneName() == "%s GND In2.Cu" % POUR_GUARD
    assert [brd.GetLayerName(l) for l in g.GetLayerSet().Seq()] == ["In2.Cu"]
    assert g.GetDoNotAllowTracks() and not g.GetDoNotAllowVias()
    assert not g.GetDoNotAllowPads() and not g.GetDoNotAllowZoneFills() and not g.GetDoNotAllowFootprints()
    pour = next(z for z in brd.Zones() if not z.GetIsRuleArea() and z.IsOnLayer(brd.GetLayerID("In2.Cu")))
    assert abs(g.Outline().Area() - pour.Outline().Area()) < 1e-6 * pour.Outline().Area()


@pytest.mark.parametrize("zone, nets, layers", [
    (("GND", ["In2.Cu"], (5, 5, 15, 15)), {"OTHER"}, LAYERS),              # a net the route routes
    (("GND", ["In2.Cu"], (5, 5, 15, 15)), {"GND"}, ["F.Cu", "B.Cu"]),      # a layer the route does not use
    (("GND", ["F.Cu"], (5, 5, 15, 15)), {"GND"}, LAYERS),                  # an outer layer: other nets' pads sit in it
    (("GND", ["In2.Cu"], None), {"GND"}, LAYERS),                          # covering the board: a plane
], ids=["routed-net", "unrouted-layer", "outer-layer", "whole-board"])
def test_a_pour_the_rule_does_not_cover_is_left_alone(breakout_pcb, tmp_path, zone, nets, layers):
    pcb = _four_layer(breakout_pcb, tmp_path / "in", [zone])
    assert guard_partial_pours(str(pcb), nets, layers, 0.9) == []
    assert _guards(pcb)[0] == []


def test_a_pour_on_an_outer_and_an_inner_layer_is_guarded_on_the_inner_one(breakout_pcb, tmp_path):
    pcb = _four_layer(breakout_pcb, tmp_path / "in", [("GND", ["F.Cu", "In2.Cu"], (5, 5, 15, 15))])
    assert guard_partial_pours(str(pcb), {"GND"}, LAYERS, 0.9) == ["GND on In2.Cu"]


def test_the_routed_copy_has_the_guard_removed_and_the_pour_kept(breakout_pcb, tmp_path):
    pcb = _four_layer(breakout_pcb, tmp_path / "in", [("GND", ["In2.Cu"], (5, 5, 15, 15))])
    guard_partial_pours(str(pcb), {"GND"}, LAYERS, 0.9)
    out = tmp_path / "routed.kicad_pcb"
    shutil.copy(pcb, out)
    remove_guards(str(out))
    guards, brd = _guards(out)
    assert guards == []
    assert [z.GetNetname() for z in brd.Zones()
            if not z.GetIsRuleArea() and z.IsOnLayer(brd.GetLayerID("In2.Cu"))] == ["GND"]


def _other_net_tracks_inside(pcb, net, layer, box_poly):
    import pcbnew
    brd = pcbnew.LoadBoard(str(pcb))
    lid = brd.GetLayerID(layer)
    inside = 0
    for t in brd.GetTracks():
        if t.GetClass() != "PCB_TRACK" or t.GetLayer() != lid or t.GetNetname() == net:
            continue
        for p in (t.GetStart(), t.GetEnd()):
            if box_poly.Contains(pcbnew.VECTOR2I(p.x, p.y)):
                inside += 1
    return inside


def test_a_router_run_leaves_the_pour_to_its_net(breakout_pcb, tmp_path):
    import pcbnew
    from pathlib import Path
    from placemat.kicad.route import ROUTER_DEFAULT, route_board
    if not (Path(ROUTER_DEFAULT) / ".venv/bin/python").exists():
        pytest.skip("KiCadRoutingTools not at %s" % ROUTER_DEFAULT)
    pcb = _four_layer(breakout_pcb, tmp_path / "in", [("GND", ["In2.Cu"], (10, 10, 70, 70))])
    brd = pcbnew.LoadBoard(str(pcb))
    for t in list(brd.GetTracks()):
        brd.Delete(t)                                    # the router has every signal to lay
    brd.Save(str(pcb))
    pour = next(z for z in brd.Zones() if not z.GetIsRuleArea() and z.IsOnLayer(brd.GetLayerID("In2.Cu")))
    outline = pcbnew.SHAPE_POLY_SET(pour.Outline())
    report = route_board(pcb, tmp_path / "route", exclude_nets={"V48P", "GND"}, layers=LAYERS, quick=True)
    assert report.pours_kept == ["GND on In2.Cu"]
    assert _other_net_tracks_inside(report.routed_pcb, "GND", "In2.Cu", outline) == 0
    assert not any(POUR_GUARD in str(b) for b in report.keepout_breaches)


def test_a_teardrop_zone_on_an_inner_layer_is_not_guarded(breakout_pcb, tmp_path):
    from tests.test_route_settings import add_teardrop_zone
    pcb = _four_layer(breakout_pcb, tmp_path / "in", [])
    add_teardrop_zone(pcb, "GND", "In2.Cu")
    assert guard_partial_pours(str(pcb), {"GND"}, LAYERS, 0.9) == []
    assert _guards(pcb)[0] == []
