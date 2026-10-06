"""A route as the studio draws it: the board under the copper, and a finished route replayed from its record.

`board_doc(geometry)` is the board as the page draws it where no placement of its own is in front of it (a standalone `placemat route`): the
outline, and each part's courtyard, pads and drills, from the board file as it was read. `route_doc(record)` turns a route record
(route_progress.write_record) into a plan document the page's own timeline plays: a step for each part, then a step for each net in the
order the router first committed copper for it (kind `copper`, its result as the note), the copper that survived the whole route as the
ops, each tagged with the step that laid it. Nothing here parses text: both read records and the board geometry."""
from __future__ import annotations

import math

from .preview_json import _poly, VERSION as PLAN_VERSION


def _circle(cx: float, cy: float, r: float, n: int = 16) -> list:
    return [[round(cx + r * math.cos(2 * math.pi * i / n), 3), round(cy + r * math.sin(2 * math.pi * i / n), 3)] for i in range(n)]


def _extent(loops) -> list:
    pts = [p for l in loops for p in l]
    if not pts:
        return [0, 0, 100, 60]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]


def board_doc(geometry) -> dict:
    """The board as drawn under copper: {"board", "items", "layers", ...} in the plan document's shape, each footprint one part item."""
    loops = [_poly(l) for l in (getattr(geometry, "board_polygon", None) or geometry.outline)]
    items = []
    for fp in geometry.footprints:
        face = fp.face.value
        shapes = []
        court = fp.courtyard_poly or ()
        if court:
            shapes.append({"kind": "courtyard", "faces": [face], "poly": _poly(court)})
        else:
            b = fp.courtyard_box
            shapes.append({"kind": "courtyard", "faces": [face], "poly": [[b.left, b.top], [b.right, b.top], [b.right, b.bottom], [b.left, b.bottom]]})
        for p in fp.pads:
            for poly in p.outlines:
                shapes.append({"kind": "through" if p.through else "pad", "faces": ["back", "front"] if p.through else [face],
                               "layers": sorted(l.value for l in p.layers), "poly": _poly(poly), "net": p.net, "number": p.number})
            if p.through and p.drill_mm:
                c = p.box.center
                shapes.append({"kind": "hole", "faces": ["back", "front"], "poly": _circle(c.x, c.y, p.drill_mm / 2.0), "number": p.number})
        items.append({"key": fp.inst, "kind": "part", "placed": True, "members": [{"ref": fp.ref, "inst": fp.inst, "value": fp.value, "cell": fp.cell or "", "shapes": shapes}],
                      "at": [round(fp.location.x, 3), round(fp.location.y, 3)], "rotation": round(fp.rotation, 3), "face": face, "freedom": "fixed", "priority": None,
                      "how": "decided", "note": "", "notes": [], "unplaced": None, "why": "", "rank": None, "rank_of": None, "pocket": None, "lock": "", "findings": [], "file": "", "line": 0, "moved_mm": 0.0})
    drawn = bool(loops)
    if not drawn:                                    # a board with no outline yet: the extent is where its parts are
        loops = [[p for it in items for m in it["members"] for s in m["shapes"] for p in s["poly"]]]
        ext = _extent(loops)
        ext = [ext[0] - 2, ext[1] - 2, ext[2] + 2, ext[3] + 2]
        loops = []
    else:
        ext = _extent(loops)
    return {"board": {"loops": loops, "drawn": drawn, "extent": ext}, "keepouts": [], "reservations": [], "items": items,
            "layers": [l.value for l in geometry.layers]}


def _run_finding(d: dict, refs: set, keys: set) -> dict:
    """A finding of a run record (report.RunRecord.findings_with_severity: kind, severity, sentence and, from a run that kept them, cause and
    facts) as the page's finding record: where it is and which parts it names are read from its facts, as preview_json does for a live plan."""
    from . import finding_text
    from .findings import FindingCause
    cause = FindingCause.parse(d.get("cause")) if d.get("cause") else None
    facts = d.get("facts") or {}
    where, first = {"at": None, "refs": [], "pads": []}, ""
    if cause is not None:
        try:
            where, first = finding_text.locate(cause, facts, refs), finding_text.subject(cause, facts)
        except (KeyError, ValueError, TypeError, IndexError):          # facts of another version name nothing
            pass
    return {"kind": d.get("kind", ""), "severity": d.get("severity", "warning"), "text": d.get("text", ""), "at": where["at"], "item": first if first in keys else "",
            "refs": where["refs"], "pads": where["pads"], "cause": d.get("cause"), "facts_v": d.get("facts_v"), "facts": facts, "suggestions": []}


