"""placemat freeze: lock entries into the script, accepted only when the
frozen script places exactly as the lock did."""
import json

import pytest

pytest.importorskip("pcbnew")

from tests.test_explore_cli import _cli, _module


def _placements(script):
    from placemat.previewer import preview
    plan = preview(script, svg_only=True, quiet=True).plan
    return {s.item: s.placement for s in plan.steps if s.kind in ("part", "cell") and s.placement is not None}


def _accepted(tmp_path):
    mod, script = _module(tmp_path, searched=True)
    rc, out = _cli("preview", script, "--svg", "--explore", "8", "--jobs", "2", "--accept")
    assert rc == 0 and "accepted" in out, out
    return mod, script


def test_freezing_moves_the_entries_into_the_script_and_places_the_same(tmp_path):
    mod, script = _accepted(tmp_path)
    before_src = script.read_text()
    locked = _placements(script)
    rc, out = _cli("freeze", script, "--all")
    assert rc == 0 and "froze" in out, out
    src = script.read_text()
    assert "radius=0" in src and src != before_src
    assert json.loads((mod / "UsbC_layout.lock.json").read_text())["entries"] == []
    assert _placements(script) == locked
    # every line freeze did not edit is still there, in order
    import ast
    edited = set()
    for n in ast.walk(ast.parse(before_src)):
        if isinstance(n, (ast.Call, ast.ImportFrom)) and (
                (isinstance(n, ast.ImportFrom) and n.module == "placemat")
                or (isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "place"
                    and ast.unparse(n.args[0]) in ("R_CC2", "C_VBUS"))):
            edited |= set(range(n.lineno, n.end_lineno + 1))
    old, new = before_src.splitlines(), src.splitlines()
    kept = [l for k, l in enumerate(old, start=1) if k not in edited]
    it = iter(new)
    assert all(any(l == m for m in it) for l in kept)


def test_a_freeze_that_would_move_anything_leaves_the_script_alone(tmp_path, monkeypatch):
    mod, script = _accepted(tmp_path)
    before = script.read_text()
    from placemat import freeze
    real = freeze.frozen_args
    monkeypatch.setattr(freeze, "frozen_args", lambda *a, **k: {**real(*a, **k), "rotation": "45"})
    report = freeze.freeze(script, None)
    assert not report["frozen"] and report["differences"]
    assert script.read_text() == before
    assert json.loads((mod / "UsbC_layout.lock.json").read_text())["entries"]


def test_an_item_with_no_entry_is_named(tmp_path):
    mod, script = _accepted(tmp_path)
    rc, out = _cli("freeze", script, "no_such_item")
    assert rc != 0 and "no_such_item" in out
