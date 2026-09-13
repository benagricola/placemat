"""Silences KiCad's own chatter. pcbnew's wxWidgets layer writes assertion
notes and image-handler debug lines straight to file descriptor 2, past
Python's sys.stderr; this captures fd 2 for the duration of a call and
lets through only the lines that are not that noise."""
from __future__ import annotations

from contextlib import contextmanager
import os
import re
import sys
import tempfile

NOISE = (
    re.compile(r"property\.h\(\d+\): assert"),
    re.compile(r"Debug: Adding duplicate image handler"),
    re.compile(r"swig/python detected a memory leak"),
)


def _is_noise(line: str) -> bool:
    return any(p.search(line) for p in NOISE)


@contextmanager
def quiet_stderr():
    """Capture fd 2 while the block runs; afterwards re-emit anything that
    was not KiCad noise."""
    sys.stderr.flush()
    saved = os.dup(2)
    with tempfile.TemporaryFile(mode="w+b") as tmp:
        os.dup2(tmp.fileno(), 2)
        try:
            yield
        finally:
            sys.stderr.flush()
            os.dup2(saved, 2)
            os.close(saved)
            tmp.seek(0)
            for raw in tmp.read().decode(errors="replace").splitlines():
                if raw.strip() and not _is_noise(raw):
                    print(raw, file=sys.stderr)


def import_pcbnew():
    """`import pcbnew` without the assertion notes it prints on load."""
    with quiet_stderr():
        import pcbnew
    return pcbnew
