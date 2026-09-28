"""`placemat lock <script> --current --partial` locks the items that stand
where the board has them and lists the rest; without --partial one item
that would not stand holds back all of them."""
from types import SimpleNamespace

import pytest


class _Entry(SimpleNamespace):
    pass


def _stand_ins(monkeypatch, written):
    """lock.current and the resolve: a, b and c stand on the first look and d
    does not; c does not come back when locked, whatever else is."""
    from placemat import lock, previewer
    board = SimpleNamespace(settings=SimpleNamespace(route_adopt_tolerance=0.01))

    def resolve(script, lock_entries=None):
        return board, ("check" if lock_entries is not None else "first"), SimpleNamespace(pcb="x"), "run1"

    def current(board, plan, written_pads, existing, tol, keys=None, release="", run=""):
        if plan == "first":
            ks = ["a", "b", "c"] if keys is None else sorted(keys)
            return [_Entry(key=k) for k in ks], ks, ({"d": "d stands at (1, 1) on the board"} if keys is None else {})
        held = [k for k in sorted(keys) if k != "c"]
        return [], held, {"c": "placed at (5, 5)"}
    monkeypatch.setattr(previewer, "resolve_like_last_run", resolve)
    monkeypatch.setattr(previewer, "written_pads", lambda pcb: {})
    monkeypatch.setattr(lock, "current", current)
    monkeypatch.setattr(lock, "read", lambda path: [])
    monkeypatch.setattr(lock, "write", lambda path, entries: written.append([e.key for e in entries]))


def test_partial_locks_what_stands_after_checking_again(monkeypatch, tmp_path, capsys):
    from placemat import cli
    written = []
    _stand_ins(monkeypatch, written)
    script = tmp_path / "Board_layout.py"
    script.write_text("")
    assert cli.main(["lock", str(script), "--current", "--partial"]) == 1
    assert written == [["a", "b"]]
    out = capsys.readouterr().out
    assert "locked 2 of 4" in out and "c: locked, it would not come back there" in out and "d: d stands" in out


def test_without_partial_nothing_is_written(monkeypatch, tmp_path, capsys):
    from placemat import cli
    written = []
    _stand_ins(monkeypatch, written)
    script = tmp_path / "Board_layout.py"
    script.write_text("")
    assert cli.main(["lock", str(script), "--current"]) == 1
    assert written == []
