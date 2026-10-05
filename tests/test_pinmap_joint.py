"""Parts whose movable nets connect to each other's are studied together: their poses searched in combination (at most
`pins.joint_combinations`), both ends of a shared net free."""
import pytest

from placemat.pinmap_core import linked_groups, native_core, study, study_group
from tests.pinmap_boards import input_of, point_pad, quad, settings

CORES = ["native", "python"]


@pytest.fixture(params=CORES)
def native(request):
    if request.param == "native" and native_core() is None:
        pytest.skip("the native module is not in use")
    return request.param == "native"


def facing_away():
    """U1 with nets A-C on its west side and U2, 10 mm east, with the same nets on its east side: each faces away from
    the other, so the nets go round both bodies until both parts turn."""
    p1, u1 = quad("U1", 10, 10, {"W": ["A", "B", "C"]}, {"Pm.PinPool": "1-3"})
    p2, u2 = quad("U2", 20, 10, {"E": ["A", "B", "C"]}, {"Pm.PinPool": "1-3"})
    return input_of(p1 + p2, {"U1": u1, "U2": u2})[0]


def test_parts_sharing_a_net_that_may_move_on_both_are_one_group_and_a_held_link_does_not_join_them():
    assert linked_groups(facing_away()) == [("U1", "U2")]
    p1, u1 = quad("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2", "Pm.PinFixed": "1"})
    p2, u2 = quad("U2", 20, 10, {"W": ["A", "B"]}, {"Pm.PinPool": "1-2"})
    inp, _ = input_of(p1 + p2 + point_pad("T1", "B", 30, 30), {"U1": u1, "U2": u2})
    assert linked_groups(inp) == [("U1", "U2")]                        # B may move on both
    p2, u2 = quad("U2", 20, 10, {"W": ["A", ""]}, {"Pm.PinPool": "1-2"})
    inp, _ = input_of(p1 + p2 + point_pad("T1", "B", 30, 30), {"U1": u1, "U2": u2})
    assert linked_groups(inp) == [("U1",), ("U2",)]                    # A is fixed on U1: only U2's end moves


def test_a_joint_study_beats_studying_each_part_alone(native):
    inp = facing_away()
    s = settings(pins_length_weight=0.1)
    best = lambda g: min(r.breakdown.total for r in g.results)
    joint = study_group(inp, ("U1", "U2"), s, native=native)
    alone = [study_group(inp, (r,), s, native=native) for r in ("U1", "U2")]
    assert best(joint) < min(best(g) for g in alone)
    win = min(joint.results, key=lambda r: r.breakdown.total)
    assert win.poses == (("U1", 180.0, False), ("U2", 180.0, False))
    assert [g.refs for g in study(inp, s, native=native)] == [("U1", "U2")]


def test_a_joint_study_searches_at_most_the_combinations_it_is_allowed(native):
    g = study_group(facing_away(), ("U1", "U2"), settings(pins_joint_combinations=5), native=native)
    assert (g.searched, g.of) == (5, 16)
    assert g.results[0].poses == (("U1", 0.0, False), ("U2", 0.0, False))
