"""Lanes: a bus run down a board at a fixed x, tapping pads at their own y.
A tap that would cross another same-layer lane hops to the far layer round
it; the hop is derived from the registered lanes, never typed."""
from placemat.board import Board
from placemat.copper import Track, Via
from placemat.values import CopperLayer, Location, Net, Part, PadRef
from tests.fixtures import footprint, snapshot


def make_board():
    fps = [footprint("H1", 10, 30, inst="h1", nets=("CANH", "CANH_S0")),
           footprint("H2", 10, 60, inst="h2", nets=("CANH_S0", "CANH_S1")),
           footprint("H3", 10, 90, inst="h3", nets=("PERMIT_B", "X"))]
    return Board(snapshot(fps, width=100, height=120, extra_nets=("V48P",)), edge_margin=1.0)


def test_a_lane_tap_is_a_straight_track_at_the_pads_own_y():
    b = make_board()
    lane = b.lane(Net("CANH_S0"), x=30.0, layer=CopperLayer.F, width=0.3)
    lane.hop(PadRef(Part("h1"), "CANH_S0"), PadRef(Part("h2"), "CANH_S0"))
    plan = b.resolve()
    tracks = [o for o in plan.copper if isinstance(o, Track)]
    assert len(tracks) == 3          # tap, run, tap
    ys = sorted({t.start.y for t in tracks} | {t.end.y for t in tracks})
    assert ys == [30.0, 60.0]
    run = [t for t in tracks if t.start.x == t.end.x == 30.0][0]
    assert {run.start.y, run.end.y} == {30.0, 60.0}
    assert not [o for o in plan.copper if isinstance(o, Via)]


def test_a_tap_across_another_same_layer_lane_bridges_on_the_far_layer():
    b = make_board()
    inner = b.lane(Net("PERMIT_B"), x=20.0, layer=CopperLayer.F, width=0.3)    # between the pads and the outer lane
    inner.run(0.0, 120.0)
    outer = b.lane(Net("CANH_S0"), x=30.0, layer=CopperLayer.F, width=0.3)
    outer.tap(PadRef(Part("h1"), "CANH_S0"))
    plan = b.resolve()
    vias = [o for o in plan.copper if isinstance(o, Via) and o.net == "CANH_S0"]
    bridge = [o for o in plan.copper if isinstance(o, Track) and o.net == "CANH_S0" and o.layer is CopperLayer.B]
    assert len(vias) == 2 and len(bridge) == 1
    xs = sorted(v.at.x for v in vias)
    assert xs[0] < 20.0 < xs[1]           # the bridge straddles the crossed lane
    assert all(v.at.y == 30.0 for v in vias)


def test_a_lane_on_the_other_layer_is_not_crossed():
    b = make_board()
    other = b.lane(Net("PERMIT_B"), x=20.0, layer=CopperLayer.B, width=0.3)
    other.run(0.0, 120.0)
    outer = b.lane(Net("CANH_S0"), x=30.0, layer=CopperLayer.F, width=0.3)
    outer.tap(PadRef(Part("h1"), "CANH_S0"))
    plan = b.resolve()
    assert not [o for o in plan.copper if isinstance(o, Via) and o.net == "CANH_S0"]


def test_a_chain_taps_each_pad_once():
    b = make_board()
    lane = b.lane(Net("CANH_S0"), x=30.0, layer=CopperLayer.F, width=0.3)
    lane.chain([PadRef(Part("h1"), "CANH_S0"), PadRef(Part("h2"), "CANH_S0")])
    plan = b.resolve()
    taps = [o for o in plan.copper if isinstance(o, Track) and o.start.y == o.end.y]
    assert len(taps) == 2


def test_a_crossing_joins_two_lanes_at_a_y_and_bridges_lanes_it_passes():
    b = make_board()
    left = b.lane(Net("CANH_S0"), x=30.0, layer=CopperLayer.F, width=0.3)
    right = b.lane(Net("CANH_S0"), x=70.0, layer=CopperLayer.F, width=0.3)
    mid = b.lane(Net("PERMIT_B"), x=50.0, layer=CopperLayer.F, width=0.3)
    mid.run(0.0, 120.0)
    left.cross_to(right, y=110.0)
    plan = b.resolve()
    vias = [o for o in plan.copper if isinstance(o, Via) and o.net == "CANH_S0"]
    assert len(vias) == 2 and all(v.at.y == 110.0 for v in vias)


def test_a_finger_is_notched_round_same_layer_lanes_and_bridged():
    from placemat.copper import Pour
    b = make_board()
    lane = b.lane(Net("PERMIT_B"), x=50.0, layer=CopperLayer.F, width=0.3)
    lane.run(0.0, 120.0)
    b.finger(Net("V48P"), layer=CopperLayer.F, y_lo=40.0, y_hi=46.0, x_from=60.0, x_to=20.0)
    plan = b.resolve()
    pours = [o for o in plan.copper if isinstance(o, Pour)]
    vias = [o for o in plan.copper if isinstance(o, Via) and o.net == "V48P"]
    bridges = [o for o in plan.copper if isinstance(o, Track) and o.net == "V48P" and o.layer is CopperLayer.B]
    assert len(pours) == 2 and len(vias) == 2 and len(bridges) == 1
    xs = sorted(x for p in pours for x, _ in p.points)
    assert 50.0 not in xs and any(48 < x < 50 for x in xs) and any(50 < x < 52 for x in xs)
