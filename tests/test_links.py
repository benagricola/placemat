"""Links price the search: a part is pulled toward the pads it connects to,
by the weight of each connection, and a SHORT link with a limit is a bound."""
import pytest

from placemat.layout import Board
from placemat.values import Near, CopperLayer, LinkWeight, Location, Net, Part, PadRef
from tests.fixtures import board_geometry, footprint


def make_board():
    fps = [footprint("U1", 10, 10, w=6, h=2, inst="u1", nets=("VIN", "OUT")),      # pads at 7.6 and 12.4
           footprint("C1", 40, 40, inst="c1", nets=("VIN", "GND")),
           footprint("R1", 40, 45, inst="r1", nets=("OUT", "ENDSTOP")),
           footprint("J1", 45, 10, w=4, h=4, inst="j1", nets=("ENDSTOP", "GND"))]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)


def test_link_weights_are_enums_or_integers_and_zero_means_ignored():
    assert LinkWeight.SHORT > LinkWeight.PREFER > LinkWeight.DEFAULT > LinkWeight.FREE
    assert int(LinkWeight.FREE) == 0
    b = make_board()
    b.link(PadRef(Part("c1"), "VIN"), PadRef(Part("u1"), "VIN"), weight=LinkWeight.SHORT, limit_mm=2.0)
    b.link(PadRef(Part("r1"), "OUT"), PadRef(Part("u1"), "OUT"), weight=3)
    with pytest.raises(KeyError):
        b.link(PadRef(Part("c1"), "NOPE"), PadRef(Part("u1"), "VIN"))
    with pytest.raises(ValueError):
        b.link(PadRef(Part("c1"), "VIN"), PadRef(Part("u1"), "VIN"), weight=-1)


def test_a_searched_part_is_seeded_where_its_nets_already_are(monkeypatch):
    b = make_board()
    b.place(Part("u1"), at=Location(20, 30))
    seeds = []
    original_seed = b._seed_hint
    def observed(item, occ, targets, rotation, face):
        hint = original_seed(item, occ, targets, rotation, face)
        if item.inst == "c1":
            pads = occ.candidate_pad_locations(item, hint)
            seeds.append((pads[("C1", "1")], occ.pad_location("U1", "1")))
        return hint
    monkeypatch.setattr(b, "_seed_hint", observed)
    b.place(Part("c1"))                     # no hint: seed on the shared VIN pad
    plan = b.resolve()
    c1 = plan.box("c1")
    u1_vin = plan.occupancy.pad_location("U1", "1")
    assert seeds and all(a.distance(b) < 0.001 for a, b in seeds)
    assert "seeded" in plan.step("c1").note


def test_a_short_link_pulls_harder_than_the_default_and_its_limit_is_reported():
    b = make_board()
    b.place(Part("u1"), at=Location(30, 30))
    b.place(Part("j1"), at=Location(30, 50))
    b.link(PadRef(Part("r1"), "OUT"), PadRef(Part("u1"), "OUT"), weight=LinkWeight.SHORT, limit_mm=3.0)
    b.link(PadRef(Part("r1"), "ENDSTOP"), PadRef(Part("j1"), "ENDSTOP"), weight=LinkWeight.FREE,
           why="the endstop cable is metres; the board run does not matter")
    b.place(Part("r1"), radius=12.0, step=0.5)
    plan = b.resolve()
    r1_out = plan.occupancy.pad_location("R1", "1")
    u1_out = plan.occupancy.pad_location("U1", "2")
    distance = r1_out.distance(u1_out)
    link = plan.links[0]
    assert link.achieved_mm == pytest.approx(distance, abs=0.0005)
    assert link.within_limit == (link.achieved_mm <= 3.0)
    from placemat import score
    terms = score.whole(b, plan.occupancy, plan)
    assert terms['link_over'] == pytest.approx(b.settings.score_link_over * int(link.weight) * max(0.0, distance - 3.0))
    if not link.within_limit:
        assert any('link' in str(f) and 'limit' in str(f) for f in plan.findings)


def test_a_short_link_over_its_limit_is_a_finding():
    b = make_board()
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("c1"), at=Location(50, 50))                  # fixed far away
    b.link(PadRef(Part("c1"), "VIN"), PadRef(Part("u1"), "VIN"), weight=LinkWeight.SHORT, limit_mm=2.0,
           why="bypass at the pin")
    plan = b.resolve()
    assert any("bypass at the pin" in f and "limit" in f for f in plan.findings)


