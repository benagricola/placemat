"""The command line: `try` lines under findings, the suggestions in the JSON records, and `placemat apply`."""
import json

import pytest

from placemat import cli, suggestions as sg
from placemat.console import Console
from placemat.findings import Finding
from tests.suggest_support import resolve, suggestions_of
from tests.test_suggestions_link_over import SCRIPT


@pytest.fixture
def planned(tmp_path):
    board, plan, path = resolve(tmp_path, SCRIPT)
    sg.remember(tmp_path, path, "run 1a2b3c4d", plan.findings)
    return plan, path


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    return code, capsys.readouterr()


def test_a_critical_or_warning_finding_prints_its_best_suggestion_and_the_ids_of_the_others(tmp_path, planned, capsys):
    plan, path = planned
    (f,) = [f for f in plan.findings if f.kind == "link_over"]
    assert f.severity == "warning"
    lines = f.try_lines()
    assert lines[0] == "    try %s: %s" % (f.suggestions[0].id, f.suggestions[0].text)
    assert lines[1] == "    or " + ", ".join(s.id for s in f.suggestions[1:])


def test_a_notice_prints_no_try_line():
    from tests.test_finding_suggestions import _suggestion
    f = Finding("setup", "x", "notice", case="setup.accept", suggestions=[_suggestion()])
    assert f.try_lines() == []


def test_the_console_prints_the_try_lines_under_the_finding(tmp_path, planned, capsys):
    plan, path = planned
    (f,) = [f for f in plan.findings if f.kind == "link_over"]
    out = Console()
    out.finding(f)
    text = capsys.readouterr().out
    assert "[warning] link C1.1" in text and "    try %s: %s" % (f.suggestions[0].id, f.suggestions[0].text) in text


def test_a_finding_without_suggestions_prints_one_line(capsys):
    out = Console()
    out.finding(Finding("unplaced", "c4: no room"))
    assert capsys.readouterr().out.count("\n") == 1


def test_the_detail_of_a_finding_carries_its_case_and_suggestions(planned):
    plan, path = planned
    (f,) = [f for f in plan.findings if f.kind == "link_over"]
    d = f.detail()
    assert d["kind"] == "link_over" and d["case"] == "link_over" and d["text"] == str(f)
    assert [s["id"] for s in d["suggestions"]] == [s.id for s in f.suggestions]
    assert all(s["digests"] for s in d["suggestions"])
    plain = Finding("setup", "x").detail()
    assert plain == {"kind": "setup", "severity": "warning", "text": "x"}


def test_apply_dry_run_prints_the_diff_and_writes_nothing(tmp_path, planned, capsys):
    plan, path = planned
    before = path.read_text()
    s = next(s for s in suggestions_of(plan) if s.text.startswith("Pull c1"))
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path), "--dry-run")
    assert code == 0
    assert "weight=LinkWeight.PREFER" in out.out and "--- a/" in out.out
    assert path.read_text() == before


def test_apply_writes_the_file_and_logs_it_and_undo_puts_it_back(tmp_path, planned, capsys):
    plan, path = planned
    before = path.read_text()
    s = next(s for s in suggestions_of(plan) if s.text.startswith("Pull c1"))
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path))
    assert code == 0 and "weight=LinkWeight.PREFER" in path.read_text()
    assert (tmp_path / ".placemat" / "applied.jsonl").exists()
    code, out = run_cli(capsys, "apply", "--undo", "--script", str(path))
    assert code == 0 and path.read_text() == before


def test_apply_refuses_when_the_script_changed_since_the_run(tmp_path, planned, capsys):
    plan, path = planned
    s = next(s for s in suggestions_of(plan) if s.text.startswith("Pull c1"))
    path.write_text(path.read_text() + "# edited\n")
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path))
    assert code == 1 and "changed since run 1a2b3c4d" in out.out
    assert "weight=" not in path.read_text()


def test_apply_refuses_an_unknown_id(tmp_path, planned, capsys):
    plan, path = planned
    code, out = run_cli(capsys, "apply", "s99z", "--script", str(path))
    assert code == 1 and "no suggestion s99z" in out.out


def test_undo_with_nothing_applied_says_so(tmp_path, planned, capsys):
    plan, path = planned
    code, out = run_cli(capsys, "apply", "--undo", "--script", str(path))
    assert code == 1 and "nothing applied" in out.out


def test_undo_refuses_when_the_file_moved_on(tmp_path, planned, capsys):
    plan, path = planned
    s = next(s for s in suggestions_of(plan) if s.text.startswith("Pull c1"))
    run_cli(capsys, "apply", s.id, "--script", str(path))
    path.write_text(path.read_text() + "# by hand\n")
    code, out = run_cli(capsys, "apply", "--undo", "--script", str(path))
    assert code == 1 and "changed since" in out.out and "# by hand" in path.read_text()


def test_apply_json_gives_the_diff_per_file(tmp_path, planned, capsys):
    plan, path = planned
    s = next(s for s in suggestions_of(plan) if s.text.startswith("Pull c1"))
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path), "--dry-run", "--json")
    doc = json.loads(out.out)
    assert code == 0 and doc["id"] == s.id and doc["dry_run"] is True
    assert doc["files"][0]["file"] == str(path) and "weight=LinkWeight.PREFER" in doc["files"][0]["diff"]


def test_apply_without_an_id_is_a_usage_error(tmp_path, planned, capsys):
    plan, path = planned
    code, out = run_cli(capsys, "apply", "--script", str(path))
    assert code == 2


def test_the_command_and_the_studio_apply_through_the_same_function(tmp_path, planned, capsys, monkeypatch):
    plan, path = planned
    seen = []
    real = sg.apply_suggestion

    def spy(suggestions, id, dry_run=False, **kw):
        seen.append(id)
        return real(suggestions, id, dry_run=dry_run, **kw)
    monkeypatch.setattr(sg, "apply_suggestion", spy)
    s = next(s for s in suggestions_of(plan) if s.text.startswith("Pull c1"))
    run_cli(capsys, "apply", s.id, "--script", str(path), "--dry-run")
    assert seen == [s.id]


def test_a_suggestion_read_back_from_the_kept_plan_equals_the_one_in_the_record(tmp_path, planned):
    plan, path = planned
    kept = sg.recall(tmp_path, path)[str(path.resolve())]["suggestions"]
    (f,) = [f for f in plan.findings if f.kind == "link_over"]
    assert kept == list(f.suggestions)
    assert sg.from_json(f.detail()["suggestions"]) == list(f.suggestions)
