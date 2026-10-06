"""The realboard lock: real-board runs (KiCad, the router) take it one at a time. It is the file flock(1) takes, so a run
under `flock <lock> ...` and one that takes it here exclude each other. $REALBOARD_LOCK overrides the path."""
from __future__ import annotations

import contextlib
import fcntl
import os

LOCK_ENV = "REALBOARD_LOCK"
DEFAULT_LOCK = "/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock"


@contextlib.contextmanager
def realboard():
    """Hold the lock exclusively, waiting for it; released on exit."""
    with open(os.environ.get(LOCK_ENV, DEFAULT_LOCK), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
