"""A region that forbids: what may not sit in it, fill it, route through it
or via it, and how a script says so."""
import dataclasses

import pytest

from placemat.cutouts import Circle, Cutouts, Path, Slot
from placemat.layout import Board, PlacementCollision
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.values import (Box, Centre, CopperLayer, Face, Location, Net, OnRim, Part, X, Y)
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint


def loop_of(shape, at, rotation=0.0):
    return Cutouts([shape.path_at(at, rotation)]).loops[0]


def centre_of(loop):
    xs, ys = [p[0] for p in loop], [p[1] for p in loop]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def test_a_shape_with_no_anchor_still_lands_on_its_middle():
    """The default is what cutouts already do, and they must not move."""
    for shape in (Slot(13.0, 3.0), Circle(8.0),
                  Path([(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)])):
        got = centre_of(loop_of(shape, Location(20.0, 30.0)))
        assert got == pytest.approx((20.0, 30.0), abs=0.02)


def test_an_anchor_is_the_point_that_lands_on_the_place():
    """A datasheet figure is transcribed in its own coordinates and anchored
    at the feature it is organised around - a feed pad, an outer edge."""
    p = Path([(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)], anchor=(0.0, 0.0))
    loop = loop_of(p, Location(20.0, 30.0))
    xs, ys = [q[0] for q in loop], [q[1] for q in loop]
    assert (min(xs), min(ys)) == pytest.approx((20.0, 30.0), abs=0.02)
    assert (max(xs), max(ys)) == pytest.approx((30.0, 34.0), abs=0.02)


def test_an_anchored_shape_turns_about_its_anchor():
    p = Path([(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)], anchor=(0.0, 0.0))
    loop = loop_of(p, Location(20.0, 30.0), 90.0)
    xs, ys = [q[0] for q in loop], [q[1] for q in loop]
    assert min(xs) == pytest.approx(16.0, abs=0.02)      # 4 wide, now vertical
    assert max(ys) == pytest.approx(40.0, abs=0.02)      # 10 long, now south
    assert (20.0, 30.0) == pytest.approx((max(xs), min(ys)), abs=0.02)


def test_a_slot_and_a_circle_take_an_anchor_too():
    s = Slot(13.0, 3.0, anchor=(-6.5, 0.0))              # its west tip
    loop = loop_of(s, Location(20.0, 20.0))
    assert min(q[0] for q in loop) == pytest.approx(20.0, abs=0.02)
    c = Circle(8.0, anchor=(0.0, -4.0))                  # its north point
    loop = loop_of(c, Location(20.0, 20.0))
    assert min(q[1] for q in loop) == pytest.approx(20.0, abs=0.02)


def _occ(*insts):
    fps = [footprint(i.upper(), 10.0 + n * 8.0, 10.0, w=4.0, h=4.0, inst=i, nets=("SIG", "GND"))
           for n, i in enumerate(insts)]
    g = board_geometry(fps, width=60, height=60)
    occ = Occupancy(g, edge_margin=0.0, board_box=None)
    for fp in fps:
        occ.commit(fp, Placement(fp.location, 0.0, Face.FRONT))
    return g, occ


def test_a_reservation_can_be_a_polygon_not_just_a_box():
    """An antenna clearance is a stepped polygon, and a box round it would
    forbid board the datasheet allows."""
    g, occ = _occ("u1")
    # a C whose bite faces the part: a box would hit it and the polygon must not
    occ.reserve([(6.0, 6.0), (14.0, 6.0), (14.0, 7.0), (8.0, 7.0),
                 (8.0, 13.0), (14.0, 13.0), (14.0, 14.0), (6.0, 14.0)],
                "the clearance")
    fp = g.footprints[0]
    assert occ.legal(fp, Placement(Location(11.0, 10.0), 0.0, Face.FRONT)) is None


def test_a_part_in_a_reservation_is_refused_by_its_why():
    g, occ = _occ("u1")
    occ.reserve(Box(6.0, 6.0, 14.0, 14.0), "the clearance")
    why = occ.legal(g.footprints[0], Placement(Location(10.0, 10.0), 0.0, Face.FRONT))
    assert why is not None and "the clearance" in why


