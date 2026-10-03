"""apply_suggestion: the digest check, the atomic write, the applied log, and the undo stack."""
import json
import os
import stat

import pytest

from placemat import suggestions as sg
from tests.suggest_support import resolve, suggestions_of
from tests.test_suggestions_link_over import SCRIPT


@pytest.fixture
def plan_and_path(tmp_path):
    board, plan, path = resolve(tmp_path, SCRIPT)
    return plan, path


def pick(plan, startswith):
    return next(s for s in suggestions_of(plan) if s.text.startswith(startswith))


def test_a_dry_run_returns_the_diff_and_the_lines_and_writes_nothing(tmp_path, plan_and_path):
    plan, path = plan_and_path
    before = path.read_text()
    s = pick(plan, "Pull c1")
    done = sg.apply_suggestion(suggestions_of(plan), s.id, dry_run=True)
    assert done.dry_run and done.id == s.id and done.text == s.text
    change = done.files[str(path)]
    assert change.before == before and "weight=LinkWeight.PREFER" in change.after
    assert "weight=LinkWeight.PREFER" in done.diff() and done.diff().startswith("--- a/")
    assert change.old_lines == [6] and change.new_lines == [6]
    assert path.read_text() == before


def test_apply_writes_the_file_atomically_keeping_its_mode_and_logs_it(tmp_path, plan_and_path):
    plan, path = plan_and_path
    os.chmod(path, 0o640)
    s = pick(plan, "Pull c1")
    log = tmp_path / ".placemat" / "applied.jsonl"
    done = sg.apply_suggestion(suggestions_of(plan), s.id, root=tmp_path, log=log, now="2026-10-03T10:00:00")
    assert path.read_text() == done.files[str(path)].after
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    (entry,) = [json.loads(l) for l in log.read_text().splitlines()]
    assert entry["op"] == "apply" and entry["id"] == s.id and entry["text"] == s.text and entry["at"] == "2026-10-03T10:00:00"
    assert entry["files"] == [{"file": str(path), "before": done.files[str(path)].before, "after": path.read_text()}]


def test_a_write_needs_the_root_and_the_log(tmp_path, plan_and_path):
    plan, path = plan_and_path
    s = pick(plan, "Pull c1")
    with pytest.raises(ValueError):
        sg.apply_suggestion(suggestions_of(plan), s.id)
    assert "weight=" not in path.read_text()


def test_a_file_outside_the_root_is_not_written(tmp_path, plan_and_path):
    plan, path = plan_and_path
    s = pick(plan, "Pull c1")
    inner = tmp_path / "elsewhere"
    inner.mkdir()
    with pytest.raises(sg.EditRefused, match="outside the project"):
        sg.apply_suggestion(suggestions_of(plan), s.id, root=inner, log=inner / "applied.jsonl")
    assert "weight=" not in path.read_text()


def test_a_file_that_changed_since_the_plan_refuses_and_writes_nothing(tmp_path, plan_and_path):
    plan, path = plan_and_path
    s = pick(plan, "Pull c1")
    path.write_text(path.read_text() + "# someone edited this\n")
    log = tmp_path / "applied.jsonl"
    with pytest.raises(sg.StaleSuggestion) as e:
        sg.apply_suggestion(suggestions_of(plan), s.id, root=tmp_path, log=log)
    assert e.value.files == [str(path)]
    assert path.read_text().endswith("# someone edited this\n") and "weight=" not in path.read_text()
    assert not log.exists()
    with pytest.raises(sg.StaleSuggestion):
        sg.apply_suggestion(suggestions_of(plan), s.id, dry_run=True)


def test_an_unknown_id_is_refused(plan_and_path):
    plan, path = plan_and_path
    with pytest.raises(sg.UnknownSuggestion, match="s99z"):
        sg.apply_suggestion(suggestions_of(plan), "s99z", dry_run=True)
    assert issubclass(sg.UnknownSuggestion, sg.SuggestionError)


