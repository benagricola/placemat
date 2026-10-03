"""A parameter the board method takes by position may be given by position in the script: the edit changes that
argument rather than adding a keyword that would be given twice."""
import pytest

from placemat import script_edit as se
from tests.test_script_edit import FACE, HEAD, run

BESIDE = {"form": "Beside", "args": [{"form": "Part", "args": [{"str": "c1"}]}, {"enum": "Edge.NORTH"}]}


def test_set_kwarg_replaces_a_parameter_given_by_position():
    text = HEAD + 'board.place(Part("c4"), Near(x), rotation=90)\n'
    out = run("set_kwarg", text, "board.place", args={"name": "at"}, value=BESIDE)
    assert out == HEAD + 'board.place(Part("c4"), Beside(Part("c1"), Edge.NORTH), rotation=90)\n'


def test_set_kwarg_adds_a_positional_parameter_as_a_keyword_where_it_is_not_given():
    text = HEAD + 'board.place(Part("c4"), rotation=90)\n'
    out = run("set_kwarg", text, "board.place", args={"name": "at"}, value=BESIDE)
    assert out == HEAD + 'board.place(Part("c4"), rotation=90, at=Beside(Part("c1"), Edge.NORTH))\n'


def test_a_link_weight_given_by_position_is_replaced():
    text = HEAD + 'board.link(a, b, LinkWeight.DEFAULT, limit_mm=4.0)\n'
    out = run("set_kwarg", text, "board.link", kind="link", key="a>b", args={"name": "weight"},
              value={"enum": "LinkWeight.SHORT"})
    assert out == HEAD + 'board.link(a, b, LinkWeight.SHORT, limit_mm=4.0)\n'


def test_remove_kwarg_of_a_positional_argument_that_is_last_of_the_positionals():
    text = HEAD + 'board.place(Part("c4"), Near(x), rotation=90)\n'
    assert run("remove_kwarg", text, "board.place", args={"name": "at"}) == HEAD + 'board.place(Part("c4"), rotation=90)\n'


def test_remove_kwarg_of_a_positional_argument_with_positionals_after_it_is_refused():
    text = HEAD + 'board.link(a, b, LinkWeight.DEFAULT, 4.0)\n'
    with pytest.raises(se.EditRefused, match="given by position"):
        run("remove_kwarg", text, "board.link", kind="link", key="a>b", args={"name": "weight"})


def test_a_call_that_spreads_args_may_give_a_positional_parameter_there():
    text = HEAD + 'args = (Part("c4"), None)\nboard.place(*args)\n'
    with pytest.raises(se.EditRefused, match="spreads"):
        run("set_kwarg", text, "board.place", args={"name": "at"}, value=BESIDE)
    assert run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE).endswith("face=Face.EITHER)\n")


def test_edit_list_creates_the_keyword_when_asked_to_and_it_is_absent():
    text = HEAD + 'board.keepout(shape, "ant", at=a)\n'
    out = run("edit_list", text, "board.keepout", kind="keepout", key="ant",
              args={"arg": "allow", "action": "add", "create": True}, value={"str": "SIG"})
    assert out == HEAD + 'board.keepout(shape, "ant", at=a, allow=["SIG"])\n'
