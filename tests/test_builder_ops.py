"""The engine's pieces the board builder needs (docs/superpowers/specs/2026-10-03-studio-board-builder-design.md): create_file,
region anchors with bind, ensure_import, remove_constant, read_intent, move_statement, apply_edits, redo. Text in, text out."""
import json

import pytest

from placemat import facts, script_edit as se, suggestions as sg
from placemat.suggestions import Edit, Target
from tests.test_script_edit import line_of

HEAD = '"""A board."""\nfrom placemat import board, Beside, Edge, Part\n'


def ed(op, file="layout.py", target=None, args=None, value=None, refs=None):
    return Edit(op, target, args or {}, value, refs or {}, file)


def one(edit, text, file="layout.py"):
    out = se.apply_edits([edit], lambda p: text if p == file else (_ for _ in ()).throw(OSError(p)))
    return out[file][1]


# ------------------------------------------------------------------ ensure_import
def test_names_are_added_to_the_placemat_import_board_first_and_the_rest_in_order():
    out = one(ed("ensure_import", args={"names": ["Along", "Cutout"]}), HEAD + "board.rect(60, 40)\n")
    assert out == '"""A board."""\nfrom placemat import board, Along, Beside, Cutout, Edge, Part\nboard.rect(60, 40)\n'


def test_a_name_already_imported_and_a_star_import_change_nothing():
    assert se.apply_edits([ed("ensure_import", args={"names": ["Edge"]})], lambda p: HEAD) == {}
    star = '"""A."""\nfrom placemat import *\n'
    assert se.apply_edits([ed("ensure_import", args={"names": ["Edge"]})], lambda p: star) == {}


def test_a_parenthesised_import_is_rewritten_in_the_same_shape():
    text = '"""A."""\nfrom placemat import (board, Edge,\n                      Part)\n\nboard.rect(60, 40)\n'
    out = one(ed("ensure_import", args={"names": ["Beside"]}), text)
    assert out.startswith('"""A."""\nfrom placemat import (board, Beside, Edge,\n                      Part)\n')
    assert out.endswith("\nboard.rect(60, 40)\n")


def test_a_script_without_a_placemat_import_gets_one_after_the_docstring():
    out = one(ed("ensure_import", args={"names": ["Part", "board"]}), '"""A."""\nx = 1\n')
    assert out == '"""A."""\nfrom placemat import board, Part\nx = 1\n'


def test_an_import_with_a_comment_inside_is_refused():
    with pytest.raises(se.EditRefused, match="comment"):
        one(ed("ensure_import", args={"names": ["Along"]}), '"""A."""\nfrom placemat import (board,  # the board\n    Edge)\n')


def test_an_import_then_a_statement_that_needs_it_are_one_apply():
    text = HEAD + "board.rect(60, 40)\n"
    value = {"form": "board.place", "args": [{"form": "Part", "args": [{"str": "c1"}]}],
             "kwargs": {"at": {"form": "OnEdge", "args": [{"enum": "Edge.NORTH"}], "kwargs": {"along": {"enum": "Along.MID"}}}}}
    out = se.apply_edits([ed("ensure_import", args={"names": ["Along", "OnEdge"]}),
                          ed("insert_statement", args={"after": {"region": "outline"}}, value=value)],
                         lambda p: text)["layout.py"][1]
    assert "from placemat import board, Along, Beside, Edge, OnEdge, Part" in out
    assert 'board.place(Part("c1"), at=OnEdge(Edge.NORTH, along=Along.MID))' in out


# ------------------------------------------------------------------ remove_constant
CONST = HEAD + "\n# measured by a run\nC4_GAP_MM = 0.3\nBOARD_W = 60\n\nboard.rect(BOARD_W, 40)\nboard.place(Part(\"c4\"))\n"


def test_an_unused_constant_goes_with_the_comment_above_it():
    out = one(ed("remove_constant", args={"name": "C4_GAP_MM"}), CONST)
    assert out == HEAD + "\nBOARD_W = 60\n\nboard.rect(BOARD_W, 40)\nboard.place(Part(\"c4\"))\n"


