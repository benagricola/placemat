"""A module's via on an escape lane is only needed when the lane is walled in within the module. A lane that can still
reach the frame's edge on its own layer without the via ends as a stub there, and the parent board's router decides
whether it changes layer: a via there is the finding `escape.via_unneeded`, in a module run only (a frame that is not
drawn). A via of a plane net is no escape and is no finding."""
from placemat.findings import FindingCause as C
from placemat.values import CopperLayer, Edge, Location, Net, Part
from tests.escape_fixtures import PD_NETS, board_with, qfn

F, B = CopperLayer.F, CopperLayer.B
SIZE = 16.0


def _module(nets=PD_NETS, draw=False, extra=()):
    """The QFN-32 at the middle of a 16 mm frame, its north row's pins 32, 31 and 30 escaping west."""
    b = board_with([qfn(cx=SIZE / 2, cy=SIZE / 2, nets=nets)], width=SIZE, height=SIZE, keep_going=True,
                   nets=("Z",) + tuple(extra))
    b.rect(SIZE, SIZE, draw=draw)
    b.place(Part("pd"), at=Location(SIZE / 2, SIZE / 2))
    return b


def _stubs(b, esc, nets, skip=()):
    for n, net in nets.items():
        if n not in skip:
            b.track(Net(net), [esc[n]], layer=F)


def _unneeded(plan):
    return [f for f in plan.findings if f.cause is C.ESCAPE_VIA_UNNEEDED]


def _wall(b):
    """A ring of another net's track on the component face round the chip and its lanes, a few mm off them."""
    ring = [Location(3.5, 2.5), Location(13.0, 2.5), Location(13.0, 13.5), Location(3.5, 13.5), Location(3.5, 2.5)]
    b.track(Net("Z"), ring, layer=F, width=0.2, why="a wall round the chip")


def test_a_lane_via_whose_lane_reaches_the_frame_edge_is_a_finding():
    b = _module()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31], why="north row")
    _stubs(b, esc, PD_NETS)
    plan = b.resolve()
    (f,) = _unneeded(plan)
    assert f.severity == "warning"
    assert (f.facts["ref"], f.facts["part"], f.facts["pin"], f.facts["net"]) == ("U1", "pd", "31", "SENSE")
    assert f.facts["via"]["kind"] == "lane"
    assert f.facts["layers"] == ["F.Cu"]
    assert "U1 pin 31 (SENSE)" in f and "vias=" in f


def test_the_lane_via_finding_suggests_taking_the_pin_out_of_vias():
    b = _module()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31], why="north row")
    _stubs(b, esc, PD_NETS)
    (f,) = _unneeded(b.resolve())
    (s,) = f.suggestions
    assert s.lever == "vias"
    (e,) = s.edits
    assert (e.op, e.target.kind, e.args["arg"], e.args["action"], e.value) == ("edit_list", "escape", "vias", "remove",
                                                                               {"num": 31})


def test_a_board_via_that_a_track_from_a_lane_ends_on_is_a_finding():
    b = _module()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, why="north row")
    _stubs(b, esc, PD_NETS, skip=(30,))
    via = b.via(Net("PGOOD"), Location(5.0, 3.75), why="past the lane's end")
    b.track(Net("PGOOD"), [esc[30], via], layer=F)
    (f,) = _unneeded(b.resolve())
    assert (f.facts["pin"], f.facts["net"], f.facts["via"]["kind"]) == ("30", "PGOOD", "via")
    assert f.facts["via"]["at"] == [5.0, 3.75]
    assert f.facts["via"]["key"].startswith("via PGOOD#")


def test_a_board_via_at_a_lanes_end_is_a_finding_that_suggests_removing_it():
    b = _module()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, why="north row")
    _stubs(b, esc, PD_NETS)
    b.via(Net("PGOOD"), esc[30].end, why="the lane's end")
    (f,) = _unneeded(b.resolve())
    assert (f.facts["pin"], f.facts["via"]["kind"]) == ("30", "via")
    (s,) = f.suggestions
    (e,) = s.edits
    assert (s.lever, e.op, e.target.kind, e.target.key) == ("via", "remove_statement", "via", f.facts["via"]["key"])


def test_a_lane_walled_in_within_the_module_keeps_its_via():
    b = _module()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31], why="north row")
    _stubs(b, esc, PD_NETS)
    _wall(b)
    assert _unneeded(b.resolve()) == []


def test_a_plane_nets_via_on_a_lane_is_no_finding():
    nets = {**PD_NETS, 31: "GND"}
    b = _module(nets)
    b.plane(Net("GND"), [B], why="the ground plane")
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31], why="north row")
    _stubs(b, esc, nets)
    assert _unneeded(b.resolve()) == []


def test_a_drawn_board_is_not_a_module_and_has_no_such_finding():
    b = _module(draw=True)
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31], why="north row")
    _stubs(b, esc, PD_NETS)
    assert _unneeded(b.resolve()) == []


def test_a_ground_via_in_a_pad_is_no_finding():
    nets = {**PD_NETS, 1: "GND"}
    b = _module(nets)
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, why="north row")
    _stubs(b, esc, PD_NETS)
    b.via(Net("GND"), Location(SIZE / 2 - 2.45, SIZE / 2 - 1.75), why="pin 1's ground drop")
    assert _unneeded(b.resolve()) == []
