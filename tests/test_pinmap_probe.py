"""`placemat apply <id> --search` on a pin map suggestion studies its parts again with `pins.probe_budget_steps` a part,
on the board as the last run placed it, and keeps a better map as `<id>.1`."""
import json
from types import SimpleNamespace

from placemat import cli, previewer, settings as settings_mod, suggestions as sg
from placemat.findings import FindingCause as C
from placemat.pinmap import longer_advice
from tests.pinmap_boards import settings
from tests.test_pinmap_wiring import board


def advice_of(plan):
    f = next(f for f in plan.findings if f.cause is C.PINS_REMAP)
    return f.suggestions[0]


def kept_worse(tmp_path, monkeypatch, b, plan):
    s = advice_of(plan)
    s = sg.Suggestion(s.text, (), 1, "pins", "s1a", how="advice", advice=dict(s.advice, total=s.advice["total"] + 1.0))
    script = tmp_path / "x_layout.py"
    script.write_text("")
    sg.keep(tmp_path, script, "run 1", [s])
    monkeypatch.setattr(previewer, "resolve_like_last_run", lambda path: (b, plan, None, "1"))
    monkeypatch.setattr(settings_mod, "load", lambda *a, **k: settings(pins_probe_budget_steps=30000))
    return script, s


def test_a_longer_study_offers_a_map_only_when_it_beats_the_one_suggested():
    b = board()
    plan = b.resolve()
    s = advice_of(plan)
    assert longer_advice(b, plan, s.advice, 60000)[0] is None             # this board has nothing better to find
    worse = dict(s.advice, total=s.advice["total"] + 1.0)
    better, g = longer_advice(b, plan, worse, 60000)
    assert better["total"] == g["best"]["total"] < worse["total"] and better["map"] == s.advice["map"]


def test_the_search_keeps_a_better_map_as_the_next_id(tmp_path, monkeypatch, capsys):
    b = board()
    plan = b.resolve()
    script, s = kept_worse(tmp_path, monkeypatch, b, plan)
    assert cli._pin_search(SimpleNamespace(json=False), tmp_path, script, s) == 0
    kept = sg.recall(tmp_path, script)[str(script.resolve())]["suggestions"]
    found = next(x for x in kept if x.id == "s1a.1")
    assert found.how == "advice" and found.text.endswith(", found by a longer study")
    assert "s1a.1: " in capsys.readouterr().out


def test_a_study_that_raises_exits_non_zero_and_keeps_nothing(tmp_path, monkeypatch, capsys):
    b = board()
    plan = b.resolve()
    script, s = kept_worse(tmp_path, monkeypatch, b, plan)

    def boom(*a, **k):
        raise RuntimeError("no room")
    monkeypatch.setattr("placemat.pinmap.plan_summary", boom)
    assert cli._pin_search(SimpleNamespace(json=False), tmp_path, script, s) == 1
    seen = capsys.readouterr()
    assert "RuntimeError: no room" in seen.out + seen.err
    kept = sg.recall(tmp_path, script)[str(script.resolve())]["suggestions"]
    assert [x.id for x in kept] == ["s1a"]


def test_a_study_that_raises_gives_its_error_as_fields_in_json(tmp_path, monkeypatch, capsys):
    b = board()
    plan = b.resolve()
    script, s = kept_worse(tmp_path, monkeypatch, b, plan)

    def boom(*a, **k):
        raise RuntimeError("no room")
    monkeypatch.setattr("placemat.pinmap.plan_summary", boom)
    assert cli._pin_search(SimpleNamespace(json=True), tmp_path, script, s) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == {"type": "RuntimeError", "message": "no room"} and out["found"] is None


def test_a_group_no_longer_studied_exits_non_zero_in_text(tmp_path, monkeypatch, capsys):
    b = board()
    plan = b.resolve()
    script, s = kept_worse(tmp_path, monkeypatch, b, plan)
    monkeypatch.setattr("placemat.pinmap.plan_summary", lambda *a, **k: [])
    assert cli._pin_search(SimpleNamespace(json=False), tmp_path, script, s) == 1
    seen = capsys.readouterr()
    assert "no longer studied on this board" in seen.out + seen.err
    kept = sg.recall(tmp_path, script)[str(script.resolve())]["suggestions"]
    assert [x.id for x in kept] == ["s1a"]


def test_a_group_no_longer_studied_gives_a_reason_in_json(tmp_path, monkeypatch, capsys):
    b = board()
    plan = b.resolve()
    script, s = kept_worse(tmp_path, monkeypatch, b, plan)
    monkeypatch.setattr("placemat.pinmap.plan_summary", lambda *a, **k: [])
    assert cli._pin_search(SimpleNamespace(json=True), tmp_path, script, s) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["study"] is None and out["found"] is None and out["reason"] == "not_studied"


def test_a_panic_in_the_native_core_exits_non_zero_with_its_error(tmp_path, monkeypatch, capsys):
    from tests.test_pinmap_wiring import PanicException
    b = board()
    plan = b.resolve()
    script, s = kept_worse(tmp_path, monkeypatch, b, plan)

    def panics(*a, **k):
        raise PanicException("index out of bounds")
    monkeypatch.setattr("placemat.pinmap.plan_summary", panics)
    assert cli._pin_search(SimpleNamespace(json=True), tmp_path, script, s) == 1
    assert json.loads(capsys.readouterr().out)["error"] == {"type": "PanicException", "message": "index out of bounds"}


def _tripped(tmp_path, monkeypatch):
    from dataclasses import replace
    b = board()
    plan = b.resolve()
    script, s = kept_worse(tmp_path, monkeypatch, b, plan)
    b.settings = replace(b.settings, pins_guard_ms=1e-9)
    return script, s


def test_a_longer_study_past_its_guard_says_so_and_keeps_nothing(tmp_path, monkeypatch, capsys):
    script, s = _tripped(tmp_path, monkeypatch)
    assert cli._pin_search(SimpleNamespace(json=False), tmp_path, script, s) == 1
    seen = capsys.readouterr()
    assert "s1a: the study of U1 ran past its wall-clock guard, pins.guard_ms of " in seen.out + seen.err
    assert "; no map is given" in seen.out + seen.err
    kept = sg.recall(tmp_path, script)[str(script.resolve())]["suggestions"]
    assert [x.id for x in kept] == ["s1a"]


def test_a_longer_study_past_its_guard_gives_its_reason_in_json(tmp_path, monkeypatch, capsys):
    script, s = _tripped(tmp_path, monkeypatch)
    assert cli._pin_search(SimpleNamespace(json=True), tmp_path, script, s) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["reason"] == "slow" and out["found"] is None and out["study"]["slow"] is True
    assert out["study"]["steps"] == 0 and out["study"]["budget_steps"] == 30000
