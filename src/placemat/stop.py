"""Stopping a long command: SIGTERM, SIGHUP and SIGINT raise `Stopped` in the
main thread, so what a command has done is kept and what it says is its own
last line, not silence. A second signal ends the process at once.

`Stopped` is a BaseException, like KeyboardInterrupt: an `except Exception`
in the middle of a run does not swallow it."""
from __future__ import annotations

import os
import signal

SIGNALS = tuple(s for s in (getattr(signal, n, None) for n in ("SIGTERM", "SIGHUP", "SIGINT")) if s is not None)


class Stopped(BaseException):
    """The process was asked to stop. `explore` and `stage` are filled in as
    the stop passes up through what was running."""

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = int(signum)
        self.explore = None             # the explore's partial report, when one was running
        self.partial = None             # the explore's partial result (explore.ExploreResult)
        self.stage = ""                 # what was running: "explore", "resolve", "route" ...
        self.said = False               # its final line has been printed

    @property
    def name(self) -> str:
        try:
            return signal.Signals(self.signum).name
        except ValueError:
            return "signal %d" % self.signum

    @property
    def exit_code(self) -> int:
        return 128 + self.signum


_seen: list = []


def _handler(signum, frame):
    if _seen:
        os._exit(128 + signum)          # the second signal: no cleanup
    _seen.append(signum)
    raise Stopped(signum)


def install() -> dict:
    """Handle the stopping signals in the main thread; returns what was
    there, for `restore`. Anywhere else (a thread, a host that owns its
    signals) nothing is installed."""
    previous = {}
    _seen.clear()
    try:
        for s in SIGNALS:
            previous[s] = signal.signal(s, _handler)
    except ValueError:                  # not the main thread
        pass
    return previous


def restore(previous: dict) -> None:
    for s, h in previous.items():
        try:
            signal.signal(s, h)
        except (ValueError, TypeError):
            pass
    _seen.clear()


def pid_alive(pid) -> bool:
    """Whether a process with this pid exists (this user's or not)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def record(s: "Stopped", command: str = "", **more) -> dict:
    """What a stop was, as data: the signal, what was running, and what the caller adds (the run id, the record's path,
    the seconds, the explore's partial report). Text is made from it by `line`, at the edge."""
    return {"kind": "stopped", "signal": s.name, "stage": s.stage, "command": command, **more}


def line(rec: dict) -> str:
    """The one line a stop record says, for the console and `placemat watch`."""
    who = ("run %s" % rec["run_id"]) if rec.get("run_id") else rec.get("command") or "the command"
    out = "%s stopped by %s" % (who, rec["signal"])
    if rec.get("stage"):
        out += " during %s" % rec["stage"]
    if rec.get("elapsed_s") is not None:
        out += " after %.0f s" % rec["elapsed_s"]
    if rec.get("run_id"):
        out += "; the layout folder is as the last run left it; %s" % rec.get("record", "")
    return out.rstrip("; ")


def say(text: str, both: bool = True) -> None:
    """A stop's own words: never lost to -q or --json. On stderr always, and
    on stdout too unless the console is quiet; `both=False` leaves stderr
    out when stdout has it (a terminal shows both streams)."""
    import sys
    from .console import console
    if not console.quiet:
        console.say("stop", text, level="fail")
    if both or console.quiet:
        print(text, file=sys.stderr, flush=True)


def parent_death_signal() -> None:
    """In a worker: be killed when the parent dies, however it dies (Linux
    PR_SET_PDEATHSIG; elsewhere a daemon process is all there is)."""
    import sys
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes
        ctypes.CDLL(None, use_errno=True).prctl(1, int(signal.SIGKILL), 0, 0, 0)     # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass
