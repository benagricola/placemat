"""placemat - PCB layout as code: placement, copper and the gates around them.

A layout script DECLARES and this library SCHEDULES. The public surface is
small on purpose:

    from placemat import stage, context

    layout, board = context()

    @stage("cells")
    def _cells():
        board.settle_all([dict(inst="buck"), dict(inst="can")])

`layout` is the artwork and the file; `board` is the board being laid out. The runner builds both, and resolves the
PROJECT - the fab profile, where the cells and parts are, which boards exist.
Nothing here climbs the filesystem looking for any of it.

The command line is `placemat`; `placemat --help` lists what it can do.
"""
from placemat.project import Project, use, active, fab, repo_root   # noqa: F401
from placemat.layout_stage import (STAGES, stage, context, plan, run,  # noqa: F401
                                   registered, reset)

__all__ = ["Project", "use", "active", "fab", "repo_root",
           "STAGES", "stage", "context", "plan", "run", "registered", "reset"]
