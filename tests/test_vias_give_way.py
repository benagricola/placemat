"""A carried via that meets another net's copper gives way instead of
refusing the placement: it shares a same-net via close by, moves a little,
or - a plane's drop - is dropped while its pad keeps its share."""
import pytest

from placemat.board_geometry import CopperItem
from placemat.copper import Track, Via
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.values import Box, Cell, CopperLayer, Face, Location, Near, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint, track

F, B = CopperLayer.F, CopperLayer.B


def _via(net, x, y, owner=None, size=0.45, drill=0.2, layers=None):
    ring = circle_polygon(Location(x, y), size / 2)
    return CopperItem("via", net, layers or frozenset([F, B]), (ring,), Box.of_points(ring), owner, size, drill,
                      ((x, y),))


def _cell_board(other=None, extra=(), via_at=(39.1, 41.9), tail=True, keep_going=True, **kw):
    """Cell m: U1 (front) with its GND pad at (39.1, 40) and a GND via of the
    cell's at `via_at`, joined to the pad by a tail. Searched with no room to
    move, it lands 20 mm up and left: the via at (19.1, 21.9), over the pad
    S of R9 on the back. `other`: a GND via on the board, where it lands."""
    vx, vy = via_at
    copper = [_via("GND", vx, vy, owner="m")]
    if tail:
        copper.append(track("GND", 39.1, 40.0, vx, vy, w=0.2, owner="m"))
    if other is not None:
        copper.append(_via("GND", *other))
    copper += list(extra)
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=("GND", "X"), cell="m"),
           footprint("R9", 19.5, vy - 20, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    g = board_geometry(fps, cells=["m"], copper=copper, width=50, height=50, extra_nets=("GND", "Y"))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    b = Board(g, edge_margin=0.5, keep_going=keep_going, **kw)
    b.place(Part("r9"), at=Location(19.5, vy - 20), face=Face.BACK)
    b.place(Cell("m"), at=Near(Location(centre.x - 20, centre.y - 20), radius=0, rotations=(0,)))
    return b


def _tracks(plan):
    return [c for c in plan.copper if isinstance(c, Track)]


def test_a_cells_via_shares_a_same_net_via_within_reach():
    plan = _cell_board(other=(19.1, 22.85)).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.via, a.net) == ("share", "m via 0", "GND")
    assert a.to == (19.1, 22.85)
    t = a.tail
    assert (t.layer, t.width) == (F, 0.2)
    assert (round(t.start.x, 6), round(t.start.y, 6), round(t.end.x, 6), round(t.end.y, 6)) == (19.1, 20.0, 19.1, 22.85)
    assert t in _tracks(plan)
    occ = plan.occupancy
    assert not [c for c in occ.copper if c.owner == "m" and c.kind == "through"]        # the cell's via is gone
    assert not [f for f in plan.findings if f.kind in ("copper", "unplaced")], list(plan.findings)


def test_a_same_net_via_further_than_via_share_is_not_shared():
    plan = _cell_board(other=(19.1, 23.4)).resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "via GND at (19.10, 21.90)" in step.note and "cannot give way" in step.note, step.note
    assert "no GND via within 1.00 mm to share" in step.note
    assert not plan.occupancy.given_way


def test_a_joining_tail_that_would_meet_another_net_is_not_drawn():
    crossing = track("Y", 18.6, 21.0, 19.6, 21.0, w=0.2)          # across the pad's way to both vias
    plan = _cell_board(other=(19.1, 22.85), extra=[crossing]).resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "no tail to the GND via within 1.00 mm is clear" in step.note, step.note


def test_via_share_zero_shares_nothing():
    from placemat.settings import Settings
    plan = _cell_board(other=(19.1, 22.85), settings=Settings(place_via_share=0.0)).resolve()
    assert plan.step("m").placement is None


def test_a_via_at_a_pad_shares_and_the_plan_draws_the_tail_not_the_via():
    """U1's GND pad lands over R9's pad S on the back; a GND via 0.93 mm
    away takes its place."""
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="u1", nets=("GND", "X")),
           footprint("R9", 20.5, 20, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    g = board_geometry(fps, copper=[_via("GND", 20.1, 20.93)], width=50, height=50, extra_nets=("GND",))
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Part("r9"), at=Location(20.5, 20), face=Face.BACK)
    b.place(Part("u1"), at=Near(Location(21.0, 20), radius=0, rotations=(0,)))      # pad 1 (GND) at (20.1, 20), over S
    b.via(Net("GND"), PadRef(Part("u1"), 1), size=0.45, drill=0.2)
    plan = b.resolve()
    assert plan.step("u1").placement is not None, plan.step("u1").note
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.via) == ("share", "pad via 0")
    assert not [c for c in plan.copper if isinstance(c, Via)]
    [t] = _tracks(plan)
    assert (round(t.start.x, 6), round(t.start.y, 6), round(t.end.x, 6), round(t.end.y, 6)) == (20.1, 20.0, 20.1, 20.93)
    assert t.layer is F


