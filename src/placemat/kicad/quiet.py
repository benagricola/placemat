"""Silences KiCad's own chatter without losing it. pcbnew's wxWidgets layer
writes assertion notes and image-handler debug lines straight to file
descriptor 2, past Python's sys.stderr; this captures fd 2 for the
duration of a call, lets through every line that is not one of the known
noise patterns, and keeps the whole capture so the runner can write it to
a log. PLACEMAT_SHOW_KICAD=1 shows everything on stderr as well."""
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


captured: list = []        # every line KiCad wrote, noise included, in order


def drain() -> str:
    """Everything captured so far, and start again."""
    text = "\n".join(captured)
    captured.clear()
    return text


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
            show_all = os.environ.get("PLACEMAT_SHOW_KICAD") not in (None, "", "0")
            for raw in tmp.read().decode(errors="replace").splitlines():
                if not raw.strip():
                    continue
                captured.append(raw)
                if show_all or not _is_noise(raw):
                    from ..console import errors
                    errors.say("kicad", raw)


def import_pcbnew():
    """`import pcbnew` without the assertion notes it prints on load."""
    with quiet_stderr():
        import pcbnew
    return pcbnew
