"""The realboard lock: real-board runs (KiCad, the router) take it one at a time. It is the file flock(1) takes, so a run
under `flock <lock> ...` and one that takes it here exclude each other. It is placemat-realboard.lock in the system's
temporary directory; $REALBOARD_LOCK overrides the path."""
from __future__ import annotations

import contextlib
import fcntl
import os
import tempfile

LOCK_ENV = "REALBOARD_LOCK"
LOCK_NAME = "placemat-realboard.lock"


def lock_path() -> str:
    return os.environ.get(LOCK_ENV) or os.path.join(tempfile.gettempdir(), LOCK_NAME)


@contextlib.contextmanager
def realboard():
    """Hold the lock exclusively, waiting for it; released on exit."""
    with open(lock_path(), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
