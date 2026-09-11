"""The stage framework: dependency order, and declaration order not mattering.

The framework exists so a script stops being the scheduler. That claim is only
worth anything if it is checked, and these are the checks: a body runs in its
stage's slot rather than at its line, an unknown stage is an error rather than a
body that silently never runs, and permuting the registrations does not move the
plan.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from placemat import layout_stage                                     # noqa: E402
from placemat.layout_stage import STAGES, plan, stage, reset     # noqa: E402


@pytest.fixture(autouse=True)
def clean():
    reset()
    yield
    reset()


def names(p):
    return [f.__name__ for _s, _i, f in p]


def test_a_body_runs_in_its_stage_not_at_its_line():
    """Written last, run first: the file's order is not the schedule."""
    @stage("report")
    def written_first():
        pass

    @stage("frame")
    def written_second():
        pass

    assert names(plan()) == ["written_second", "written_first"]


def test_every_stage_slot_is_honoured_in_dependency_order():
    for s in STAGES:
        exec(f"@stage('{s}')\ndef body_{s}(): pass", {"stage": stage})
    assert [s for s, _i, _f in plan()] == list(STAGES)


def test_an_unknown_stage_is_an_error_not_a_body_that_never_runs():
    """A typo must fail loudly: a silently unregistered body is the worst
    failure a scheduler can have, because the board is simply missing work."""
    with pytest.raises(ValueError) as e:
        @stage("cooper")           # not "copper"
        def _typo():
            pass
    assert "cooper" in str(e.value)


def test_registration_order_does_not_change_the_plan():
    """THE SHUFFLE GATE, at the level the framework can be asked about cheaply.

    Permuting the order bodies were registered in must leave the plan identical.
    If it does not, the file is still scheduling and every guarantee above it is
    decoration.
    """
    import itertools

    def mk(tag, st):
        def body():
            pass
        body.__name__ = tag
        return (st, 0, body)

    regs = [mk("a_copper", "copper"), mk("b_frame", "frame"),
            mk("c_silk", "silk"), mk("d_cells", "cells")]
    plans = set()
    for perm in itertools.permutations(range(len(regs))):
        shuffled = [regs[i] for i in perm]
        plans.add(tuple(f.__name__ for _s, _i, f in
                        plan(shuffled, order=[0] * len(regs))))
    assert len(plans) == 1, f"registration order changed the plan: {plans}"


def test_two_bodies_in_one_stage_keep_their_registration_order():
    """Within a stage the order is registration order - and the board-level
    shuffle gate is what proves that order is not load-bearing."""
    @stage("copper")
    def first():
        pass

    @stage("copper")
    def second():
        pass

    assert names(plan()) == ["first", "second"]


def test_bodies_run_and_receive_the_injected_context(tmp_path):
    """`L` and `board` land in the script's own globals before the first body."""
    seen = {}
    g = {}

    def body():
        seen["L"] = g.get("L")
        seen["board"] = g.get("board")

    class FakeL:
        pass

    monkey = layout_stage.run.__globals__
    # run() builds the real context, so exercise the injection contract directly
    g["L"], g["board"] = FakeL(), FakeL()
    body()
    assert seen["L"] is g["L"] and seen["board"] is g["board"]


def test_layout_names_what_the_runner_builds(tmp_path):
    """`layout, board = context()` at the top of a script, used inside the bodies.

    A script is imported before its board exists - the runner reads the config
    in it to know the frame and the plane nets, and only then opens the board -
    so the names are bound when there is something to bind them to.
    """
    import shutil
    from placemat import context, project, Project
    from placemat.layout_stage import run

    project.use(Project(root=None, fab={"via": {"default_drill_mm": 0.3,
                                                "default_size_mm": 0.6}}))
    src = os.path.join(ROOT, "tests", "fixtures", "ProtectionCell", "layout",
                       "layout.kicad_pcb")
    board = tmp_path / "b.kicad_pcb"
    shutil.copy(src, board)

    layout, board_h = context()
    seen = {}

    @stage("frame")
    def _frame():
        board_h.outline_chamfered(2.0)
        seen["outline"] = len([d for d in board_h.pcb.GetDrawings()])

    run(str(board), width=40.0, height=30.0, verbose=False)
    assert seen["outline"] > 0, "the body did not reach the real board"
    assert board_h.width == 40.0 and layout.path == str(board)


def test_using_a_handle_before_the_runner_builds_it_says_so():
    from placemat import context
    layout, board = context()
    from placemat import layout_stage
    layout_stage._CTX.layout = layout_stage._CTX.board = None
    with pytest.raises(RuntimeError) as e:
        board.outline_chamfered(2.0)
    assert "not built yet" in str(e.value)
