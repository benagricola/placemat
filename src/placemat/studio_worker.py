"""The studio's warm resolve: one process that keeps placemat (and pcbnew, when
the board needs it) imported, the cached generation read and the last
resolve's record, and resolves a script as `placemat preview` does - nothing
written to the board, no DRC, no render - sending what it learns as it goes.

A Session turns one request into events: `board` (the outline, once it is
known), an `item` as each step settles, then `done` with the whole plan, or
`cancelled`, or `error`. `main()` runs a Session over JSON lines on stdin and
stdout, so studio.py can stop and start it. A cancel is honoured at the next
step or progress call, which keeps the process warm; a resolve that does not
reach one is the server's to kill."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time


class Cancelled(BaseException):
    """Raised inside a resolve that was asked to stop. Not an Exception: a
    script or a pass that catches those does not swallow it."""


def _views(src) -> Path:
    return src.board_dir / ".placemat" / "views" / "studio"


class Session:
    def __init__(self, send=None):
        self.send = send or (lambda event: None)
        self.cache: dict = {}
        self._cancel: int | None = None
        self.sent_models: set = set()           # model ids the studio has been given jobs for (studio_3d.py)

    def _models(self, plan):
        """The 3D view's model context for the board this plan was read from (model_plan.py), or None when it cannot be made."""
        try:
            from .model_plan import ModelContext
            from .settings import active
            s = active()
            dirs = [d for d in (s.studio_3d_model_dirs or "").split(os.pathsep) if d]
            from .model_convert import find_kicad_cli
            return ModelContext(plan.geometry.path, dirs, find_kicad_cli(s.studio_3d_kicad_cli))
        except Exception:
            return None

    def _send_jobs(self, ctx) -> None:
        if ctx is not None:
            jobs = ctx.new_jobs(self.sent_models)
            if jobs:
                self.send({"ev": "model_jobs", "jobs": jobs})

    def cancel(self, id) -> None:
        self._cancel = id

    def _check(self, id) -> None:
        if self._cancel == id:
            raise Cancelled()

    def resolve(self, id, script, fresh=False) -> None:
        from .previewer import resolved
        from .preview_json import board_json, declared_sites, item_json, plan_json, step_extras
        from .project import find_board
        from .runner import RunFailure
        send, t0 = self.send, time.monotonic()
        state = {"sites": {}, "first": None, "board": False, "models": None}

        def on_board(board):
            state["sites"] = declared_sites(board)

        def on_step(plan, step):
            self._check(id)
            now = time.monotonic()
            if state["first"] is None:
                state["first"] = now - t0
            if not state["board"]:
                state["board"] = True
                send({"ev": "board", "id": id, **board_json(plan)})
            if state["models"] is None:
                state["models"] = self._models(plan) or False
            ctx = state["models"] or None
            send({"ev": "item", "id": id, "item": item_json(plan, step, state["sites"], ctx), **step_extras(plan, step)})
            self._send_jobs(ctx)

        last_phase = [0.0]

        def on_begin(plan, info):
            """What the engine is starting or doing: the queue's size, the item it begins, a phase of a long step. Phases
            go out a few times a second, the rest as they come."""
            self._check(id)
            now = time.monotonic()
            if info["kind"] == "phase":
                if now - last_phase[0] < 0.25:
                    return
                last_phase[0] = now
            send({"ev": "begin", "id": id, **info})

        try:
            out = _views(find_board(Path(script).resolve()))
            with resolved(script, out, quiet=True, progress=lambda text: self._check(id), on_step=on_step, on_begin=on_begin,
                          cache=self.cache, on_board=on_board, fresh=fresh) as r:
                t1 = time.monotonic()
                self._check(id)
                send({"ev": "board", "id": id, **board_json(r.plan)})       # the frame a fit board settled on
                score = _score(r)
                ctx = state["models"] or self._models(r.plan)
                doc = plan_json(r.plan, state["sites"], score, ctx)
                self._send_jobs(ctx)
                t2 = time.monotonic()
                from . import reuse as reuse_mod
                send({"ev": "done", "id": id, "doc": doc,
                      "reused": reuse_mod.summary(r.plan.reuse, r.previous, r.source),
                      "notes": ["the cached generation is out of date (%s): this shows the old one" % r.stale] if r.stale else [],
                      "timing": {"resolve_s": round(t1 - t0, 3), "first_step_s": round(state["first"] if state["first"] is not None else t1 - t0, 3),
                                 "plan_s": round(t2 - t1, 3), "total_s": round(t2 - t0, 3)}})
        except Cancelled:
            send({"ev": "cancelled", "id": id})
        except RunFailure as e:
            d = e.details
            send({"ev": "error", "id": id, "message": "%s: %s" % (e, d.get("error", "")), "file": d.get("script", ""),
                  "line": d.get("line"), "source": d.get("source"), "detail": d.get("traceback", "")})
        except Exception as e:                  # a known failure or not, the page gets its type, message and the script's own line
            send(error_event(id, e, script))


    def try_(self, id, script, overlay) -> None:
        """Resolve `script` with `overlay` ({path: text}) in place of those files on disk, as a try of a suggestion: the last
        record is replayed from and none is written, no step is sent, and the answer is one `try_done` with the plan (or
        `try_cancelled`, `try_error`). A cancel is honoured at the next step, as a resolve's is."""
        from .previewer import resolved
        from .preview_json import declared_sites, plan_json
        from .project import find_board
        from .runner import RunFailure
        send, t0, state = self.send, time.monotonic(), {"sites": {}}

        def on_board(board):
            state["sites"] = declared_sites(board)

        def check(*_):
            self._check(id)

        try:
            out = _views(find_board(Path(script).resolve()))
            with resolved(script, out, quiet=True, progress=check, on_step=check, on_begin=check, cache=self.cache,
                          on_board=on_board, overlay=overlay) as r:
                self._check(id)
                ctx = self._models(r.plan)
                doc = plan_json(r.plan, state["sites"], _score(r), ctx)
                self._send_jobs(ctx)
                send({"ev": "try_done", "id": id, "doc": doc, "timing": {"total_s": round(time.monotonic() - t0, 3)}})
        except Cancelled:
            send({"ev": "try_cancelled", "id": id})
        except RunFailure as e:
            d = e.details
            send({"ev": "try_error", "id": id, "message": "%s: %s" % (e, d.get("error", "")), "file": d.get("script", ""), "line": d.get("line")})
        except Exception as e:
            ev = error_event(id, e, script)
            send({"ev": "try_error", "id": id, "message": ev["message"], "file": ev["file"], "line": ev["line"]})


