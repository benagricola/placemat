"""The placement order, as arithmetic - no board, no toolchain.

The order a stage is placed in IS an allocation of area, adjacency and
standoff, so it is the kind of thing that has to hold on cases nobody has built
yet. `next_to_place` is pure for exactly that reason: every rule below is four
lines to state and runs in microseconds, where asking the same question of a
board costs a five-minute pass.

The invariants, not the coordinates: which candidate wins, and why.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from placemat.board_layout import next_to_place, rect_union_area, ORDER_WEIGHTS   # noqa: E402


def cand(name, area, w, h, pull=0.0, apart=0.0, bbox_area=None):
    return dict(name=name, area=area, w=w, h=h, pull=pull, apart=apart,
                bbox_area=bbox_area if bbox_area is not None else w * h)


# -- the union area the fit ratio is built on ---------------------------------

def test_union_counts_overlap_once():
    """Two boxes overlapping by half do not cost one and a half boxes."""
    a = (0.0, 0.0, 10.0, 10.0)
    b = (5.0, 0.0, 15.0, 10.0)
    assert rect_union_area([a, b]) == pytest.approx(150.0)


def test_union_of_disjoint_is_the_sum():
    assert rect_union_area([(0, 0, 2, 2), (10, 10, 12, 12)]) == pytest.approx(8.0)


def test_union_ignores_degenerate_boxes():
    assert rect_union_area([(0, 0, 0, 5), None, (0, 0, 2, 2)]) == pytest.approx(4.0)


# -- the two hard rules -------------------------------------------------------

def test_fit_dominates_over_a_heavier_link():
    """A cell that may not fit at all outranks one that merely wants to be near."""
    big = cand("mcu", area=520.0, w=22.0, h=23.6)          # 26% of the free area
    linked = cand("can", area=141.0, w=21.8, h=6.5, pull=10.0)
    i, why = next_to_place([big, linked], free_area=2000.0)
    assert [big, linked][i]["name"] == "mcu"
    assert "fit dominates" in why


def test_seed_on_difficulty_when_nothing_is_placed():
    """With no pull anywhere, the biggest and most awkward starts the board."""
    strip = cand("opto", area=90.0, w=21.5, h=4.2)
    blob = cand("buck", area=92.0, w=11.8, h=7.9)
    i, why = next_to_place([strip, blob], free_area=4000.0)
    assert [strip, blob][i]["name"] == "opto", "the long thin cell needs the scarce hole"
    assert "seed on difficulty" in why


def test_pull_decides_once_something_is_down():
    """Same size, same shape: the declared link is the whole difference."""
    near = cand("can", area=100.0, w=10.0, h=10.0, pull=10.0)
    far = cand("permit", area=100.0, w=10.0, h=10.0, pull=1.0)
    i, _ = next_to_place([near, far], free_area=4000.0)
    assert [near, far][i]["name"] == "can"


def test_standoff_is_claimed_before_the_room_goes():
    """A victim whose aggressor is down comes forward over a better-linked peer."""
    victim = cand("adc", area=40.0, w=8.0, h=5.0, pull=1.0, apart=1.0)
    chatty = cand("io", area=40.0, w=8.0, h=5.0, pull=10.0)
    i, why = next_to_place([victim, chatty], free_area=4000.0)
    assert [victim, chatty][i]["name"] == "adc"
    assert "standoff" in why


# -- the property that lets ONE function serve cells and loose parts ----------

def test_a_loose_part_is_ordered_by_its_link_not_its_shape():
    """A 0402 is as lopsided as a long strip; holes its size are everywhere.

    This is the invariant that makes a single rule safe for both populations:
    shape is multiplied into fit, so an awkward outline costs nothing until
    holes of that size are scarce. Without it every passive would outrank the
    cells and the board would be laid out smallest-first.
    """
    passive = cand("c_bypass", area=0.5, w=1.0, h=0.5, pull=1.0)     # 2:1, area ~0
    linked = cand("r_series", area=0.5, w=0.7, h=0.7, pull=10.0)     # square, heavier link
    i, _ = next_to_place([passive, linked], free_area=2000.0)
    assert [passive, linked][i]["name"] == "r_series"


def test_the_same_shape_wins_when_it_is_a_cell_on_a_tight_board():
    """The identical outline, scaled up against a scarce board, flips the answer."""
    strip = cand("strip_cell", area=200.0, w=40.0, h=20.0, pull=1.0)
    linked = cand("small_cell", area=20.0, w=4.5, h=4.5, pull=10.0)
    i, why = next_to_place([strip, linked], free_area=800.0)
    assert [strip, linked][i]["name"] == "strip_cell"
    assert "fit dominates" in why


def test_fit_is_relative_so_a_roomy_board_lets_links_lead():
    """Same two candidates, a board with room: adjacency decides instead."""
    strip = cand("strip_cell", area=200.0, w=40.0, h=20.0, pull=1.0)
    linked = cand("small_cell", area=20.0, w=4.5, h=4.5, pull=10.0)
    i, _ = next_to_place([strip, linked], free_area=40000.0)
    assert [strip, linked][i]["name"] == "small_cell"


def test_empty_is_an_error_not_a_silent_none():
    with pytest.raises(ValueError):
        next_to_place([], free_area=100.0)


# -- the shuffle gate: declaration order must not be an input -----------------
# The whole point of deriving an order is that the FILE stops being the
# allocator. That property is only real if it is checked: reorder the
# declarations, get the same answer, or the file is still scheduling the board.

import itertools   # noqa: E402


def test_the_winner_does_not_depend_on_the_order_asked():
    """Every permutation of the same stage picks the same candidate."""
    stage = [cand("mcu", 520.0, 22.0, 23.6),
             cand("can", 141.0, 21.8, 6.5, pull=10.0),
             cand("permit", 98.0, 21.7, 4.5, pull=1.0),
             cand("buck", 92.0, 11.8, 7.9)]
    winners = set()
    for perm in itertools.permutations(stage):
        i, _ = next_to_place(list(perm), free_area=2000.0)
        winners.add(perm[i]["name"])
    assert len(winners) == 1, f"declaration order changed the winner: {winners}"


def test_a_dead_tie_is_still_deterministic():
    """Identical candidates must not be separated by the order they were written.

    This is the case that catches a ranker built on max(): with equal scores it
    returns the lowest index, which IS the caller's order. A stage of identical
    parts would then be allocated by line number, quietly, and nothing would
    ever report it.
    """
    tie = [cand("b_part", 50.0, 10.0, 5.0, pull=1.0),
           cand("a_part", 50.0, 10.0, 5.0, pull=1.0),
           cand("c_part", 50.0, 10.0, 5.0, pull=1.0)]
    winners = {perm[next_to_place(list(perm), free_area=4000.0)[0]]["name"]
               for perm in itertools.permutations(tie)}
    assert len(winners) == 1, f"a tie was broken by declaration order: {winners}"


def test_near_ties_are_stable_too():
    """Scores that differ below float noise must not flip with the input order."""
    near = [cand("x", 50.0, 10.0, 5.0, pull=1.0),
            cand("y", 50.0 + 1e-12, 10.0, 5.0, pull=1.0)]
    winners = {perm[next_to_place(list(perm), free_area=4000.0)[0]]["name"]
               for perm in itertools.permutations(near)}
    assert len(winners) == 1, f"float noise decided the order: {winners}"


# -- the term that reads the REQUEST, not the cell ----------------------------

def test_two_identical_cells_are_separated_by_the_room_at_their_hints():
    """The case that started this: same cell, same shape, different places asked.

    Two OptoSense strips are interchangeable by every other term - identical
    area, identical outline - so without this the tie-break decides, and which
    one goes first is worth a whole cell landing or not. The one with fewer
    places left to land takes one while any are left.
    """
    cramped = dict(cand("opto_in1", 90.0, 21.5, 4.2, pull=1.0), room=0.4)
    roomy = dict(cand("opto_in2", 90.0, 21.5, 4.2, pull=1.0), room=6.0)
    i, why = next_to_place([roomy, cramped], free_area=4000.0)
    assert [roomy, cramped][i]["name"] == "opto_in1"
    assert "room" in why


def test_unmeasured_room_does_not_read_as_scarce():
    """A candidate the caller could not measure must not win by default."""
    unknown = cand("no_hint", 90.0, 21.5, 4.2, pull=1.0)          # no room key
    cramped = dict(cand("cramped", 90.0, 21.5, 4.2, pull=1.0), room=0.2)
    i, _ = next_to_place([unknown, cramped], free_area=4000.0)
    assert [unknown, cramped][i]["name"] == "cramped"


def test_room_does_not_override_a_cell_that_may_not_fit_at_all():
    """Fit still dominates: plenty of room nearby cannot rescue the board."""
    huge = cand("mcu", 520.0, 22.0, 23.6)
    cramped = dict(cand("strip", 90.0, 21.5, 4.2, pull=1.0), room=0.1)
    i, why = next_to_place([cramped, huge], free_area=1800.0)
    assert [cramped, huge][i]["name"] == "mcu"
    assert "fit dominates" in why


def test_the_room_term_is_still_permutation_invariant():
    import itertools
    stage = [dict(cand("a", 90.0, 21.5, 4.2, pull=1.0), room=0.4),
             dict(cand("b", 90.0, 21.5, 4.2, pull=1.0), room=6.0),
             dict(cand("c", 92.0, 11.8, 7.9, pull=1.0), room=2.0)]
    winners = {perm[next_to_place(list(perm), free_area=4000.0)[0]]["name"]
               for perm in itertools.permutations(stage)}
    assert len(winners) == 1, f"the room term reintroduced an order dependence: {winners}"