def test_a_fixed_cells_via_gives_way_where_it_was_put():
    """A cell placed firmly gives way as a searched one does: its commit
    shares the via, so the placement is legal and no finding says otherwise."""
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=("GND", "X"), cell="m"),
           footprint("R9", 19.5, 1.9, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    copper = [_via("GND", 39.1, 41.9, owner="m"), track("GND", 39.1, 40.0, 39.1, 41.9, w=0.2, owner="m"),
              _via("GND", 19.1, 22.85)]
    g = board_geometry(fps, cells=["m"], copper=copper, width=50, height=50, extra_nets=("GND",))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    b = Board(g, edge_margin=0.5)
    b.place(Part("r9"), at=Location(19.5, 21.9), face=Face.BACK)
    b.place(Cell("m"), at=Location(centre.x - 20, centre.y - 20))
    plan = b.resolve()                                          # no PlacementCollision
    assert [a.kind for a in plan.occupancy.given_way.values()] == ["share"]
    assert not [f for f in plan.findings if f.kind == "fixed"], list(plan.findings)


def test_sharing_costs_score_via_share_in_the_search():
    from placemat.placement import Placement
    from placemat.placer import scan
    plan = _cell_board(other=(19.1, 22.85))
    b = plan
    occ = Occupancy(b.geometry, 0.5, settings=b.settings)
    occ.commit(b.geometry.footprint("R9"), Placement(Location(19.5, 21.9), 0.0, Face.BACK))
    centre = occ._geometry(b.geometry.cells["m"]).reference.location
    hint = Placement(Location(centre.x - 20, centre.y - 20), 0.0, Face.FRONT)
    r = scan(occ, b.geometry.cells["m"], hint, 0.0, 0.2, (0.0,), score=lambda p: 0.0)
    assert r.chosen is not None and r.score == 1.0


def test_a_riders_via_gives_way_as_its_item_is_placed():
    """c1 rides u1, its GND pad 2.5 mm north of u1's pad 1, where R9's pad S
    lies on the back; a GND via 0.93 mm off takes its pad's via."""
    from placemat.values import Pin, X, Y
    fps = [footprint("U1", 40, 40, w=8, h=3, inst="u1", nets=("A", "B")),
           footprint("C1", 45, 45, w=2, h=1, inst="c1", nets=("GND", "C")),
           footprint("R9", 27.0, 17.5, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    g = board_geometry(fps, copper=[_via("GND", 26.6, 16.57)], width=60, height=60, extra_nets=("GND",))
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Part("r9"), at=Location(27.0, 17.5), face=Face.BACK)
    b.place(Part("u1"), at=Near(Location(30, 20), radius=0, rotations=(0,)))
    b.place(Part("c1"), at=Pin(1, X(PadRef(Part("u1"), 1)), Y(PadRef(Part("u1"), 1), -2.5)))
    b.via(Net("GND"), PadRef(Part("c1"), 1), size=0.45, drill=0.2)
    plan = b.resolve()
    assert plan.placement("u1") is not None and plan.placement("c1") is not None, plan.step("u1").note
    assert [(a.kind, a.via) for a in plan.occupancy.given_way.values()] == [("share", "pad via 0")]
    assert not [f for f in plan.findings if f.kind in ("fixed", "unplaced", "copper")], list(plan.findings)


def test_an_item_searched_along_an_edge_slides_to_where_its_vias_give_way():
    """A board as wide as u1 and its keep-in: every slot along the north
    edge puts u1's GND pad (turned outward, at the east end), and its via,
    over R9's pad S on the back. A GND via 0.93 mm below the middle slot
    takes the via there."""
    from placemat.values import Edge, OnEdge
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="u1", nets=("GND", "X")),
           footprint("R9", 3.0, 1.0, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK, rotation=180.0)]
    g = board_geometry(fps, copper=[_via("GND", 3.4, 1.93)], width=5, height=20, extra_nets=("GND",))
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Part("r9"), at=Location(3.0, 1.0), rotation=180.0, face=Face.BACK)
    b.place(Part("u1"), at=OnEdge(Edge.NORTH))
    b.via(Net("GND"), PadRef(Part("u1"), 1), size=0.45, drill=0.2)
    plan = b.resolve()
    assert plan.placement("u1") is not None, plan.step("u1").note
    assert plan.box("u1").center.x == 2.5
    assert [(a.kind, a.via) for a in plan.occupancy.given_way.values()] == [("share", "pad via 0")]


# ------------------------------------------------------------------ moving
def _settings(**kw):
    from placemat.settings import Settings
    return Settings(**kw)


