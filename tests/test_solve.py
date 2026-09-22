"""The global pre-solve, pure: springs, the solver, spreading. No KiCad."""
import pytest

from placemat import solve


def test_conjugate_gradient_solves_a_small_system_exactly():
    # 4x - y = 3, -x + 3y = 5  ->  x = 14/11, y = 23/11
    A = {0: {0: 4.0, 1: -1.0}, 1: {0: -1.0, 1: 3.0}}
    x, used, residual = solve.cg_solve(A, [3.0, 5.0], [0.0, 0.0], 50, 1e-12)
    assert x == [pytest.approx(14 / 11), pytest.approx(23 / 11)]
    assert residual < 1e-9 and used <= 2


def test_a_solve_that_hits_its_cap_says_so():
    A = {i: {i: 2.0, **({i + 1: -1.0} if i < 49 else {}), **({i - 1: -1.0} if i > 0 else {})} for i in range(50)}
    x, used, residual = solve.cg_solve(A, [1.0] * 50, [0.0] * 50, 3, 1e-12)
    assert used == 3 and residual > 1e-12


def _pin(item, dx=0.0, dy=0.0, key=()):
    return solve.Pin(item, dx, dy, key)


def test_one_item_between_two_anchors_lands_at_the_weighted_midpoint():
    nets = {"A": [_pin(None, 0.0, 0.0), _pin("u")], "B": [_pin("u"), _pin(None, 10.0, 0.0)]}
    pos = {"u": (100.0, 100.0)}
    springs = solve.axis_springs(nets, pos, 0, lambda a, b: 1.0, unit_span=True)
    got, _, _ = solve.solve_axis(["u"], springs, 0, pos, 5.0, 0.0, {}, 100, 1e-12)
    assert got["u"] == pytest.approx(5.0)


def test_a_short_link_pulls_harder_than_a_default_one():
    left, right = _pin(None, 0.0, 0.0, ("J1", "1")), _pin(None, 10.0, 0.0, ("J2", "1"))
    u_l, u_r = _pin("u", key=("U1", "1")), _pin("u", key=("U1", "2"))
    nets = {"A": [left, u_l], "B": [u_r, right]}
    weight = lambda a, b: 8.0 if {a.key, b.key} == {("J1", "1"), ("U1", "1")} else 1.0
    pos = {"u": (5.0, 0.0)}
    got, _, _ = solve.solve_axis(["u"], solve.axis_springs(nets, pos, 0, weight, True), 0, pos, 5.0, 0.0, {}, 100, 1e-12)
    assert got["u"] < 5.0                    # nearer the end the SHORT link names


def test_a_chain_of_three_spreads_evenly_between_its_anchors():
    nets = {"A": [_pin(None, 0.0, 0.0), _pin("a")], "B": [_pin("a"), _pin("b")],
            "C": [_pin("b"), _pin("c")], "D": [_pin("c"), _pin(None, 12.0, 0.0)]}
    pos = {k: (0.0, 0.0) for k in "abc"}
    got, _, _ = solve.solve_axis(list("abc"), solve.axis_springs(nets, pos, 0, lambda a, b: 1.0, True),
                                 0, pos, 6.0, 0.0, {}, 200, 1e-12)
    assert [got[k] for k in "abc"] == [pytest.approx(3.0), pytest.approx(6.0), pytest.approx(9.0)]


def test_a_pin_offset_pulls_the_item_by_its_pin_not_its_centre():
    nets = {"A": [_pin(None, 0.0, 0.0), _pin("u", dx=2.0)]}
    pos = {"u": (50.0, 0.0)}
    got, _, _ = solve.solve_axis(["u"], solve.axis_springs(nets, pos, 0, lambda a, b: 1.0, True),
                                 0, pos, 0.0, 1e-9, {}, 100, 1e-12)
    assert got["u"] == pytest.approx(-2.0, abs=1e-5)   # its pin, 2 mm right of its origin, lands on the anchor


def test_bisection_gives_every_item_its_own_cell_and_keeps_their_order():
    pos = {k: (float(i) * 0.01, 5.0) for i, k in enumerate("abcd")}      # piled on a line
    got = solve.bisect_spread({k: 1.0 for k in "abcd"}, pos, (0.0, 0.0, 40.0, 10.0))
    xs = [got[k][0] for k in "abcd"]
    assert xs == sorted(xs) and len(set(round(x, 6) for x in xs)) == 4
    assert xs == [pytest.approx(5.0), pytest.approx(15.0), pytest.approx(25.0), pytest.approx(35.0)]


def test_spread_positions_stay_inside_the_region():
    pos = {k: (500.0, -300.0) for k in "abcdefg"}
    got = solve.bisect_spread({k: 1.0 + i for i, k in enumerate("abcdefg")}, pos, (0.0, 0.0, 30.0, 20.0))
    assert all(0.0 <= x <= 30.0 and 0.0 <= y <= 20.0 for x, y in got.values())


def test_a_bigger_item_gets_a_bigger_cell():
    pos = {"big": (0.0, 0.0), "small": (1.0, 0.0)}
    got = solve.bisect_spread({"big": 3.0, "small": 1.0}, pos, (0.0, 0.0, 40.0, 10.0))
    assert got["big"][0] == pytest.approx(15.0) and got["small"][0] == pytest.approx(35.0)


def _board_nets():
    return {"A": [_pin(None, 0.0, 10.0), _pin("a")], "B": [_pin("a"), _pin("b")],
            "C": [_pin("b"), _pin("c")], "D": [_pin("c"), _pin(None, 40.0, 10.0)]}


def test_the_same_input_solves_to_the_same_numbers_twice():
    args = (list("abc"), _board_nets(), lambda a, b: 1.0, {k: 4.0 for k in "abc"},
            (0.0, 0.0, 40.0, 20.0), {k: (200.0, 200.0) for k in "abc"}, 6, 200, 1e-9)
    assert solve.global_solve(*args) == solve.global_solve(*args)


def test_the_solve_spreads_a_chain_along_its_anchors_inside_the_board():
    r = solve.global_solve(list("abc"), _board_nets(), lambda a, b: 1.0, {k: 4.0 for k in "abc"},
                           (0.0, 0.0, 40.0, 20.0), {k: (200.0, 200.0) for k in "abc"}, 6, 200, 1e-9)
    xs = [r.hints[k][0] for k in "abc"]
    assert xs == sorted(xs) and all(0.0 <= x <= 40.0 for x in xs)
    assert all(0.0 <= r.hints[k][1] <= 20.0 for k in "abc")
    assert r.rounds == 6 and r.iterations > 0


def test_an_anchored_pad_never_moves():
    nets = {"A": [_pin(None, 7.0, 3.0), _pin("a")]}
    r = solve.global_solve(["a"], nets, lambda a, b: 1.0, {"a": 1.0}, (0.0, 0.0, 20.0, 20.0),
                           {"a": (0.0, 0.0)}, 3, 100, 1e-9)
    assert set(r.hints) == {"a"}
