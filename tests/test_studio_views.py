"""A followed command or a past run shown in place of the studio's own resolve acts on its own script, board and inputs: the found
store of a probe, the applied log behind Undo and Redo, the notes, Apply's refusal for another script, and the studio's own run
compare with no script chosen. A real fixture project, staged as a copy; the studio is not started and nothing is resolved."""
import json

import pytest

from placemat import notes as notes_mod, suggestions as sg
from placemat.studio import Studio, SuggestRefused
from tests import real_modules

PARENT = {"id": "s1a", "text": "search X", "how": "searched",
          "figure": {"name": "X_MM", "kind": "bisect", "lo": 0, "hi": 5, "edit": 0}}


@pytest.fixture
def project(tmp_path):
    """The usb5v module's script, in a project that holds logicsupply's too."""
    return real_modules.stage(tmp_path, "usb5v")


def _parent(script):
    return dict(PARENT, edits=[{"op": "set_constant", "args": {"name": "X_MM"}, "file": str(script)}])


def _follow(studio, script, cid=3, done=True):
    studio._on_channel(cid, {"ev": "hello", "pid": 99999999, "command": "preview", "script": str(script), "args": ["preview"]})
    studio._on_channel(cid, {"ev": "plan", "doc": {"items": [], "findings": [{"text": "f", "kind": "link", "suggestions": [_parent(script)]}]}})
    if done:
        studio._on_channel(cid, {"ev": "done", "record": ""})
    return {"kind": "cmd", "ref": str(cid)}


def _found(script):
    found = sg.Suggestion("set it to 2 mm", (sg.Edit("set_constant", None, {"name": "X_MM"}, 2.0, {}, str(script)),), id="s1a.1")
    sg.keep(script.parent, script, "studio, cmd 3", sg.from_json([_parent(script)]))
    sg.add_found(script.parent, script, found)


def test_what_a_probe_found_for_a_followed_commands_suggestion_is_read_from_its_scripts_store(project):
    _found(project)
    s = Studio(None, port=0, open_browser=False, root=project.parents[2])
    view = _follow(s, project)
    assert s.suggest_found("s1a.1", view)["id"] == "s1a.1"
    rec, pool, finding, past = s._suggestion(None, "s1a.1", view)
    assert past.kind == "cmd" and "s1a.1" in [x.id for x in pool] and finding["text"] == "f"
    with pytest.raises(SuggestRefused):
        s.suggest_found("s1a.1")                        # no view: the studio has no script, so no store


def test_with_the_script_chosen_a_view_of_it_finds_what_a_probe_found(project):
    _found(project)
    s = Studio(project, port=0, open_browser=False)
    view = _follow(s, project)
    assert s._suggestion(None, "s1a.1", view)[3].script == str(project)


def test_apply_of_a_view_of_another_script_is_refused_as_try_is(project):
    other = project.parents[1] / "logicsupply" / "LogicSupply_layout.py"
    s = Studio(project, port=0, open_browser=False)
    view = _follow(s, other)
    with pytest.raises(SuggestRefused) as e:
        s.suggest_apply(None, "s1a", view)
    assert e.value.status == 409 and "choose it" in str(e.value) and "LogicSupply_layout.py" in str(e.value)


def test_undo_and_redo_read_the_views_board_log_and_with_no_log_say_nothing_was_applied(project):
    log = sg.log_path(project.parent)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"seq": 1, "op": "apply", "id": "s9a", "text": "earlier apply", "at": "x", "files": []}) + "\n")
    s = Studio(None, port=0, open_browser=False, root=project.parents[2])
    view = _follow(s, project)
    assert [a["id"] for a in s.applied_state(view)["applied"]] == ["s9a"]
    assert s.applied_state(None)["applied"] == []
    with pytest.raises(SuggestRefused) as e:
        s.suggest_undo()
    assert e.value.status == 409 and str(e.value) == "nothing has been applied here"
    with pytest.raises(SuggestRefused) as e:
        s.suggest_redo()
    assert e.value.status == 409


def test_notes_of_every_board_are_read_with_no_script_chosen_each_with_its_scripts_path(project):
    other = project.parents[1] / "logicsupply" / "LogicSupply_layout.py"
    notes_mod.add(project.parent, project.name, "look here", None, "agent")
    notes_mod.add(other.parent, other.name, "and here", None, "agent")
    s = Studio(None, port=0, open_browser=False, root=project.parents[2])
    s.scripts()
    s._tick(0.0)
    got = {n["description"]: n["path"] for n in s.notes_list()}
    assert got == {"look here": str(project.parent / project.name), "and here": str(other.parent / other.name)}
    assert json.loads(s.hello()[0][1])["notes"] == s.notes_list()


def test_a_run_compare_with_no_script_chosen_is_none_not_a_crash(project):
    s = Studio(None, port=0, open_browser=False, root=project.parents[2])
    assert s.compare_run("abcd1234") is None and s.run_doc("abcd1234") is None


def test_a_failed_command_says_what_failed_and_keeps_where(project):
    s = Studio(None, port=0, open_browser=False, root=project.parents[2])
    s._on_channel(4, {"ev": "hello", "pid": 99999998, "command": "run", "script": str(project), "args": ["run"]})
    s._on_channel(4, {"ev": "error", "kind": "run_failure", "failure": "script", "detail": "NameError: x", "file": str(project), "line": 12})
    d = s.cmd_detail(4)
    assert "NameError: x" in d["summary"]["message"]
    assert [(e["file"], e["line"]) for e in d["events"] if e.get("ev") == "error"] == [(str(project), 12)]