def test_a_constant_something_still_reads_is_not_removed():
    with pytest.raises(se.EditRefused, match="uses"):
        one(ed("remove_constant", args={"name": "BOARD_W"}), CONST)
    with pytest.raises(se.EditRefused, match="no constant"):
        one(ed("remove_constant", args={"name": "NOPE"}), CONST)


# ------------------------------------------------------------------ region anchors and bind
def ins(region, text, bind=None, call='board.place(Part("c9"))'):
    args = {"after": {"region": region}}
    if bind:
        args["bind"] = bind
    value = {"form": "board.place", "args": [{"form": "Part", "args": [{"str": "c9"}]}]}
    return one(ed("insert_statement", args=args, value=value), text)


BODY = (HEAD + "\nGAP = 0.3\n\nboard.rect(60, 40)\nnorth = board.edge(facing=Edge.NORTH)\n"
        'board.place(Part("c1"), at=Beside(Part("c2"), Edge.NORTH))\n'
        'board.place(Part("c3"), at=Beside(Part("c1"), Edge.EAST))\n\nboard.place(Part("c4"))\n')


def test_the_header_region_is_after_the_imports():
    assert ins("header", BODY).startswith(HEAD + 'board.place(Part("c9"))\n')


def test_the_constants_region_is_after_the_constants_block():
    out = ins("constants", BODY)
    assert "GAP = 0.3\nboard.place(Part(\"c9\"))\n" in out


def test_the_outline_region_is_after_the_outline_and_the_edge_bindings_that_follow_it():
    out = ins("outline", BODY)
    assert "north = board.edge(facing=Edge.NORTH)\nboard.place(Part(\"c9\"))\nboard.place(Part(\"c1\")" in out


def test_the_decided_region_ends_at_the_last_placement_that_says_where():
    out = ins("decided", BODY)
    assert out.index('Part("c3")') < out.index('Part("c9")') < out.index('Part("c4"))')


def test_the_searched_region_is_after_the_last_bare_place_and_starts_after_a_blank_line_when_new():
    assert ins("searched", BODY).endswith('board.place(Part("c4"))\nboard.place(Part("c9"))\n')
    no_search = BODY.replace('\nboard.place(Part("c4"))\n', "")
    out = ins("searched", no_search)
    assert out.endswith('Edge.EAST))\n\nboard.place(Part("c9"))\n')


def test_a_statement_may_be_bound_to_a_name_the_script_does_not_have():
    value = {"form": "board.edge", "kwargs": {"facing": {"enum": "Edge.SOUTH"}}}
    out = one(ed("insert_statement", args={"after": {"region": "outline"}, "bind": "south"}, value=value), BODY)
    assert "north = board.edge(facing=Edge.NORTH)\nsouth = board.edge(facing=Edge.SOUTH)\n" in out
    with pytest.raises(se.EditRefused, match="north"):
        one(ed("insert_statement", args={"after": {"region": "outline"}, "bind": "north"}, value=value), BODY)


def test_a_region_a_script_does_not_have_falls_back_to_the_one_before_it():
    assert ins("decided", HEAD + "board.rect(60, 40)\n").endswith("board.rect(60, 40)\nboard.place(Part(\"c9\"))\n")


# ------------------------------------------------------------------ read_intent
def read(text, needle="board.place", kind="place", key="c1", name="at"):
    t = Target(kind, key, "layout.py", line_of(text, needle))
    return se.read_intent(text, t, name)


def test_a_relation_is_read_back_as_the_intent_expression_that_writes_it():
    text = HEAD + 'board.place(Part("c1"), at=Beside(Part("c2"), Edge.NORTH, gap=GAP))\n'
    got = read(text)
    assert got == {"form": "Beside", "args": [{"item": "c2"}, {"enum": "Edge.NORTH"}], "kwargs": {"gap": {"name": "GAP"}}}


