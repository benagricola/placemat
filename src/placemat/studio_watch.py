"""What `placemat studio` watches with: a poll of modification times (no
inotify) and a debounce, both free of clocks and threads so they can be
tested; studio.py runs them on a timer."""
from __future__ import annotations

import os
from pathlib import Path


class Poller:
    """Which of a set of files changed between two scans. The set is asked
    for again each scan (an import added to the script adds a file). A file
    first seen with the scan is a baseline, not a change; one that appears
    or goes after that is."""

    def __init__(self, files):
        self._files = files
        self._seen = {}
        self.scan()

    @staticmethod
    def _stamp(path: Path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def scan(self) -> set:
        changed, current = set(), {}
        for path in self._files():
            path = Path(path)
            stamp = self._stamp(path)
            current[path] = stamp
            if path in self._seen and self._seen[path] != stamp:
                changed.add(path)
        for path, stamp in self._seen.items():
            if path not in current and stamp is not None:
                changed.add(path)
        self._seen = current
        return changed


class Debounce:
    """The quiet period before a resolve, and what a change during one does.
    `changed` records files and when; `due` hands them over once `quiet`
    seconds have passed with no further change and nothing is running. A
    change while a resolve runs returns True: the caller cancels it, and the
    resolve starts again when `stopped` says it has stopped and the quiet
    period is over."""

    def __init__(self, quiet: float):
        self.quiet = quiet
        self._pending: set = set()
        self._last = 0.0
        self.running = False

    def changed(self, now: float, paths) -> bool:
        self._pending |= set(paths)
        self._last = now
        return self.running

    def expedite(self) -> None:
        """Whatever is pending is due now, without a quiet period."""
        self._last = float("-inf")

    def started(self) -> None:
        self.running = True

    def stopped(self) -> None:
        self.running = False

    def due(self, now: float):
        if not self._pending or self.running or now - self._last < self.quiet:
            return None
        out, self._pending = self._pending, set()
        return out