def test_undo_puts_the_text_back_and_is_logged_and_works_as_a_stack(tmp_path, plan_and_path):
    plan, path = plan_and_path
    log = tmp_path / "applied.jsonl"
    original = path.read_text()
    first = pick(plan, "Pull c1")
    sg.apply_suggestion(suggestions_of(plan), first.id, root=tmp_path, log=log)
    once = path.read_text()
    # a second apply from a fresh plan (the file moved on, so the plan is rebuilt)
    board, plan2, _ = resolve(tmp_path, once.split("\n\n", 1)[1], name="layout.py")
    second = next(s for s in suggestions_of(plan2) if s.text.startswith("Place c1 before"))
    sg.apply_suggestion(suggestions_of(plan2), second.id, root=tmp_path, log=log)
    twice = path.read_text()
    assert twice != once
    undone = sg.undo_last(log, root=tmp_path)
    assert undone.id == second.id and path.read_text() == once
    undone = sg.undo_last(log, root=tmp_path)
    assert undone.id == first.id and path.read_text() == original
    with pytest.raises(sg.NothingToUndo):
        sg.undo_last(log, root=tmp_path)
    ops = [json.loads(l)["op"] for l in log.read_text().splitlines()]
    assert ops == ["apply", "apply", "undo", "undo"]
    assert [e["undone"] for e in sg.applied_entries(log)] == [True, True]


def test_undo_refuses_when_the_file_has_moved_on_and_writes_nothing(tmp_path, plan_and_path):
    plan, path = plan_and_path
    log = tmp_path / "applied.jsonl"
    s = pick(plan, "Pull c1")
    sg.apply_suggestion(suggestions_of(plan), s.id, root=tmp_path, log=log)
    path.write_text(path.read_text() + "# edited by hand\n")
    moved = path.read_text()
    with pytest.raises(sg.UndoRefused, match="changed since"):
        sg.undo_last(log, root=tmp_path)
    assert path.read_text() == moved
    assert len(log.read_text().splitlines()) == 1


def test_a_dry_run_undo_writes_nothing(tmp_path, plan_and_path):
    plan, path = plan_and_path
    log = tmp_path / "applied.jsonl"
    original = path.read_text()
    s = pick(plan, "Pull c1")
    sg.apply_suggestion(suggestions_of(plan), s.id, root=tmp_path, log=log)
    done = sg.undo_last(log, root=tmp_path, dry_run=True)
    assert done.dry_run and done.files[str(path)].after == original
    assert path.read_text() != original and len(log.read_text().splitlines()) == 1


def test_a_suggestion_whose_edit_writes_two_files_is_applied_to_both_and_undone_from_both(tmp_path):
    (tmp_path / "shared.py").write_text("X = 1\n")
    (tmp_path / "placemat.toml").write_text("")
    script = (tmp_path / "cell.py")
    script.write_text('from placemat import board, Part, PadRef\nfrom shared import X\n\nboard.link(a, b, limit_mm=4.0)\n')
    target = sg.Target("link", "a>b", str(script), 4)
    from placemat import script_edit
    edit = sg.Edit("set_kwarg", target, {"name": "limit_mm"},
                   {"const": {"name": "LIM_MM", "value": 5.1, "comment": "from a run", "file": str(tmp_path / "shared.py")}})
    digests = {str(script): script_edit.digest(script.read_text()),
               str(tmp_path / "shared.py"): script_edit.digest("X = 1\n")}
    s = sg.Suggestion("Raise the limit", edit, 1, "limit", "s1a", digests)
    s = sg.Suggestion(s.text, sg.Edit(edit.op, sg.Target("link", "a>b", str(script), 4, 1, digests[str(script)]), edit.args,
                                      edit.value), 1, "limit", "s1a", digests)
    log = tmp_path / "applied.jsonl"
    done = sg.apply_suggestion([s], "s1a", root=tmp_path, log=log)
    assert set(done.files) == {str(script), str(tmp_path / "shared.py")}
    assert "LIM_MM = 5.1" in (tmp_path / "shared.py").read_text()
    assert "from shared import X, LIM_MM" in script.read_text()
    sg.undo_last(log, root=tmp_path)
    assert (tmp_path / "shared.py").read_text() == "X = 1\n" and "LIM_MM" not in script.read_text()