def _moving_board(via_at, tail, r9_at, r9_w=2.0, r9_nets=("S", "T"), net="SIG", settings=None, planes=()):
    """Cell m: U1 (front) with its `net` pad at (39.1, 40) and a via of the
    cell's at `via_at`, joined to the pad by a tail when `tail`. It lands
    20 mm up and left, R9 on the back at `r9_at` (where it stands then)."""
    vias = [via_at] if isinstance(via_at[0], (int, float)) else list(via_at)
    copper = [_via(net, vx, vy, owner="m") for vx, vy in vias]
    if tail:
        copper += [track(net, 39.1, 40.0, vx, vy, w=0.2, owner="m") for vx, vy in vias]
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=(net, "X"), cell="m"),
           footprint("R9", r9_at[0], r9_at[1], w=r9_w, h=1, inst="r9", nets=r9_nets, face=Face.BACK)]
    g = board_geometry(fps, cells=["m"], copper=copper, width=50, height=50, extra_nets=(net,))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    kw = {"settings": settings} if settings is not None else {}
    b = Board(g, edge_margin=0.5, keep_going=True, **kw)
    for n in planes:
        b.plane(Net(n), [CopperLayer.B])
    b.place(Part("r9"), at=Location(*r9_at), face=Face.BACK)
    b.place(Cell("m"), at=Near(Location(centre.x - 20, centre.y - 20), radius=0, rotations=(0,)))
    return b


def test_a_signal_via_moves_to_the_nearest_clear_spot_and_its_tail_is_redrawn():
    """The via lands at (19.1, 22.2), its ring 0.07 mm from R9's pad S (top
    edge 22.5) on the back; 0.15 mm up, on the 0.05 mm grid, it clears it."""
    plan = _moving_board((39.1, 42.2), True, (19.5, 23.0)).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.via) == ("move", "m via 0")
    assert a.to == (19.1, 22.05) and round(a.moved_mm, 6) == 0.15
    t = a.tail
    assert (t.layer, t.width) == (F, 0.2)
    assert (round(t.start.x, 6), round(t.start.y, 6), round(t.end.x, 6), round(t.end.y, 6)) == (19.1, 20.0, 19.1, 22.05)
    assert t in _tracks(plan)
    [ring] = [c for c in plan.occupancy.copper if c.owner == "m" and c.kind == "through"]
    assert ring.points == ((19.1, 22.05),)
    assert not [f for f in plan.findings if f.kind in ("copper", "unplaced")], list(plan.findings)


def test_a_via_inside_its_pad_moves_only_within_the_pad():
    """A via at the middle of U1's pad, R9's pad 2 on the back 0.02 mm off
    its ring to the left: it moves 0.2 mm right, still inside its pad."""
    plan = _moving_board((39.1, 40.0), False, (17.45, 20.0), r9_w=3.0).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.to, a.tail) == ("move", (19.3, 20.0), None)


def test_a_via_inside_its_pad_with_room_only_outside_it_is_refused():
    """R9's pad S on the back covers the right of U1's pad: clear spots are
    to the left, 0.35 mm off, where the via would leave its pad."""
    plan = _moving_board((39.1, 40.0), False, (20.1, 20.0)).resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "no spot within 0.50 mm inside its pad is clear" in step.note, step.note


def test_a_via_with_no_clear_spot_within_via_move_is_refused_and_named():
    plan = _moving_board((39.1, 42.2), True, (19.5, 23.0), settings=_settings(place_via_move=0.1)).resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "via SIG at (19.10, 22.20)" in step.note and "no spot within 0.10 mm is clear" in step.note, step.note


def test_moving_costs_score_via_move_in_the_search():
    from placemat.placement import Placement
    from placemat.placer import scan
    b = _moving_board((39.1, 42.2), True, (19.5, 23.0))
    occ = Occupancy(b.geometry, 0.5, settings=b.settings)
    centre = occ._geometry(b.geometry.cells["m"]).reference.location
    hint = Placement(Location(centre.x - 20, centre.y - 20), 0.0, Face.FRONT)
    r = scan(occ, b.geometry.cells["m"], hint, 0.0, 0.2, (0.0,), score=lambda p: 0.0)
    assert r.chosen is not None and r.score == 2.0


def test_a_via_that_could_share_or_move_shares():
    """The cell's via could move 0.15 mm off R9's pad S, and a SIG via of the
    board is 0.9 mm off: sharing costs less, so it shares."""
    first = _moving_board((39.1, 42.2), True, (19.5, 23.0)).geometry
    fps = list(first.footprints)
    copper = [c for c in first.copper if c.kind != "pad"] + [_via("SIG", 18.2, 22.2)]
    g = board_geometry(fps, cells=["m"], copper=copper, width=50, height=50, extra_nets=("SIG",))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Part("r9"), at=Location(19.5, 23.0), face=Face.BACK)
    b.place(Cell("m"), at=Near(Location(centre.x - 20, centre.y - 20), radius=0, rotations=(0,)))
    plan = b.resolve()
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.to) == ("share", (18.2, 22.2))


