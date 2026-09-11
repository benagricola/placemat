"""The board-level shuffle gate: registration order must not reach the copper.

The framework's whole claim is that a script stops being the scheduler. The
unit-level gate checks that the PLAN does not move; this one checks the thing
that actually matters - that the BOARD does not move. Bodies are registered in
every order, the stages are run, and the saved files must be byte-identical.

It runs on a real cell fragment rather than synthetic footprints, so the
geometry, the groups and the clearances are the ones the library really meets,
and it still loads in milliseconds.
"""
import itertools
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from placemat import layout_stage                                          # noqa: E402
from placemat.layout_stage import plan, reset                         # noqa: E402

CELL = os.path.join(ROOT, "tests", "fixtures", "ProtectionCell", "layout", "layout.kicad_pcb")


@pytest.fixture(autouse=True)
def clean():
    reset()
    yield
    reset()


def build(tmp_path, order, tag):
    """Run four bodies in `order` of registration; return the saved bytes.

    Each body draws something a later body could disturb, so an ordering fault
    shows up as different copper rather than as nothing at all.
    """
    import shutil
    from placemat.layout_helpers import ModuleLayout
    from placemat.board_layout import BoardLayout

    work = tmp_path / f"board_{tag}.kicad_pcb"
    shutil.copy(CELL, work)

    layout = ModuleLayout(str(work))
    board = BoardLayout(layout, width=40.0, height=30.0)

    def frame():
        board.outline_chamfered(2.0)

    def copper():
        layout.poly("gnd", [(5.0, 5.0), (12.0, 5.0), (12.0, 9.0), (5.0, 9.0)], layer="F.Cu")

    def silk():
        board.silk_line(2.0, 20.0, 18.0, 20.0)

    def report():
        board.note_rect(1.0, 1.0, 6.0, 6.0)

    bodies = {"frame": frame, "copper": copper, "silk": silk, "report": report}
    regs = [(s, 0, bodies[s]) for s in order]
    for _stage, _i, fn in plan(regs, order=[0] * len(regs)):
        fn()
    layout.save(render=False)
    # Modulo ITEM IDENTITY: pcbnew mints a fresh uuid for everything a script
    # creates, so two runs of the SAME order differ byte for byte. What has to
    # hold is that the geometry, the nets and the layers are the same board.
    return re.sub(rb'\(uuid "[^"]*"\)', b"(uuid)", open(work, "rb").read())


@pytest.mark.board
def test_the_board_is_identical_under_every_registration_order(tmp_path):
    stages = ("frame", "copper", "silk", "report")
    first = None
    for perm in itertools.permutations(stages):
        out = build(tmp_path, perm, "_".join(perm)[:40])
        if first is None:
            first = out
        assert out == first, (
            "registration order %s produced a different board - the file is "
            "still scheduling" % (perm,))
