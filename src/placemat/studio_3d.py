"""The studio's side of the 3D view: the converter process (model_convert.py), the queue of models to convert, what is known about each, and the
bodies of the 3D routes. The page's viewer is studio_3d.js; the plan document carries each part's models and matrices (model_plan.py).

Jobs arrive from the resolve worker (and from other commands' streamed items) as `{id, kind, path | board+ref, name}`. Nothing a client sends
names a file: a job names a model file or a board file, which is checked to exist and to be of the kind it says before it is queued, and a
mesh is served by its id, validated as 32 hex characters (or `e-` and up to 32).

Events to the page: `model` {id, state, tris, message} as each conversion finishes or fails, `models` {done, total, current} while a batch
runs, and `models3d` {cli, ok, message, version} when the converter is ready (its self-test) or has stopped. The converter's own events
carry failures as records (model_convert.failure_text); the page's `message` is made here, where they arrive."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

from . import model_cache
from .childenv import child_env
from .model_convert import failure_text
from .model_mesh import CONVERTER_VERSION

ID_RE = re.compile(r"^(?:[0-9a-f]{32}|e-[0-9a-f]{1,32})$")
STEP_EXT = (".step", ".stp")
VRML_EXT = (".wrl", ".wrz")
LIB_FILES = {"three.module.min.js": "text/javascript", "three.core.min.js": "text/javascript", "OrbitControls.js": "text/javascript",
             "viewer.js": "text/javascript", "viewer_core.js": "text/javascript", "LICENSE": "text/plain; charset=utf-8"}
LIB_DIR = Path(__file__).with_name("vendor") / "three"
VIEWER = Path(__file__).with_name("studio_3d.js")
VIEWER_CORE = Path(__file__).with_name("studio_3d_core.js")      # the viewer's pure parts, served as viewer_core.js


def lib_file(name: str):
    """(path, content type) of a file the 3D view loads, from the fixed list; None for any other name."""
    if name not in LIB_FILES:
        return None
    p = VIEWER if name == "viewer.js" else VIEWER_CORE if name == "viewer_core.js" else LIB_DIR / name
    return (p, LIB_FILES[name]) if p.is_file() else None


def valid_job(job) -> dict | None:
    """`job` as a clean converter job, or None when it is not one this studio may run."""
    if not isinstance(job, dict) or not isinstance(job.get("id"), str) or not ID_RE.match(job["id"]):
        return None
    kind = job.get("kind")
    out = {"id": job["id"], "kind": kind, "name": str(job.get("name") or "")[:200]}
    if kind in ("file", "vrml"):
        path = job.get("path")
        if not isinstance(path, str) or not path.lower().endswith(STEP_EXT + VRML_EXT) or not os.path.isfile(path):
            return None
        if (kind == "vrml") != path.lower().endswith(VRML_EXT):
            return None
        out["path"] = path
    elif kind == "embedded":
        board, ref = job.get("board"), job.get("ref")
        if not isinstance(board, str) or not board.endswith(".kicad_pcb") or not os.path.isfile(board) or not isinstance(ref, str) or not ref:
            return None
        out.update(board=board, ref=ref)
    else:
        return None
    return out


class Models3D:
    """The converter process and what is known about the models it was given. `emit(name, data)` tells the page."""

    def __init__(self, cfg, emit, log_path: Path | None = None, command: list | None = None):
        self.cfg, self.emit, self.log_path = cfg, emit, log_path
        self.command = command or [sys.executable, "-m", "placemat.model_convert"]
        self.lock = threading.RLock()
        self.known: dict = {}                 # id -> {"state": loading | ok | failed, "tris", "message"}
        self.jobs: dict = {}                  # id -> the job, for a retry
        self.queue: deque = deque()
        self.busy = False
        self.proc = None
        self.ready: dict | None = None        # the converter's `ready` event
        self.progress = {"done": 0, "total": 0, "current": ""}
        self._stopped = False
        self.cache = model_cache.Cache(model_cache.default_dir(cfg.studio_3d_cache_dir), cfg.studio_3d_cache_mb)

    # ---- state, for hello and GET /3d/models
    def status(self) -> dict:
        with self.lock:
            r = self.ready or {}
            test = r.get("selftest") or {}
            return {"started": self.proc is not None, "ready": self.ready is not None, "cli": bool(r.get("cli")), "ok": bool(test.get("ok")),
                    "message": failure_text(test["failure"]) if test.get("failure") else "", "version": test.get("version", ""), "progress": dict(self.progress),
                    "converter": CONVERTER_VERSION, "max_tris": int(self.cfg.studio_3d_max_tris), "appear_ms": int(self.cfg.studio_3d_appear_ms),
                    "plate_mm": float(self.cfg.studio_3d_plate_mm)}

    def table(self) -> dict:
        with self.lock:
            return {k: dict(v) for k, v in self.known.items()}

    # ---- jobs
    def submit(self, jobs) -> int:
        """Queue the valid jobs not known yet; returns how many were new."""
        new = []
        with self.lock:
            for j in jobs or ():
                j = valid_job(j)
                if j is None or j["id"] in self.known:
                    continue
                self.known[j["id"]] = {"state": "loading", "tris": None, "message": ""}
                self.jobs[j["id"]] = j
                new.append(j)
            self.queue.extend(new)
        if new:
            self._kick()
        return len(new)

    def _kick(self) -> None:
        with self.lock:
            if self.busy or not self.queue or self._stopped:
                return
            batch = list(self.queue)
            self.queue.clear()
            if not self._ensure():
                for j in batch:
                    self._set(j["id"], "failed", None, "the model converter could not start")
                return
            self.busy = True
            self.progress = {"done": 0, "total": len(batch), "current": ""}
            ok = self._send({"cmd": "batch", "jobs": batch})
            if not ok:
                self.busy = False
                for j in batch:
                    self._set(j["id"], "failed", None, "the model converter stopped")

    def _ensure(self) -> bool:
        if self.proc is not None and self.proc.poll() is None:
            return True
        try:
            log = open(self.log_path, "ab") if self.log_path else subprocess.DEVNULL
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1,
                                         env=child_env(headless=False))
        except OSError:
            self.proc = None
            return False
        self.ready = None
        threading.Thread(target=self._read, args=(self.proc,), daemon=True, name="placemat-3d-converter").start()
        cfg = self.cfg
        self._send({"cmd": "start", "cfg": {"kicad_cli": cfg.studio_3d_kicad_cli, "batch": cfg.studio_3d_batch, "timeout_s": cfg.studio_3d_batch_timeout_s,
                                           "model_tris": cfg.studio_3d_model_tris, "cache_dir": cfg.studio_3d_cache_dir, "cache_mb": cfg.studio_3d_cache_mb}})
        return True

    def _send(self, msg: dict) -> bool:
        try:
            self.proc.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n")
            self.proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError, AttributeError):
            return False

    def _set(self, id: str, state: str, tris, message: str) -> None:
        with self.lock:
            self.known[id] = {"state": state, "tris": tris, "message": message}
        self.emit("model", {"id": id, "state": state, "tris": tris, "message": message})

    def _read(self, proc) -> None:
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("ev")
            if kind == "ready":
                with self.lock:
                    self.ready = ev
                self.emit("models3d", self.status())
            elif kind == "model":
                self._set(ev["id"], ev["state"], ev.get("tris"), failure_text(ev["failure"]) if ev.get("failure") else "")
            elif kind == "progress":
                with self.lock:
                    self.progress = {"done": ev["done"], "total": ev["total"], "current": ev.get("current", "")}
                self.emit("models", dict(self.progress))
            elif kind == "batch_done":
                with self.lock:
                    self.busy = False
                    self.progress = {"done": 0, "total": 0, "current": ""}
                self.emit("models", dict(self.progress))
                self._kick()
        code = proc.wait()
        with self.lock:
            if self.proc is proc:
                self.proc, self.busy = None, False
                lost = [i for i, v in self.known.items() if v["state"] == "loading"]
        if not self._stopped and code != 0:
            for i in lost:
                self._set(i, "failed", None, "the model converter stopped (exit %s)" % code)
            self.emit("models3d", dict(self.status(), message="the model converter stopped (exit %s)" % code))

    # ---- retry
    def retry(self, id: str | None = None) -> int:
        """Forget failures (one id, or every one) and queue them again; returns how many."""
        with self.lock:
            ids = [i for i, v in self.known.items() if v["state"] == "failed" and (id is None or i == id)]
            jobs = [self.jobs[i] for i in ids if i in self.jobs]
            for i in ids:
                self.known.pop(i, None)
        if self.proc is not None and self.proc.poll() is None:
            self._send({"cmd": "retry", "id": id})
        else:
            self.cache.retry(id)
        return self.submit(jobs)

    # ---- the mesh
    def mesh_path(self, id: str):
        """The cached mesh file for a valid id, or None."""
        if not isinstance(id, str) or not ID_RE.match(id):
            return None
        return self.cache.get(id)

    def stop(self) -> None:
        self._stopped = True
        proc = self.proc
        if proc is None:
            return
        try:
            proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=3)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            pass
        if proc.poll() is None:
            proc.kill()
            proc.wait()
