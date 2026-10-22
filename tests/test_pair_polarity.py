"""A differential pair's two halves joining the same two parts cross as the router judges a coupled pair's polarity
(KiCadRoutingTools py_router/diff_pair_routing.py `_detect_polarity`): P's side of the way out where the pair leaves
one part against its side of the way in where it arrives at the other. Their airwires crossing as chords says nothing:
two parts whose pair pins face the same way have chords that cross on a pair the router couples without a swap."""
import dataclasses
import math
import random

import pytest

from placemat import score
from placemat.board_geometry import NetClass
from placemat.findings import FindingCause as C
from placemat.layout import Board
from placemat.ratsnest import Anchor, Edge, pair_crossed, pair_sides
from placemat.values import Face, Location, Part
from tests.fixtures import board_geometry
from tests.pinmap_boards import quad_footprint, settings

PAIR = NetClass("USB", 0.2, 0.2, 0.6, 0.3, diff_pair_width=0.15, diff_pair_gap=0.15)


def _part(ref, x, y, north=("", ""), south=("", "")):
    """A part with two pins on each side, `north` and `south` west to east: its pins' way out is their side's."""
    return quad_footprint(ref, x, y, {"N": list(north), "S": list(south), "E": ["", ""], "W": ["", ""]})


def _geometry(*parts):
    g = board_geometry(list(parts))
    return dataclasses.replace(g, netclasses={**g.netclasses, "DP": PAIR, "DN": PAIR})


def _board(*parts, back=()):
    g = _geometry(*parts)
    board = Board(g, keep_going=True, settings=settings(cleanup_enabled=False))
    board.pin_study = False
    board.rect(width=40, height=40)
    for fp in g.footprints:
        board.place(Part(fp.inst), at=fp.location, rotations=(0,), face=Face.BACK if fp.ref in back else Face.FRONT)
    return board, board.resolve()


def _pair_measures(board, plan):
    crossed = score._incremental(board, plan.occupancy, plan)["crossings"].get("pair", 0)
    found = [f for f in plan.findings if f.cause is C.PAIR_CROSSED]
    return crossed, len(found)


def test_pins_facing_the_same_way_with_crossing_chords_are_not_crossed():
    # U1's pins leave north, DP west; U2's pins face north too, so the pair comes round into them from the north,
    # where DP east of DN keeps its side
    board, plan = _board(_part("U1", 10, 10, north=("DP", "DN")), _part("U2", 10, 20, north=("DN", "DP")))
    assert _pair_measures(board, plan) == (0, 0)


def test_pins_facing_the_same_way_with_parallel_chords_are_crossed():
    board, plan = _board(_part("U1", 10, 10, north=("DP", "DN")), _part("U2", 10, 20, north=("DP", "DN")))
    assert _pair_measures(board, plan) == (1, 1)
    found = next(f for f in plan.findings if f.cause is C.PAIR_CROSSED)
    assert found.facts["judged"] == "sides"
    assert str(found) == ("DP/DN cross between U1 and U2: swap the pair's pins at one end, or put one of the parts on "
                          "the other face")


def test_pins_facing_each_other_cross_as_their_chords_do():
    straight, _ = _board(_part("U1", 10, 10, south=("DP", "DN")), _part("U2", 10, 20, north=("DP", "DN")))
    swapped, _ = _board(_part("U1", 10, 10, south=("DP", "DN")), _part("U2", 10, 20, north=("DN", "DP")))
    assert _pair_measures(straight, straight.resolve()) == (0, 0)
    assert _pair_measures(swapped, swapped.resolve()) == (1, 1)


def test_a_part_on_the_other_face_reverses_its_side():
    front, plan = _board(_part("U1", 10, 10, north=("DP", "DN")), _part("U2", 10, 20, north=("DP", "DN")))
    assert _pair_measures(front, plan) == (1, 1)
    back, plan = _board(_part("U1", 10, 10, north=("DP", "DN")), _part("U2", 10, 20, north=("DP", "DN")), back=("U2",))
    assert _pair_measures(back, plan) == (0, 0)