# ------------------------------------------------------------------ dropping
_DROP_ONLY = dict(place_via_share=0.0, place_via_move=0.0)
_THREE = [(38.85, 39.75), (38.85, 40.25), (39.35, 40.0)]    # in U1's GND pad; R9's pad S meets the right one


def test_a_plane_drop_is_dropped_while_its_pad_keeps_its_share():
    """Three drops in the pad: it must keep ceil(0.5 * 3) = 2, so the one R9
    meets goes."""
    plan = _moving_board(_THREE, False, (20.3, 20.0), net="GND", planes=("GND",),
                         settings=_settings(**_DROP_ONLY)).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.via, a.pad, a.tail) == ("drop", "m via 2", ("U1", "1"), None)
    assert len([c for c in plan.occupancy.copper if c.owner == "m" and c.kind == "through"]) == 2


def test_a_pad_at_its_keep_share_refuses_the_candidate():
    """Two drops, both over R9's pad S: one may go, the pad keeps the other."""
    plan = _moving_board([(38.85, 40.0), (39.35, 40.0)], False, (19.8, 20.0), net="GND", planes=("GND",),
                         settings=_settings(**_DROP_ONLY)).resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "U1 pad 1 keeps 1 of its 2 drops, and must keep 1" in step.note, step.note


def test_a_pads_last_drop_is_never_dropped_whatever_drops_keep_says():
    plan = _moving_board((39.35, 40.0), False, (20.3, 20.0), net="GND", planes=("GND",),
                         settings=_settings(place_drops_keep=0.0, **_DROP_ONLY)).resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "keeps 1 of its 1 drops, and must keep 1" in step.note, step.note


def test_a_signal_via_is_never_dropped():
    plan = _moving_board(_THREE, False, (20.3, 20.0), net="SIG", settings=_settings(**_DROP_ONLY)).resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "SIG is not a plane net, so it is no drop" in step.note, step.note


def test_dropping_costs_score_via_drop_in_the_search():
    from placemat.placement import Placement
    from placemat.placer import scan
    b = _moving_board(_THREE, False, (20.3, 20.0), net="GND", planes=("GND",), settings=_settings(**_DROP_ONLY))
    occ = Occupancy(b.geometry, 0.5, settings=b.settings)
    occ.plane_nets = frozenset(["GND"])
    centre = occ._geometry(b.geometry.cells["m"]).reference.location
    hint = Placement(Location(centre.x - 20, centre.y - 20), 0.0, Face.FRONT)
    r = scan(occ, b.geometry.cells["m"], hint, 0.0, 0.2, (0.0,), score=lambda p: 0.0)
    assert r.chosen is not None and r.score == 10.0


# ---------------------------------------------------------------- shortening
IN1 = CopperLayer.IN1
_SHORTEN_ONLY = dict(place_via_share=0.0, place_via_move=0.0)


