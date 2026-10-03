"""Several edits as one suggestion: applied together or not at all, in any order, one log entry, one undo."""
import json

import pytest

from placemat import script_edit as se, suggestions as sg
from placemat.suggestions import Edit, Suggestion, Target
from tests.test_script_edit import FACE, HEAD, line_of

TEXT = HEAD + ('board.row([Part("r1"), Part("r2"), Part("r3")], Edge.NORTH)\n'
               'board.place(Part("c4"))\n'
               'board.place(Part("c5"))\n')


def e(op, needle, kind="place", key="c4", args=None, value=None, digest=""):
    return Edit(op, Target(kind, key, "layout.py", line_of(TEXT, needle), digest=digest), args or {}, value)


def read(path):
    if path != "layout.py":
        raise OSError(path)                       # a module the script imports: not among these files
    return TEXT


def test_two_edits_to_one_file_are_applied_whatever_their_order():
    a = e("set_kwarg", 'Part("c4")', args={"name": "face"}, value=FACE)
    b = e("insert_statement", 'Part("c5")', key="c5", value={"form": "board.place", "args": [{"form": "Part", "args": [{"str": "c6"}]}]})
    one = se.apply_edits([a, b], read)["layout.py"]
    two = se.apply_edits([b, a], read)["layout.py"]
    assert one == two and one[0] == TEXT
    assert 'board.place(Part("c4"), face=Face.EITHER)' in one[1] and one[1].endswith('board.place(Part("c6"))\n')


def test_an_edit_that_adds_a_constant_above_does_not_move_the_others_off_their_lines():
    a = e("set_kwarg", 'Part("c5")', key="c5", args={"name": "face"}, value=FACE)
    b = e("set_kwarg", 'Part("c4")', args={"name": "gap"},
          value={"const": {"name": "C4_GAP", "value": 0.3, "comment": "measured", "scope": "cell"}})
    out = se.apply_edits([a, b], read)["layout.py"][1]
    assert "C4_GAP = 0.3" in out and 'board.place(Part("c4"), gap=C4_GAP)' in out and 'Part("c5"), face=Face.EITHER' in out


def test_a_removal_from_a_list_and_an_inserted_statement_are_one_change():
    a = e("edit_list", "board.row", kind="row", key="r1", args={"arg": 0, "action": "remove"},
          value={"form": "Part", "args": [{"str": "r2"}]})
    b = e("insert_statement", 'Part("c5")', key="c5", value={"form": "board.place", "args": [{"form": "Part", "args": [{"str": "r2"}]}]})
    out = se.apply_edits([a, b], read)["layout.py"][1]
    assert 'board.row([Part("r1"), Part("r3")], Edge.NORTH)' in out and out.endswith('board.place(Part("r2"))\n')


def test_one_that_cannot_be_made_leaves_the_others_unmade():
    a = e("set_kwarg", 'Part("c4")', args={"name": "face"}, value=FACE)
    b = e("remove_kwarg", 'Part("c5")', key="c5", args={"name": "why"})            # c5 has no why=
    with pytest.raises(se.EditRefused):
        se.apply_edits([a, b], read)


def test_a_stale_digest_on_any_edit_refuses_all():
    a = e("set_kwarg", 'Part("c4")', args={"name": "face"}, value=FACE, digest=se.digest(TEXT))
    b = e("set_kwarg", 'Part("c5")', key="c5", args={"name": "face"}, value=FACE, digest="not the file's")
    with pytest.raises(se.StaleEdit):
        se.apply_edits([a, b], read)


def test_the_suggestion_record_carries_edits_and_how():
    a = e("set_kwarg", 'Part("c4")', args={"name": "face"}, value=FACE)
    b = e("set_kwarg", 'Part("c5")', key="c5", args={"name": "face"}, value=FACE)
    s = Suggestion("both", (a, b), 1, "face", "s1a")
    d = json.loads(json.dumps(s.to_json()))
    assert [x["op"] for x in d["edits"]] == ["set_kwarg", "set_kwarg"] and d["how"] == "instant" and "edit" not in d
    assert Suggestion.from_json(d) == s
    assert Suggestion.from_json({"text": "old", "edit": a.to_json()}).edits == (a,)       # a record from before edits


def test_a_multi_edit_suggestion_applies_atomically_and_one_undo_reverts_it(tmp_path):
    script = tmp_path / "layout.py"
    script.write_text(TEXT)
    d = se.digest(TEXT)

    def make(needle, key):
        return Edit("set_kwarg", Target("place", key, str(script), line_of(TEXT, needle), 1, d), {"name": "face"}, FACE)
    s = Suggestion("both", (make('Part("c4")', "c4"), make('Part("c5")', "c5")), 1, "face", "s1a", {str(script): d})
    log = tmp_path / "applied.jsonl"
    done = sg.apply_suggestion([s], "s1a", root=tmp_path, log=log)
    after = script.read_text()
    assert after.count("face=Face.EITHER") == 2 and set(done.files) == {str(script)}
    assert len(log.read_text().splitlines()) == 1
    sg.undo_last(log, root=tmp_path)
    assert script.read_text() == TEXT


def test_a_multi_edit_suggestion_that_fails_part_way_writes_nothing(tmp_path):
    script = tmp_path / "layout.py"
    script.write_text(TEXT)
    d = se.digest(TEXT)
    ok = Edit("set_kwarg", Target("place", "c4", str(script), line_of(TEXT, 'Part("c4")'), 1, d), {"name": "face"}, FACE)
    bad = Edit("remove_kwarg", Target("place", "c5", str(script), line_of(TEXT, 'Part("c5")'), 1, d), {"name": "why"})
    s = Suggestion("both", (ok, bad), 1, "face", "s1a", {str(script): d})
    with pytest.raises(sg.EditRefused):
        sg.apply_suggestion([s], "s1a", dry_run=True)
    with pytest.raises(sg.EditRefused):
        sg.apply_suggestion([s], "s1a", root=tmp_path, log=tmp_path / "applied.jsonl")
    assert script.read_text() == TEXT and not (tmp_path / "applied.jsonl").exists()
