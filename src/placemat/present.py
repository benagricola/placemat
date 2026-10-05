"""The studio's edge: the sentences a page shows, made from the records that arrive.

What crosses a socket or a pipe (the live channel, the resolve worker's events, the plan JSON of preview_json.py) is records: causes and
facts, notes and refusals as `{"kind"|"code", ...}`. The studio server is the edge to its page, and the page reads sentences beside the
records it already reads. This module makes them with the renderers the console and `placemat watch` use (finding_text, refusals, step_text,
`channel.describe`), so a sentence has one wording wherever it is shown. Each function returns a copy with the texts added, as `text`,
`note`, `why` fields beside the records."""
from __future__ import annotations

from . import finding_text, step_text
from .findings import FindingCause
from .refusals import Owner, Refusal, ReservedBy


def facts(f):
    """A finding's facts with each refusal and each owner of a refusal also in the words the console uses for it ("text"), so the
    page shows them as written and parses nothing: a refusal is {"code", ...}, an owner is under "owner" in a blame."""
    if isinstance(f, dict):
        out = {k: facts(v) for k, v in f.items()}
        if "code" in f and isinstance(f["code"], str):
            try:
                out["text"] = str(Refusal.from_json(f))
            except (KeyError, ValueError, TypeError):
                pass
        if isinstance(f.get("where"), dict) and "form" in f["where"]:        # where a one-freedom item slides
            out["where"] = dict(out["where"], text=finding_text.where_text(f["where"]))
        turns = f.get("turns")                  # a refusal at each rotation tried, [rotation, refusal, ...] each; a pin map
        if isinstance(turns, list) and turns and all(isinstance(t, (list, tuple)) for t in turns):     # pose's are records
            out["turns_text"] = finding_text.turns_text(f["turns"])
        if isinstance(f.get("room_lost"), dict) and f["room_lost"]:
            out["room_lost"] = dict(out["room_lost"], text=finding_text.room_lost_text(f["room_lost"]).lstrip("; "))
        if isinstance(f.get("owner"), dict) and "form" in f["owner"]:
            try:
                out["owner"] = dict(out["owner"], text=str(Owner.from_json(f["owner"])))
            except (KeyError, ValueError, TypeError):
                pass
        return out
    if isinstance(f, (list, tuple)):
        return [facts(v) for v in f]
    return f


def finding(f: dict) -> dict:
    """A finding record with its sentence. A record that has a text already (a run record from before findings were records only)
    keeps it."""
    out = dict(f, facts=facts(f.get("facts") or {}))
    if not f.get("text"):
        cause = FindingCause.parse(f.get("cause"))
        try:
            out["text"] = finding_text.render(cause, f.get("facts") or {}) if cause is not None else ""
        except (KeyError, ValueError, TypeError):           # facts of another version
            out["text"] = ""
    return out


# ------------------------------------------------------------------ a step's notes
def _refusal_text(r) -> str:
    try:
        return str(Refusal.from_json(r))
    except (KeyError, ValueError, TypeError):
        return ""


def _one(n: dict) -> dict:
    """A note with its sentence and, where the page labels parts of it, those parts: `text`; `why_text` for the refusal under `why`;
    `head` and `tail` of a `where`; `lines` of a `vias` note, each {"n", "text", "warn"}; `detail` of a push; the ordinals of a rank."""
    out = dict(n)
    kind = n.get("kind")
    try:
        out["text"] = step_text.render(n)
    except (KeyError, ValueError, TypeError):
        out["text"] = ""
    if isinstance(n.get("why"), dict) and "code" in n["why"]:
        out["why_text"] = _refusal_text(n["why"])
    try:
        if kind == "where":
            out["head"], out["tail"] = finding_text.where_parts(n["where"])
        elif kind == "vias":
            out["lines"] = [{"n": c, "text": line[len(str(c)) + 1:] if c is not None else line, "warn": warn}
                            for c, line, warn in finding_text.via_lines(n["facts"])]
        elif kind == "push":
            out["detail"] = "%.2g at %.1f mm, limit %.2g" % (n["value"], n["at_mm"], n["limit"])
        elif kind == "rank":
            out["area_ord"], out["pins_ord"] = step_text.ordinal(n["area_rank"]), step_text.ordinal(n["pins_rank"])
        elif kind == "pocket":
            out["why_text"] = step_text.POCKET_WHY
        elif kind == "moved_off_hint" and n.get("for_score"):
            out["why_text"] = step_text.FOR_SCORE
    except (KeyError, ValueError, TypeError):
        pass
    return out


def notes(ns) -> list:
    """A step's notes, each with its sentence (see `_one`)."""
    return [_one(n) for n in ns or ()]