def test_a_named_part_may_sit_in_a_reservation():
    """An antenna's own matching network lives inside its clearance, and
    those parts are named individually: allowing their NETS would admit
    every part that carries GND."""
    g, occ = _occ("u1")
    occ.reserve(Box(6.0, 6.0, 14.0, 14.0), "the clearance", owners=("U1",))
    assert occ.legal(g.footprints[0], Placement(Location(10.0, 10.0), 0.0, Face.FRONT)) is None


def test_a_box_reservation_still_works():
    """Labels reserve their own text box and must not change."""
    g, occ = _occ("u1")
    occ.reserve(Box(40.0, 40.0, 50.0, 50.0), "a label")
    assert occ.legal(g.footprints[0], Placement(Location(10.0, 10.0), 0.0, Face.FRONT)) is None


def make_board(*insts, margin=0.5, keep_going=False):
    fps = [footprint(i.upper(), 50.0, 3.0 + n * 6.0, w=4.0, h=4.0, inst=i, nets=("SIG", "GND"))
           for n, i in enumerate(insts)]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=margin, keep_going=keep_going)


def test_a_part_may_not_sit_in_a_keepout():
    b = make_board("u1")
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0), why="the clearance")
    b.place(Part("u1"), at=Location(20.0, 20.0))
    with pytest.raises(PlacementCollision, match="antenna"):
        b.resolve()


def test_a_part_named_in_allow_may():
    b = make_board("u1")
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0),
              allow=(Part("u1"),), why="its own matching network lives here")
    b.place(Part("u1"), at=Location(20.0, 20.0))
    plan = b.resolve()
    assert not plan.findings, plan.findings
    assert plan.box("u1").center == Location(20.0, 20.0)


def test_a_keepout_is_placed_from_the_part_it_serves():
    b = make_board("u1")
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(6.0), "antenna", at=Centre(X(Part("u1")), Y(Part("u1"), 6.0)),
              why="the clearance sits inboard of the antenna")
    b.place(Part("u1"), at=Location(20.0, 10.0))
    plan = b.resolve()
    assert plan.keepouts["antenna"].centre == Location(20.0, 16.0)


def test_a_keepout_from_a_searched_part_is_refused():
    b = make_board("u1")
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(6.0), "antenna", at=Centre(X(Part("u1")), Y(Part("u1"), 6.0)), why="a")
    b.place(Part("u1"))
    with pytest.raises(ValueError, match="only FIXED and EDGE"):
        b.resolve()


def test_two_keepouts_may_not_share_a_name():
    b = make_board()
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(4.0), "a", at=Location(10.0, 10.0), why="x")
    with pytest.raises(ValueError, match="already a keepout named"):
        b.keepout(Circle(4.0), "a", at=Location(30.0, 10.0), why="y")


def test_a_keepout_says_why():
    b = make_board()
    b.size(width=40.0, height=40.0)
    with pytest.raises(ValueError, match="why"):
        b.keepout(Circle(4.0), "a", at=Location(10.0, 10.0))


def test_a_keepout_and_a_free_placement_coexist():
    """The 0.4.18 defect, one region type later: a keepout shares the intent
    list with the placements, so everything that reads what an ITEM declared
    must not see one."""
    b = make_board("u1")
    b.disc(diameter=40.0)
    b.keepout(Circle(4.0), "antenna", at=Location(20.0, 30.0), why="a")
    b.place(Part("u1"), at=OnRim())
    plan = b.resolve()
    assert not plan.findings, plan.findings


def _rule_areas(plan, copper_layers=4):
    """Apply a plan's keepouts to an empty board and hand back its rule areas."""
    import pcbnew
    from placemat.kicad.write import _draw_keepouts
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(copper_layers)
    _draw_keepouts(b, plan)
    return [z for z in b.Zones() if z.GetIsRuleArea()]


