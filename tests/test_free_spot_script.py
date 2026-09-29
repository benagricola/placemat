"""A via written at the nearest legal spot to a pad, resolved when the pad's
part is placed, against the copper planned before it. Pure."""
from placemat import FreeSpot
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("GND", "SIG")),
           footprint("R1", 20, 26, w=2, h=1, inst="r1", nets=("SIG", "V3"))]
    return Board(board_geometry(fps, width=40, height=40, extra_nets=("GND",)), edge_margin=0.5)


def test_a_free_spot_resolves_to_a_clear_position_near_its_pad():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")), why="tap")
    plan = b.resolve()
    (via,) = [c for c in plan.copper if type(c).__name__ == "Via"]
    pad = plan.occupancy.pad_location("U1", "1")
    assert via.at.distance(pad) <= 2.0 + 1e-6
    assert not any("via" in f and "nowhere" in f for f in plan.findings)


def test_a_second_via_near_the_same_pad_lands_clear_of_the_first():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    ref = PadRef(Part("u1"), "GND")
    b.via(Net("GND"), at=FreeSpot(near=ref), why="tap one")
    b.via(Net("SIG"), at=FreeSpot(near=PadRef(Part("u1"), "SIG")), why="tap two")
    plan = b.resolve()
    vias = [c for c in plan.copper if type(c).__name__ == "Via"]
    assert len(vias) == 2
    gap = vias[0].at.distance(vias[1].at) - (vias[0].size + vias[1].size) / 2.0
    assert gap >= 0.2 - 1e-6                       # the class clearance between the two nets


def test_a_free_spot_with_nowhere_to_go_is_a_finding_and_draws_nothing():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND"), radius=0.05), why="tap")
    plan = b.resolve()
    assert not [c for c in plan.copper if type(c).__name__ == "Via"]
    assert any("nowhere" in f for f in plan.findings)


def test_a_free_spot_stays_out_of_its_own_pad():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")), why="tap")
    plan = b.resolve()
    (via,) = [c for c in plan.copper if type(c).__name__ == "Via"]
    assert via.at.distance(plan.occupancy.pad_location("U1", "1")) > 0.4


from placemat.copper import Track, Via


def _tails(plan):
    return [c for c in plan.copper if isinstance(c, Track) and c.net == "GND"]


def test_a_free_spot_via_draws_its_tail_to_the_pad():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")), why="tap")
    plan = b.resolve()
    (via,) = [c for c in plan.copper if isinstance(c, Via)]
    (tail,) = _tails(plan)
    pad = plan.occupancy.pad_location("U1", "1")
    assert {(round(p.x, 6), round(p.y, 6)) for p in (tail.start, tail.end)} == {
        (round(pad.x, 6), round(pad.y, 6)), (round(via.at.x, 6), round(via.at.y, 6))}
    assert tail.layer is CopperLayer.F
    assert abs(tail.width - b.geometry.netclass("GND").track_width) < 1e-9


def test_tail_false_or_a_via_in_the_pad_draws_no_tail():
    for spot in (dict(tail=False), dict(in_pad=True)):
        b = _board()
        b.place(Part("u1"), at=Location(20, 20))
        b.place(Part("r1"), at=Location(20, 26))
        b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND"), **spot), why="tap")
        plan = b.resolve()
        assert [c for c in plan.copper if isinstance(c, Via)]
        assert not _tails(plan), spot


def test_the_tail_meets_a_searched_and_turned_parts_pad_where_it_landed():
    b = _board()
    b.place(Part("u1"), rotations=(90,))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")), why="tap")
    plan = b.resolve()
    assert plan.placement("u1").rotation == 90
    pad = plan.occupancy.pad_location("U1", "1")
    (tail,) = _tails(plan)
    assert any(p.distance(pad) < 1e-6 for p in (tail.start, tail.end))


def test_a_via_keeps_clear_of_a_tail_planned_before_it_in_the_batch():
    """Tails of one batch are not in the occupancy yet: the search judges
    against them itself. A GND tail laid across the spot a SIG via takes
    without it moves the SIG via clear of that tail."""
    from placemat.geometry import poly_distance
    from placemat.layout import _CopperContext
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    plan = b.resolve()
    spot = FreeSpot(near=PadRef(Part("u1"), "SIG"))

    def search(tails):
        ctx = _CopperContext(b, plan.occupancy)
        ctx.plan = plan
        ctx.planned_tails = list(tails)
        return b._free_spot(ctx, spot, "SIG", 0.3, 0.6)
    alone, _, _, _, _ = search([])
    across = Track("GND", CopperLayer.F, 0.2, Location(alone.x, alone.y - 2), Location(alone.x, alone.y + 2))
    moved, _, _, _, _ = search([across])
    ring = Via("SIG", moved, 0.3, 0.6).polygon
    assert moved.distance(alone) > 1e-6
    assert poly_distance(ring, across.polygon) >= 0.2 - 1e-6


