"""`placemat lock <script> --current --partial` locks the items that stand
where the board has them and lists the rest; without --partial one item
that would not stand holds back all of them."""
from types import SimpleNamespace



class _Entry(SimpleNamespace):
    pass


def _stand_ins(monkeypatch, written):
    """lock.current and the resolve: a, b and c stand on the first look and d
    does not; c does not come back when locked, whatever else is."""
    from placemat import lock, previewer
    board = SimpleNamespace(settings=SimpleNamespace(route_adopt_tolerance=0.01))

    def resolve(script, lock_entries=None):
        return board, ("check" if lock_entries is not None else "first"), SimpleNamespace(pcb="x"), "run1"

    def current(board, plan, written_pads, existing, tol, keys=None, release="", run="", refused=None):
        if plan == "first":
            ks = ["a", "b", "c"] if keys is None else sorted(keys)
            refused = {} if refused is None else refused
            if keys is None:
                refused["d"] = "d stands at (1, 1) on the board"
            return [_Entry(key=k) for k in ks], ks, refused
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


def test_an_item_hanging_off_a_refused_one_is_dropped_not_looped_on(monkeypatch, tmp_path, capsys):
    """B hangs off A; both stand on the first look, A does not come back when
    locked. The recomputation must not lock A again for B's sake: B goes
    too, saying why, and the command ends."""
    from placemat import cli, lock, previewer
    item = lambda ref: SimpleNamespace(ref=ref)
    plan = SimpleNamespace(turns={"A": {"order": 0}, "B": {"order": 1, "anchor": ("refA", "1")}},
                           _items={"A": item("refA"), "B": item("refB")})
    board = SimpleNamespace(settings=SimpleNamespace(route_adopt_tolerance=0.01))
    calls = []

    def resolve(script, lock_entries=None):
        calls.append(lock_entries)
        if len(calls) > 10:
            raise AssertionError("the partial lock is looping")
        return board, (plan if lock_entries is None else "check"), SimpleNamespace(pcb="x"), "run1"

    def current(board, p, written_pads, existing, tol, keys=None, release="", run="", refused=None):
        if p == "check":
            return [], [k for k in sorted(keys) if k != "A"], {"A": "placed at (5, 5)"}
        refused = {} if refused is None else refused
        locked = lock._with_anchors(plan, sorted(keys) if keys is not None else ["A", "B"], refused)
        return [_Entry(key=k) for k in locked], locked, refused
    written = []
    monkeypatch.setattr(previewer, "resolve_like_last_run", resolve)
    monkeypatch.setattr(previewer, "written_pads", lambda pcb: {})
    monkeypatch.setattr(lock, "current", current)
    monkeypatch.setattr(lock, "read", lambda path: [])
    monkeypatch.setattr(lock, "write", lambda path, entries: written.append([e.key for e in entries]))
    script = tmp_path / "Board_layout.py"
    script.write_text("")
    assert cli.main(["lock", str(script), "--current", "--partial"]) == 1
    assert written == []
    out = capsys.readouterr().out
    assert "B: it hangs off A" in out and "locked 0 of 2" in out, out
