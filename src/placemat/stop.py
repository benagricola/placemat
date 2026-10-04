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
        self.cause = _cause             # who asked, when it was not a person: {"cause": "max_time", "limit_s": ...} (`request`)

    @property
    def name(self) -> str:
        try:
            return signal.Signals(self.signum).name
        except ValueError:
            return "signal %d" % self.signum

    @property
    def label(self) -> str:
        """What stopped it, for a sentence: the signal, or the time cap."""
        if self.cause and self.cause.get("cause") == "max_time":
            return "the time cap (--max-time %g s)" % self.cause["limit_s"]
        return self.name

    @property
    def exit_code(self) -> int:
        return 128 + self.signum


_seen: list = []
_cause: dict | None = None


def request(cause: str, **facts) -> None:
    """Ask this process to stop, as a SIGTERM does, for a reason of its own (the time cap, timecap.py): the handler raises
    `Stopped` carrying `cause`. A process that did not install the handlers is not stopped."""
    global _cause
    if not _installed:
        return
    _cause = {"cause": cause, **facts}
    os.kill(os.getpid(), signal.SIGTERM)


_installed: list = []


def _handler(signum, frame):
    if _seen:
        os._exit(128 + signum)          # the second signal: no cleanup
    global _cause
    _seen.append(signum)
    s = Stopped(signum)
    _cause = None                       # a request is for one stop
    raise s


def install() -> dict:
    """Handle the stopping signals in the main thread; returns what was
    there, for `restore`. Anywhere else (a thread, a host that owns its
    signals) nothing is installed."""
    global _cause
    previous = {}
    _seen.clear()
    _cause = None
    try:
        for s in SIGNALS:
            previous[s] = signal.signal(s, _handler)
        _installed[:] = [True]
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
    _installed.clear()


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
    return {"kind": "stopped", "signal": s.name, "stage": s.stage, "command": command, **cause_fields(s), **more}


def cause_fields(s: "Stopped") -> dict:
    """What a stop by something other than a person adds to its record: the cause (`max_time` and its limit) and where the
    command had got to (timecap.Clock.report); nothing for a signal sent from outside."""
    if not s.cause:
        return {}
    from . import timecap
    return {**s.cause, **timecap.report()}


def line(rec: dict) -> str:
    """The one line a stop record says, for the console and `placemat watch`."""
    who = ("run %s" % rec["run_id"]) if rec.get("run_id") else rec.get("command") or "the command"
    if rec.get("cause") == "max_time":
        return _cap_line(rec, who)
    out = "%s stopped by %s" % (who, rec["signal"])
    if rec.get("stage"):
        out += " during %s" % rec["stage"]
    if rec.get("elapsed_s") is not None:
        out += " after %.0f s" % rec["elapsed_s"]
    if rec.get("run_id"):
        out += "; the layout folder is as the last run left it; %s" % rec.get("record", "")
    return out.rstrip("; ")


def _cap_line(rec: dict, who: str) -> str:
    """What a stop by the time cap says: how far the placement got, what was under way, and that the rerun goes on from there."""
    out = "%s stopped at --max-time %g s" % (who, rec["limit_s"])
    if rec.get("stage"):
        out += " during %s" % rec["stage"]
    done, of = rec.get("steps_done"), rec.get("steps_of")
    if done is not None and rec.get("stage") == "resolve":
        out += ": %d%s steps done" % (done, (" of %d" % of) if of else "")
        now = rec.get("in_progress")
        if now:
            from .timecap import pass_phrase
            out += ", %s in progress (%s, %.0f s)" % (now["item"], pass_phrase(now["pass"], now.get("within"), now.get("firm_pass")), now["elapsed_s"])
        found = rec.get("findings") or {}
        if found.get("count"):
            out += ", %d finding(s) so far (%s)" % (found["count"], ", ".join("%d %s" % (n, s) for s, n in found["by_severity"].items()))
        else:
            out += ", no findings so far"
    if rec.get("explore"):
        out += "; the explore keeps its %d variant(s) and its checkpoint" % rec["explore"].get("tried", 0)
    if rec.get("stage") in ("resolve", "explore", "generate"):
        out += "; run it again and it goes on from there"
        if (done or 0) > 0 and rec.get("stage") == "resolve":
            out += " (the %d finished steps are replayed, not searched again)" % done
        out += ", with a larger --max-time or none"
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