def _shorten_board(via_at, r9_at, plane_layer=IN1, tiers=None, settings=None):
    """Cell m: U1 (front) with its GND pad at (39.1, 40) and a through GND
    via of the cell's at `via_at`, on a 3-layer board (F, plane_layer, B)
    whose plane_layer carries a GND plane. R9 on the back at `r9_at`, where
    it stands once the cell lands 20 mm up and left."""
    import dataclasses
    net = "GND"
    copper = [_via(net, *via_at, owner="m", layers=frozenset([F, plane_layer, B])),
             track(net, 39.1, 40.0, via_at[0], via_at[1], w=0.2, owner="m")]
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=(net, "X"), cell="m"),
           footprint("R9", r9_at[0], r9_at[1], w=2.0, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    g = board_geometry(fps, cells=["m"], copper=copper, width=50, height=50, extra_nets=(net,))
    g = dataclasses.replace(g, layers=(F, plane_layer, B))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    kw = {"settings": settings} if settings is not None else {}
    b = Board(g, edge_margin=0.5, keep_going=True, fab_via_tiers=(tiers or {}), **kw)
    b.plane(Net(net), [plane_layer])
    b.place(Part("r9"), at=Location(*r9_at), face=Face.BACK)
    b.place(Cell("m"), at=Near(Location(centre.x - 20, centre.y - 20), radius=0, rotations=(0,)))
    return b


def test_a_drop_shortens_to_the_nearest_plane_layer_when_the_tier_is_yes():
    b = _shorten_board((39.1, 41.9), (19.5, 21.9), tiers={"micro": "yes"}, settings=_settings(**_SHORTEN_ONLY))
    plan = b.resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    [a] = plan.occupancy.given_way.values()
    assert a.kind == "shorten" and a.net == "GND"
    assert a.cost == pytest.approx(b.settings.score_via_shorten)
    [ring] = [c for c in plan.occupancy.copper if c.owner == "m" and c.kind == "through"]
    assert ring.layers == frozenset([F, IN1])
    assert not [f for f in plan.findings if f.kind in ("copper", "unplaced")], list(plan.findings)


def test_an_if_needed_tier_is_judged_but_never_applied():
    b = _shorten_board((39.1, 41.9), (19.5, 21.9), tiers={"micro": "if-needed"}, settings=_settings(**_SHORTEN_ONLY))
    plan = b.resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "if-needed" in step.note and "micro" in step.note and "F-In1" in step.note, step.note
    assert not plan.occupancy.given_way


def test_no_tier_refuses_without_mentioning_shorten():
    b = _shorten_board((39.1, 41.9), (19.5, 21.9), settings=_settings(**_SHORTEN_ONLY))
    plan = b.resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "if-needed" not in step.note and "shorten" not in step.note.lower(), step.note


# ------------------------------------------------------------------ items already placed, and the report
def _later_board(copper, r9_at, net="GND", planes=(), settings=None, m_searched=False):
    """Cell m (U1 with its `net` pad at (39.1, 40), and `copper` of the
    cell's) placed first, 20 mm up and left - firmly, or searched there
    with no room to move - then R9, searched on the back with no room to
    move, at `r9_at`."""
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=(net, "X"), cell="m"),
           footprint("R9", 5, 5, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    g = board_geometry(fps, cells=["m"], copper=copper, width=50, height=50, extra_nets=(net,))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    b = Board(g, edge_margin=0.5, keep_going=True, **({"settings": settings} if settings else {}))
    for n in planes:
        b.plane(Net(n), [CopperLayer.B])
    at = Location(centre.x - 20, centre.y - 20)
    if m_searched:
        from placemat.values import Priority
        b.place(Cell("m"), at=Near(at, radius=0, rotations=(0,)), priority=Priority.HIGH)
    else:
        b.place(Cell("m"), at=at)
    b.place(Part("r9"), at=Near(Location(*r9_at), radius=0, rotations=(0,)), face=Face.BACK)
    return b


def _shared_later(**kw):
    """The cell's GND via at (19.1, 21.9) once placed, R9's pad S on it, and
    a GND via of the board's 0.95 mm off."""
    return _later_board([_via("GND", 39.1, 41.9, owner="m"), track("GND", 39.1, 40.0, 39.1, 41.9, w=0.2, owner="m"),
                         _via("GND", 19.1, 22.85)], (19.5, 21.9), **kw)


def test_a_placed_cells_via_shares_for_a_later_back_part():
    plan = _shared_later().resolve()
    assert plan.step("r9").placement is not None, plan.step("r9").note
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.via, a.home, a.under) == ("share", "m via 0", "m", "R9")
    assert a.tail in _tracks(plan) and a.tail.layer is F          # on the via's own face, not R9's
    assert not [f for f in plan.findings if f.kind in ("copper", "unplaced", "fixed")], list(plan.findings)


def test_a_placed_cells_via_moves_for_a_later_back_part():
    """R9's pad S lands 0.07 mm off the cell's via: the via moves 0.15 mm."""
    plan = _later_board([_via("SIG", 39.1, 42.2, owner="m"), track("SIG", 39.1, 40.0, 39.1, 42.2, w=0.2, owner="m")],
                        (19.5, 23.0), net="SIG").resolve()
    assert plan.step("r9").placement is not None, plan.step("r9").note
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.to, a.under) == ("move", (19.1, 22.05), "R9")
    assert [c.points for c in plan.occupancy.copper if c.owner == "m" and c.kind == "through"] == [((19.1, 22.05),)]


def test_a_via_move_is_the_same_native_or_not(monkeypatch):
    """The native offset search (giveway._native_move_offsets) picks the
    same spot the pure-Python per-offset loop would - on a placed via
    that must move for a later part (the scenario where a native search
    naturally sees its own via as a registered obstacle, and must exclude
    it - giveway.py's own `_native_move_offsets` doc)."""
    import pytest
    from placemat import geometry, giveway
    if geometry._native is None:
        pytest.skip("no native module")
    runs = {}
    for native_on in (False, True):
        monkeypatch.setattr(giveway, "_NATIVE_MOVE_SEARCH", native_on)
        plan = _later_board(
            [_via("SIG", 39.1, 42.2, owner="m"), track("SIG", 39.1, 40.0, 39.1, 42.2, w=0.2, owner="m")],
            (19.5, 23.0), net="SIG").resolve()
        runs[native_on] = ([(a.kind, a.via, a.to, round(a.moved_mm, 6)) for a in plan.occupancy.given_way.values()],
                           plan.step("r9").placement, plan.step("r9").note)
    assert runs[True] == runs[False]
    assert runs[True][0] and runs[True][0][0][0] == "move"       # a move actually happened, on both paths