def test_a_tail_is_no_wider_than_its_pad_when_the_class_is_wider():
    """A power class's track can be wider than a small pad; the tail necks
    down to the pad's narrower side, as a hand-drawn one does."""
    import dataclasses
    g = _board().geometry
    wide = dataclasses.replace(g.netclasses["GND"], track_width=2.0)
    b = Board(dataclasses.replace(g, netclasses={**g.netclasses, "GND": wide}), edge_margin=0.5)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")), why="tap")
    plan = b.resolve()
    (tail,) = _tails(plan)
    assert tail.width <= 1.0 + 1e-9


def _pin_row(pitch, width):
    """A fine-pitch row of pins on nets N0..N16 above an exposed pad, the
    row a via on each neighbouring pin crowds."""
    from placemat.board_geometry import Footprint
    from placemat.values import Box, Face
    from tests.fixtures import pad
    pads = [pad("U1", "u1", i + 1, "N%d" % i, 16 + i * pitch, 20, width, 0.8) for i in range(17)]
    pads.append(pad("U1", "u1", 99, "EP", 16 + 8 * pitch, 22.0, 16 * pitch + 1, 2.2))
    body = Box(15.5, 19.5, 16 + 16 * pitch + 0.5, 23.5)
    fp = Footprint("U1", "u1", None, "U1", Location(20, 21.5), 0.0, Face.FRONT, body, body.inflate(0.1), body,
                   tuple(pads))
    return board_geometry([fp], width=40, height=40)


def test_vias_on_neighbouring_pins_keep_clear_of_each_others_tails():
    import itertools
    from placemat.geometry import poly_distance
    for pitch, width in ((0.4, 0.2), (0.5, 0.25), (0.65, 0.3)):
        for order in itertools.permutations(range(5, 8), 3):
            b = Board(_pin_row(pitch, width), edge_margin=0.5)
            b.place(Part("u1"), at=Location(20, 21.5))
            for i in order:
                b.via(Net("N%d" % i), at=FreeSpot(near=PadRef(Part("u1"), i + 1)))
            plan = b.resolve()
            vias = [c for c in plan.copper if isinstance(c, Via)]
            tails = [c for c in plan.copper if isinstance(c, Track)]
            gaps = [poly_distance(t.polygon, v.polygon) for t in tails for v in vias if v.net != t.net]
            gaps += [poly_distance(t.polygon, u.polygon) for t in tails for u in tails if u.net != t.net]
            assert min(gaps, default=9.0) >= 0.2 - 1e-6, (pitch, width, order)


def test_a_pin_of_two_apart_lands_gets_its_tail_from_one_of_them():
    """The centre of two lands' union can be bare board between them: the
    search and the tail start from a land's own centre."""
    from placemat.board_geometry import Footprint
    from placemat.geometry import point_in_polygon
    from placemat.values import Box, Face
    from tests.fixtures import pad
    lands = (pad("J1", "j1", 1, "GND", 18.0, 20.0, 0.8, 0.8), pad("J1", "j1", 1, "GND", 19.8, 20.0, 0.8, 0.8),
             pad("J1", "j1", 2, "SIG", 18.9, 21.5, 0.6, 0.6))
    body = Box(17.4, 19.4, 20.4, 22.0)
    fp = Footprint("J1", "j1", None, "J1", Location(18.9, 20.7), 0.0, Face.FRONT, body, body.inflate(0.1), body,
                   lands)
    b = Board(board_geometry([fp], width=40, height=40), edge_margin=0.5)
    b.place(Part("j1"), at=Location(18.9, 20.7))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("j1"), 1)))
    plan = b.resolve()
    (tail,) = [c for c in plan.copper if isinstance(c, Track)]
    assert any(point_in_polygon((tail.start.x, tail.start.y), land.outlines[0]) for land in lands[:2])


