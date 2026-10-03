"""`placemat apply <id> --search`: the probe on the command line, on the synthetic chamfer board of test_probe_synthetic (each
candidate a real resolve of the edited text)."""
import json

import pytest

from placemat import cli, probe, suggestions as sg
from placemat.stop import Stopped
from tests.test_probe_synthetic import _meets, _resolved, resolve_in_place, IMPORTS, BODY


@pytest.fixture
def planned(tmp_path, monkeypatch):
    path = tmp_path / "layout.py"
    path.write_text(IMPORTS + BODY)
    b, plan = _resolved(path)
    sg.remember(tmp_path, path, "run 1a2b3c4d", plan.findings)
    (f,) = _meets(plan)
    s = next(s for s in f.suggestions if s.how == "searched" and s.figure["name"] == "chamfer")
    monkeypatch.setattr(probe, "overlay_resolver", lambda script, timeout: resolve_in_place(path))
    return tmp_path, path, s


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def test_a_searched_suggestion_is_not_applied_it_says_to_search(planned, capsys):
    tmp, path, s = planned
    before = path.read_text()
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path))
    assert code == 1 and "--search" in out and path.read_text() == before


def test_search_without_yes_and_without_a_terminal_does_not_start(planned, capsys, monkeypatch):
    tmp, path, s = planned
    monkeypatch.setattr("sys.stdin", type("Dev", (), {"isatty": lambda self: False})())
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path), "--search")
    assert code == 2 and "pass --yes" in out and "resolves the whole board for each candidate" in out
    assert not (tmp / ".placemat" / "probes").exists()


def test_search_prints_a_line_per_candidate_and_keeps_the_best_as_a_new_suggestion(planned, capsys):
    tmp, path, s = planned
    before = path.read_text()
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path), "--search", "--yes")
    assert code == 0 and path.read_text() == before
    assert "probe %s: the chamfer of the A track" % s.id in out and out.count("  %s = " % s.id) >= 2 and "found " in out
    found = sg.recall(tmp, path)[str(path)]["suggestions"]
    (new,) = [x for x in found if x.id == s.id + ".1"]
    assert new.how == "instant" and "found by a probe" in new.text
    code, out = run_cli(capsys, "apply", new.id, "--script", str(path), "--dry-run")
    assert code == 0 and "CHAMFER_MM" in out
    code, out = run_cli(capsys, "apply", new.id, "--script", str(path))
    assert code == 0 and "CHAMFER_MM" in path.read_text()
    assert not _meets(_resolved(path)[1])


def test_search_json_is_the_result_and_the_found_suggestion(planned, capsys):
    tmp, path, s = planned
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path), "--search", "--yes", "--json")
    doc = json.loads(out[out.index("{"):])
    assert doc["id"] == s.id and doc["result"]["state"] == "found" and doc["found"]["id"] == s.id + ".1"


def test_a_stop_keeps_the_results_and_the_next_search_continues_from_them(planned, capsys, monkeypatch):
    tmp, path, s = planned
    real = resolve_in_place(path)
    calls = []

    def stopping(overlay):
        calls.append(overlay)
        if len(calls) == 4:                     # the base, the far end, one more, then the stop
            raise Stopped(15)
        return real(overlay)
    monkeypatch.setattr(probe, "overlay_resolver", lambda script, timeout: stopping)
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path), "--search", "--yes")
    assert code == 128 + 15 and "stopped by you after 2 of" in out
    saved = [p for p in (tmp / ".placemat" / "probes").glob("*.jsonl")]
    assert len(saved) == 1 and len(saved[0].read_text().splitlines()) == 2
    resolved = []

    def counting(overlay):
        resolved.append(overlay)
        return real(overlay)
    monkeypatch.setattr(probe, "overlay_resolver", lambda script, timeout: counting)
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path), "--search", "--yes")
    assert code == 0 and "continuing %s from 2 saved result(s)" % s.id in out
    assert ", saved)" in out


def test_a_changed_script_starts_fresh_and_says_so(planned, capsys):
    tmp, path, s = planned
    folder = tmp / ".placemat" / "probes"
    folder.mkdir(parents=True)
    old = folder / ("%s.%s.jsonl" % (s.id, "0" * 16))
    old.write_text(json.dumps(probe.Candidate(0.1, True).to_json()) + "\n")
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path), "--search", "--yes")
    assert code == 0 and "changed since an earlier probe" in out and not old.exists()


def test_search_of_an_instant_suggestion_is_refused(planned, capsys):
    tmp, path, s = planned
    (f,) = _meets(_resolved(path)[1])
    instant = next(x for x in f.suggestions if x.how == "instant")
    sg.remember(tmp, path, "run 2", _resolved(path)[1].findings)
    code, out = run_cli(capsys, "apply", instant.id, "--script", str(path), "--search", "--yes")
    assert code == 2 and "not a searched suggestion" in out


def test_a_script_changed_since_the_plan_is_refused_before_any_resolve(planned, capsys, monkeypatch):
    tmp, path, s = planned
    called = []
    monkeypatch.setattr(probe, "overlay_resolver", lambda script, timeout: called.append(1))
    path.write_text(path.read_text() + "# edited\n")
    code, out = run_cli(capsys, "apply", s.id, "--script", str(path), "--search", "--yes")
    assert code == 1 and "changed since the plan was made" in out and called == [1] and not (tmp / ".placemat" / "probes").exists()
