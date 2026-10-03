"""script_edit: text in, text out. Each edit changes the one declaration it targets and nothing else."""
import ast

import pytest

from placemat import script_edit as se
from placemat.suggestions import Edit, Target

HEAD = "from placemat import board, Beside, Edge, Face, LinkWeight, Part, Priority\n\n"


def line_of(text, needle, nth=1):
    seen = 0
    for n, line in enumerate(text.splitlines(), 1):
        if needle in line:
            seen += 1
            if seen == nth:
                return n
    raise AssertionError("no %r in the text" % needle)


def edit(op, text, needle, kind="place", key="c4", nth=1, args=None, value=None, refs=None, **target):
    t = Target(kind, key, "script.py", line_of(text, needle, nth), **target)
    return Edit(op, t, args or {}, value, refs or {})


def run(op, text, needle, **kw):
    return se.apply(edit(op, text, needle, **kw), text)


FACE = {"enum": "Face.EITHER"}


def assert_parses_and_outside_equal(before, after, needle):
    ast.parse(after)
    b, a = before.splitlines(keepends=True), after.splitlines(keepends=True)
    assert b[0] == a[0]
    assert b[-1] == a[-1] or b[-2] == a[-2]


# ------------------------------------------------------------------ set_kwarg
def test_set_kwarg_adds_a_keyword_to_a_call_on_one_line():
    text = HEAD + 'board.place(Part("c4"))  # the cap\nboard.place(Part("c5"))\n'
    out = run("set_kwarg", text, '"c4"', args={"name": "face"}, value=FACE)
    assert out == HEAD + 'board.place(Part("c4"), face=Face.EITHER)  # the cap\nboard.place(Part("c5"))\n'


def test_set_kwarg_adds_a_keyword_on_its_own_line_after_the_last_argument_with_a_trailing_comma():
    text = HEAD + 'board.place(\n    Part("c4"),\n    at=Beside(Part("c1"), Edge.NORTH),  # beside c1\n)\n'
    out = run("set_kwarg", text, 'board.place(', args={"name": "face"}, value=FACE)
    assert out == HEAD + ('board.place(\n    Part("c4"),\n    at=Beside(Part("c1"), Edge.NORTH),  # beside c1\n'
                          '    face=Face.EITHER,\n)\n')


def test_set_kwarg_adds_a_keyword_without_a_trailing_comma_where_the_call_has_none():
    text = HEAD + 'board.place(\n    Part("c4"),\n    at=Beside(Part("c1"), Edge.NORTH)  # beside c1\n)\n'
    out = run("set_kwarg", text, 'board.place(', args={"name": "face"}, value=FACE)
    assert out == HEAD + ('board.place(\n    Part("c4"),\n    at=Beside(Part("c1"), Edge.NORTH),  # beside c1\n'
                          '    face=Face.EITHER\n)\n')


def test_set_kwarg_in_a_call_whose_closing_parenthesis_is_indented_keeps_it_there():
    text = HEAD + 'board.place(\n    Part("c4"),\n    at=Beside(Part("c1"), Edge.NORTH),\n    )\n'
    out = run("set_kwarg", text, 'board.place(', args={"name": "face"}, value=FACE)
    assert out == HEAD + ('board.place(\n    Part("c4"),\n    at=Beside(Part("c1"), Edge.NORTH),\n'
                          '    face=Face.EITHER,\n    )\n')


def test_set_kwarg_in_an_aligned_call_goes_on_a_new_line_at_the_same_column():
    text = HEAD + 'board.place(Part("c4"),\n            at=Beside(Part("c1"), Edge.NORTH))\n'
    out = run("set_kwarg", text, 'board.place(', args={"name": "face"}, value=FACE)
    assert out == HEAD + ('board.place(Part("c4"),\n            at=Beside(Part("c1"), Edge.NORTH),\n'
                          '            face=Face.EITHER)\n')


def test_set_kwarg_replaces_a_keyword_already_there_and_keeps_its_layout():
    text = HEAD + 'board.place(\n    Part("c4"),\n    face=Face.FRONT,  # keep it on top\n    why="x",\n)\n'
    out = run("set_kwarg", text, 'board.place(', args={"name": "face"}, value=FACE)
    assert out == HEAD + 'board.place(\n    Part("c4"),\n    face=Face.EITHER,  # keep it on top\n    why="x",\n)\n'


def test_set_kwarg_refuses_a_value_the_call_already_has():
    text = HEAD + 'board.place(Part("c4"), face=Face.EITHER)\n'
    with pytest.raises(se.EditRefused, match="already"):
        run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE)


def test_set_kwarg_after_star_args_is_fine_and_after_double_star_is_refused():
    text = HEAD + 'args = (Part("c4"),)\nboard.place(*args)\n'
    assert run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE).endswith("board.place(*args, face=Face.EITHER)\n")
    text = HEAD + 'kw = {}\nboard.place(Part("c4"), **kw)\n'
    with pytest.raises(se.EditRefused, match="kwargs"):
        run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE)


