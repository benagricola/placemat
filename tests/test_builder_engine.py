"""Engine pieces the board builder added on top of the phase 5 ops (test_builder_ops.py): a polygon constant, the skeleton's
docstring, a block of statements and a comment in a region insert, rows counting as decided placements, find_board(wanted=)."""
import ast

import pytest

from placemat import project, script_edit as se
from tests.test_builder_ops import HEAD, ed, one


def one_of(edits, text, file="layout.py"):
    return se.apply_edits(edits, lambda p: text)[file][1]


def test_a_polygon_is_a_constant_list_of_pairs_with_its_comment():
    text = HEAD
    pts = [[0, 0], [60, 0], [60, 25], [35, 25], [35, 40], [0, 40]]
    out = one(ed("set_constant", args={"name": "BOARD_OUTLINE_MM", "comment": "The outline's vertices."}, value=pts), text)
    assert out == text + "\n# The outline's vertices.\nBOARD_OUTLINE_MM = [(0, 0), (60, 0), (60, 25), (35, 25), (35, 40), (0, 40)]\n"
    with pytest.raises(se.EditRefused, match="list of"):
        one(ed("set_constant", args={"name": "X", "comment": ""}, value=[[0, 0, 1]]), text)
    with pytest.raises(se.EditRefused, match="list of"):
        one(ed("set_constant", args={"name": "X", "comment": ""}, value=[[0, "a"]]), text)


def test_the_skeleton_docstring_is_the_name_and_the_description_or_the_name_and_layout():
    assert se.skeleton("Demo", "layout.").startswith('"""Demo: layout."""\nfrom placemat import board\n')
    assert se.skeleton("Demo", "").startswith('"""Demo layout."""\nfrom placemat import board\n')
    assert se.skeleton("Demo", '  has "quotes"  ').startswith('"""Demo: has \'quotes\'"""\n')


def test_a_block_is_inserted_as_consecutive_statements_in_one_edit():
    part = lambda k: {"form": "Part", "args": [{"str": k}]}
    link = {"form": "board.link", "args": [{"form": "PadRef", "args": [part("c1"), 1]}, {"form": "PadRef", "args": [part("u1"), {"str": "VIN"}]}],
            "kwargs": {"weight": {"enum": "LinkWeight.SHORT"}}}
    place = {"form": "board.place", "args": [{"form": "Part", "args": [{"str": "c1"}]}]}
    text = HEAD.replace("Beside, Edge, Part", "Beside, Edge, LinkWeight, PadRef, Part") + "board.rect(60, 40)\n"
    out = one(ed("insert_statement", args={"after": {"region": "searched"}, "comment": "Searched from their links."},
                 value={"block": [link, place]}), text)
    assert out.endswith('board.rect(60, 40)\n\n# Searched from their links.\nboard.link(PadRef(Part("c1"), 1), PadRef(Part("u1"), "VIN"), '
                        'weight=LinkWeight.SHORT)\nboard.place(Part("c1"))\n')
    ast.parse(out)


def test_the_comment_goes_above_the_first_statement_of_a_new_region_only():
    place = {"form": "board.place", "args": [{"form": "Part", "args": [{"str": "c1"}]}]}
    text = HEAD + "board.rect(60, 40)\n"
    first = one(ed("insert_statement", args={"after": {"region": "searched"}, "comment": "Searched from their links."}, value=place), text)
    place2 = {"form": "board.place", "args": [{"form": "Part", "args": [{"str": "c2"}]}]}
    second = one(ed("insert_statement", args={"after": {"region": "searched"}, "comment": "Searched from their links."}, value=place2), first)
    assert second == first + 'board.place(Part("c2"))\n'


def test_rows_count_as_decided_placements():
    row = {"form": "board.row", "args": [{"list": [{"form": "Part", "args": [{"str": "j1"}]}]}, {"enum": "Edge.WEST"}]}
    text = HEAD + 'board.rect(60, 40)\n\nboard.place(Part("c4"))\n'
    out = one(ed("insert_statement", args={"after": {"region": "decided"}}, value=row), text)
    assert out.index("board.row") < out.index('Part("c4")')
    place = {"form": "board.place", "args": [{"form": "Part", "args": [{"str": "c9"}]}], "kwargs": {"at": {"enum": "Edge.NORTH"}}}
    out2 = one(ed("insert_statement", args={"after": {"region": "decided"}}, value=place), out)
    assert out2.index("board.row") < out2.index('Part("c9")') < out2.index('Part("c4")')


def test_the_outline_is_a_new_region_with_a_blank_line_when_there_is_none():
    rect = {"form": "board.rect", "kwargs": {"width": {"name": "W"}, "height": {"num": 40}}}
    text = HEAD + "\nW = 60\n"
    out = one(ed("insert_statement", args={"after": {"region": "outline"}}, value=rect), text)
    assert out.endswith("W = 60\n\nboard.rect(width=W, height=40)\n")


def test_find_board_takes_the_name_of_a_script_that_does_not_exist_yet(tmp_path):
    (tmp_path / "two.zen").write_text('Board(name = "Alpha", layout_path = "layout/Alpha")\nBoard(name = "Beta", layout_path = "layout/Beta")\n')
    with pytest.raises(FileNotFoundError, match="declares 2 boards"):
        project.find_board(tmp_path)
    assert project.find_board(tmp_path, wanted="Beta").name == "Beta"


def test_a_declaration_an_expression_names_moves_with_the_text_the_edits_before_it_changed():
    from placemat.suggestions import Target
    text = HEAD + 'board.rect(60, 40)\nboard.place(Part("c2"), at=Edge.NORTH)\n'
    line = text.splitlines().index('board.place(Part("c2"), at=Edge.NORTH)') + 1
    const = ed("set_constant", args={"name": "GAP", "comment": "a gap"}, value=0.3)
    beside = {"form": "board.place", "args": [{"form": "Part", "args": [{"str": "c1"}]}],
              "kwargs": {"at": {"form": "Beside", "args": [{"item": "c2"}, {"enum": "Edge.SOUTH"}], "kwargs": {"gap": {"name": "GAP"}}}}}
    insert = ed("insert_statement", args={"after": {"region": "decided"}}, value=beside, refs={"c2": Target("place", "c2", "layout.py", line)})
    out = one_of([const, insert], text)
    assert 'board.place(Part("c1"), at=Beside(Part("c2"), Edge.SOUTH, gap=GAP))' in out
