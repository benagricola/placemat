"""Link weights: what they accept, and the ALLOCATION they imply.

The ordering rule is the one worth testing hardest. Adjacency is scarce and
goes to whoever asks first, so the order loose parts are placed in IS an
allocation - place a preference first and the room a constrained link needed is
gone, which reads as "the board is full" when it is really "the room went to the
wrong connections". That rule is a pure function of the declared weights, so it
can be proved without a board.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from placemat.layout_helpers import LinkWeight, ModuleLayout        # noqa: E402
from placemat.board_layout import BoardLayout                        # noqa: E402


# -- the weight field ---------------------------------------------------------

def test_named_weights_are_their_numbers():
    """A LinkWeight IS a float, so the named and numeric forms take one code
    path and a member can be compared, summed and multiplied like any weight."""
    assert LinkWeight.SHORT == 10.0
    assert LinkWeight.PREFER == 1.0
    assert LinkWeight.FIXED == 0.0


@pytest.mark.parametrize("good", [0, 1, 3, 10, 0.5, 2.75, LinkWeight.SHORT, LinkWeight.FIXED])
def test_accepts_any_finite_non_negative_weight(good):
    """The scale is continuous: 3 means "worth three ordinary connections per
    millimetre", for a link that sits between two of the names."""
    assert ModuleLayout.link_weight(good) >= 0.0


@pytest.mark.parametrize("bad", [-1, float("inf"), float("nan"), "short", None, True])
def test_rejects_what_is_not_a_weight(bad):
    """Rejected AT THE DECLARATION, where the mistake is: a bad weight that
    reaches the objective silently mis-prices a connection instead of failing."""
    with pytest.raises(ValueError):
        ModuleLayout.link_weight(bad)


# -- the allocation -----------------------------------------------------------

def _ranker(links):
    """A BoardLayout with nothing but declared links - enough for the ordering
    rule, which reads weights and nothing else."""
    board = BoardLayout.__new__(BoardLayout)
    board.layout = type("L", (), {"links": links, "LINK_DEFAULT": LinkWeight.PREFER})()
    board._inst_of_ref = {}
    return board


def link(a, b, w):
    return {"weight": float(w), "a": {"ref": a, "pad": "1"}, "b": {"ref": b, "pad": "1"}}


def test_heaviest_link_is_placed_first():
    board = _ranker([link("cap", "ic", LinkWeight.SHORT), link("res", "ic", LinkWeight.PREFER)])
    assert board.by_link_priority(["res", "cap"]) == ["cap", "res"]


def test_a_between_weight_outranks_a_preference_and_yields_to_short():
    board = _ranker([link("bypass", "ic", 10), link("gate_r", "fet", 3), link("pull", "net", 1)])
    assert board.by_link_priority(["pull", "gate_r", "bypass"]) == ["bypass", "gate_r", "pull"]


def test_undeclared_parts_weigh_prefer():
    """Declaring nothing changes nothing: an undeclared link weighs exactly what
    every link weighed before weights existed."""
    board = _ranker([link("cap", "ic", LinkWeight.SHORT)])
    assert board.by_link_priority(["plain", "cap"]) == ["cap", "plain"]


def test_fixed_links_ask_for_no_adjacency():
    """Mechanics decided the endpoint, so the connection must not outrank a
    part that actually needs the room."""
    board = _ranker([link("probe", "pin", LinkWeight.FIXED), link("cap", "ic", LinkWeight.PREFER)])
    assert board.by_link_priority(["probe", "cap"]) == ["cap", "probe"]


def test_ties_keep_the_callers_order():
    """So a script's own reasoning about the rest of the board survives the
    sort, instead of being replaced by an arbitrary one."""
    board = _ranker([])
    assert board.by_link_priority(["c", "a", "b"]) == ["c", "a", "b"]


def test_a_part_is_ranked_by_its_heaviest_link():
    """A part holding one constrained link and three preferences is a
    constrained part - the strongest claim decides, not the average."""
    board = _ranker([link("multi", "x", 1), link("multi", "y", LinkWeight.SHORT),
                  link("other", "z", 3)])
    assert board.by_link_priority(["other", "multi"]) == ["multi", "other"]