@needs_kicad
def test_a_keepout_writes_a_rule_area_on_every_copper_layer():
    b = make_board()
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(8.0), "antenna", at=Location(20.0, 20.0), why="the clearance")
    plan = b.resolve()
    for n in (2, 6, 32):
        (z,) = _rule_areas(plan, copper_layers=n)
        assert len(list(z.GetLayerSet().Seq())) == n
        assert z.GetDoNotAllowZoneFills() and z.GetDoNotAllowTracks()
        assert z.GetDoNotAllowVias() and z.GetDoNotAllowPads()
        assert z.GetDoNotAllowFootprints()


@needs_kicad
def test_excludes_narrows_what_the_rule_area_forbids():
    b = make_board()
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(8.0), "screw", at=Location(20.0, 20.0),
              excludes=("parts",), why="the screw head sweeps here")
    (z,) = _rule_areas(b.resolve())
    assert z.GetDoNotAllowFootprints()
    assert not z.GetDoNotAllowZoneFills() and not z.GetDoNotAllowTracks()


@needs_kicad
def test_layers_narrows_where():
    import pcbnew
    b = make_board()
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(8.0), "shield", at=Location(20.0, 20.0),
              layers=[CopperLayer.F], why="under the can")
    (z,) = _rule_areas(b.resolve(), copper_layers=6)
    assert list(z.GetLayerSet().Seq()) == [pcbnew.F_Cu]


@needs_kicad
def test_a_plane_fills_round_a_keepout():
    """The whole reason planes need no clipping: KiCad's filler honours the
    rule area, so board.plane() is untouched by this feature."""
    import pcbnew
    from placemat.kicad.write import _draw_keepouts
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(2)
    net = pcbnew.NETINFO_ITEM(b, "GND")
    b.Add(net)

    def vec(x, y):
        return pcbnew.VECTOR2I(int(x * 1e6), int(y * 1e6))

    for a, c in (((0, 0), (40, 0)), ((40, 0), (40, 40)), ((40, 40), (0, 40)), ((0, 40), (0, 0))):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(vec(*a))
        s.SetEnd(vec(*c))
        b.Add(s)
    z = pcbnew.ZONE(b)
    z.SetLayer(pcbnew.F_Cu)
    z.SetNetCode(net.GetNetCode())
    z.SetIsRuleArea(False)
    z.SetMinThickness(200000)
    o = z.Outline()
    o.NewOutline()
    for x, y in ((1, 1), (39, 1), (39, 39), (1, 39)):
        o.Append(vec(x, y).x, vec(x, y).y)
    b.Add(z)

    board = make_board()
    board.size(width=40.0, height=40.0)
    board.keepout(Path([(-6.0, -6.0), (6.0, -6.0), (6.0, 6.0), (-6.0, 6.0)]),
                  "antenna", at=Location(31.0, 31.0), why="the clearance")
    _draw_keepouts(b, board.resolve())
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    filled = z.GetFilledPolysList(pcbnew.F_Cu).Area() / 1e12
    assert filled == pytest.approx(38.0 * 38.0 - 12.0 * 12.0, rel=0.02)


def test_a_pour_crossing_a_keepout_is_a_finding():
    """A rule area does not touch a pour - a pour keeps exactly the shape it
    is given - so it is reported rather than silently reshaped."""
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0), why="the clearance")
    b.pour(Net("GND"), [Location(15, 15), Location(35, 15), Location(35, 35), Location(15, 35)],
           layer=CopperLayer.F)
    plan = b.resolve()
    assert any("antenna" in f and "pour" in f for f in plan.findings), plan.findings


def test_a_track_crossing_a_keepout_is_a_finding():
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0), why="the clearance")
    b.track(Net("GND"), [Location(5, 20), Location(35, 20)], layer=CopperLayer.F)
    plan = b.resolve()
    assert any("antenna" in f and "track" in f for f in plan.findings), plan.findings


def test_an_allowed_net_may_cross():
    b = make_board("u1")
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0),
              allow=(Net("GND"),), why="the feed crosses its own clearance")
    b.track(Net("GND"), [Location(5, 20), Location(35, 20)], layer=CopperLayer.F)
    assert not b.resolve().findings


def test_a_keepout_that_excludes_nothing_of_the_kind_is_quiet():
    b = make_board("u1")
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "screw", at=Location(20.0, 20.0),
              excludes=("parts",), why="the screw head sweeps here")
    b.track(Net("GND"), [Location(5, 20), Location(35, 20)], layer=CopperLayer.F)
    assert not b.resolve().findings


