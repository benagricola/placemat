"""script_edit: an edit inside a call that is an argument of the target (a `Beside` inside `at=`, a `Past` in a points
list, a `Cutout` in `holes=`, an intent `Centre`), reached by `args["into"]`, and checked by masking that inner call."""
import pytest

from placemat import script_edit as se
from tests.test_script_edit import FACE, line_of, run as _run

HEAD = ("from placemat import board, Along, Beside, Centre, Cutout, Edge, Location, PadRef, Part, Past, Slot, X, Y\n\n")


def run(op, text, needle, into, **kw):
    args = dict(kw.pop("args", {}), into=into)
    return _run(op, text, needle, args=args, **kw)


AT = [{"kw": "at"}]


def test_a_keyword_is_added_to_the_beside_in_at():
    text = HEAD + 'board.place(Part("c4"), at=Beside(Part("c1"), Edge.NORTH))  # near c1\n'
    out = run("set_kwarg", text, "board.place", AT, args={"name": "gap"}, value=0.3)
    assert out == HEAD + 'board.place(Part("c4"), at=Beside(Part("c1"), Edge.NORTH, gap=0.3))  # near c1\n'


def test_a_keyword_the_inner_call_has_is_replaced_in_place_and_one_it_gives_by_position_too():
    text = HEAD + 'board.place(Part("c4"), at=Beside(Part("c1"), Edge.NORTH, None, 0.5))\n'
    out = run("set_kwarg", text, "board.place", AT, args={"name": "gap"}, value=0.9)
    assert out == HEAD + 'board.place(Part("c4"), at=Beside(Part("c1"), Edge.NORTH, None, 0.9))\n'


def test_a_positional_argument_of_the_inner_call_is_replaced():
    text = HEAD + 'board.place(Part("c4"), at=Beside(Part("c1"), Edge.NORTH))\n'
    out = run("set_arg", text, "board.place", AT, args={"index": 1}, value={"enum": "Edge.SOUTH"})
    assert out == HEAD + 'board.place(Part("c4"), at=Beside(Part("c1"), Edge.SOUTH))\n'


def test_a_keyword_of_the_inner_call_is_removed_and_the_comments_round_it_stay():
    text = HEAD + 'board.place(\n    Part("c4"),\n    at=Beside(\n        Part("c1"),  # the neighbour\n        Edge.NORTH,\n        gap=0.5,\n    ),\n)\n'
    out = run("remove_kwarg", text, "board.place(", AT, args={"name": "gap"})
    assert out == HEAD + 'board.place(\n    Part("c4"),\n    at=Beside(\n        Part("c1"),  # the neighbour\n        Edge.NORTH,\n    ),\n)\n'


def test_one_axis_of_an_intent_centre_is_freed_with_none():
    text = HEAD + 'board.place(Part("c4"), at=Centre(X(PadRef(Part("u1"), 3)), Y(PadRef(Part("u1"), 3))))\n'
    out = run("set_arg", text, "board.place", AT, args={"index": 1}, value=None)
    assert out == HEAD + 'board.place(Part("c4"), at=Centre(X(PadRef(Part("u1"), 3)), None))\n'


def test_a_past_inside_a_points_list_gets_an_across():
    text = HEAD + ('board.track("A", [PadRef(Part("u1"), 1), Past([PadRef(Part("u2"), 2)], Edge.EAST), '
                   'PadRef(Part("u3"), 4)], layer=1)\n')
    out = run("set_kwarg", text, "board.track", [{"pos": 1}, {"find": "Past"}], kind="track", key="A",
              args={"name": "across"}, value={"enum": "Along.START"}, refs={})
    assert 'Past([PadRef(Part("u2"), 2)], Edge.EAST, across=Along.START)' in out


def test_a_cutout_in_holes_gets_a_new_relation():
    text = HEAD + 'board.rect(60, 40, holes=[Cutout(Slot(8, 2), "slot", at=Location(10, 10))])\n'
    out = run("set_kwarg", text, "board.rect", [{"kw": "holes"}, {"find": "Cutout"}], kind="rect", key="board",
              args={"name": "at"}, value={"form": "Beside", "args": [{"str": "x"}, {"enum": "Edge.NORTH"}]})
    assert out == HEAD + 'board.rect(60, 40, holes=[Cutout(Slot(8, 2), "slot", at=Beside("x", Edge.NORTH))])\n'


def test_an_element_is_named_by_its_place_in_the_list():
    text = HEAD + 'board.rect(60, 40, holes=[Cutout(Slot(8, 2), "a", at=Location(1, 1)), Cutout(Slot(8, 2), "b", at=Location(2, 2))])\n'
    out = run("set_kwarg", text, "board.rect", [{"kw": "holes"}, {"elem": 1}], kind="rect", key="board",
              args={"name": "why"}, value={"str": "x"})
    assert out.count('why="x"') == 1 and 'at=Location(2, 2), why="x")' in out


def test_a_list_inside_the_inner_call_is_edited():
    text = HEAD + 'board.track("A", [PadRef(Part("u1"), 1), Past([PadRef(Part("u2"), 2), PadRef(Part("u3"), 1)], Edge.EAST)], layer=1)\n'
    out = run("edit_list", text, "board.track", [{"pos": 1}, {"find": "Past"}], kind="track", key="A",
              args={"arg": 0, "action": "remove", "indices": [1]})
    assert 'Past([PadRef(Part("u2"), 2)], Edge.EAST)' in out


def test_two_inner_calls_of_the_name_are_refused():
    text = HEAD + 'board.track("A", [Past([PadRef(Part("u2"), 2)], Edge.EAST), Past([PadRef(Part("u3"), 2)], Edge.WEST)], layer=1)\n'
    with pytest.raises(se.EditRefused, match="Past"):
        run("set_kwarg", text, "board.track", [{"pos": 1}, {"find": "Past"}], kind="track", key="A",
            args={"name": "across"}, value=None)


def test_a_path_that_does_not_end_at_a_call_is_refused():
    text = HEAD + 'board.place(Part("c4"), at=Location(10, 10), face=Edge.NORTH)\n'
    with pytest.raises(se.EditRefused):
        run("set_kwarg", text, "board.place", [{"kw": "face"}], args={"name": "gap"}, value=0.3)
    with pytest.raises(se.EditRefused):
        run("set_kwarg", text, "board.place", [{"kw": "why"}], args={"name": "gap"}, value=0.3)


def test_nothing_outside_the_inner_call_changes():
    text = HEAD + 'board.place(Part("c4"), at=Beside(Part("c1"), Edge.NORTH), why="a, b")  # c4\nboard.place(Part("c5"))\n'
    out = run("set_kwarg", text, "board.place", AT, args={"name": "gap"}, value=0.3)
    a, b = text.splitlines(), out.splitlines()
    assert a[0] == b[0] and a[-1] == b[-1] and a[3].replace("Edge.NORTH)", "Edge.NORTH, gap=0.3)") == b[3]