def run_doc(base: dict, findings=(), score=None) -> dict:
    """A recorded run as the page draws it where no resolve is under way: `base` is the run's plan.json (its own steps, copper and findings) or a
    board_doc of the run's written board (a step for each part). The run record's findings replace a board_doc's none, placed from their facts; a
    plan.json keeps its own. `score` is the run's total, when it has one."""
    doc = {"version": PLAN_VERSION, "board": {"loops": [], "drawn": True, "extent": [0, 0, 100, 60]}, "keepouts": [], "reservations": [], "items": [], "layers": [],
           "links": [], "congestion": None, "findings": [], "unplaced": [], "pocketed": [], "copper": []}
    doc.update(base)
    if not base.get("steps"):
        doc["steps"] = [{"i": n, "item": it["key"], "kind": "part", "placed": True, "note": "", "notes": [], "unplaced": None, "why": "", "freedom": "fixed", "rank": None,
                         "rank_of": None, "pocket": None, "lock": "", "copper": [], "loop": None} for n, it in enumerate(doc["items"])]
    if not base.get("findings") and findings:
        refs = {m[k] for it in doc["items"] for m in it["members"] for k in ("ref", "inst") if m.get(k)}
        keys = {it["key"] for it in doc["items"]}
        doc["findings"] = [_run_finding(f, refs, keys) for f in findings]
    if score is not None and not base.get("score"):
        doc["score"] = {"total": score}
    doc["counts"] = base.get("counts") or {"placed": len(doc["items"]), "findings": len(doc["findings"])}
    return doc


def _face_of(layer: str) -> str:
    return "front" if layer == "F.Cu" else "back" if layer == "B.Cu" else "inner"


def _seg_key(s) -> tuple:
    return (round(s[0], 3), round(s[1], 3), round(s[2], 3), round(s[3], 3), s[4], round(s[5], 3))


def _via_key(v) -> tuple:
    return (round(v[0], 3), round(v[1], 3), round(v[2], 3), round(v[3], 3))


def net_names(ev) -> list:
    n = ev.get("net")
    return [n] if isinstance(n, str) else list(n or [])


def net_key(ev) -> str:
    """The net an event is about, as one name: a pair's two nets are "P/N"."""
    return "/".join(str(n) for n in net_names(ev)) or "?"


def lay(events: list) -> dict:
    """The events of a route in laid order as copper by step: {"order": [net, ...] (a step each, in the order the router took the nets up: its
    search began, it committed copper, or it failed), "ops": {step: [op, ...]} every op laid during that step, standing or not, "result":
    {net: "routed" | "no route found" | "ripped" | "unfinished"}}. An op is {"t": "track" | "via", ..., "net": the net it belongs to,
    "gone": the step during which it was ripped, or None if it stood to the end} in the plan document's copper shape. Copper committed
    while another net's search is under way (a restore after a rip) is laid in that net's step. A pair is one net, "P/N"."""
    order, ops, live, result, begun = [], {}, {}, {}, set()
    cur = None

    def step(n):
        if n not in order:
            order.append(n)
        return n

    for ev in events:
        kind = ev.get("ev")
        if kind in ("net_begin", "route_net_begin"):
            cur = step(net_key(ev))
            begun.add(cur)
        elif kind in ("commit", "route_commit"):
            n = net_key(ev)
            at = step(cur if cur is not None else n)
            for s in ev.get("seg", ()):
                op = {"t": "track", "layer": s[4], "face": _face_of(s[4]), "width": s[5], "a": [s[0], s[1]], "b": [s[2], s[3]], "net": n, "gone": None}
                ops.setdefault(at, []).append(op)
                live[(n, "s") + _seg_key(s)] = op
            for v in ev.get("via", ()):
                op = {"t": "via", "at": [v[0], v[1]], "size": v[2], "drill": v[3], "net": n, "layers": [], "gone": None}
                ops.setdefault(at, []).append(op)
                live[(n, "v") + _via_key(v)] = op
        elif kind in ("rip", "route_rip"):
            n = net_key(ev)
            at = step(cur if cur is not None else n)
            for key in [(n, "s") + _seg_key(s) for s in ev.get("seg", ())] + [(n, "v") + _via_key(v) for v in ev.get("via", ())]:
                op = live.pop(key, None)
                if op is not None:
                    op["gone"] = at
        elif kind in ("net_end", "route_net_end"):
            n = step(net_key(ev))
            result[n] = "routed" if ev.get("ok") else "no route found"
        elif kind in ("queue_end", "route_queue_end"):
            cur = None
    standing = {}
    for op in live.values():
        standing[op["net"]] = standing.get(op["net"], 0) + 1
    for n in order:
        if result.get(n) == "routed" and not standing.get(n):
            result[n] = "ripped"
        if n not in result:
            result[n] = "routed" if standing.get(n) else "unfinished" if n in begun else "ripped"
    return {"order": order, "ops": {n: ops.get(n, []) for n in order}, "result": result}