def test_a_track_clear_of_a_keepout_is_quiet():
    b = make_board("u1")
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(6.0), "antenna", at=Location(20.0, 20.0), why="the clearance")
    b.track(Net("GND"), [Location(5, 35), Location(35, 35)], layer=CopperLayer.F)
    assert not b.resolve().findings


def test_a_track_on_another_layer_than_the_region_is_quiet():
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0), layers=(CopperLayer.F,),
              why="the clearance on F")
    b.track(Net("GND"), [Location(5, 20), Location(35, 20)], layer=CopperLayer.B)
    assert not b.resolve().findings


def test_a_track_on_the_region_s_own_layer_is_still_a_finding():
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0), layers=(CopperLayer.F,),
              why="the clearance on F")
    b.track(Net("GND"), [Location(5, 20), Location(35, 20)], layer=CopperLayer.F)
    assert any("antenna" in f for f in b.resolve().findings)


def test_a_region_with_no_layers_still_catches_every_layer():
    for layer in (CopperLayer.F, CopperLayer.B):
        b = make_board("u1", keep_going=True)
        b.size(width=40.0, height=40.0)
        b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0), why="every layer")
        b.track(Net("GND"), [Location(5, 20), Location(35, 20)], layer=layer)
        assert any("antenna" in f for f in b.resolve().findings), layer


def test_a_via_is_caught_by_a_region_on_any_single_layer():
    """A via joins every copper layer, so a region on one of them contains it."""
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20.0, 20.0), layers=(CopperLayer.B,),
              why="the clearance on B")
    b.via(Net("GND"), Location(20.0, 20.0))
    assert any("antenna" in f and "via" in f for f in b.resolve().findings)


def test_a_region_partly_off_the_board_is_still_enforced():
    """The fairing case: a fence whose outer boundary IS the board outline,
    sampled into chords, and a chord across an arc bulges past the true curve.
    The region must still fence the parts it was written to fence."""
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "seal", at=Location(38.0, 20.0), why="the gland")
    plan = b.resolve()
    assert "seal" in plan.keepouts
    assert any("seal" in r.why for r in plan.occupancy.reservations)


def test_that_region_s_step_counts_the_points_that_fell_outside():
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(10.0), "seal", at=Location(38.0, 20.0), why="the gland")
    note = b.resolve().step("keepout seal").note
    assert "off the board" in note and "of its" in note


def test_a_region_wholly_inside_says_nothing_about_the_board_edge():
    b = make_board("u1")
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(4.0), "mid", at=Location(20.0, 20.0), why="the middle")
    assert "off the board" not in b.resolve().step("keepout mid").note


def test_a_region_wholly_off_the_board_raises():
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(4.0), "nowhere", at=Location(200.0, 200.0), why="forbids nothing")
    with pytest.raises(ValueError) as e:
        b.resolve()
    assert "nowhere" in str(e.value) and "off the board" in str(e.value)


def test_a_wholly_off_board_region_raises_even_with_keep_going():
    """A script error, of the same class as two keepouts sharing one name.
    --keep-going carries on past board conditions, not past those."""
    b = make_board("u1", keep_going=True)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(4.0), "nowhere", at=Location(200.0, 200.0), why="forbids nothing")
    with pytest.raises(ValueError):
        b.resolve()


def test_a_keepout_may_not_take_a_name_a_rule_area_on_the_board_already_has():
    """A stamped cell brings its module's regions with it. A script that
    reuses one of their names would leave two regions and no way to say
    which won."""
    from placemat.board_geometry import RuleArea
    g = board_geometry([footprint("U1", 10, 10, inst="u1", nets=("A", "B"))], width=40, height=40)
    g = dataclasses.replace(g, rule_areas=(
        RuleArea("keepout antenna_1", "ant_rf", ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
                 frozenset([CopperLayer.F]), frozenset(["parts"])),))
    b = Board(g, edge_margin=1.0)
    b.size(width=40.0, height=40.0)
    with pytest.raises(ValueError) as e:
        b.keepout(Circle(4.0), "antenna_1", at=Location(20, 20), why="clashes")
    assert "antenna_1" in str(e.value) and "ant_rf" in str(e.value)


