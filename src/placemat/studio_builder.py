"""The studio's board builder, server side: the state of a builder session and what each of its requests does.

The page sends structured requests (an outline, a fact, a subject and a target); this module turns them into edits with `builder`
and its parts, and the edits go through the suggestions engine's one application path (digest check, atomic write, applied log).
The page never sends source text. The board is generated and read by `builder_worker` in a process of its own, so pcbnew stays
out of the studio server; its progress lines reach the pages as `build` events on the studio's stream.

The module holds no layout state of its own: after every resolve the page reads what is placed, how and relative to what from the
script and the plan."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from . import builder, builder_facts as bf, builder_intents as bi, builder_parts as bp, builder_worker, channel, script_edit, suggestions as sg, zen_edit
from .suggestions import Edit



class BuildRefused(Exception):
    """A builder request that is not carried out: `status` is the HTTP status, the message names the rule. Nothing was written."""

    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


def refuse(e: builder.BuilderRefused) -> BuildRefused:
    return BuildRefused(422, e.reason, rule=e.rule, **e.extra)


def subprocess_reader(request: dict, say):
    """Run `builder_worker` on `request`; `say(progress)` gets its progress records. Returns the worker's last event (`board` or `error`)."""
    proc = subprocess.Popen([sys.executable, "-m", "placemat.builder_worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, cwd=str(Path(request["zen"]).resolve().parent))
    say.proc = proc
    last = {"ev": "error", "kind": "no_answer", "tail": ""}
    try:
        proc.stdin.write(json.dumps(request))
        proc.stdin.close()
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("ev") == "progress":
                say({k: v for k, v in ev.items() if k != "ev"})
            else:
                last = ev
        proc.wait()
    finally:
        say.proc = None
    return last


class Say:
    """The progress sink of one reader run, keeping the process so a stop can end it."""
    proc = None

    def __init__(self, f):
        self.f = f

    def __call__(self, progress):
        self.f(progress)


class BuilderService:
    def __init__(self, studio, reader=None):
        self.studio = studio
        self.reader = reader or subprocess_reader
        self.session = None                 # {"zen": Path, "name": str, "board_dir": Path, "script": Path}
        self.record = None                  # the worker's last record of the board
        self.phase = "idle"                 # idle, working, ready, error
        self.text = ""                      # the last progress line, or the error
        self.tail = ""                      # a failed generation's log tail
        self.offers: dict = {}              # sid -> {"rid", "suggestion", "subject"}
        self._unbuilt = None
        self._counter = 0
        self._say = None
        self._thread = None
        self._again = 0                     # a read asked for while one is under way: 1 follows it, 2 follows it fresh

    # ------------------------------------------------------------ the endpoints
    def handle(self, path: str, query: dict, body):
        """GET (`body` None) and POST of /build/...: each endpoint is one method; the request is data, never source."""
        get = lambda k, d="": (query.get(k) or [d])[0]
        if body is None:
            if path == "/build/state":
                return self.state()
            if path == "/build/facts":
                return self.facts({k[4:]: True for k in query if k.startswith("ack_")})
            if path == "/build/parts":
                return self.parts(get("resolve"))
            raise BuildRefused(404, "no such builder page")
        if not isinstance(body, dict):
            raise BuildRefused(400, "the request is a JSON object")
        if path == "/build/start":
            return self.start(str(body.get("id", "")), current=bool(body.get("current")))
        if path == "/build/reload":
            self.need_session()
            self.load(fresh=bool(body.get("fresh")))
            return {"started": True}
        if path == "/build/close":
            self.session, self.record, self.phase = None, None, "idle"
            self.offers.clear()
            return {"closed": True}
        if path == "/build/facts/apply":
            return self.facts_apply(body.get("request") or {})
        if path == "/build/facts/confirm":
            return self.facts_confirm(body.get("acks") or {})
        if path == "/build/outline/suggest":
            return self.outline_suggest(body)
        if path == "/build/outline/create":
            return self.outline_create(body)
        if path == "/build/offer":
            return self.offer(body)
        if path == "/build/turns":
            return self.turns(body)
        if path == "/build/turn":
            return self.turn_offer(body)
        raise BuildRefused(404, "no such builder request")

    def need_session(self) -> None:
        if self.session is None:
            raise BuildRefused(409, "no board is open in the builder: start one from the start view")

    def state(self) -> dict:
        out = self.hello()
        rec = self.record
        out["board"] = None if rec is None else {"total_courtyard_area": rec["total_courtyard_area"], "parts": len(rec["parts"]),
                                                 "cells": len(rec["cells"]), "copper_layers": rec["copper_layers"],
                                                 "confirmed": rec.get("confirmed", "")}
        out["script"] = self.studio.script.name if self.studio.script else ""
        return out

    # ------------------------------------------------------------ what there is to start
    def unbuilt(self, refresh: bool = False) -> list:
        """The boards of the project's `.zen` files that have no layout script: each declared by a `Board`, `Project` or `Layout`
        with no `<Board>_layout.py` beside the `.zen`, and no listed script laid out for it either."""
        from .project import declared_boards
        from .studio import _SCAN_LIMIT, _SKIP_DIRS
        if self._unbuilt is not None and not refresh:
            return self._unbuilt
        root = self.studio.root
        have = set()
        for e in self.studio._scripts or ():
            try:
                have.add((str(e["src"].zen.resolve()), e["src"].name))
            except (AttributeError, OSError):
                pass
        out, seen = [], 0
        for folder, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith("."))
            for name in sorted(files):
                seen += 1
                if seen > _SCAN_LIMIT:
                    break
                if not name.endswith(".zen"):
                    continue
                zen = Path(folder, name)
                try:
                    boards, _off = declared_boards(zen)
                except OSError:
                    continue
                for b in boards:
                    script = zen.parent / ("%s_layout.py" % b.name)
                    if script.exists() or (str(zen.resolve()), b.name) in have:
                        continue
                    rel = Path(os.path.relpath(zen, root)).as_posix()
                    out.append({"id": "%s#%s" % (rel, b.name), "zen": rel, "name": b.name, "folder": Path(rel).parent.as_posix()})
        self._unbuilt = out
        return out

    def hello(self) -> dict:
        return {"unbuilt": self.unbuilt(), "phase": self.phase, "text": self.text, "tail": self.tail,
                "session": self.session_json(), "ready": self.record is not None,
                "settings": {"grid_mm": self.studio.cfg.studio_builder_grid_mm, "max_fill": self.studio.cfg.studio_builder_max_fill,
                             "aspect": self.studio.cfg.studio_builder_aspect}}

    def session_json(self):
        s = self.session
        if s is None:
            return None
        return {"zen": self._rel(s["zen"]), "name": s["name"], "script": self._rel(s["script"]), "exists": s["script"].is_file(),
                "board_dir": self._rel(s["board_dir"])}

    def _rel(self, p) -> str:
        try:
            return Path(os.path.relpath(p, self.studio.root)).as_posix()
        except ValueError:
            return str(p)

    # ------------------------------------------------------------ a session
    def start(self, entry_id: str = "", *, current: bool = False) -> dict:
        """Start on an unbuilt board of the project (its id from `unbuilt`), or, with `current`, on the script the studio watches:
        generate and read the board, on a thread, the progress and the result going to the pages as `build` events."""
        st = self.studio
        if current:
            if st.script is None:
                raise BuildRefused(409, "choose a layout script first")
            self.session = {"zen": st.src.zen, "name": st.src.name, "board_dir": st.src.board_dir, "script": st.script}
        else:
            hit = next((e for e in self.unbuilt() if e["id"] == entry_id), None)
            if hit is None:
                raise BuildRefused(404, "%s is not a board of this project without a layout script" % entry_id)
            zen = (st.root / hit["zen"]).resolve()
            script = zen.parent / ("%s_layout.py" % hit["name"])
            if script.exists():
                raise BuildRefused(409, "%s exists: it is opened as an existing script, not started again" % script.name)
            self.session = {"zen": zen, "name": hit["name"], "board_dir": zen.parent, "script": script}
        self.record = None
        self.offers.clear()
        self.load()
        return {"session": self.session_json()}

    def load(self, fresh: bool = False) -> None:
        """Generate (or restore) the board and read it, on a thread."""
        with self.studio.lock:
            if self.phase == "working":             # one read at a time: this one follows the one under way
                self._again = max(self._again or 0, 1 + int(fresh))
                return
            self.phase, self.text, self.tail = "working", "starting", ""
        self.studio.hub.emit("build", {"state": "working", "text": "starting"})
        self._thread = threading.Thread(target=self._load_all, args=(fresh,), daemon=True)
        self._thread.start()

    def _load_all(self, fresh: bool) -> None:
        self._load(fresh)
        while self._again:
            with self.studio.lock:
                again, self._again = self._again, 0
                self.phase, self.text, self.tail = "working", "starting", ""
            self.studio.hub.emit("build", {"state": "working", "text": "starting"})
            self._load(again == 2)

    def _load(self, fresh: bool) -> None:
        s = self.session
        request = {"zen": str(s["zen"]), "name": s["name"], "script": str(s["script"]) if s["script"].is_file() else None, "fresh": fresh}

        def progress(record):
            text = builder_worker.progress_text(record)
            with self.studio.lock:
                self.text = text
            self.studio.hub.emit("build", {"state": "working", "text": text})
        say = Say(progress)
        self._say = say
        try:
            ev = self.reader(request, say)
        except Exception as e:                  # a reader that fails leaves the page a message, not a hang
            ev = {"ev": "error", "kind": "exception", "type": type(e).__name__, "detail": str(e), "tail": ""}
        with self.studio.lock:
            if ev.get("ev") == "board":
                self.record = {k: v for k, v in ev.items() if k != "ev"}
                self.phase, self.text, self.tail = "ready", "", ""
            else:
                self.phase, self.text, self.tail = "error", channel.failure_text(ev) or "the board could not be read", ev.get("tail", "")
        self.studio.hub.emit("build", {"state": self.phase, "text": self.text, "tail": self.tail})

    def wait(self, timeout: float = 60.0) -> None:
        t = self._thread
        if t is not None:
            t.join(timeout)

    def need_ready(self) -> dict:
        if self.session is None:
            raise BuildRefused(409, "no board is open in the builder: start one from the start view")
        if self.record is None:
            raise BuildRefused(409, "the board is not read yet: %s" % (self.text or "wait for it"))
        return self.record

    # ------------------------------------------------------------ facts
    def _zen_text(self) -> str:
        try:
            return self.session["zen"].read_text(encoding="utf-8")
        except OSError:
            return ""

    def _zen_state(self) -> dict:
        s, text = self.session, self._zen_text()
        state = zen_edit.stackup_state(text, s["name"])
        out = {"file": self._rel(s["zen"]), "stackup": state["state"], "why": state.get("why", ""), "rows": None, "classes": None,
               "copper_layers": None}
        if state["state"] in ("literal", "none"):
            out["rows"] = zen_edit.read_stackup(text, s["name"])
            out["classes"] = zen_edit.read_netclasses(text, s["name"])
            out["copper_layers"] = zen_edit.read_copper_layers(text, s["name"])
        elif state["state"] == "elsewhere":
            out["classes"] = None
        out["editable"] = state["state"] in ("literal", "none")
        if state["state"] == "unreadable":
            out["editable"] = False
        return out

    def _confirmed_doc(self, digest: str):
        if not digest:
            return None
        f = self.session["board_dir"] / ".placemat" / "views" / "builder" / ("facts_%s.json" % digest)
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):
            return None

    def facts(self, acks: dict | None = None) -> dict:
        """The facts panel: the model (a row for each fact, its state, the gate), what each form is prefilled with, and the
        candidates a form offers."""
        rec = self.need_ready()
        s = self.session
        zen = self._zen_state()
        fab_file = rec.get("fab_file") or ""
        fab_scope = "none" if not fab_file else ("board" if Path(fab_file).parent.resolve() == s["board_dir"].resolve() else "root")
        confirmed = rec.get("confirmed", "")
        model = bf.facts_model(rec["facts"], zen=zen, fab={"file": self._rel(fab_file) if fab_file else ""},
                               rise={"set": rec.get("rise_set", False), "file": self._rel(rec["rise_file"]) if rec.get("rise_file") else ""},
                               confirmed_digest=confirmed, confirmed_doc=self._confirmed_doc(confirmed), acks=acks or {})
        model["confirmable"] = bf.can_confirm(model) if s["script"].is_file() else ["the layout script does not exist yet: it is made from the outline"]
        profile = {}
        if fab_file:
            try:
                profile = json.loads(Path(fab_file).read_text())
            except (OSError, ValueError):
                profile = {}
        return {"model": model, "zen": zen, "fab": {"file": self._rel(fab_file) if fab_file else "", "scope": fab_scope, "profile": profile,
                                                    "says": ("a profile at %s is the default: a change for this board writes %s beside the board"
                                                             % (self._rel(fab_file), bf.FAB_PROFILE)) if fab_scope == "root" else
                                                    ("there is no %s: this board's choices are written to the project root, as its default"
                                                     % bf.FAB_PROFILE) if fab_scope == "none" else ""},
                "candidates": bf.pair_candidates(rec["nets"]), "nets": rec["nets"], "copper_layers": rec["copper_layers"],
                "rise": {"value": rec["facts"]["rise_c"], "set": rec.get("rise_set", False)}, "board_name": s["name"],
                "defaults": {"via_kinds": list(bf.VIA_KINDS), "tiers": list(bf.TIERS), "min_keys": list(bf.FAB_MIN_KEYS), "roles": list(bf.LAYER_ROLES)}}

    def _write(self, edits, digests, label: str, source: str = "builder"):
        s = self.session
        root = self.studio.root
        try:
            return sg.apply_edits(edits, digests, root=root, log=sg.log_path(s["board_dir"]), label=label, source=source)
        except sg.StaleSuggestion as e:
            raise BuildRefused(409, str(e), files=[self._rel(f) for f in getattr(e, "files", ())])
        except sg.EditRefused as e:
            raise BuildRefused(422, str(e))

    def facts_apply(self, request: dict) -> dict:
        """Write a batch of facts to their homes (one apply, one log entry), regenerate the board, and read the facts back: what
        the generator did not take is in `readback`, with an undo offered by the page."""
        self.need_ready()
        s = self.session
        try:
            plan = bf.facts_edits(request, zen_file=str(s["zen"]), board_name=s["name"], board_dir=s["board_dir"], root=self.studio.root)
        except builder.BuilderRefused as e:
            raise refuse(e)
        except script_edit.EditRefused as e:
            raise BuildRefused(422, e.reason)
        if request.get("dry_run"):
            return {"label": plan["label"], "says": plan["says"], "files": self._diff(plan)}
        if s["script"].is_file() and self.studio._cur is not None:
            pass
        done = self._write(plan["edits"], plan["digests"], plan["label"])
        self.studio.hub.emit("applied", {"applied": self.studio.applied_list(), "text": done.text, "id": done.id, "redo": self.studio.redo_text()})
        self.load(fresh=False)
        self.wait()
        out = {"label": plan["label"], "says": plan["says"], "applied": True, "files": [self._rel(p) for p in done.files]}
        if self.phase == "ready":
            out["readback"] = bf.readback(request, self.record["facts"])
        else:
            out["error"] = self.text
            out["tail"] = self.tail
        out["undo"] = True
        return out

    def _diff(self, plan) -> list:
        changed = script_edit.apply_edits(plan["edits"], lambda p: Path(p).read_text(encoding="utf-8"))
        out = []
        for path, (before, after) in changed.items():
            fc = sg.FileChange(path, before, after)
            out.append({"file": self._rel(path), "diff": fc.diff, "created": before is None})
        return out

    def facts_confirm(self, acks: dict | None = None) -> dict:
        """Record the facts' digest for this board's script, as `placemat facts --confirm` records it. The script must exist (the
        key is its path); every row must be decided and every flag acknowledged."""
        rec = self.need_ready()
        s = self.session
        if not s["script"].is_file():
            raise BuildRefused(409, "the layout script does not exist yet: the confirmation is keyed to its path. Make it from the outline first")
        model = self.facts(acks)["model"]
        holds = bf.can_confirm(model)
        if holds:
            raise BuildRefused(422, "not everything is decided: %s" % "; ".join(holds), holds=holds, rule="nothing proceeds on a default")
        plan = bf.confirm_edit(s["script"], rec["facts"]["digest"], s["board_dir"])
        done = self._write(plan["edits"], plan["digests"], plan["label"])
        folder = s["board_dir"] / ".placemat" / "views" / "builder"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ("facts_%s.json" % rec["facts"]["digest"])).write_text(json.dumps(rec["facts"]))
        self.record = dict(self.record, confirmed=rec["facts"]["digest"])
        self.studio.hub.emit("applied", {"applied": self.studio.applied_list(), "text": done.text, "id": done.id, "redo": self.studio.redo_text()})
        self.studio.hub.emit("build", {"state": "facts", "text": "confirmed"})
        return {"confirmed": rec["facts"]["digest"], "file": self._rel(plan["file"]), "undo": True}

    # ------------------------------------------------------------ the outline
    def outline_suggest(self, req: dict) -> dict:
        """The size the parts suggest for a shape, or the fill a typed size gives."""
        rec = self.need_ready()
        cfg = self.studio.cfg
        faces = int(req.get("faces", 1))
        fill = float(req.get("fill") if req.get("fill") not in (None, "") else cfg.studio_builder_max_fill)
        aspect = float(req.get("aspect") if req.get("aspect") not in (None, "") else cfg.studio_builder_aspect)
        shape = req.get("shape", "rect")
        total = float(rec["total_courtyard_area"])
        try:
            if req.get("typed"):
                spec = dict(req["typed"], shape=shape)
                return {"fill": builder.resulting_fill(total, faces, spec), "area": builder.shape_area(spec), "total_area": total,
                        "faces": faces, "typed": True}
            out = builder.suggest_size(total, faces, fill, aspect, shape, cfg.studio_builder_grid_mm,
                                       slot_aspect=req.get("slot_aspect"), template={"kind": req["template"]} if req.get("template") else None)
        except builder.BuilderRefused as e:
            raise refuse(e)
        except (TypeError, ValueError, KeyError) as e:
            raise BuildRefused(400, "the request is not an outline size: %s" % e)
        out["grid_mm"] = cfg.studio_builder_grid_mm
        return out

    def _spec(self, req: dict) -> dict:
        spec = dict(req["spec"])
        o = spec.get("origin")
        if o and o.get("mode") == "suggested":
            o = dict(o, total_area=float(self.need_ready()["total_courtyard_area"]))
            spec["origin"] = o
        return spec

    def outline_create(self, req: dict) -> dict:
        """Write the layout script in one write: the skeleton with the outline in it. Until this there is no script and nothing to
        resolve; after it the studio watches the new script."""
        self.need_ready()
        s = self.session
        script = s["script"]
        if script.exists():
            raise BuildRefused(409, "%s exists: it is opened as an existing script, not made again" % script.name)
        try:
            text = builder.new_script(s["name"], str(req.get("description") or ""), self._spec(req), str(script))
        except builder.BuilderRefused as e:
            raise refuse(e)
        except script_edit.EditRefused as e:
            raise BuildRefused(422, e.reason)
        done = self._write([Edit("create_file", None, {"text": text}, None, {}, str(script))], {str(script): ""}, "Make the layout script for %s" % s["name"])
        self.studio.hub.emit("applied", {"applied": self.studio.applied_list(), "text": done.text, "id": done.id, "redo": self.studio.redo_text()})
        self.after_created()
        return {"script": self._rel(script), "text": text, "undo": True}

    def after_created(self) -> None:
        """The script now exists: make it one the studio lists and watch it."""
        st = self.studio
        script = self.session["script"]
        self._unbuilt = None
        with st.lock:
            st._scripts = None
        rel = next((e["id"] for e in st.scripts() if e["path"] == script.resolve()), None)
        if rel is None:
            raise BuildRefused(500, "the new script is not one the studio can list")
        st.switch(rel)
        self.load()

    def after_undo(self, done) -> None:
        """An undo or a redo changed files: if the script is gone, the board is back to no layout; if it is back, it is watched."""
        s = self.session
        if s is None:
            return
        gone = [p for p, c in done.files.items() if Path(p).resolve() == s["script"].resolve() and c.after is None]
        if gone and self.studio.script is not None and self.studio.script.resolve() == s["script"].resolve():
            self.studio.leave_script()
            self._unbuilt = None
            self.studio.hub.emit("build", {"state": "no_layout", "text": ""})
        back = [p for p, c in done.files.items() if Path(p).resolve() == s["script"].resolve() and c.before is None and c.after is not None]
        if back and self.studio.script is None:
            self.after_created()

    # ------------------------------------------------------------ placement: offers
    def _ctx(self, rid) -> bi.Ctx:
        board = self.need_ready()
        rec = self.studio.record(int(rid) if str(rid).lstrip("-").isdigit() else -1)
        if rec is None:
            raise BuildRefused(404, "no such resolve (the last %d are kept)" % self.studio.keep)
        script = self.studio.script
        if script is None or self.session is None or script.resolve() != self.session["script"].resolve():
            raise BuildRefused(409, "the builder is not working on the script the studio watches")
        return bi.Ctx(rec.texts, str(script), rec.doc, board)

    def gate(self) -> dict:
        """Whether placement is open: the facts are confirmed and match the board as generated now."""
        self.need_ready()
        facts = self.facts()
        return facts["model"]["gate"] | {"holds": facts["model"]["gate"]["holds"], "reasons": facts["model"]["reasons"]}

    def _need_gate(self) -> None:
        g = self.gate()
        if not g["open"]:
            raise BuildRefused(423, "placement waits for the board's facts: %s" % ("; ".join(r["text"] for r in g["reasons"]) or "confirm them"),
                               holds=g["holds"], rule="nothing proceeds on a default")

    def _register(self, rid, ctx: bi.Ctx, subject, suggestion: sg.Suggestion, **meta) -> dict:
        self._counter += 1
        sid = "b%d" % self._counter
        from dataclasses import replace
        s = replace(suggestion, id=sid, rank=self._counter)
        self.offers[sid] = {"rid": int(rid), "suggestion": s, "subject": subject}
        if len(self.offers) > 400:
            for k in list(self.offers)[:100]:
                del self.offers[k]
        out = {"id": sid, "text": s.text, **meta}
        try:
            out["preview"] = {Path(p).name: v for p, v in ((p, {"added": v["added"], "removed": v["removed"]}) for p, v in bi.preview(ctx, s).items())}
        except script_edit.EditRefused as e:
            out["refused"] = e.reason
        return out

    def offer(self, req: dict) -> dict:
        """The offers for a click: `{"resolve", "subject": [keys], "target": {...}|null, "params": {...}}` is the menu for the pair;
        `{"kind": "search", "keys"?, "either_face"?}` the search of the rest; `{"kind": "remove", "subject": [key]}` an item taken off;
        `{"kind": "outline", "spec"}` a change of the outline. Each offer is a suggestion with an id, which /suggest/show, /try and
        /apply take as for a finding's."""
        rid = req.get("resolve")
        kind = req.get("kind", "place")
        allowed = {"resolve", "kind", "subject", "target", "params", "keys", "either_face", "spec", "intent"}
        extra = set(req) - allowed
        if extra:
            raise BuildRefused(400, "the request carries more than the builder takes: %s" % ", ".join(sorted(extra)))
        ctx = self._ctx(rid)
        try:
            if kind == "place":
                self._need_gate()
                subjects = req.get("subject") or []
                offers = bi.menu(ctx, list(subjects), req.get("target"), req.get("params") or {})
                if req.get("intent"):
                    offers = [o for o in offers if o.intent == req["intent"]]
                out = []
                for o in offers:
                    if o.needs:
                        out.append({"intent": o.intent, "text": o.text, "needs": o.needs, "notes": o.notes})
                    else:
                        out.append(self._register(rid, ctx, subjects[0], bi.offer_suggestion(ctx, o, subjects if len(subjects) > 1 else subjects[0]), intent=o.intent,
                                                  needs=[], notes=o.notes))
                return {"offers": out}
            if kind == "search":
                self._need_gate()
                got = bi.search_rest(ctx, req.get("keys"), bool(req.get("either_face")))
                return {"offers": [self._register(rid, ctx, None, got["suggestion"], intent="search", count=got["count"], keys=got["keys"])]}
            if kind == "remove":
                self._need_gate()
                subject = (req.get("subject") or [None])[0]
                return {"offers": [self._register(rid, ctx, subject, bi.remove_edits(ctx, subject), intent="remove")]}
            if kind == "move":
                self._need_gate()
                subject = (req.get("subject") or [None])[0]
                return {"offers": [self._register(rid, ctx, subject, bi.move_offer(ctx, subject, (req.get("params") or {}).get("direction")), intent="move")]}
            if kind == "row":
                self._need_gate()
                p = req.get("params") or {}
                subject = (req.get("subject") or [None])[0]
                return {"offers": [self._register(rid, ctx, subject, bi.row_edit(ctx, subject, p.get("action", ""), p.get("member", ""), p.get("before", "")), intent="row")]}
            if kind == "item":
                self._need_gate()
                subject = (req.get("subject") or [None])[0]
                return {"offers": [self._register(rid, ctx, subject, bi.item_mods(ctx, subject, req.get("params") or {}), intent="item")]}
            if kind == "outline":
                from . import builder_outline as bo
                got = bo.change_outline(ctx, self._spec(req), req.get("params") or {})
                return {"offers": [self._register(rid, ctx, None, got["suggestion"], intent="outline", affected=got.get("affected", []))],
                        "affected": got.get("affected", [])}
        except builder.BuilderRefused as e:
            raise refuse(e)
        except script_edit.EditRefused as e:
            raise BuildRefused(422, e.reason)
        raise BuildRefused(400, "%r is not a builder request" % (kind,))

    def suggestion(self, rid, sid):
        """(record, pool, finding) of a builder suggestion, in the shape /suggest/show, /try and /apply take, or None."""
        hit = self.offers.get(sid)
        if hit is None or str(hit["rid"]) != str(rid):
            return None
        rec = self.studio.record(hit["rid"])
        if rec is None:
            return None
        s = hit["suggestion"]
        finding = {"text": s.text, "kind": "builder", "cause": None, "facts": {}, "item": hit.get("subject") or "", "suggestions": [s.to_json()]}
        return rec, [s], finding

    # ------------------------------------------------------------ the parts list and the outline as read
    def parts(self, rid=None) -> dict:
        """The parts list for a resolve (the newest by default): rows with status, counts, the outline as read, and whether the plan
        is the one the page last saw."""
        board = self.need_ready()
        st = self.studio
        with st.lock:
            rec = st.record(int(rid)) if rid not in (None, "") else (st.history[-1] if st.history else None)
        script = st.script
        if rec is None or script is None:
            listing = bp.parts_rows(board, None, {}, Path("."))
            return {"rows": listing["rows"], "counts": listing["counts"], "resolve": None, "outline": None,
                    "total_courtyard_area": board["total_courtyard_area"]}
        ctx = bi.Ctx(rec.texts, str(script), rec.doc, board)
        return {"rows": ctx.listing["rows"], "counts": ctx.listing["counts"], "resolve": rec.id, "outline": ctx.outline,
                "total_courtyard_area": board["total_courtyard_area"], "gate": self.gate()["open"]}

    def turn_offer(self, req: dict) -> dict:
        """A chosen quarter turn as an offer: `rotation=90` (with `why=`) written in the part's own call."""
        from . import builder_turns as bt
        self._need_gate()
        ctx = self._ctx(req.get("resolve"))
        try:
            s = bt.turn_edits(ctx, str(req.get("subject", "")), req.get("rotation"))
        except builder.BuilderRefused as e:
            raise refuse(e)
        return {"offers": [self._register(req.get("resolve"), ctx, req.get("subject"), s, intent="turn")]}

    def turns(self, req: dict) -> dict:
        """The four quarter turns of a placed item with the ratsnest crossings each makes, the fewest marked."""
        from . import builder_turns as bt
        ctx = self._ctx(req.get("resolve"))
        try:
            return bt.turn_counts(ctx, str(req.get("subject", "")))
        except builder.BuilderRefused as e:
            raise refuse(e)
