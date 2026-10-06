"""The keys that say whether a step can be replayed from the previous run."""
import dataclasses

from placemat import reuse
from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import LinkWeight, Location, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board(**settings):
    fps = [footprint("J1", 5, 10, inst="j1", nets=("A", "GND")),
           footprint("R1", 20, 10, inst="r1", nets=("A", "B")),
           footprint("R2", 30, 12, inst="r2", nets=("B", "C")),
           footprint("R3", 35, 5, inst="r3", nets=("C", "D"))]
    b = Board(board_geometry(fps, width=40, height=20), edge_margin=0.5,
              settings=dataclasses.replace(Settings(), **settings))
    b.place(Part("j1"), at=Location(5, 10))
    return b


def _declare(b, r2_radius=3.0):
    b.place(Part("r1"))
    b.place(Part("r2"), radius=r2_radius)
    b.place(Part("r3"))
    return b


def _keys(b):
    ctx = reuse.context_key(b, "extra")
    out, prev = [], ctx
    for i in b._intents:
        prev = reuse.step_key(prev, i, reuse.links_on(b, i))
        out.append(prev)
    return ctx, out


def test_the_same_board_gives_the_same_keys():
    assert _keys(_declare(_board())) == _keys(_declare(_board()))


def test_a_global_change_changes_the_context():
    base = _keys(_declare(_board()))[0]
    b = _declare(_board())
    b.keepout(Circle(2.0), "clear", at=Location(10, 5), why="a clearance")
    assert _keys(b)[0] != base
    assert _keys(_declare(_board(place_step=0.1)))[0] != base
    assert reuse.context_key(_declare(_board()), "other extra") != base


def test_one_items_change_changes_its_key_and_every_later_one_only():
    a = _keys(_declare(_board()))[1]
    b = _keys(_declare(_board(), r2_radius=5.0))[1]
    assert a[:2] == b[:2] and a[2] != b[2] and a[3] != b[3]


def test_a_link_changes_the_keys_of_the_items_it_joins_only():
    def with_link(target):
        b = _declare(_board())
        b.link(PadRef(Part(target), 2), PadRef(Part("r3"), 1), weight=LinkWeight.SHORT)
        return _keys(b)
    base = _keys(_declare(_board()))
    linked = with_link("r2")
    assert linked[0] == base[0]
    assert linked[1][:2] == base[1][:2] and linked[1][2] != base[1][2]


def test_with_the_solve_on_any_placement_change_changes_the_context():
    a = _keys(_declare(_board(solve_enabled=True)))[0]
    b = _keys(_declare(_board(solve_enabled=True), r2_radius=5.0))[0]
    assert a != b


def test_a_step_and_its_placement_round_trip_through_json():
    import json
    from placemat.layout import Step
    from placemat.placement import Placement
    from placemat.values import Face, Freedom, Priority
    s = Step("r1", "part", Priority.DEFAULT, Placement(Location(1.25, 2.0 / 3.0), 90.0, Face.BACK), 0.1 + 0.2,
             ({"kind": "slid", "mm": 0.5, "units": "mm"},), "why", 0, Freedom.SEARCHED, 3, 7, unplaced=({"form": "no_pocket"},))
    assert reuse.step_from_json(json.loads(json.dumps(reuse.step_to_json(s)))) == s
    empty = Step("x", "part", None)
    assert reuse.step_from_json(json.loads(json.dumps(reuse.step_to_json(empty)))) == empty


def test_an_object_without_a_readable_form_does_not_make_every_run_different():
    a, b = reuse.canonical(object()), reuse.canonical(object())
    assert a == b and "0x" not in a


def test_a_setting_that_cannot_change_a_placement_leaves_the_context_alone():
    base = _keys(_declare(_board()))[0]
    assert _keys(_declare(_board(preview_px_per_mm=80.0, timeout_render=10)))[0] == base
    assert _keys(_declare(_board(place_radius=4.0)))[0] != base


# ------------------------------------------------------------ copper as declared
def _copper(b, width=0.25, via_at=None, past_edge=None):
    from placemat.values import CopperLayer, Edge, FreeSpot, Net, Past
    b.track(Net("A"), [PadRef(Part("j1"), 1), PadRef(Part("r1"), 1)], layer=CopperLayer.F, width=width, why="joins A")
    b.via(Net("GND"), via_at if via_at is not None else FreeSpot(PadRef(Part("j1"), 2)))
    b.via(Net("C"), Past([PadRef(Part("r3"), 1)], past_edge or Edge.EAST))
    return b


def test_a_copper_declarations_arguments_change_the_context():
    from placemat.values import Edge, FreeSpot
    base = _keys(_copper(_declare(_board())))[0]
    assert _keys(_copper(_declare(_board())))[0] == base
    assert _keys(_copper(_declare(_board()), width=0.4))[0] != base
    assert _keys(_copper(_declare(_board()), via_at=Location(12, 3)))[0] != base
    assert _keys(_copper(_declare(_board()), via_at=FreeSpot(PadRef(Part("j1"), 2), radius=3.0)))[0] != base
    assert _keys(_copper(_declare(_board()), past_edge=Edge.WEST))[0] != base


def test_a_copper_value_that_resolves_later_is_digested_as_declared():
    """A FreeSpot or a Past is the form the script wrote, not the point it resolves to: the same
    declaration digests the same before and after a resolve."""
    b = _copper(_declare(_board()))
    before = reuse.context_key(b, "extra")
    b.resolve()
    assert reuse.context_key(_copper(_declare(_board())), "extra") == before
    assert all("function()" not in c.form for c in b._copper)