def test_the_side_is_the_same_whatever_the_part_is_turned_to():
    g = _geometry(_part("U1", 10, 10, north=("DP", "DN")), _part("U2", 10, 20, north=("DN", "DP")))
    sides = pair_sides(g, {"DP": "DN", "DN": "DP"})
    assert sides[("U1", "7", "8")] == -sides[("U1", "8", "7")] != 0
    for turn in (0, 90, 180, 270, 45):
        board = Board(g, keep_going=True, settings=settings(cleanup_enabled=False))
        board.pin_study = False
        board.rect(width=40, height=40)
        board.place(Part("u1"), at=Location(10, 10), rotations=(turn,))
        board.place(Part("u2"), at=Location(25, 25), rotations=(0,))
        plan = board.resolve()
        assert _pair_measures(board, plan) == (0, 0), turn


def test_airwires_that_do_not_join_the_same_two_parts_are_judged_as_chords():
    sides = {("U1", "1", "2"): 1.0, ("U1", "2", "1"): -1.0, ("U2", "1", "2"): 1.0, ("U2", "2", "1"): -1.0}
    e = Edge("DP", Anchor("U1", "1", 0, 0), Anchor("U2", "1", 10, 0))
    f = Edge("DN", Anchor("U1", "2", 0, 1), Anchor("U3", "2", 10, 1))
    assert pair_crossed(sides, lambda ref: False, e, f) is None
    via = Edge("DN", Anchor("U1", "2", 0, 1), Anchor("", "via", 10, 1))
    assert pair_crossed(sides, lambda ref: False, e, via) is None
    g = Edge("DN", Anchor("U1", "2", 0, 1), Anchor("U2", "2", 10, 1))
    assert pair_crossed(sides, lambda ref: False, e, g) is not None
    assert pair_crossed({}, lambda ref: False, e, g) is None


def test_the_search_delta_matches_the_whole_score_for_a_pair():
    from placemat.board_geometry import members_of
    from placemat.score_delta import Delta
    board, plan = _board(_part("U1", 10, 10, north=("DP", "DN")), _part("U2", 10, 20, north=("DN", "DP")),
                         _part("U3", 25, 10, south=("DP", "DN")))
    occ = plan.occupancy
    rng = random.Random(5)
    native_checked = 0
    for step in plan.steps:
        if step.placement is None or step.item not in plan._items:
            continue
        item = plan._items[step.item]
        refs = [fp.ref for fp in members_of(item)]
        original = step.placement
        occ.lift(refs)
        lifted = score.whole(board, occ, plan)
        for _ in range(12):
            delta = Delta(board, occ, item, plan.links, plan=plan)
            candidate = dataclasses.replace(original, location=Location(original.location.x + rng.uniform(-8, 8),
                                                                       original.location.y + rng.uniform(-8, 8)),
                                            face=rng.choice((Face.FRONT, Face.BACK)))
            change = delta(candidate, prune_above=-math.inf)
            native = delta.native([candidate.rotation], candidate.face)
            cross = native.wire_cross(candidate.location.x, candidate.location.y, 0)[1] if native is not None else None
            occ.commit(item, candidate)
            after = score.whole(board, occ, plan)
            want = after["crossings"] - lifted["crossings"]
            assert change.terms["crossings"] == pytest.approx(want, abs=1e-6), (step.item, candidate)
            if cross is not None:
                assert cross == pytest.approx(want, abs=1e-6), (step.item, candidate)
                native_checked += 1
            occ.lift(refs)
        occ.commit(item, original)
    from placemat import geometry
    assert native_checked or geometry._native is None


@pytest.mark.parametrize("backend", ["python", "native"])
def test_a_candidates_pair_leaves_to_one_part_are_not_priced_as_chords(backend):
    from placemat import geometry
    from placemat.ratsnest import Ratsnest
    if backend == "native" and (geometry._native is None or not hasattr(geometry._native, "NativeRatsnest")):
        pytest.skip("native ratsnest not built")
    mirror = geometry._native.NativeRatsnest() if backend == "native" else None
    rn = Ratsnest({}, mirror=mirror, partners={"DP": "DN", "DN": "DP"}, prices=(1.0, 1.0, 1.0, 1.0, 25.0))
    rn.set_net("DP", [Anchor("U2", "1", 10, 0)])
    rn.set_net("DN", [Anchor("U2", "2", 9, 0)])
    rn.set_net("S", [Anchor("U3", "1", 9.5, -5), Anchor("U4", "1", 9.5, 8)])
    # the candidate's DP west of its DN: its leaves to U2 cross as chords, and both cross S
    pads = [("DP", 9, 10), ("DN", 10, 10)]
    assert rn.leaf_costs(pads)[0] == 2.0
    rn.set_net("DN", [Anchor("U5", "2", 9, 0)])
    assert rn.leaf_costs(pads)[0] == 2.0 + 25.0