def test_set_kwarg_refuses_a_form_or_enum_the_script_does_not_import():
    text = 'from placemat import board, Part\n\nboard.place(Part("c4"))\n'
    with pytest.raises(se.EditRefused, match="not imported"):
        run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE)


def test_set_kwarg_writes_enums_through_a_module_alias_and_a_star_import():
    text = 'import placemat as pm\n\npm.board.place(pm.Part("c4"))\n'
    assert run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE) == \
        'import placemat as pm\n\npm.board.place(pm.Part("c4"), face=pm.Face.EITHER)\n'
    text = 'from placemat import *\n\nboard.place(Part("c4"))\n'
    assert run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE).endswith("face=Face.EITHER)\n")


def test_set_kwarg_refuses_an_enum_placemat_does_not_have():
    text = HEAD + 'board.place(Part("c4"))\n'
    with pytest.raises(se.EditRefused, match="no NOPE"):
        run("set_kwarg", text, "board.place", args={"name": "face"}, value={"enum": "Face.NOPE"})


# ------------------------------------------------------------------ the target
def test_a_target_not_found_exactly_once_is_refused():
    text = HEAD + 'board.place(Part("c4"))\n'
    t = Target("place", "c4", "script.py", 99)
    with pytest.raises(se.EditRefused, match="not one"):
        se.apply(Edit("set_kwarg", t, {"name": "face"}, FACE), text)
    text = HEAD + 'board.place(Part("c4")); board.place(Part("c5"))\n'
    with pytest.raises(se.EditRefused, match="not one"):
        run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE)


def test_a_call_in_a_loop_is_refused():
    text = HEAD + 'for n in ("c4", "c5"):\n    board.place(Part(n))\n'
    with pytest.raises(se.EditRefused, match="loop"):
        run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE)


def test_a_target_shared_by_several_items_is_refused():
    text = HEAD + 'def put(n):\n    board.place(Part(n))\n\n\nput("c4")\nput("c5")\n'
    with pytest.raises(se.EditRefused, match="declares 2 items"):
        run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE, shared=2)


def test_a_changed_digest_is_refused():
    text = HEAD + 'board.place(Part("c4"))\n'
    e = edit("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE, digest=se.digest(text))
    assert se.apply(e, text).endswith("face=Face.EITHER)\n")
    with pytest.raises(se.StaleEdit):
        se.apply(e, text + "# moved\n")


def test_a_keepout_is_found_by_the_name_it_was_given():
    text = HEAD + 'board.keepout(shape, "ant", at=a)\nboard.keepout(shape, "vent", at=b)\n'
    e = edit("set_kwarg", text, "board.keepout", kind="keepout", key="vent", nth=1, args={"name": "layers"},
             value={"list": [{"enum": "Face.EITHER"}]})
    with pytest.raises(se.EditRefused, match="not one"):
        se.apply(e, text)           # the line is the "ant" call's, not "vent"'s


def test_the_declared_line_may_be_inside_a_multi_line_call():
    text = HEAD + 'board.place(\n    Part("c4"),\n)\n'
    out = se.apply(edit("set_kwarg", text, 'Part("c4")', args={"name": "face"}, value=FACE), text)
    assert 'face=Face.EITHER' in out


# ------------------------------------------------------------------ remove_kwarg
def test_remove_kwarg_moves_a_comment_to_the_previous_arguments_line_and_keeps_the_closing_parenthesis():
    text = HEAD + 'board.place(\n    Part("c4"),\n    at=Edge.NORTH,\n    face=Face.FRONT,  # keep it on top\n)\n'
    out = run("remove_kwarg", text, "board.place", args={"name": "face"})
    assert out == HEAD + 'board.place(\n    Part("c4"),\n    at=Edge.NORTH,  # keep it on top\n)\n'


def test_remove_kwarg_joins_a_comment_to_the_one_already_on_the_previous_line():
    text = HEAD + 'board.place(\n    Part("c4"),\n    at=Edge.NORTH,  # beside\n    face=Face.FRONT,  # keep it on top\n)\n'
    out = run("remove_kwarg", text, "board.place", args={"name": "face"})
    assert out == HEAD + 'board.place(\n    Part("c4"),\n    at=Edge.NORTH,  # beside  # keep it on top\n)\n'


def test_remove_kwarg_of_a_middle_argument_moves_its_comment_up():
    text = HEAD + 'board.place(\n    Part("c4"),\n    at=Edge.NORTH,\n    face=Face.FRONT,  # keep it on top\n    why="x",\n)\n'
    out = run("remove_kwarg", text, "board.place", args={"name": "face"})
    assert out == HEAD + 'board.place(\n    Part("c4"),\n    at=Edge.NORTH,  # keep it on top\n    why="x",\n)\n'


def test_remove_kwarg_of_the_last_argument_without_a_trailing_comma_leaves_none():
    text = HEAD + 'board.place(\n    Part("c4"),\n    at=Edge.NORTH,\n    face=Face.FRONT  # keep it on top\n)\n'
    out = run("remove_kwarg", text, "board.place", args={"name": "face"})
    assert out == HEAD + 'board.place(\n    Part("c4"),\n    at=Edge.NORTH  # keep it on top\n)\n'


def test_remove_kwarg_of_the_first_argument_leaves_its_comment_on_a_line_of_its_own():
    text = HEAD + 'board.keepout(\n    face=Face.FRONT,  # keep it on top\n    name="a",\n)\n'
    out = run("remove_kwarg", text, "board.keepout", kind="keepout", key="a", args={"name": "face"})
    assert out == HEAD + 'board.keepout(\n    # keep it on top\n    name="a",\n)\n'


def test_remove_kwarg_on_one_line():
    text = HEAD + 'board.place(Part("c4"), at=Edge.NORTH, face=Face.FRONT)  # c4\n'
    assert run("remove_kwarg", text, "board.place", args={"name": "face"}) == HEAD + 'board.place(Part("c4"), at=Edge.NORTH)  # c4\n'
    assert run("remove_kwarg", text, "board.place", args={"name": "at"}) == HEAD + 'board.place(Part("c4"), face=Face.FRONT)  # c4\n'


def test_remove_kwarg_of_the_only_argument():
    text = HEAD + 'board.fanout(\n    depth=2.0,\n)\n'
    out = run("remove_kwarg", text, "board.fanout", kind="fanout", key="u1", args={"name": "depth"})
    assert out == HEAD + 'board.fanout()\n'


def test_remove_kwarg_not_there_is_refused():
    text = HEAD + 'board.place(Part("c4"))\n'
    with pytest.raises(se.EditRefused, match="no face="):
        run("remove_kwarg", text, "board.place", args={"name": "face"})


def test_comments_and_layout_outside_the_target_are_untouched_byte_for_byte():
    text = ('"""doc."""\nfrom placemat import board, Face, Part\n\n\n# --- section ---\nX = 1   # odd   spacing\n'
            'board.place(Part("c3"))   # before\n\n\nboard.place(\n    Part("c4"),\n    face=Face.FRONT,  # c4\n)\n'
            '\n\n# after\nboard.place( Part("c5") )\n')
    out = run("remove_kwarg", text, "face=Face.FRONT", args={"name": "face"})
    cut = text.index("board.place(\n    Part(\"c4\")")
    end = text.index("\n\n\n# after")
    assert out[:cut] == text[:cut] and out[out.index("\n\n\n# after"):] == text[end:]
    assert ast.dump(ast.parse(out)).count("c5") == 1


def test_a_keyword_added_and_removed_again_gives_the_text_back():
    for text in (HEAD + 'board.place(Part("c4"), at=Edge.NORTH)\n',
                 HEAD + 'board.place(\n    Part("c4"),\n    at=Edge.NORTH,\n)\n',
                 HEAD + 'board.place(\n    Part("c4"),\n    at=Edge.NORTH\n)\n'):
        added = run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE)
        assert run("remove_kwarg", added, "board.place", args={"name": "face"}) == text


