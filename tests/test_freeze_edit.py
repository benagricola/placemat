"""freeze's editor: one call's keyword arguments changed by the positions
ast gives, every other byte of the script left as it was."""
import ast

import pytest

from placemat.freeze import FreezeError, edit_call, ensure_imports

AT = 'Near(PadRef(Part("u1"), 3).offset(0.4, -1.2), radius=0)'


def _call_kwargs(src, line):
    call = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and n.lineno == line)
    return {k.arg: ast.unparse(k.value) for k in call.keywords}


def test_a_one_line_call_gains_its_arguments_and_nothing_else_changes():
    src = '# a board\nboard.place(Part("r1"))   # the pull-up\nboard.place(Part("r2"))\n'
    out = edit_call(src, 2, {"at": AT, "rotation": "90"})
    assert out.splitlines()[0] == "# a board" and out.splitlines()[2] == 'board.place(Part("r2"))'
    assert out.splitlines()[1].endswith("   # the pull-up")
    assert _call_kwargs(out, 2) == {"at": ast.unparse(ast.parse(AT).body[0].value), "rotation": "90"}


def test_a_call_over_several_lines_keeps_its_layout():
    src = ('board.place(Part("r1"),\n'
           '            why="the pull-up")\n'
           'x = 1\n')
    out = edit_call(src, 1, {"at": AT, "rotation": "90"})
    ast.parse(out)
    lines = out.splitlines()
    assert lines[0] == 'board.place(Part("r1"),' and lines[-1] == "x = 1"
    assert all(l.startswith("            ") for l in lines[1:-1])          # new arguments at the call's indent
    assert _call_kwargs(out, 1)["why"] == "'the pull-up'"


def test_a_trailing_comma_and_a_comment_inside_the_arguments_survive():
    src = ('board.place(\n'
           '    Part("r1"),   # the first pull-up\n'
           '    why="x",\n'
           ')\n')
    out = edit_call(src, 1, {"at": AT, "rotation": "90"})
    ast.parse(out)
    assert "# the first pull-up" in out
    assert set(_call_kwargs(out, 1)) == {"why", "at", "rotation"}


def test_a_line_with_non_ascii_text_is_edited_at_the_right_place():
    src = 'board.place(Part("r1"), why="10 kΩ pull-up, 3.3 V")   # µC strap\n'
    out = edit_call(src, 1, {"rotation": "180"})
    assert out.endswith('why="10 kΩ pull-up, 3.3 V", rotation=180)   # µC strap\n')


def test_existing_at_and_rotation_are_replaced_and_rotations_removed():
    src = 'board.place(Part("r1"), at=Near(Location(1, 2)), rotation=0, rotations=(0, 90), why="w")\n'
    out = edit_call(src, 1, {"at": AT, "rotation": "90"}, remove=("rotations",))
    kw = _call_kwargs(out, 1)
    assert set(kw) == {"at", "rotation", "why"} and kw["rotation"] == "90" and "radius=0" in kw["at"]
    assert out.count("at=") == 1


@pytest.mark.parametrize("src", [
    'for k in KEYS:\n    board.place(Part(k))\n',
    'def put(k):\n    board.place(Part(k))\n',
    'board.place(Part("r1"), **EXTRA)\n',
])
def test_a_call_freeze_cannot_edit_for_one_item_is_refused_with_its_line(src):
    line = 2 if src.startswith(("for", "def")) else 1
    with pytest.raises(FreezeError, match="line %d" % line):
        edit_call(src, line, {"rotation": "90"})


def test_imports_are_added_to_the_placemat_import_and_nothing_else():
    src = '"""doc"""\nfrom placemat import board, Part  # names\nimport math\n'
    out = ensure_imports(src, ["Near", "PadRef", "Part"])
    assert out.splitlines()[1] == "from placemat import board, Part, Near, PadRef  # names"
    assert ensure_imports(out, ["Near"]) == out
    bare = ensure_imports('import math\n', ["Near"])
    assert bare == 'import math\nfrom placemat import Near\n'
