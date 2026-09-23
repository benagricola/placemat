"""Where two tracks of different nets cross on one layer, priority decides
which passes under, never the order they were declared in."""
from placemat.layout import Board
from placemat.copper import Pour, Track, Via
from placemat.values import CopperLayer, Location, Net, Part, PadRef, Priority, X, Y
from tests.fixtures import board_geometry, footprint, declared_findings

F, B = CopperLayer.F, CopperLayer.B


def make_board():
    fps = [footprint("H1", 10, 30, inst="h1", nets=("CANH", "CANH_S0")),
           footprint("H2", 10, 60, inst="h2", nets=("CANH_S0", "CANH_S1")),
           footprint("H3", 10, 90, inst="h3", nets=("PERMIT_B", "X"))]
    return Board(board_geometry(fps, width=100, height=120, extra_nets=("V48P",)), edge_margin=1.0)


def vias(plan, net):
    return [o for o in plan.copper if isinstance(o, Via) and o.net == net]


def far_pieces(plan, net):
    return [o for o in plan.copper if isinstance(o, Track) and o.net == net and o.layer is B]


def test_a_track_allowed_to_bridge_passes_under_the_one_it_crosses():
    b = make_board()
    b.track(Net("PERMIT_B"), [(20.0, 0.0), (20.0, 120.0)], layer=F)
    b.track(Net("CANH_S0"), [(40.0, 30.0), (12.0, 30.0)], layer=F, bridge=True)
    plan = b.resolve()
    assert len(vias(plan, "CANH_S0")) == 2 and len(far_pieces(plan, "CANH_S0")) == 1
    xs = sorted(v.at.x for v in vias(plan, "CANH_S0"))
    assert xs[0] < 20.0 < xs[1] and all(v.at.y == 30.0 for v in vias(plan, "CANH_S0"))
    assert not vias(plan, "PERMIT_B")
    assert not declared_findings(plan)


def test_declaration_order_does_not_change_the_result():
    def run(first_vertical):
        b = make_board()
        if first_vertical:
            b.track(Net("PERMIT_B"), [(20.0, 0.0), (20.0, 120.0)], layer=F)
            b.track(Net("CANH_S0"), [(40.0, 30.0), (12.0, 30.0)], layer=F, bridge=True)
        else:
            b.track(Net("CANH_S0"), [(40.0, 30.0), (12.0, 30.0)], layer=F, bridge=True)
            b.track(Net("PERMIT_B"), [(20.0, 0.0), (20.0, 120.0)], layer=F)
        return sorted(repr(o) for o in b.resolve().copper)
    assert run(True) == run(False)


def test_a_crossing_nobody_may_bridge_is_a_finding_and_both_are_drawn():
    b = make_board()
    b.track(Net("PERMIT_B"), [(20.0, 0.0), (20.0, 120.0)], layer=F)
    b.track(Net("CANH_S0"), [(40.0, 30.0), (12.0, 30.0)], layer=F)
    plan = b.resolve()
    assert not vias(plan, "CANH_S0") and not vias(plan, "PERMIT_B")
    assert any("PERMIT_B" in f and "CANH_S0" in f and "cross" in f for f in plan.findings)
    assert len([o for o in plan.copper if isinstance(o, Track)]) == 2


def test_the_lower_priority_track_yields_when_both_may_bridge():
    b = make_board()
    b.track(Net("PERMIT_B"), [(20.0, 0.0), (20.0, 40.0)], layer=F, bridge=True, priority=Priority.HIGH)
    b.track(Net("CANH_S0"), [(40.0, 30.0), (12.0, 30.0)], layer=F, bridge=True)      # DEFAULT, longer
    plan = b.resolve()
    assert len(vias(plan, "CANH_S0")) == 2 and not vias(plan, "PERMIT_B")


def test_at_equal_priority_the_shorter_track_yields():
    b = make_board()
    b.track(Net("PERMIT_B"), [(20.0, 0.0), (20.0, 120.0)], layer=F, bridge=True)    # 120 long
    b.track(Net("CANH_S0"), [(40.0, 30.0), (12.0, 30.0)], layer=F, bridge=True)      # 35 long
    plan = b.resolve()
    assert len(vias(plan, "CANH_S0")) == 2 and not vias(plan, "PERMIT_B")
    assert any("shorter" in s.note for s in plan.steps if s.kind == "copper")


def test_fixed_copper_never_yields():
    b = make_board()
    b.track(Net("PERMIT_B"), [(20.0, 0.0), (20.0, 40.0)], layer=F, bridge=True, priority=Priority.HIGH)
    b.track(Net("CANH_S0"), [(40.0, 30.0), (12.0, 30.0)], layer=F, bridge=True, priority=Priority.HIGH)
    plan = b.resolve()
    assert len(vias(plan, "CANH_S0")) == 2 and not vias(plan, "PERMIT_B")


def test_a_track_crossing_two_others_gets_two_bridges():
    b = make_board()
    b.track(Net("PERMIT_B"), [(20.0, 0.0), (20.0, 120.0)], layer=F)
    b.track(Net("X"), [(30.0, 0.0), (30.0, 120.0)], layer=F)
    b.track(Net("CANH_S0"), [(40.0, 30.0), (12.0, 30.0)], layer=F, bridge=True)
    plan = b.resolve()
    assert len(vias(plan, "CANH_S0")) == 4 and len(far_pieces(plan, "CANH_S0")) == 2


def test_tracks_on_different_layers_or_the_same_net_do_not_bridge():
    b = make_board()
    b.track(Net("PERMIT_B"), [(20.0, 0.0), (20.0, 120.0)], layer=B)
    b.track(Net("CANH_S0"), [(25.0, 0.0), (25.0, 120.0)], layer=F)
    b.track(Net("CANH_S0"), [(40.0, 30.0), (12.0, 30.0)], layer=F, bridge=True)
    plan = b.resolve()
    assert not vias(plan, "CANH_S0") and not declared_findings(plan)


def test_pad_referenced_points_make_a_bus_without_a_lane_object():
    b = make_board()
    h1, h2 = PadRef(Part("h1"), "CANH_S0"), PadRef(Part("h2"), "CANH_S0")
    b.track(Net("CANH_S0"), [(30.0, Y(h1)), (30.0, Y(h2))], layer=F)            # the vertical line
    b.track(Net("CANH_S0"), [h1, (30.0, Y(h1))], layer=F, bridge=True)          # the taps
    b.track(Net("CANH_S0"), [h2, (30.0, Y(h2))], layer=F, bridge=True)
    plan = b.resolve()
    tracks = [o for o in plan.copper if isinstance(o, Track)]
    assert len(tracks) == 3
    vertical = [t for t in tracks if t.start.x == t.end.x == 30.0][0]
    assert {vertical.start.y, vertical.end.y} == {30.0, 60.0}


def test_a_finger_is_cut_and_bridged_where_a_track_crosses_it():
    b = make_board()
    b.track(Net("PERMIT_B"), [(50.0, 0.0), (50.0, 120.0)], layer=F)
    b.finger(Net("V48P"), layer=F, from_=Location(60.0, 43.0), to=Location(20.0, 43.0), width=6.0)
    plan = b.resolve()
    pours = [o for o in plan.copper if isinstance(o, Pour)]
    assert len(pours) == 2 and len(vias(plan, "V48P")) == 2 and len(far_pieces(plan, "V48P")) == 1
    xs = sorted(x for p in pours for x, _ in p.points)
    assert 50.0 not in xs and any(48 < x < 50 for x in xs) and any(50 < x < 52 for x in xs)
