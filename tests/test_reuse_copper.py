"""A replay reuses the planned copper as well as the steps: the batches of declared copper and the rooms kept for it while
parts are placed, recorded in the reuse record. Only under the same script inputs (`Board.copper_inputs`), since the
context holds no copper declaration's arguments. Synthetic boards, and a script run for the inputs' digest."""
import dataclasses

import pytest

from placemat import context
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import CopperLayer, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint

F = CopperLayer.F


def _board(width=0.25, via_at=(30.0, 25.0), inputs="script v1", r2_at=None):
    fps = [footprint("J1", 5, 10, inst="j1", nets=("A", "GND")),
           footprint("U1", 20, 10, w=6, h=3, inst="u1", nets=("A", "B")),
           footprint("R1", 25, 15, inst="r1", nets=("B", "C")),
           footprint("R2", 30, 12, inst="r2", nets=("C", "GND"))]
    b = Board(board_geometry(fps, width=60, height=30), edge_margin=0.5, keep_going=True,
              settings=dataclasses.replace(Settings(), place_envelope="physical"))
    b.place(Part("j1"), at=Location(5, 10))
    b.place(Part("u1"))
    b.place(Part("r1"))
    b.place(Part("r2"), at=Location(*r2_at) if r2_at else None)
    b.track(Net("A"), [PadRef(Part("j1"), 1), PadRef(Part("u1"), 1)], layer=F, width=width, why="joins the input")
    b.track(Net("C"), [PadRef(Part("r1"), 2), PadRef(Part("r2"), 1)], layer=F, width=width)
    b.via(Net("GND"), at=Location(*via_at))
    b.copper_inputs = inputs
    return b


def _said(plan):
    return ([(s.item, s.kind, s.placement, s.notes, s.ops, s.laid) for s in plan.steps], list(plan.findings),
            list(plan.copper), list(plan.occupancy.copper))


def _never(*a, **k):
    raise AssertionError("planned again though the record holds it")


def test_a_replay_puts_back_the_copper_it_planned_and_says_the_same(monkeypatch):
    first = _board().resolve()
    assert set(first.reuse["copper"]) == {"fixed", "other"}
    assert any(e.get("rooms") for e in first.reuse["steps"])          # a track's room, kept once its ends were placed
    monkeypatch.setattr(Board, "_plan_copper_now", _never)
    monkeypatch.setattr(Board, "_rooms_after", _never)
    again = _board().resolve(reuse=first.reuse)
    assert again.reuse["reused"] == len(first.reuse["steps"])
    assert _said(again) == _said(first)
    assert [t.width for t in again.copper if type(t).__name__ == "Track"] == [0.25] * len(
        [t for t in first.copper if type(t).__name__ == "Track"])


def test_a_replay_of_a_replay_is_the_same_too():
    first = _board().resolve()
    second = _board().resolve(reuse=first.reuse)
    third = _board().resolve(reuse=second.reuse)
    assert _said(third) == _said(first)


@pytest.mark.parametrize("change", [{"width": 0.4}, {"via_at": (32.0, 25.0)}])
def test_copper_changed_in_the_script_is_planned_again_though_every_step_replays(change):
    first = _board().resolve()
    fresh = _board(inputs="script v2", **change).resolve()
    again = _board(inputs="script v2", **change).resolve(reuse=first.reuse)
    assert again.reuse["reused"] == len(first.reuse["steps"])          # the context does not hold copper's arguments
    assert _said(again) == _said(fresh) and list(again.copper) != list(first.copper)


def test_the_copper_is_planned_again_after_a_step_that_did_not_replay():
    first = _board().resolve()
    again = _board(r2_at=(40, 20)).resolve(reuse=first.reuse)
    assert again.reuse["reused"] < len(first.reuse["steps"])
    assert _said(again) == _said(_board(r2_at=(40, 20)).resolve())


def test_with_no_script_inputs_nothing_is_recorded_or_reused(monkeypatch):
    first = _board(inputs="").resolve()
    assert "copper" not in first.reuse and not any("rooms" in e for e in first.reuse["steps"])
    again = _board(inputs="").resolve(reuse=_board().resolve().reuse)   # a record made under some inputs
    assert _said(again) == _said(_board(inputs="").resolve())


def test_a_record_that_cannot_be_read_is_planned_again():
    first = _board().resolve()
    rec = dict(first.reuse, copper={k: dict(v, data="not a record") for k, v in first.reuse["copper"].items()},
               steps=[dict(e, rooms="!") if e.get("rooms") else e for e in first.reuse["steps"]])
    assert _said(_board().resolve(reuse=rec)) == _said(first)


def test_a_replay_leaves_the_record_it_replayed_from_as_it_was():
    first = _board().resolve()
    import copy
    kept = copy.deepcopy(first.reuse)
    _board(width=0.4, inputs="script v2").resolve(reuse=first.reuse)
    assert first.reuse == kept


# ------------------------------------------------------------ the script's inputs
def _digest(script):
    with context.reads() as got:
        context.run_script(script, object())
    return context.inputs_digest(got, script)


def test_the_inputs_digest_follows_the_script_its_helpers_and_the_files_it_reads(tmp_path):
    (tmp_path / "helper.py").write_text("W = 0.2\n")
    (tmp_path / "data.toml").write_text("w = 1\n")
    script = tmp_path / "Main_layout.py"
    script.write_text("import pathlib\nimport helper\nTEXT = (pathlib.Path(__file__).parent / 'data.toml').read_text()\n")
    first = _digest(script)
    assert _digest(script) == first
    (tmp_path / "data.toml").write_text("w = 2\n")
    second = _digest(script)
    assert second != first
    (tmp_path / "helper.py").write_text("W = 0.3\n")
    third = _digest(script)
    assert third != second
    script.write_text(script.read_text() + "# a comment\n")
    fourth = _digest(script)
    assert fourth != third
    with context.overlay({script: script.read_text() + "X = 1\n"}):
        assert _digest(script) != fourth
    assert _digest(script) == fourth