def test_read_then_rendered_is_the_source_it_came_from():
    text = HEAD + 'board.place(Part("c1"), at=Beside(Part("c2"), Edge.NORTH, 0.5))\n'
    got = read(text)
    out = one(ed("set_kwarg", target=Target("place", "c1", "layout.py", line_of(text, "board.place")),
                 args={"name": "at"}, value=got, refs={"c2": Target("place", "c2", "layout.py", 3)}), text.replace(
                     'board.place(Part("c1")', 'board.place(Part("c2"), at=Edge.NORTH)\nboard.place(Part("c1")'))
    assert out


def test_a_coordinate_or_arithmetic_is_by_hand():
    assert read(HEAD + 'board.place(Part("c1"), at=Location(10, 20))\n') is None
    assert read(HEAD + 'board.place(Part("c1"), at=Centre(10, 20))\n') is None
    assert read(HEAD + 'board.place(Part("c1"), at=Beside(Part("c2"), Edge.NORTH, gap=GAP * 2))\n') is None


def test_an_argument_the_call_does_not_give_is_absent_not_by_hand():
    assert read(HEAD + 'board.place(Part("c1"))\n') == {"absent": True}


def test_an_intent_centre_is_read():
    text = HEAD + 'board.place(Part("c1"), at=Centre(X(PadRef(Part("u1"), 3)), None))\n'
    got = read(text)
    assert got["form"] == "Centre" and got["args"][1] is None and got["args"][0]["form"] == "X"


# ------------------------------------------------------------------ move_statement
MOVE = HEAD + 'board.place(Part("c1"), at=Edge.NORTH)  # first\nboard.place(Part("c2"), at=Edge.EAST)\nboard.place(Part("c3"), at=Edge.SOUTH)\n'


def move(key, after=None, before=None):
    t = Target("place", key, "layout.py", line_of(MOVE, 'Part("%s")' % key))
    other = after or before
    args = {"after" if after else "before": Target("place", other, "layout.py", line_of(MOVE, 'Part("%s")' % other)).to_json()}
    return one(ed("move_statement", target=t, args=args), MOVE)


def test_a_statement_moves_after_another_and_takes_its_trailing_comment():
    out = move("c1", after="c3")
    assert out == HEAD + 'board.place(Part("c2"), at=Edge.EAST)\nboard.place(Part("c3"), at=Edge.SOUTH)\nboard.place(Part("c1"), at=Edge.NORTH)  # first\n'


def test_a_statement_moves_before_another():
    out = move("c3", before="c1")
    assert out.splitlines()[2].startswith('board.place(Part("c3")')


def test_moving_a_statement_changes_only_the_order():
    import ast
    out = move("c2", after="c3")
    a = sorted(ast.dump(s) for s in ast.parse(MOVE).body)
    b = sorted(ast.dump(s) for s in ast.parse(out).body)
    assert a == b and out != MOVE


# ------------------------------------------------------------------ skeleton, create_file, apply_edits, redo
def test_the_skeleton_is_a_script_that_declares_the_outline():
    text = se.skeleton("main", "the main board", {"form": "board.rect", "args": [{"num": 60}, {"num": 40}]})
    assert text.startswith('"""main: the main board"""\nfrom placemat import board\n') and text.endswith("board.rect(60, 40)\n")
    import ast
    ast.parse(text)


def test_create_file_writes_the_skeleton_and_refuses_a_file_that_exists(tmp_path):
    path = tmp_path / "new.py"
    text = se.skeleton("main", "d", {"form": "board.rect", "args": [{"num": 60}, {"num": 40}]})
    e = ed("create_file", file=str(path), args={"text": text})
    done = sg.apply_edits([e], {str(path): ""}, root=tmp_path, log=tmp_path / "applied.jsonl", label="New board", source="builder")
    assert path.read_text() == text and done.files[str(path)].before is None
    entry = json.loads((tmp_path / "applied.jsonl").read_text().splitlines()[0])
    assert entry["files"][0]["before"] is None and entry["source"] == "builder" and entry["text"] == "New board"
    with pytest.raises(sg.StaleSuggestion):
        sg.apply_edits([e], {str(path): ""}, root=tmp_path, log=tmp_path / "applied.jsonl")


