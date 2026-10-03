"""Notes: records an agent leaves for the studio (`placemat studio note`), the file they are kept in, and the studio reading it."""
import json
import os
import time

import pytest

from placemat import notes
from placemat.cli import main
from placemat.studio import Studio
from tests import real_modules


def test_a_target_is_one_of_a_point_an_item_or_a_pad_and_a_bad_one_is_refused():
    assert notes.target_of() is None
    assert notes.target_of(at="12.5,-4") == {"kind": "point", "x": 12.5, "y": -4.0}
    assert notes.target_of(item="c_cpu") == {"kind": "item", "name": "c_cpu"}
    assert notes.target_of(pad="U1.3") == {"kind": "pad", "ref": "U1", "pad": "3"}
    assert notes.target_of(pad="X.Y.12") == {"kind": "pad", "ref": "X.Y", "pad": "12"}
    for bad in ({"at": "12"}, {"at": "a,b"}, {"pad": "U1"}, {"at": "1,2", "item": "c"}):
        with pytest.raises(ValueError):
            notes.target_of(**bad)


def test_notes_are_appended_as_records_bounded_and_expire(tmp_path):
    a = notes.add(tmp_path, "x_layout.py", "trying   c_cpu\nfurther west", {"kind": "item", "name": "c_cpu"}, "agent-1", now=1000.0)
    assert a["description"] == "trying c_cpu further west" and a["from"] == "agent-1" and a["script"] == "x_layout.py" and a["v"] == 1
    for n in range(7):
        notes.add(tmp_path, "x_layout.py" if n % 2 else "y_layout.py", "note %d" % n, None, "", keep=5, now=2000.0 + n)
    path = notes.path_for(tmp_path)
    assert path.parts[-4:] == (".placemat", "views", "studio", "notes.jsonl")
    got = notes.read(tmp_path)
    assert [n["description"] for n in got] == ["note %d" % n for n in range(2, 7)]                  # the file keeps the last five
    assert [n["description"] for n in notes.read(tmp_path, "x_layout.py")] == ["note 3", "note 5"]
    path.write_text(path.read_text() + "not json\n{}\n")
    assert len(notes.read(tmp_path)) == 5                                                           # a line that is not a note is skipped
    assert [n["description"] for n in notes.live(got, 3, now=2007.0)] == ["note 4", "note 5", "note 6"] and len(notes.live(got, 0, now=9e9)) == 5
    with pytest.raises(ValueError):
        notes.add(tmp_path, "x_layout.py", "   ")


def test_the_author_is_given_else_from_the_environment_else_the_login(monkeypatch):
    monkeypatch.delenv("PLACEMAT_FROM", raising=False)
    assert notes.author("me") == "me"
    monkeypatch.setenv("PLACEMAT_FROM", "agent-7")
    assert notes.author() == "agent-7"
    monkeypatch.delenv("PLACEMAT_FROM")
    assert notes.author()


@pytest.fixture
def staged(tmp_path):
    return real_modules.stage(tmp_path, "usb5v")


def test_the_command_appends_a_note_for_the_script_and_refuses_what_it_cannot_place(staged, monkeypatch):
    monkeypatch.delenv("PLACEMAT_FROM", raising=False)
    board_dir = staged.parent
    assert main(["studio", "note", "trying c_hf1 further west", "--item", "c_hf1", "--from", "agent-1", "--script", str(staged)]) == 0
    monkeypatch.chdir(staged.parent)
    assert main(["studio", "note", "look here", "--at", "3.5,-2"]) == 0                      # no --script: the project's only layout script
    assert [n["target"] for n in notes.read(board_dir) if n["description"] == "look here"] == [{"kind": "point", "x": 3.5, "y": -2.0}]
    (rec,) = [n for n in notes.read(board_dir) if n["description"].startswith("trying")]
    assert rec["script"] == staged.name and rec["from"] == "agent-1" and rec["target"] == {"kind": "item", "name": "c_hf1"}
    assert main(["studio", "note", "x", "--at", "1,2", "--item", "c", "--script", str(staged)]) == 2
    assert main(["studio", "note", "x", "--at", "nope", "--script", str(staged)]) == 2
    assert main(["studio", "note", "--script", str(staged)]) == 2
    assert main(["studio", "note", "x", "--script", str(staged.parent / "nothing.py")]) == 2


def test_the_studio_tells_its_pages_of_a_new_note_for_its_script_and_gives_a_late_page_the_ones_that_have_not_expired(staged):
    s = Studio(staged, port=0, open_browser=False)
    q = s.hub.subscribe(lambda: [])
    old = notes.add(staged.parent, staged.name, "long ago", None, "a", now=time.time() - 7200)
    other = notes.add(staged.parent, "other_layout.py", "for another script", None, "a")
    s._check_notes()
    assert not [1 for n, t in list(q.queue) if n == "note" and json.loads(t)["description"] == "for another script"]
    fresh = notes.add(staged.parent, staged.name, "trying c_hf1 further west", {"kind": "point", "x": 1.0, "y": 2.0}, "agent-1")
    s._check_notes()
    seen = []
    while not q.empty():
        name, text = q.get_nowait()
        if name == "note":
            seen.append(json.loads(text))
    assert [n["id"] for n in seen if n["id"] == fresh["id"]] == [fresh["id"]] and old["id"] in [n["id"] for n in seen]
    s._check_notes()
    assert q.empty()                                                                              # nothing new: nothing sent twice
    data = json.loads(s.hello()[0][1])
    assert [n["id"] for n in data["notes"]] == [fresh["id"]] and data["note_age_s"] == 3600       # the expired one is not offered
    assert other["id"] not in [n["id"] for n in data["notes"]]