def error_event(id, e, script) -> dict:
    """An `error` event for an exception: its type and message, and the innermost frame that is in the script or a
    module it imports (file, line, source line), the whole traceback as the detail."""
    import traceback
    from .project import script_files
    try:
        mine = {Path(f).resolve() for f in script_files(Path(script).resolve(), missing=True)} | {Path(script).resolve()}
    except Exception:
        mine = {Path(script).resolve()}
    frames = [f for f in traceback.extract_tb(e.__traceback__) if Path(f.filename).resolve() in mine]
    where = frames[-1] if frames else None
    text = str(e).splitlines()[0] if str(e) else ""
    return {"ev": "error", "id": id, "message": "%s: %s" % (type(e).__name__, text) if text else type(e).__name__,
            "file": str(Path(where.filename).resolve()) if where else "", "line": where.lineno if where else None,
            "source": where.line if where else None, "detail": "".join(traceback.format_exception(e))}


def _score(r):
    """The run score of the resolved plan (score.py), as {total, terms}, or
    None when it cannot be worked out."""
    from . import score as score_mod
    try:
        m = score_mod.plan_measures(r.board, r.plan)
        terms = score_mod.terms(m, r.cfg)
        return {"total": round(score_mod.total(m, r.cfg), 3), "terms": {k: round(v, 3) for k, v in terms.items() if v}}
    except Exception as e:                      # a score is a courtesy: the plan is shown without it
        print("studio worker: score failed: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return None


def main() -> int:
    """JSON lines in: {"cmd": "resolve", "id", "script"}, {"cmd": "try", "id", "script", "overlay"}, {"cmd": "cancel", "id"}, {"cmd": "quit"}.
    JSON lines out: the Session's events, and {"ev": "ready"} once placemat is loaded."""
    from . import channel
    channel.disable()                           # the studio's own resolve is not a command to report to the studios
    import faulthandler
    faulthandler.enable()                       # a crash that kills the process leaves a Python traceback in the log
    out = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)                               # whatever else prints goes to stderr, not into the protocol
    sys.stdout = sys.stderr
    lock = threading.Lock()

    def send(event):
        with lock:
            out.write(json.dumps(event, separators=(",", ":")) + "\n")
            out.flush()

    session = Session(send)
    import queue
    todo: queue.Queue = queue.Queue()

    def read():
        for line in sys.stdin:
            try:
                cmd = json.loads(line)
            except ValueError:
                continue
            if cmd.get("cmd") == "cancel":
                session.cancel(cmd.get("id"))
            else:
                todo.put(cmd)
        todo.put({"cmd": "quit"})

    threading.Thread(target=read, daemon=True).start()
    from . import previewer, preview_json, layout    # noqa: F401  (warm: imported before the first request)
    send({"ev": "ready"})
    while True:
        cmd = todo.get()
        if cmd.get("cmd") == "quit":
            return 0
        if cmd.get("cmd") == "resolve":
            session.resolve(cmd["id"], cmd["script"], bool(cmd.get("fresh")))
        elif cmd.get("cmd") == "try":
            session.try_(cmd["id"], cmd["script"], cmd.get("overlay") or {})


if __name__ == "__main__":
    sys.exit(main())
