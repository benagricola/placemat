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


def make():
    """Six passives round a part on a small board."""
    fps = [footprint("U1", 10, 10, w=8, h=4, inst="mcu", nets=("A", "B"))]
    fps += [footprint("R%d" % k, 60, 60 + 2 * k, w=2, h=1, inst="r%d" % k, nets=NETS[k]) for k in range(6)]
    b = Board(board_geometry(fps, width=30, height=30), edge_margin=1.0)
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