def test_undo_removes_a_created_file_and_redo_makes_it_again(tmp_path):
    path = tmp_path / "new.py"
    log = tmp_path / "applied.jsonl"
    e = ed("create_file", file=str(path), args={"text": "x = 1\n"})
    sg.apply_edits([e], {str(path): ""}, root=tmp_path, log=log, label="New", source="builder")
    sg.undo_last(log, root=tmp_path)
    assert not path.exists()
    done = sg.redo_last(log, root=tmp_path)
    assert path.read_text() == "x = 1\n" and done.text == "New"
    with pytest.raises(sg.NothingToRedo):
        sg.redo_last(log, root=tmp_path)


def _script(tmp_path, text="board.place(Part(\"c1\"))\n"):
    p = tmp_path / "layout.py"
    p.write_text(HEAD + text)
    return p


def _face(path, n):
    text = path.read_text()
    t = Target("place", "c1", str(path), line_of(text, "board.place"), 1, se.digest(text))
    return ed("set_kwarg", file="", target=t, args={"name": "priority"}, value={"num": n}), {str(path): se.digest(text)}


def test_redo_reapplies_the_last_undone_apply_and_a_new_apply_drops_what_could_be_redone(tmp_path):
    path = _script(tmp_path)
    log = tmp_path / "applied.jsonl"
    e1, d1 = _face(path, 1)
    sg.apply_edits([e1], d1, root=tmp_path, log=log, label="one", source="builder")
    after1 = path.read_text()
    sg.undo_last(log, root=tmp_path)
    assert "priority" not in path.read_text()
    sg.redo_last(log, root=tmp_path)
    assert path.read_text() == after1
    sg.undo_last(log, root=tmp_path)
    e2, d2 = _face(path, 2)
    sg.apply_edits([e2], d2, root=tmp_path, log=log, label="two", source="builder")
    with pytest.raises(sg.NothingToRedo):
        sg.redo_last(log, root=tmp_path)


def test_redo_refuses_when_the_file_was_edited_since_the_undo(tmp_path):
    path = _script(tmp_path)
    log = tmp_path / "applied.jsonl"
    e1, d1 = _face(path, 1)
    sg.apply_edits([e1], d1, root=tmp_path, log=log, label="one", source="builder")
    sg.undo_last(log, root=tmp_path)
    path.write_text(path.read_text() + "# by hand\n")
    with pytest.raises(sg.RedoRefused):
        sg.redo_last(log, root=tmp_path)


def test_apply_suggestion_and_apply_edits_are_one_path(tmp_path, monkeypatch):
    path = _script(tmp_path)
    e1, d1 = _face(path, 1)
    s = sg.Suggestion("set it", (e1,), 1, "x", "s1a", d1)
    seen = []
    real = sg.apply_edits

    def spy(*a, **k):
        seen.append((a, k))
        return real(*a, **k)
    monkeypatch.setattr(sg, "apply_edits", spy)
    sg.apply_suggestion([s], "s1a", root=tmp_path, log=tmp_path / "applied.jsonl")
    assert len(seen) == 1 and seen[0][1]["label"] == "set it"


# ------------------------------------------------------------------ the confirm edit
def test_confirming_is_a_text_function_the_apply_path_can_log():
    text = '[place]\nstep = 0.1\n'
    out = facts.confirmed_text(text, "abc123", "layout.py")
    assert out.startswith(text) and '[facts.boards]\n"layout.py" = "abc123"\n' in out
    done = se.apply_edits([ed("confirm_facts", file="placemat.toml", args={"digest": "abc123", "key": "layout.py"})],
                          lambda p: text)["placemat.toml"]
    assert done == (text, out)