def _first_move_runs(monkeypatch, make):
    """`make()` resolved with a via's whole move judged natively and by the Python loop: what each
    gave way to (and the steps' notes), and how many moves the native call judged."""
    from placemat import geometry, giveway
    if geometry._native is None:
        pytest.skip("no native module")
    used = []
    real = giveway._native_first_move

    def counting(*a, **k):
        out = real(*a, **k)
        used.append(out[0])
        return out
    monkeypatch.setattr(giveway, "_native_first_move", counting)
    runs = {}
    for native_on in (False, True):
        monkeypatch.setattr(giveway, "_NATIVE_FIRST_MOVE", native_on)
        used.clear()
        plan = make().resolve()
        runs[native_on] = ([(a.kind, a.via, a.at, a.to, a.tail, a.old_tail, a.cost, round(a.moved_mm, 6))
                            for a in plan.occupancy.given_way.values()],
                           [(st.item, st.placement, st.note) for st in plan.steps], sum(used))
    return runs


_MOVES = {
    "a tail redrawn": lambda: _moving_board((39.1, 42.2), True, (19.5, 23.0)),
    "inside its pad": lambda: _moving_board((39.1, 40.0), False, (17.45, 20.0), r9_w=3.0),
    "refused inside its pad": lambda: _moving_board((39.1, 40.0), False, (20.1, 20.0)),
    "refused within via_move": lambda: _moving_board((39.1, 42.2), True, (19.5, 23.0),
                                                     settings=_settings(place_via_move=0.1)),
    "a placed via": lambda: _later_board([_via("SIG", 39.1, 42.2, owner="m"),
                                          track("SIG", 39.1, 40.0, 39.1, 42.2, w=0.2, owner="m")],
                                         (19.5, 23.0), net="SIG"),
}


@pytest.mark.parametrize("name", sorted(_MOVES))
def test_a_via_move_is_the_same_with_one_native_call_as_with_the_loop(monkeypatch, name):
    runs = _first_move_runs(monkeypatch, _MOVES[name])
    assert runs[True][:2] == runs[False][:2]
    assert runs[False][2] == 0
    if name != "refused within via_move":            # no spot is clear of the board: nothing left to judge
        assert runs[True][2] >= 1, "the native first_move judged no move"


def test_a_via_move_past_the_board_edge_takes_the_next_spot(monkeypatch):
    """The board's edge is judged in Python, per spot: where it refuses the nearest clear spot
    the native call is asked again from the next offset, and the same spot is taken as by the loop."""
    real = Occupancy._edge_why

    def edge(self, body):
        if body.width < 0.6 and 21.75 < body.top < 21.9:     # a via's ring, in a band the nearest spot lies in
            return "too near the edge"
        return real(self, body)
    free = _first_move_runs(monkeypatch, _MOVES["a tail redrawn"])
    monkeypatch.setattr(Occupancy, "_edge_why", edge)
    runs = _first_move_runs(monkeypatch, _MOVES["a tail redrawn"])
    assert runs[True][:2] == runs[False][:2]
    assert runs[True][2] >= 1
    assert runs[True][0][0][3] != free[True][0][0][3]       # the edge moved the choice


def test_first_move_is_not_used_on_a_board_with_a_net_tie(monkeypatch):
    from placemat import giveway
    monkeypatch.setattr(giveway, "_has_net_ties", lambda occ: True)
    runs = _first_move_runs(monkeypatch, _MOVES["a tail redrawn"])
    assert runs[True][:2] == runs[False][:2]
    assert runs[True][2] == 0


def test_a_net_tie_footprint_is_seen_on_the_board():
    import dataclasses
    from placemat import giveway
    g = _moving_board((39.1, 42.2), True, (19.5, 23.0)).geometry
    assert not giveway._has_net_ties(Occupancy(g))
    tied = tuple(dataclasses.replace(fp, net_tie_pads=frozenset(["1"])) if fp.ref == "R9" else fp
                 for fp in g.footprints)
    assert giveway._has_net_ties(Occupancy(dataclasses.replace(g, footprints=tied)))


def test_a_placed_owner_keeps_its_keep_share():
    """Both of the cell's drops in U1's pad lie under R9's pad S: one may go
    for it, the pad keeps the other, so R9 is refused there."""
    plan = _later_board([_via("GND", 38.85, 40.0, owner="m"), _via("GND", 39.35, 40.0, owner="m")], (19.8, 20.0),
                        planes=("GND",), settings=_settings(**_DROP_ONLY)).resolve()
    step = plan.step("r9")
    assert step.placement is None
    assert "cannot give way" in step.note and "U1 pad 1 keeps 1 of its 2 drops, and must keep 1" in step.note, \
        step.note
    assert not plan.occupancy.given_way


