"""What a run says about the steps it reused, and its record on disk."""
import json

from placemat import reuse


def _rec(context="c1", n=10, reused=0, first=None, parts=None):
    return {"version": reuse.VERSION, "context": context, "steps": [{"key": str(k)} for k in range(n)],
            "reused": reused, "first_change": first,
            "parts": parts or {"tool": "t", "board": "b", "settings": "s", "fab": "f"}}


def test_the_line_names_how_many_steps_came_from_which_run_and_the_first_change():
    assert reuse.summary(_rec(reused=7, first="r2"), _rec(), "run abc123") == \
        "reused 7 of 10 steps from run abc123 (first change: r2)"
    assert reuse.summary(_rec(reused=10), _rec(), "run abc123") == "reused all 10 steps from run abc123"


def test_a_changed_context_names_what_changed():
    prev = _rec(context="c0", parts={"tool": "t", "board": "b0", "settings": "s", "fab": "f0"})
    assert reuse.summary(_rec(context="c1"), prev, "run abc123") == \
        "reused 0 steps: the generated board and the fab profile changed since run abc123"
    same_parts = _rec(context="c0")
    assert reuse.summary(_rec(context="c1"), same_parts, "run abc123") == \
        "reused 0 steps: the script's board-wide declarations changed since run abc123"


def test_with_no_previous_record_nothing_is_said():
    assert reuse.summary(_rec(), None, None) == ""


def test_a_record_round_trips_through_its_file(tmp_path):
    r = _rec(reused=3, first="x")
    r["steps"][0].update({"step": {"item": "x"}, "commits": [[("fp", "R1"), [1.0, 2.0, 90.0, "front"]]]})
    p = tmp_path / "reuse.json"
    reuse.write(p, r)
    back = reuse.read(p)
    assert back["reused"] == 3 and back["steps"][0]["commits"][0][0] == ["fp", "R1"]
    assert reuse.read(tmp_path / "missing.json") is None
    (tmp_path / "bad.json").write_text("{not json")
    assert reuse.read(tmp_path / "bad.json") is None
