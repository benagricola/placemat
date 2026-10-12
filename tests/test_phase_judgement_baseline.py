"""Ruling S15: an obligation is violated only by a real DRC error its phase's input board did not already have."""
import json

from placemat.kicad import phase_run

OB = {"net": "GND", "from": {"ref": "C1", "pad": "1"}, "to": {"ref": "C2", "pad": "1"}, "widths": None}


def _error(x, nets=("GND",)):
    return {"type": "hole_clearance", "severity": "error",
            "items": [{"description": "Pad 1 [%s] of J1" % n, "pos": {"x": x, "y": 5.0}} for n in nets]}


def _drc(path, *errors):
    path.write_text(json.dumps({"violations": list(errors), "unconnected_items": []}))
    return path


def _judge(tmp_path, monkeypatch, after, baseline):
    monkeypatch.setattr(phase_run, "joined_pairs", lambda *_: [True])
    (got,) = phase_run.judge_obligations("board.kicad_pcb", [OB], _drc(tmp_path / "after.json", *after),
                                         is_real=lambda _: True,
                                         baseline_json=None if baseline is None else _drc(tmp_path / "before.json", *baseline))
    return got["violated"]


def test_an_error_the_input_board_already_had_does_not_mark_the_net(tmp_path, monkeypatch):
    assert _judge(tmp_path, monkeypatch, [_error(10.0)], [_error(10.0)]) is False


def test_an_error_the_phase_added_marks_the_net(tmp_path, monkeypatch):
    assert _judge(tmp_path, monkeypatch, [_error(10.0), _error(20.0)], [_error(10.0)]) is True


def test_with_no_baseline_every_error_counts(tmp_path, monkeypatch):
    assert _judge(tmp_path, monkeypatch, [_error(10.0)], None) is True


def test_a_phases_input_drc_is_the_phase_befores_or_the_routes_own(tmp_path):
    import pytest
    (tmp_path / "drc_before.json").write_text("{}")
    assert phase_run.phase_input_drc(tmp_path, 0) == tmp_path / "drc_before.json"
    with pytest.raises(FileNotFoundError):                         # p1's is not there: a fault, not the route's
        phase_run.phase_input_drc(tmp_path, 2)
    (tmp_path / "p1_drc.json").write_text("{}")
    assert phase_run.phase_input_drc(tmp_path, 2) == tmp_path / "p1_drc.json"


def test_an_error_matching_a_baseline_error_by_its_least_item_but_not_its_others_is_new(tmp_path, monkeypatch):
    """M3: a new GND via against the same hole as a pre-existing GND pad error shares type, nets and the hole's
    position (the least item) with it; its other item differs, so it is new."""
    from placemat.kicad.drc import new_errors, real_errors
    def err(other):
        return {"type": "hole_clearance", "severity": "error",
                "items": [{"description": "NPTH pad of J1", "pos": {"x": 1.0, "y": 1.0}},
                          {"description": other, "pos": {"x": 5.0, "y": 5.0}}]}
    base = real_errors({"violations": [err("Pad A1 [GND] of J1 on B.Cu")]}, lambda _: True)
    after = real_errors({"violations": [err("Pad A1 [GND] of J1 on B.Cu"), err("Via [GND] on F.Cu - B.Cu")]},
                        lambda _: True)
    assert [e["items"][1][0] for e in new_errors(after, base)] == ["Via [GND] on F.Cu - B.Cu"]


def test_two_like_errors_against_one_baseline_error_leave_one_new():
    from placemat.kicad.drc import new_errors
    e = {"type": "clearance", "nets": ("A", "B"), "at_mm": (1.0, 1.0), "items": (("x", 1.0, 1.0),)}
    assert len(new_errors([e, dict(e)], [e])) == 1
