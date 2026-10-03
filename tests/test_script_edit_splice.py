"""script_edit: what the splicing editor reads from the text (tokens, not a tree) and keeps through an edit."""
import pytest

from placemat import script_edit as se
from placemat.freeze import edit_call
from tests.test_script_edit import FACE, HEAD, run
from tests.test_script_edit_more import lst


def test_commas_brackets_and_hashes_inside_strings_are_not_layout():
    text = HEAD + 'board.place(Part("c4"), why="a, (b) # not a comment", at=(Beside(Part("c1"), Edge.NORTH)))  # tail\n'
    assert run("remove_kwarg", text, "board.place", args={"name": "why"}) == \
        HEAD + 'board.place(Part("c4"), at=(Beside(Part("c1"), Edge.NORTH)))  # tail\n'
    assert run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE).endswith(
        'Edge.NORTH)), face=Face.EITHER)  # tail\n')


def test_an_argument_that_spans_lines_is_one_item():
    text = HEAD + ('board.place(\n    Part("c4"),\n    at=Beside(\n        Part("c1"),\n        Edge.NORTH,\n    ),  # beside\n'
                   '    why="x",\n)\n')
    out = run("remove_kwarg", text, "board.place", args={"name": "why"})
    assert out == HEAD + 'board.place(\n    Part("c4"),\n    at=Beside(\n        Part("c1"),\n        Edge.NORTH,\n    ),  # beside\n)\n'
    out = run("remove_kwarg", text, "board.place", args={"name": "at"})
    assert out == HEAD + 'board.place(\n    Part("c4"),  # beside\n    why="x",\n)\n'


def test_a_keyword_added_to_a_call_whose_last_line_holds_several_arguments_goes_on_a_new_line_at_that_indent():
    text = HEAD + 'board.place(Part("c4"), at=Edge.NORTH,\n            why="x")\n'
    out = run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE)
    assert out == HEAD + 'board.place(Part("c4"), at=Edge.NORTH,\n            why="x",\n            face=Face.EITHER)\n'


def test_a_comment_on_a_line_of_its_own_above_an_argument_stays_when_another_is_removed():
    text = HEAD + 'board.place(\n    Part("c4"),\n    # about face\n    face=Face.FRONT,\n    why="x",\n)\n'
    out = run("remove_kwarg", text, "board.place", args={"name": "why"})
    assert out == HEAD + 'board.place(\n    Part("c4"),\n    # about face\n    face=Face.FRONT,\n)\n'


def test_removing_the_last_argument_after_a_comment_puts_the_closing_parenthesis_on_its_own_line():
    text = HEAD + 'board.place(\n    Part("c4"),  # c4\n    at=Edge.NORTH)\n'
    out = run("remove_kwarg", text, "board.place", args={"name": "at"})
    assert out == HEAD + 'board.place(\n    Part("c4")  # c4\n    )\n'


def test_a_tuple_left_with_one_element_keeps_its_comma():
    text = HEAD + 'board.keepout(shape, "ant", allow=("A", "B", "C"))\n'
    out = run("edit_list", text, "board.keepout", kind="keepout", key="ant",
              args={"arg": "allow", "action": "remove", "indices": [0, 2]}, value=None)
    assert out.endswith('allow=("B",))\n')
    out = lst({"action": "remove"}, {"str": "B"}, HEAD + 'board.keepout(shape, "ant", allow=("A", "B"))\n')
    assert out.endswith('allow=("A",))\n')


def test_a_comment_moves_with_an_element_to_the_end_when_the_bracket_shares_the_last_line():
    text = HEAD + 'board.keepout(shape, "ant", allow=[\n    "A",  # first\n    "B"])\n'
    out = lst({"action": "move", "after": {"str": "B"}}, {"str": "A"}, text)
    assert out == HEAD + 'board.keepout(shape, "ant", allow=[\n    "B",\n    "A"  # first\n    ])\n'


def test_non_ascii_text_before_the_target_does_not_shift_the_edit():
    text = '"""café µF"""\n' + HEAD + 'x = "ΩΩ"; y = 1\nboard.place(Part("c4"), why="10 kΩ")\n'
    out = run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE)
    assert out.endswith('why="10 kΩ", face=Face.EITHER)\n')


def test_a_file_with_a_lone_carriage_return_is_refused():
    text = HEAD + 'board.place(Part("c4"))\r# old mac line\n'
    with pytest.raises(se.EditRefused, match="carriage return"):
        run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE)


def test_a_call_in_a_comprehension_is_refused_as_in_a_loop():
    text = HEAD + '[board.place(Part(n)) for n in ("c4", "c5")]\n'
    with pytest.raises(se.EditRefused, match="loop"):
        run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE)


def test_freeze_keeps_a_trailing_comma_and_the_comment_after_it():
    src = 'board.place(\n    Part("r1"),\n    why="x",  # the pull-up\n)\n'
    out = edit_call(src, 1, {"rotation": "90"})
    assert out == 'board.place(\n    Part("r1"),\n    why="x",  # the pull-up\n    rotation=90,\n)\n'
