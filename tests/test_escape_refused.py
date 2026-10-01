"""What board.escape() refuses, at its declaration and when the part is placed, and the finding for a lane
reserved and never drawn. Pure: synthetic boards."""
import pytest

from placemat import reuse
from placemat.settings import Settings
from placemat.values import Corner, CopperLayer, Edge, Location, Net, PadRef, Part
from tests.escape_fixtures import PD_NETS, board_with, pd_board, qfn

F = CopperLayer.F


def _board(**kw):
    b = board_with([qfn(nets={**PD_NETS, 8: "W8"}), qfn("U2", "other", 10, 10)], **kw)
    return b


def test_pins_of_another_part_are_refused():
    b = _board()
    with pytest.raises(ValueError, match="another part|pin of other"):
        b.escape(Part("pd"), [32, PadRef(Part("other"), 1)], why="x")


def test_pins_of_another_row_are_refused():
    b = _board()
    with pytest.raises(ValueError, match="not on pin 32's row"):
        b.escape(Part("pd"), [32, 8], why="x")                      # pin 8 is on the west row


def test_a_pin_named_twice_is_refused():
    b = _board()
    with pytest.raises(ValueError, match="named twice"):
        b.escape(Part("pd"), [32, 31, "VOUT"], why="x")             # VOUT is pin 32 again


def test_a_pin_the_part_does_not_have_is_refused():
    b = _board()
    with pytest.raises(KeyError):
        b.escape(Part("pd"), [32, 99], why="x")


def test_a_turn_along_the_row_s_axis_is_refused_at_declaration_when_the_rotation_is_known():
    b = _board()
    b.place(Part("pd"), at=Location(30, 30), rotation=0.0)
    with pytest.raises(ValueError, match="runs along the row's axis"):
        b.escape(Part("pd"), [32, 31], turn=Edge.NORTH, why="x")
    with pytest.raises(ValueError, match="turns back into the row"):
        b.escape(Part("pd"), [32, 31], turn=Corner.SW, why="x")      # a south corner on a north row


def test_a_turn_along_the_axis_is_refused_when_the_part_is_placed_if_it_was_not_known_before():
    b = _board()
    b.escape(Part("pd"), [32, 31], turn=Edge.NORTH, why="x")
    b.place(Part("pd"), at=Location(30, 30))
    with pytest.raises(ValueError, match="runs along the row's axis"):
        b.resolve()


def test_vias_widths_and_pairs_name_only_pins_the_escape_names():
    b = _board()
    with pytest.raises(ValueError, match="vias= names pin 30"):
        b.escape(Part("pd"), [32, 31], vias=[30], why="x")
    with pytest.raises(ValueError, match="widths= names pin 30"):
        b.escape(Part("pd"), [32, 31], widths={30: 0.3}, why="x")
    with pytest.raises(ValueError, match="pairs= names pin 30"):
        b.escape(Part("pd"), [32, 31], turn=Edge.WEST, pairs=[(31, 30)], why="x")


def test_a_pair_whose_lanes_are_not_neighbours_is_refused():
    b = _board()
    with pytest.raises(ValueError, match="not neighbours"):
        b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, pairs=[(32, 30)], why="x")


def test_a_pair_or_a_run_needs_a_turn():
    b = _board()
    with pytest.raises(ValueError, match="without turn="):
        b.escape(Part("pd"), [32, 31], pairs=[(32, 31)], why="x")
    with pytest.raises(ValueError, match="run= is how far"):
        b.escape(Part("pd"), [32, 31], run=1.0, why="x")


def test_a_run_or_a_depth_of_nothing_or_less_is_refused():
    b = _board()
    for kw in ({"run": 0.0}, {"run": -1.0}, {"depth": 0.0}, {"depth": -0.5}, {"via_size": 0.0}, {"via_drill": -0.1}):
        with pytest.raises(ValueError, match="more than 0"):
            b.escape(Part("pd"), [32, 31], turn=Edge.WEST, why="x", **kw)


def test_a_negative_chamfer_is_refused_and_none_is_allowed():
    b = _board()
    with pytest.raises(ValueError, match="chamfer= is 0 or more"):
        b.escape(Part("pd"), [32, 31], turn=Edge.WEST, chamfer=-0.1, why="x")
    b.escape(Part("pd"), [32, 31], turn=Edge.WEST, chamfer=0.0, why="square")


def test_a_turn_that_is_neither_an_edge_nor_a_corner_is_refused():
    b = board_with([qfn(nets={32: "VOUT"})])
    with pytest.raises(TypeError, match="Edge across the row or a Corner"):
        b.escape(Part("pd"), [32], turn="west", why="x")


def test_a_via_with_no_legal_spot_is_refused_naming_what_stands_in_the_way():
    b = pd_board(settings=Settings(place_escape_via_reach=0.1))      # a second via needs 0.38 mm along its lane
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="x")
    for pin, net in ((32, "VOUT"), (31, "SENSE"), (30, "PGOOD")):
        b.track(Net(net), [esc[pin]], layer=F, why="its lane")
    with pytest.raises(ValueError, match="pin 30's via has no legal spot.*the via of pin 31"):
        b.resolve()


def test_a_lane_reserved_and_never_drawn_is_a_finding():
    b = pd_board()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="x")
    b.track(Net("VOUT"), [esc[32]], layer=F, why="its lane")
    plan = b.resolve()
    never = [f for f in plan.findings if "no track begins with it" in f]
    assert sorted(f.split(" ")[2].rstrip(":") for f in never) == ["30", "31"]
    assert {f.kind for f in never} == {"setup"}
    assert not [v for v in plan.copper if type(v).__name__ == "Via"]     # a via nobody asked for is not drawn


def test_a_script_without_an_escape_digests_as_before():
    b = pd_board()
    plain = reuse.context_key(b)
    b.escape(Part("pd"), [32], why="x")
    assert reuse.context_key(b) != plain
    assert reuse.context_key(pd_board()) == plain
