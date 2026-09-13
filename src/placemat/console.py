"""Prints the run's progress: one line per event with a timestamp and the
stage it belongs to, coloured when stdout is a terminal (NO_COLOR or a
pipe turns colour off)."""
from __future__ import annotations

import os
import sys
import time

_COLOURS = {
    "run": "1;36", "board": "36", "id": "1", "script": "36", "step": "2", "bridge": "35",
    "check": "36", "route": "36", "render": "36", "impact": "33", "record": "2",
    "finding": "33", "fail": "1;31", "note": "2",
}


class Console:
    def __init__(self, quiet: bool = False, stream=None):
        self.quiet = quiet
        self.stream = stream or sys.stdout
        self.colour = (os.environ.get("NO_COLOR") is None and hasattr(self.stream, "isatty") and self.stream.isatty())

    def _paint(self, code: str, text: str) -> str:
        return "\033[%sm%s\033[0m" % (code, text) if self.colour and code else text

    def say(self, stage: str, message: str = "", *, level: str | None = None):
        """One event. `stage` is the column that stays aligned; `level`
        overrides the colour (finding, fail)."""
        if self.quiet:
            return
        stamp = self._paint("2", time.strftime("%H:%M:%S"))
        code = _COLOURS.get(level or stage, "")
        label = self._paint(code, "%-7s" % stage)
        body = self._paint(code, message) if level in ("finding", "fail", "impact") else message
        print("%s  %s %s" % (stamp, label, body), file=self.stream, flush=True)

    def lines(self, stage: str, text: str, *, level: str | None = None):
        """A multi-line message, every line stamped and labelled."""
        for line in text.splitlines():
            self.say(stage, line, level=level)