def test_a_free_net_never_pulls():
    b = make_board()
    b.free_net(Net("ENDSTOP"))
    b.place(Part("j1"), at=Location(50, 10))
    b.place(Part("u1"), at=Location(10, 50))
    b.place(Part("r1"), radius=10.0, step=0.5)          # OUT pulls toward U1; ENDSTOP is free
    plan = b.resolve()
    r1 = plan.box("r1").center
    assert r1.distance(Location(10, 50)) < r1.distance(Location(50, 10))


def test_the_search_keeps_the_best_scoring_legal_candidate_not_the_first():
    b = make_board()
    b.place(Part("u1"), at=Location(30, 30))
    b.place(Part("c1"), at=Near(Location(30, 40), radius=6.0, step=0.5))   # a hint 10 mm south of the pin it serves
    plan = b.resolve()
    c1_vin = plan.occupancy.pad_location("C1", "1")
    u1_vin = plan.occupancy.pad_location("U1", "1")
    # Wire distance alone no longer defines the optimum. Compare the complete
    # physical objective at the legal hint, preserving the final board context.
    from dataclasses import replace
    from placemat import score
    from placemat.escapes import judging
    occ = plan.occupancy
    item = b.geometry.footprint("c1")
    chosen = occ.items["C1"].reference
    actual = (judging(occ).counts()['escape_walled'], sum(score.whole(b, occ, plan).values()))
    try:
        occ.lift(["C1"])
        hint = replace(chosen, location=Location(30, 40))
        assert occ.legal(item, hint, b.clearance) is None
        occ.commit(item, hint)
        hinted = (judging(occ).counts()['escape_walled'], sum(score.whole(b, occ, plan).values()))
    finally:
        occ.lift(["C1"])
        occ.commit(item, chosen)
    assert actual < hinted


def _plane_board():
    """U1 and C1 share only V3V3, which the script also declares as a plane."""
    fps = [footprint("U1", 10, 10, w=6, h=2, inst="u1", nets=("V3V3", "SDA")),
           footprint("C1", 50, 50, inst="c1", nets=("V3V3", "GND")),
           footprint("R1", 50, 40, inst="r1", nets=("SDA", "GND"))]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)


def test_a_declared_link_pulls_even_when_its_net_is_a_plane():
    """Two parts whose only shared net is a plane, and a script that says they
    belong together with `board.link`, were getting a measured finding and no
    behaviour: the link reported 54 mm over its 2 mm limit while contributing
    nothing to where the part went."""
    b = _plane_board()
    b.plane(Net("V3V3"), [CopperLayer.B])
    b.place(Part("u1"), at=Location(20, 30))
    b.link(PadRef(Part("c1"), "V3V3"), PadRef(Part("u1"), "V3V3"),
           weight=LinkWeight.SHORT, limit_mm=2.0)
    b.place(Part("c1"))
    plan = b.resolve()
    u1_v3v3 = plan.occupancy.pad_location("U1", "1")
    assert plan.box("c1").center.distance(u1_v3v3) < 5.0
    assert "seeded" in plan.step("c1").note


def test_a_planes_automatic_connections_still_do_not_pull():
    """The reason planes are excluded holds for everything nobody declared: a
    net with two hundred pads gives a centroid that means nothing."""
    b = _plane_board()
    b.plane(Net("V3V3"), [CopperLayer.B])
    b.place(Part("u1"), at=Location(20, 30))
    b.place(Part("c1"))                      # no link declared
    plan = b.resolve()
    assert "nothing it connects to is placed" in plan.step("c1").note


def test_the_declared_link_between_two_pads_is_the_first_declared_either_way_round():
    from placemat.values import LinkWeight, PadRef, Part
    fps = [footprint("U1", 10, 10, inst="u1", nets=("A", "B")), footprint("U2", 20, 10, inst="u2", nets=("A", "C"))]
    b = Board(board_geometry(fps, width=40, height=30))
    first = b.link(PadRef(Part("u1"), 1), PadRef(Part("u2"), 1), weight=LinkWeight.SHORT)
    b.link(PadRef(Part("u2"), 1), PadRef(Part("u1"), 1), weight=LinkWeight.PREFER)
    assert b._declared_link(("U2", "1"), ("U1", "1")) is first
    assert b._declared_link(("U1", "2"), ("U2", "1")) is None
    later = b.link(PadRef(Part("u1"), 2), PadRef(Part("u2"), 2))
    assert b._declared_link(("U2", "2"), ("U1", "2")) is later