# ------------------------------------------------------------------ set_arg and spelling
def test_set_arg_replaces_a_positional_argument():
    text = HEAD + 'board.label(Part("c4"), "text")\n'
    out = run("set_arg", text, "board.label", kind="label", args={"index": 1}, value={"str": "new"})
    assert out == HEAD + 'board.label(Part("c4"), "new")\n'


def test_an_item_is_written_as_the_script_spelled_it():
    text = HEAD + 'c1 = Part("c1")\nboard.place(c1, at=(0, 0))\nboard.place(Part("c4"))\n'
    t1 = Target("place", "c1", "script.py", line_of(text, "board.place(c1"))
    refs = {"C1": t1}
    value = {"form": "Beside", "args": [{"item": "C1"}, {"enum": "Edge.NORTH"}]}
    out = run("set_kwarg", text, 'Part("c4")', args={"name": "at"}, value=value, refs=refs)
    assert out.endswith('board.place(Part("c4"), at=Beside(c1, Edge.NORTH))\n')
    text = HEAD + 'board.place(Part("c1"), at=(0, 0))\nboard.place(Part("c4"))\n'
    refs = {"C1": Target("place", "c1", "script.py", line_of(text, 'Part("c1")'))}
    out = run("set_kwarg", text, 'Part("c4")', args={"name": "at"}, value=value, refs=refs)
    assert out.endswith('board.place(Part("c4"), at=Beside(Part("c1"), Edge.NORTH))\n')


def test_an_item_declared_in_another_scope_is_refused():
    text = HEAD + 'def one():\n    board.place(Part("c1"))\n\n\nboard.place(Part("c4"))\n'
    refs = {"C1": Target("place", "c1", "script.py", line_of(text, 'Part("c1")'))}
    value = {"form": "Beside", "args": [{"item": "C1"}, {"enum": "Edge.NORTH"}]}
    with pytest.raises(se.EditRefused, match="scope"):
        run("set_kwarg", text, 'Part("c4")', args={"name": "at"}, value=value, refs=refs)


def test_a_value_that_is_source_is_refused():
    text = HEAD + 'board.place(Part("c4"))\n'
    with pytest.raises(se.EditRefused, match="intent expression"):
        run("set_kwarg", text, "board.place", args={"name": "face"}, value="Face.EITHER")
