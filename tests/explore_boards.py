"""Synthetic boards and board factories for the explore stop and resume tests.
Module-level and picklable: explore workers are spawned, not forked."""
import multiprocessing
import os
import signal
import time

from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint

KEYS = tuple("r%d" % k for k in range(6))
NETS = [("A", "N1"), ("B", "N1"), ("A", "N2"), ("B", "N2"), ("N1", "N3"), ("N2", "N3")]
FOCUS = frozenset(KEYS)


def make(**settings):
    """Six passives round a part on a small board. `settings` replace the board's own."""
    fps = [footprint("U1", 10, 10, w=8, h=4, inst="mcu", nets=("A", "B"))]
    fps += [footprint("R%d" % k, 60, 60 + 2 * k, w=2, h=1, inst="r%d" % k, nets=NETS[k]) for k in range(6)]
    kw = {}
    if settings:
        import dataclasses
        from placemat.settings import Settings
        kw["settings"] = dataclasses.replace(Settings(), **settings)
    b = Board(board_geometry(fps, width=30, height=30), edge_margin=1.0, **kw)
    b.place(Part("mcu"), at=Location(15, 15))
    for k in KEYS:
        b.place(Part(k))
    return b


def in_worker() -> bool:
    return multiprocessing.current_process().name != "MainProcess"


class Recording:
    """make(), and each worker process's pid appended to `pids` as it starts."""

    def __init__(self, pids, delay=0.0):
        self.pids, self.delay = str(pids), delay

    def __call__(self):
        if in_worker():
            with open(self.pids, "a") as f:
                f.write("%d\n" % os.getpid())
            time.sleep(self.delay)
        return make()


class Killer:
    """make(), but a worker killed by SIGKILL (as the OOM killer would) when it builds a variant."""

    def __call__(self):
        if in_worker():
            os.kill(os.getpid(), signal.SIGKILL)
        return make()


class Raiser:
    """make(), but a worker raises when it builds a variant."""

    def __call__(self):
        if in_worker():
            raise ValueError("boom in a variant")
        return make()


class Settled:
    """make() with `settings`, and each worker's start recorded in `pids` when given."""

    def __init__(self, pids=None, delay=0.0, **settings):
        self.pids, self.delay, self.settings = None if pids is None else str(pids), delay, settings

    def __call__(self):
        if in_worker() and self.pids:
            with open(self.pids, "a") as f:
                f.write("%d\n" % os.getpid())
            time.sleep(self.delay)
        return make(**self.settings)


class StandInRouter:
    """The explore's routing worker's board writer and router (explore.VariantRouter), standing in for KiCad and the
    router: `write` makes a file in the variant's folder, `route` sleeps `delay` and returns `closures[seed]` as
    (clean, raw), or raises RuntimeError with it when it is a string. Each call is a line of `log` (JSON: seed, work,
    exclude, quick, resume, at)."""

    def __init__(self, log, closures=None, delay=0.0, default=(0.5, 0.5)):
        self.log, self.closures, self.delay, self.default = str(log), dict(closures or {}), delay, default

    def write(self, make_board, board, plan, folder):
        from pathlib import Path
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "layout.kicad_pcb").write_text("stand-in")
        return folder / "layout.kicad_pcb"

    def route(self, pcb, work, exclude_nets=(), quick=False, resume=True):
        import json
        from pathlib import Path
        from types import SimpleNamespace
        seed = int(Path(pcb).parent.name.split("-")[1])
        with open(self.log, "a") as f:
            f.write(json.dumps({"seed": seed, "work": str(work), "exclude": sorted(exclude_nets), "quick": quick,
                                "resume": resume, "at": time.time()}) + "\n")
        time.sleep(self.delay)
        got = self.closures.get(seed, self.default)
        if isinstance(got, str):
            raise RuntimeError(got)
        return SimpleNamespace(closure_clean=got[0], closure=got[1], open_before=10, open_after=3, valid=True)


def improving(n: int, top: int = 40) -> list:
    """`n` seeds of make()'s explore, each scoring better than the one before and all better than the plain placement:
    tried in this order, each is a new best."""
    from placemat import explore
    board = make()
    base = explore.score(board, board.resolve())
    scored = []
    for seed in range(1, top):
        b = make()
        s = explore.score(b, b.resolve(explore=explore.Explore(seed, FOCUS)))
        if s < base - 1e-6 and all(abs(s - x) > 1e-6 for x, _ in scored):
            scored.append((s, seed))
    scored.sort(reverse=True)
    assert len(scored) >= n, scored
    step = len(scored) // n
    return [seed for _, seed in scored[::step][:n - 1]] + [scored[-1][1]]
