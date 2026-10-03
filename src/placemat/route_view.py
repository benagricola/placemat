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
                      "how": "decided", "note": "", "why": "", "rank": None, "rank_of": None, "pocket": None, "lock": "", "findings": [], "file": "", "line": 0, "moved_mm": 0.0})
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


def _face_of(layer: str) -> str:
    return "front" if layer == "F.Cu" else "back" if layer == "B.Cu" else "inner"


def _seg_key(s) -> tuple:
    return (round(s[0], 3), round(s[1], 3), round(s[2], 3), round(s[3], 3), s[4], round(s[5], 3))


def _via_key(v) -> tuple:
    return (round(v[0], 3), round(v[1], 3), round(v[2], 3), round(v[3], 3))


def net_names(ev) -> list:
    n = ev.get("net")
    return [n] if isinstance(n, str) else list(n or [])


def lay(events: list) -> dict:
    """The events of a route in laid order as per-net copper: {"order": [net, ...] by first commit (a net that failed is added when it
    fails), "ops": {net: [op, ...]} the ops that stood at the end (a ripped net's copper is gone), "result": {net: "routed" | "no route found" |
    "ripped"}}. An op is {"t": "track" | "via", ...} in the plan document's copper shape."""
    order, live, result = [], {}, {}
    for ev in events:
        kind = ev.get("ev")
        if kind in ("commit", "route_commit"):
            names = net_names(ev)
            net = names[0] if len(names) == 1 else None
            for s in ev.get("seg", ()):
                n = net or "?"
                if n not in order:
                    order.append(n)
                live.setdefault(n, {})[("s",) + _seg_key(s)] = {"t": "track", "layer": s[4], "face": _face_of(s[4]), "width": s[5], "a": [s[0], s[1]], "b": [s[2], s[3]], "net": n}
            for v in ev.get("via", ()):
                n = net or "?"
                if n not in order:
                    order.append(n)
                live.setdefault(n, {})[("v",) + _via_key(v)] = {"t": "via", "at": [v[0], v[1]], "size": v[2], "drill": v[3], "net": n, "layers": []}
        elif kind in ("rip", "route_rip"):
            names = net_names(ev)
            net = names[0] if len(names) == 1 else None
            for s in ev.get("seg", ()):
                live.get(net or "?", {}).pop(("s",) + _seg_key(s), None)
            for v in ev.get("via", ()):
                live.get(net or "?", {}).pop(("v",) + _via_key(v), None)
        elif kind in ("net_end", "route_net_end"):
            n = ev.get("net")
            result[n] = "routed" if ev.get("ok") else "no route found"
            if n not in order:
                order.append(n)
    ops = {n: list(live.get(n, {}).values()) for n in order}
    for n in order:
        if result.get(n) == "routed" and not ops[n]:
            result[n] = "ripped"
        result.setdefault(n, "routed" if ops[n] else "ripped")
    return {"order": order, "ops": ops, "result": result}


def route_doc(record: dict, board: dict) -> dict:
    """The plan document of a finished route. `board` is the board_doc (parts only: a step for each part, then each net) or a run's plan.json
    (its own steps and copper first: the whole build, the placement and then the route). Each net is a step of kind `copper` in the order
    the router first committed copper for it, its result as the note and the copper that stood at the end as its ops."""
    events = [ev for st in record.get("stages", ()) for ev in st.get("events", ())]
    laid = lay(events)
    base = dict(board)
    doc = {"version": PLAN_VERSION, "board": {"loops": [], "drawn": True, "extent": [0, 0, 100, 60]}, "keepouts": [], "reservations": [], "items": [], "layers": [],
           "links": [], "congestion": None, "findings": [], "unplaced": [], "pocketed": []}
    doc.update(base)
    steps = [dict(s) for s in base["steps"]] if base.get("steps") else [
        {"i": n, "item": it["key"], "kind": "part", "placed": True, "note": "", "why": "", "freedom": "fixed", "rank": None, "rank_of": None, "pocket": None,
         "lock": "", "copper": [], "loop": None} for n, it in enumerate(doc["items"])]
    copper = list(base.get("copper") or [])
    for net in laid["order"]:
        at = []
        for op in laid["ops"][net]:
            at.append(len(copper))
            copper.append(op)
        tracks = sum(1 for o in laid["ops"][net] if o["t"] == "track")
        vias = len(laid["ops"][net]) - tracks
        result = laid["result"][net]
        steps.append({"i": len(steps), "item": "track " + str(net), "kind": "copper", "placed": False, "freedom": None, "rank": None, "rank_of": None, "pocket": None, "lock": "",
                      "note": "%s: %d track%s, %d via%s" % (result, tracks, "" if tracks == 1 else "s", vias, "" if vias == 1 else "s") if result == "routed" else result,
                      "why": "", "copper": at, "loop": None})
    doc.update(copper=copper, steps=steps, counts=base.get("counts") or {"placed": len(doc["items"]), "findings": len(doc["findings"])}, score=base.get("score"),
               route={"nets": len(laid["order"]), "routed": sum(1 for n in laid["order"] if laid["result"][n] == "routed"),
                      "failed": sum(1 for n in laid["order"] if laid["result"][n] != "routed")})
    return doc