def test_an_unrelated_name_is_fine():
    from placemat.board_geometry import RuleArea
    g = board_geometry([footprint("U1", 10, 10, inst="u1", nets=("A", "B"))], width=40, height=40)
    g = dataclasses.replace(g, rule_areas=(
        RuleArea("keepout antenna_1", "ant_rf", ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
                 frozenset([CopperLayer.F]), frozenset(["parts"])),))
    b = Board(g, edge_margin=1.0)
    b.size(width=40.0, height=40.0)
    b.keepout(Circle(4.0), "my_own", at=Location(20, 20), why="fine")     # no raise


def _with_rule_area(cell, poly):
    from placemat.board_geometry import RuleArea
    fps = [footprint("U1", 10, 10, w=4, h=2, cell="ant_rf", inst="ant_rf.u", nets=("A", "B")),
           footprint("R1", 30, 30, w=2, h=1, inst="r1", nets=("B", "C"))]
    g = board_geometry(fps, cells=["ant_rf"], width=60, height=60)
    return dataclasses.replace(g, rule_areas=(
        RuleArea("keepout antenna_1", cell, poly, frozenset([CopperLayer.F]),
                 frozenset(["parts"])),))


def test_a_board_level_rule_area_is_reserved_from_the_start():
    poly = ((25.0, 25.0), (35.0, 25.0), (35.0, 35.0), (25.0, 35.0))
    occ = Occupancy(_with_rule_area(None, poly), edge_margin=0.0)
    assert any("antenna_1" in r.why for r in occ.reservations)


def test_a_cell_owned_rule_area_waits_for_its_cell():
    """Its position is not known until the cell lands, exactly as the cell's
    own courtyard is not."""
    poly = ((8.0, 8.0), (14.0, 8.0), (14.0, 14.0), (8.0, 14.0))
    g = _with_rule_area("ant_rf", poly)
    occ = Occupancy(g, edge_margin=0.0)
    assert not occ.reservations
    occ.commit(g.cell("ant_rf"), Placement(Location(40.0, 40.0), 0.0, Face.FRONT))
    (r,) = occ.reservations
    assert "antenna_1" in r.why
    # the region travelled with the cell: its box centre moved with the cell's
    assert r.box.center.x > 20.0 and r.box.center.y > 20.0


def test_a_part_is_refused_for_sitting_in_a_cell_s_stamped_region():
    poly = ((8.0, 8.0), (14.0, 8.0), (14.0, 14.0), (8.0, 14.0))
    g = _with_rule_area("ant_rf", poly)
    occ = Occupancy(g, edge_margin=0.0)
    occ.commit(g.cell("ant_rf"), Placement(g.cell("ant_rf").box.center, 0.0, Face.FRONT))
    why = occ.legal(g.footprint("R1"), Placement(Location(11.0, 11.0), 0.0, Face.FRONT))
    assert why is not None and "antenna_1" in why


def test_a_rule_area_that_does_not_forbid_parts_reserves_nothing():
    from placemat.board_geometry import RuleArea
    g = board_geometry([footprint("U1", 10, 10, inst="u1", nets=("A", "B"))], width=40, height=40)
    g = dataclasses.replace(g, rule_areas=(
        RuleArea("keepout fill_only", None, ((5.0, 5.0), (9.0, 5.0), (9.0, 9.0)),
                 frozenset([CopperLayer.F]), frozenset(["fill"])),))
    assert not Occupancy(g, edge_margin=0.0).reservations


def test_the_docs_say_what_a_keepout_now_holds():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "narrows what is CHECKED" in api
    assert "seeded_by_net" in api
    skill = Path("skills/placemat/SKILL.md").read_text()
    assert "seeded" in skill
    assert "allow=" in skill                      # the do-not-widen instruction
    mig = Path("skills/placemat/references/migration.md").read_text()
    assert "0.7" in mig and "0.6" in mig          # a section per release, both present