def test_what_gave_way_is_reported_on_the_owners_step_and_as_a_finding():
    plan = _shared_later().resolve()
    [f] = [f for f in plan.findings if f.kind == "vias"]
    assert f == "m: 1 GND via shared under R9"
    assert "vias: 1 GND via shared under R9" in plan.step("m").note


def test_giving_way_for_a_later_item_leaves_the_owners_lock_entry_alone():
    """The owner's decision is its place and its declaration: what its via
    did for a later item is the plan's."""
    from placemat import lock
    alone = _later_board([_via("GND", 39.1, 41.9, owner="m"), track("GND", 39.1, 40.0, 39.1, 41.9, w=0.2, owner="m"),
                          _via("GND", 19.1, 22.85)], (5.0, 40.0), m_searched=True)
    shared = _shared_later(m_searched=True)
    plans = [alone.resolve(), shared.resolve()]
    assert [a.kind for a in plans[1].occupancy.given_way.values()] == ["share"]
    assert not plans[0].occupancy.given_way
    got = [lock.entries(b, p, ["m"])[0] for b, p in zip((alone, shared), plans)]
    assert got[0] == got[1]


# ------------------------------------------------------------------ the native sweep and the Python one agree
def _field_board():
    """A front cell whose parts each carry four GND drops in a pad and a
    signal via with a tail, over most of a small board; then a back cell,
    linked to it (scored) or not (nearest first), that fits only where some
    of those vias give way."""
    copper, fps = [], []
    k = 0
    for i in range(6):
        for j in range(6):
            x, y = 4 + 5 * i, 4 + 4.3 * j
            fps.append(footprint("U%d" % k, x, y, w=3, h=1.4, inst="m.u%d" % k, nets=("GND", "S%d" % k), cell="m"))
            px = x - 0.9
            copper += [_via("GND", px + dx, y + dy, owner="m") for dx, dy in ((-0.25, -0.25), (0.25, -0.25),
                                                                                (-0.25, 0.25), (0.25, 0.25))]
            copper += [_via("S%d" % k, x + 0.9, y + 1.6, owner="m"), track("S%d" % k, x + 0.9, y, x + 0.9, y + 1.6,
                                                                           w=0.2, owner="m")]
            k += 1
    for q in range(6):
        fps.append(footprint("Q%d" % q, 60 + 4 * (q % 3), 60 + 3 * (q // 3), w=3, h=1.4, inst="p.q%d" % q,
                             nets=("S%d" % q, "A%d" % q), cell="p"))
    return board_geometry(fps, cells=["m", "p"], copper=copper, width=34, height=30, extra_nets=("GND",))


def test_a_sweep_whose_vias_give_way_is_the_same_native_or_not(monkeypatch):
    import pytest
    from placemat import geometry, placer
    from placemat.values import LinkWeight
    if geometry._native is None:
        pytest.skip("no native module")
    seen = []

    class Recorded(placer.ScanResult):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            seen.append(self)
    monkeypatch.setattr(placer, "ScanResult", Recorded)
    g = _field_board()
    runs = {}
    for linked in (False, True):
        for on in (False, True):
            monkeypatch.setattr(placer, "NATIVE_SWEEP", on)
            del seen[:]
            b = Board(g, edge_margin=0.5, keep_going=True)
            b.plane(Net("GND"), [CopperLayer.B])
            b.place(Cell("m"), at=Location(17, 15))
            b.place(Cell("p"), at=Near(Location(17, 15), radius=10), face=Face.BACK)
            if linked:
                b.link(PadRef(Part("p.q0"), 1), PadRef(Part("m.u0"), 2), weight=LinkWeight.SHORT)
            plan = b.resolve()
            runs[(linked, on)] = ([(r.chosen, r.tried, list(r.rejected.items()), list(r.reasons.items()),
                                    list(r.blockers.items()), r.score) for r in seen],
                                  [(s.item, s.placement, s.note) for s in plan.steps], list(plan.findings))
        assert runs[(linked, True)] == runs[(linked, False)]
        assert runs[(linked, True)][1][-1][1] is not None           # the back cell placed
        assert any(f.kind == "vias" for f in plan.findings)


# ------------------------------------------------------------------ what a via shares stays
def test_a_via_does_not_share_another_via_of_its_own_item():
    """The cell's two GND vias are 0.9 mm apart; R9's pad S lands on the
    first. Sharing the second - its own - would leave it the only via there,
    and free to give way in turn: the first moves or is refused instead."""
    plan = _later_board([_via("GND", 39.1, 41.9, owner="m"), track("GND", 39.1, 40.0, 39.1, 41.9, w=0.2, owner="m"),
                         _via("GND", 39.1, 42.8, owner="m")], (19.5, 21.9)).resolve()
    shares = [a for a in plan.occupancy.given_way.values() if a.kind == "share"]
    assert not shares, shares


def _anchored_board():
    """Cell n (N1, with a GND via of its own at (19.1, 23.5)) and R9 on the
    back placed firmly; then cell m, whose GND via lands on R9's pad S and
    shares n's via (`place.via_share` 2 mm); then R2, searched on the back
    with no room to move, its pad S2 on n's via."""
    from placemat.settings import Settings
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=("GND", "X"), cell="m"),
           footprint("N1", 10, 23.5, w=2, h=1, inst="n.n1", nets=("GND", "Z"), cell="n"),
           footprint("R9", 19.5, 21.9, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK),
           footprint("R2", 5, 5, w=2, h=1, inst="r2", nets=("S2", "T2"), face=Face.BACK)]
    copper = [_via("GND", 39.1, 41.9, owner="m"), track("GND", 39.1, 40.0, 39.1, 41.9, w=0.2, owner="m"),
              _via("GND", 19.1, 23.5, owner="n")]
    g = board_geometry(fps, cells=["m", "n"], copper=copper, width=50, height=50, extra_nets=("GND",))
    occ = Occupancy(g)
    m_centre = occ._geometry(g.cells["m"]).reference.location
    n_centre = occ._geometry(g.cells["n"]).reference.location
    b = Board(g, edge_margin=0.5, keep_going=True, settings=Settings(place_via_share=2.0))
    b.place(Cell("n"), at=n_centre)
    b.place(Part("r9"), at=Location(19.5, 21.9), face=Face.BACK)
    b.place(Cell("m"), at=Location(m_centre.x - 20, m_centre.y - 20))
    b.place(Part("r2"), at=Near(Location(19.5, 23.5), radius=0, rotations=(0,)), face=Face.BACK)
    return b


