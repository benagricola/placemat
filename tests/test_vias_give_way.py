"""A carried via that meets another net's copper gives way instead of
refusing the placement: it shares a same-net via close by, moves a little,
or - a plane's drop - is dropped while its pad keeps its share."""
from placemat.board_geometry import CopperItem
from placemat.copper import Track, Via
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.values import Box, Cell, CopperLayer, Face, Location, Near, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint, track

F, B = CopperLayer.F, CopperLayer.B


def _via(net, x, y, owner=None, size=0.45, drill=0.2):
    ring = circle_polygon(Location(x, y), size / 2)
    return CopperItem("via", net, frozenset([F, B]), (ring,), Box.of_points(ring), owner, size, drill, ((x, y),))


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