def reasons(rs) -> list | None:
    """The reasons an item has no place, each with its sentence: `text` (a refusal's own, under `text` as `facts` makes it)."""
    if rs is None:
        return None
    out = []
    for r in rs:
        d = facts(r) if "code" in r else dict(r)
        try:
            d["text"] = step_text.unplaced_text([r])
        except (KeyError, ValueError, TypeError):
            d.setdefault("text", "")
        out.append(d)
    return out


def note(ns, unplaced=None) -> str:
    """A step's notes as the one line the page shows."""
    try:
        return step_text.render_all(ns or (), unplaced)
    except (KeyError, ValueError, TypeError):
        return ""


def unplaced_why(rs, ns=()) -> str:
    """Why an item has no place: its reasons, else its notes."""
    if rs is None:
        return note(ns)
    try:
        return step_text.unplaced_text(rs)
    except (KeyError, ValueError, TypeError):
        return ""


# ------------------------------------------------------------------ events
def event(ev: dict) -> dict:
    """A live-channel event as the page reads it: an item and a plan with their sentences, an error with its `message`, a route_off with
    its `why`, a probe's refusal and a candidate's error in words. The rest are records the page already reads."""
    kind = ev.get("ev")
    if kind == "item" and isinstance(ev.get("item"), dict):
        return dict(ev, item=item(ev["item"]))
    if kind == "plan" and isinstance(ev.get("doc"), dict):
        return dict(ev, doc=plan(ev["doc"]))
    if kind == "error":
        from . import channel
        return dict(ev, message=channel.failure_text(ev))
    if kind == "route_off":
        from .kicad import route_events
        return dict(ev, why=route_events.reason_text(ev.get("reason") or {}))
    if kind == "candidate" and ev.get("error"):
        from . import probe
        return dict(ev, error_text=probe.error_text(ev["error"]))
    if kind == "probe_done" and ev.get("refusal"):
        from . import probe
        return dict(ev, message=probe.refusal_text(ev["refusal"]))
    return ev


# ------------------------------------------------------------------ models
_MODEL_WHY = {
    "no_model": lambda e: "the footprint declares no 3D model",
    "not_found": lambda e: "model not found: %s" % e.get("text", ""),
    "vrml_only": lambda e: "a VRML model with no STEP beside it",
    "no_checksum": lambda e: "the embedded model %s has no checksum on the board file" % e.get("name", ""),
    "unreadable": lambda e: "model cannot be read: %s" % e.get("detail", ""),
}


def model_why(e: dict) -> str:
    """What a model entry's `why` (a word, models.ModelRef) says."""
    fn = _MODEL_WHY.get(e.get("why"))
    return fn(e) if fn is not None else ""


def member(m: dict) -> dict:
    if "models" not in m:
        return m
    return dict(m, models=[dict(e, why_text=model_why(e)) if e.get("why") else e for e in m["models"]])


# ------------------------------------------------------------------ items and plans
def item(it: dict) -> dict:
    """An item (preview_json.item_json): its note as text, its notes and findings with theirs."""
    out = dict(it, note=note(it.get("notes"), it.get("unplaced")) or it.get("note", ""), notes=notes(it.get("notes")))
    if "unplaced" in it:
        out["unplaced"] = reasons(it["unplaced"])
    if "findings" in it:
        out["findings"] = [finding(f) if isinstance(f, dict) else f for f in it["findings"]]
    if "members" in it:
        out["members"] = [member(m) for m in it["members"]]
    return out


def reservation(r: dict) -> dict:
    return dict(r, why=str(ReservedBy.from_json(r["by"]))) if isinstance(r.get("by"), dict) else r


def board(doc: dict) -> dict:
    """A board document (preview_json.board_json): the reservations' phrases."""
    out = dict(doc)
    if "reservations" in doc:
        out["reservations"] = [reservation(r) for r in doc["reservations"]]
    return out


def _step(s: dict) -> dict:
    if "notes" not in s:
        return s
    out = dict(s, note=note(s["notes"], s.get("unplaced")) or s.get("note", ""), notes=notes(s["notes"]))
    if "unplaced" in s:
        out["unplaced"] = reasons(s["unplaced"])
    return out


def _unplaced(u: dict) -> dict:
    if "reasons" not in u:
        return u
    return dict(u, why=unplaced_why(u["reasons"], u.get("notes")), reasons=reasons(u["reasons"]), notes=notes(u.get("notes")))


def plan(doc: dict) -> dict:
    """A plan document (preview_json.plan_json) with its sentences: each finding's text and the texts in its facts, each item's and
    step's note, each unplaced entry's why, each reservation's phrase. The original is left alone."""
    out = dict(board(doc))
    out["items"] = [item(i) for i in doc.get("items", ())]
    out["findings"] = [finding(f) for f in doc.get("findings", ())]
    out["steps"] = [_step(s) for s in doc.get("steps", ())]
    out["unplaced"] = [_unplaced(u) for u in doc.get("unplaced", ())]
    return out
