"""Copper the router added, inside a region that forbids it. KiCadRoutingTools
honours KiCad rule areas - a control route of the Breakout laid 52 items
through a box with no keepout and none with one - but that is a property of
another repository at one commit, so every route checks it rather than
assuming it. Pure: synthetic geometry."""
from placemat.board_geometry import CopperItem, RuleArea, added_copper, keepout_breaches
from placemat.values import Box, CopperLayer

F, B = CopperLayer.F, CopperLayer.B
REGION = ((10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0))


def _area(excludes=("tracks", "vias"), layers=(F, B), name="keepout halo_isp"):
    return RuleArea(name, None, REGION, frozenset(layers), frozenset(excludes))


def _track(net="ISP", layer=F, x=15.0):
    outline = ((x - 0.1, 5.0), (x + 0.1, 5.0), (x + 0.1, 25.0), (x - 0.1, 25.0))
    return CopperItem("track", net, frozenset([layer]), (outline,), Box(x - 0.1, 5.0, x + 0.1, 25.0), width_mm=0.2)


def _via(net="PD_IRQ", x=15.0, y=15.0):
    ring = ((x - 0.3, y - 0.3), (x + 0.3, y - 0.3), (x + 0.3, y + 0.3), (x - 0.3, y + 0.3))
    return CopperItem("via", net, frozenset([F, B]), (ring,), Box(x - 0.3, y - 0.3, x + 0.3, y + 0.3))


def test_a_routed_track_through_a_region_that_forbids_tracks_is_a_breach():
    said = keepout_breaches([_area()], [_track()])
    assert len(said) == 1 and "ISP" in said[0] and "halo_isp" in said[0] and "track" in said[0]


def test_a_via_in_a_region_that_forbids_vias_is_a_breach():
    said = keepout_breaches([_area()], [_via()])
    assert len(said) == 1 and "PD_IRQ" in said[0] and "via" in said[0]


def test_a_track_on_a_layer_the_region_does_not_cover_is_not_a_breach():
    assert keepout_breaches([_area(layers=(B,))], [_track(layer=F)]) == []


def test_a_region_that_only_keeps_fill_out_lets_a_track_through():
    assert keepout_breaches([_area(excludes=("fill",))], [_track()]) == []


def test_copper_clear_of_the_region_is_not_a_breach():
    assert keepout_breaches([_area()], [_track(x=40.0)]) == []


def test_only_the_copper_the_router_added_is_judged():
    """The script's own copper is judged by the layout's keepout check, where
    a keepout's allow= is known; the router's is what nobody else looks at."""
    mine, routers = _track(net="GND", x=12.0), _track(net="ISP", x=15.0)
    assert added_copper([mine], [mine, routers]) == [routers]


def _boards(tmp_path, through):
    """An input board with one rule area forbidding tracks, and the same board
    with one added track: through the region when `through`, clear otherwise."""
    import pcbnew
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(2)
    z = pcbnew.ZONE(b)
    z.SetIsRuleArea(True)
    z.SetLayerSet(pcbnew.LSET.AllCuMask(2))
    z.SetDoNotAllowFootprints(False)
    z.SetDoNotAllowZoneFills(False)
    z.SetDoNotAllowTracks(True)
    z.SetDoNotAllowVias(True)
    z.SetDoNotAllowPads(False)
    o = z.Outline()
    o.NewOutline()
    for x, y in REGION:
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    z.SetZoneName("keepout halo")
    b.Add(z)
    given = tmp_path / "in.kicad_pcb"
    b.Save(str(given))
    t = pcbnew.PCB_TRACK(b)
    x = 15.0 if through else 40.0
    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(5)))
    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(25)))
    t.SetWidth(pcbnew.FromMM(0.2))
    t.SetLayer(pcbnew.F_Cu)
    b.Add(t)
    routed = tmp_path / "routed.kicad_pcb"
    b.Save(str(routed))
    return given, routed


def test_the_route_reports_router_copper_inside_a_keepout(tmp_path):
    import pytest
    pytest.importorskip("pcbnew")
    from placemat.kicad.route import router_breaches
    given, routed = _boards(tmp_path, through=True)
    (said,) = router_breaches(given, routed)
    assert "track" in said and "keepout halo" in said


def test_the_route_reports_nothing_when_the_router_kept_out(tmp_path):
    import pytest
    pytest.importorskip("pcbnew")
    from placemat.kicad.route import router_breaches
    given, routed = _boards(tmp_path, through=False)
    assert router_breaches(given, routed) == []


def test_the_docs_say_who_honours_a_keepout():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "keepout_breaches" in api and "no per-net exemption" in api
    assert "## To 0.18" in Path("skills/placemat/references/migration.md").read_text()