def test_a_via_keeps_clear_of_tracks_declared_before_it_in_its_batch():
    """Tracks of one batch reach the occupancy only once the batch is
    planned: the search judges against those planned before it."""
    from placemat.geometry import poly_distance
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    for x in (19.45, 17.75):
        b.track(Net("V3"), [Location(x, 15.0), Location(x, 25.0)], layer=CopperLayer.F)
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")), why="tap")
    plan = b.resolve()
    (via,) = [c for c in plan.copper if isinstance(c, Via)]
    ours = [via] + _tails(plan)
    theirs = [c for c in plan.copper if isinstance(c, Track) and c.net == "V3"]
    assert theirs
    assert min(poly_distance(a.polygon, t.polygon) for a in ours for t in theirs) >= 0.2 - 1e-6


def test_a_tail_on_a_layer_its_pad_is_not_on_is_a_finding_and_no_via():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND"), layer=CopperLayer.B), why="tap")
    plan = b.resolve()
    assert not [c for c in plan.copper if isinstance(c, (Via, Track))]
    assert any("B.Cu" in f and "not on" in f for f in plan.findings)


def test_a_via_keeps_clear_of_an_earlier_tail_alone():
    """Only a tail of another net lies where the via would go: no via and no
    track, so the rule that moves it is the tail rule."""
    from placemat.geometry import poly_distance
    from placemat.layout import _CopperContext
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    plan = b.resolve()
    spot = FreeSpot(near=PadRef(Part("u1"), "SIG"))

    def search(tails):
        ctx = _CopperContext(b, plan.occupancy)
        ctx.plan = plan
        ctx.planned_tails = list(tails)
        return b._free_spot(ctx, spot, "SIG", 0.3, 0.6)
    alone, layer, width, start, _ = search([])
    tail = Track("GND", CopperLayer.F, 0.2, Location(alone.x - 0.1, alone.y - 1.5), Location(alone.x - 0.1, alone.y + 1.5))
    moved, _, _, _, path = search([tail])
    assert poly_distance(Via("SIG", moved, 0.3, 0.6).polygon, tail.polygon) >= 0.2 - 1e-6
    for a, c in zip(path, path[1:]):                  # every leg of its own tail
        assert poly_distance(Track("SIG", layer, width, a, c).polygon, tail.polygon) >= 0.2 - 1e-6


def test_a_via_keeps_clear_of_an_unplated_hole():
    """A connector's locating peg is a hole with no copper: the via keeps the
    hole-to-hole rule from it and its copper the hole clearance."""
    import dataclasses
    from placemat.geometry import poly_distance
    b0 = _board()
    b0.place(Part("u1"), at=Location(20, 20))
    b0.place(Part("r1"), at=Location(20, 26))
    b0.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")), why="tap")
    (alone,) = [c for c in b0.resolve().copper if isinstance(c, Via)]
    g = _board().geometry
    u1 = g.footprint("u1")
    pegged = dataclasses.replace(u1, npth=((alone.at, 1.0),))
    g = dataclasses.replace(g, footprints=tuple(pegged if f.ref == "U1" else f for f in g.footprints),
                            hole_clearance=0.25)
    b = Board(g, edge_margin=0.5)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 26))
    b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")), why="tap")
    (via,) = [c for c in b.resolve().copper if isinstance(c, Via)]
    gap = via.at.distance(alone.at) - 1.0 / 2.0
    assert gap - via.drill / 2.0 >= g.hole_to_hole - 1e-6
    assert gap - via.size / 2.0 >= 0.25 - 1e-6


def test_a_free_spot_tail_runs_at_0_45_or_90_degrees():
    """The tail from a pad to its via is drawn the way board.track() draws a
    leg: at 0, 45 or 90 degrees, a 45 and a straight where the spot is off
    both, not one leg at whatever angle the spot lies."""
    import math
    for pitch, width in ((0.4, 0.2), (0.5, 0.25), (0.65, 0.3)):
        b = Board(_pin_row(pitch, width), edge_margin=0.5)
        b.place(Part("u1"), at=Location(20, 21.5))
        for i in (5, 6, 7):
            b.via(Net("N%d" % i), at=FreeSpot(near=PadRef(Part("u1"), i + 1)))
        plan = b.resolve()
        tails = [c for c in plan.copper if isinstance(c, Track)]
        assert tails
        for t in tails:
            a = math.degrees(math.atan2(t.end.y - t.start.y, t.end.x - t.start.x)) % 45.0
            assert min(a, 45.0 - a) < 0.01, (pitch, t)
