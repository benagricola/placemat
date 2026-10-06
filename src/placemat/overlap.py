"""The stages of a run that only read the written board - kicad-cli's DRC and its renders - started as soon as the board is
written, to run while the checks work (`run.parallel`).

KiCad's Python bindings are not thread-safe, so nothing here touches pcbnew: each job is a thread that starts kicad-cli
processes and waits on them, and pcbnew stays in the main thread. A job's result, or what it raised, is taken at the point
of the run where the stage ran in sequence, so the record and the console read as they do in sequence.

With `parallel` false a job runs when its result is asked for, which is the sequence the run had before."""
from __future__ import annotations

import subprocess
import threading
import time

from . import stop
from .childenv import child_env


class Cancelled(Exception):
    """A job asked to start a process after the run was closed (stopped or failed)."""


class Children:
    """The processes the jobs have started, so closing the run can kill them."""

    def __init__(self):
        self._lock = threading.Lock()
        self._live: set = set()
        self.closed = False

    def run(self, cmd, timeout=None, input=None, capture_output=False, **kwargs) -> subprocess.CompletedProcess:
        """`subprocess.run`, with the process killable by `kill`: on a timeout or anything raised while it waits it is
        killed, as subprocess.run kills it."""
        if capture_output:
            kwargs["stdout"] = kwargs["stderr"] = subprocess.PIPE
        with self._lock:
            if self.closed:
                raise Cancelled(" ".join(map(str, cmd)))
            env = kwargs.pop("env", None)
            proc = subprocess.Popen(cmd, env=env if env is not None else child_env(), **kwargs)
            self._live.add(proc)
            stop.track(proc)
        try:
            out, err = proc.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        finally:
            with self._lock:
                self._live.discard(proc)
            stop.untrack(proc)
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)

    def kill(self) -> None:
        with self._lock:
            self.closed = True
            live = list(self._live)
        for proc in live:
            try:
                proc.kill()
            except OSError:
                pass


class Job:
    """One stage: `work(run)` is called with the function that starts its processes (`subprocess.run` in sequence,
    `Children.run` alongside). `seconds` is its own time from start to end."""

    def __init__(self, work, children: Children | None):
        self._work, self._children = work, children
        self._value, self._error, self.seconds = None, None, None
        self._thread = None
        if children is not None:
            self._thread = threading.Thread(target=self._body, daemon=True)
            self._thread.start()

    def _body(self):
        t0 = time.time()
        try:
            self._value = self._work(self._children.run if self._children is not None else subprocess.run)
        except BaseException as e:      # handed to the main thread by `result`
            self._error = e
        finally:
            self.seconds = time.time() - t0

    def result(self):
        """What the stage returned, or what it raised, raised here."""
        if self._thread is None:
            if self.seconds is None:
                self._body()
        else:
            self._thread.join()
        if self._error is not None:
            raise self._error
        return self._value

    def join(self, timeout=None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)


class Background:
    """The jobs of one run. `close` kills what they still run and waits for their threads; it is called on every way out of
    the stages, so a stop or a failure leaves no kicad-cli behind."""

    def __init__(self, parallel: bool):
        self.parallel = parallel
        self.children = Children() if parallel else None
        self.jobs: list = []

    def start(self, work) -> Job:
        job = Job(work, self.children)
        self.jobs.append(job)
        return job

    def close(self) -> None:
        if self.children is not None:
            self.children.kill()
        for job in self.jobs:
            job.join()