def open_connections(unconnected) -> list:
    """The connections a route left open, as the page marks them: {"net", "a", "b"} with `a` and `b` the two items' places (mm), from
    drc.unconnected_items of the DRC after the route. One whose items KiCad placed nowhere is left out."""
    out = []
    for u in unconnected or ():
        at = [i.get("at") for i in u.get("items", ()) if i.get("at")]
        if at:
            out.append({"net": u.get("net", ""), "a": list(at[0]), "b": list(at[1] if len(at) > 1 else at[0])})
    return out


def route_doc(record: dict, board: dict, opens=()) -> dict:
    """The plan document of a route's record. `board` is the board_doc (parts only: a step for each part, then each net) or a run's plan.json
    (its own steps and copper first: the whole build, the placement and then the route). Each net is a step of kind `copper` in the order
    the router took it up, its result as the note and the copper laid during it as its ops; copper that was ripped carries `x`, the index of
    the step during which it went, so the replay takes it away there. `opens` are the connections the route left open (open_connections),
    the doc's `open`. The router's copper and its nets' steps carry `origin` "routed", so the
page can tell them from the copper the plan laid (which has none). `route` counts the nets and says whether the record is `partial` (the
    route did not finish, or a stage did not) and how many events were `dropped`."""
    stages = record.get("stages", ())
    events = [ev for st in stages for ev in st.get("events", ())]
    laid = lay(events)
    base = dict(board)
    doc = {"version": PLAN_VERSION, "board": {"loops": [], "drawn": True, "extent": [0, 0, 100, 60]}, "keepouts": [], "reservations": [], "items": [], "layers": [],
           "links": [], "congestion": None, "findings": [], "unplaced": [], "pocketed": []}
    doc.update(base)
    steps = [dict(s) for s in base["steps"]] if base.get("steps") else [
        {"i": n, "item": it["key"], "kind": "part", "placed": True, "note": "", "notes": [], "unplaced": None, "why": "", "freedom": "fixed", "rank": None, "rank_of": None, "pocket": None,
         "lock": "", "copper": [], "loop": None} for n, it in enumerate(doc["items"])]
    first = len(steps)
    index = {net: first + k for k, net in enumerate(laid["order"])}
    copper = list(base.get("copper") or [])
    for net in laid["order"]:
        at, mine = [], laid["ops"][net]
        for op in mine:
            op = dict(op, origin="routed")
            gone = op.pop("gone")
            if gone is not None:
                op["x"] = index[gone]
            at.append(len(copper))
            copper.append(op)
        own = [o for o in mine if o["net"] == net and o["gone"] is None]
        tracks = sum(1 for o in own if o["t"] == "track")
        vias = len(own) - tracks
        result = laid["result"][net]
        steps.append({"i": len(steps), "item": "track " + str(net), "kind": "copper", "placed": False, "freedom": None, "rank": None, "rank_of": None, "pocket": None, "lock": "",
                      "note": "%s: %d track%s, %d via%s" % (result, tracks, "" if tracks == 1 else "s", vias, "" if vias == 1 else "s") if result == "routed" else result,
                      "why": "", "copper": at, "loop": None, "origin": "routed"})
    lost = sum(int(st.get("dropped") or 0) for st in stages)
    partial = not record.get("complete", True) or any(not st.get("complete", True) for st in stages)
    routed = sum(1 for n in laid["order"] if laid["result"][n] == "routed")
    said = sum(1 for ev in events if ev.get("ev") in ("net_end", "route_net_end") and ev.get("ok"))
    # nets the router said it routed, and no copper for any of them in the record: an older record's events carried none
    unread = {"code": "no_copper", "nets": said} if said and not any(laid["ops"][n] for n in laid["order"]) else None
    opens = list(opens or ())
    doc.update(copper=copper, steps=steps, counts=base.get("counts") or {"placed": len(doc["items"]), "findings": len(doc["findings"])}, score=base.get("score"), open=opens,
               route={"nets": len(laid["order"]), "routed": routed,
                      "failed": sum(1 for n in laid["order"] if laid["result"][n] in ("no route found", "ripped")), "partial": partial, "dropped": lost,
                      "open": len(opens), "unread": unread})
    return doc