def test_a_via_another_shares_does_not_give_way():
    plan = _anchored_board().resolve()
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.via, a.to) == ("share", "m via 0", (19.1, 23.5))
    step = plan.step("r2")
    assert step.placement is None
    assert "cannot give way" in step.note and "shares it" in step.note, step.note


def test_an_if_needed_tier_that_would_have_placed_is_a_needs_finding():
    b = _shorten_board((39.1, 41.9), (19.5, 21.9), tiers={"micro": "if-needed"}, settings=_settings(**_SHORTEN_ONLY))
    plan = b.resolve()
    [f] = [f for f in plan.findings if f.kind == "needs"]
    assert f.startswith("m: ") and "if-needed" in f and "micro" in f and "F-In1" in f, f


def test_no_needs_finding_without_an_if_needed_tier():
    b = _shorten_board((39.1, 41.9), (19.5, 21.9), settings=_settings(**_SHORTEN_ONLY))
    plan = b.resolve()
    assert not [f for f in plan.findings if f.kind == "needs"], list(plan.findings)


def test_the_least_give_way_cost_counts_shorten_when_a_tier_allows_it():
    """A scored scan skips a candidate that cannot beat the best at the
    cheapest way; shorten is that way when it is the cheapest allowed."""
    from placemat.giveway import least_cost
    s = _settings(**_SHORTEN_ONLY)
    assert least_cost(s) == s.score_via_drop
    assert least_cost(s, {"micro": "yes"}) == s.score_via_shorten
    assert least_cost(s, {"micro": "if-needed"}) == s.score_via_drop


def test_a_placed_vias_clear_moves_are_searched_once_per_scan():
    """The same via, against the same scan's board with the same vias set
    aside, is asked once: a second candidate that meets it reuses the
    answer."""
    import types
    from placemat import giveway
    from placemat.occupancy import ShapeIndex
    from placemat.settings import Settings

    calls = []

    class Index:
        def first_clear_offset(self, shapes, offsets, clearance, say, skip):
            calls.append(1)
            return [0, 2]

    others = ShapeIndex([])
    others._native = (Index(), [])
    occ = types.SimpleNamespace(_footprint_refs=frozenset(), _leads=frozenset(), _margins={},
                                settings=Settings())
    judge = types.SimpleNamespace(occ=occ, others=others, hidden={"m via 0"}, clearance=0.2)
    from placemat.occupancy import Shape
    poly = circle_polygon(Location(10, 10), 0.225)
    ring = Shape("m", "through", frozenset([Face.FRONT, Face.BACK]), frozenset([F, B]), "GND", poly,
                 Box.of_points(poly), carried="m via 0", points=((10.0, 10.0),))
    offsets = ((0.05, 0.0), (0.0, 0.05), (-0.05, 0.0))
    first = giveway._native_move_offsets(judge, ring, None, offsets)
    again = giveway._native_move_offsets(judge, ring, None, offsets)
    assert first == again == [(0.05, 0.0), (-0.05, 0.0)]
    assert len(calls) == 1
    judge.hidden = {"m via 0", "n via 1"}                 # another via set aside: a different board
    giveway._native_move_offsets(judge, ring, None, offsets)
    assert len(calls) == 2
