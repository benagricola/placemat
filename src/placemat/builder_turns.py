"""The builder's suggested turn: for a placed part, how many ratsnest crossings its connections make at each quarter turn.

The count is taken on the plan: the part is held at its resolved place with its pads turned about its origin, and the ratsnest
(`ratsnest.py`: KiCad's minimum spanning tree per net, crossings of airwires of different nets) is counted for each turn. It is a
quick estimate that ignores whether the turned part is legal at that spot; a Try of the turn resolves it exactly. The crossings
are the part's connections (the airwires of its pads' nets that end on it) against the connections among the parts already placed,
and against each other."""
from __future__ import annotations

import math

from . import ratsnest
from .builder import BuilderRefused
from .suggestions import Edit, Suggestion

TURNS = (0, 90, 180, 270)
TURN_WHY = "fewest ratsnest crossings of the four turns"


def pads_of(item: dict) -> list:
    """The pads of a placed item as `{"ref", "number", "net", "x", "y"}`, each at the centre of its drawn copper."""
    out = []
    for m in item.get("members", ()):
        for sh in m.get("shapes", ()):
            if sh.get("kind") in ("pad", "through") and sh.get("net"):
                xs, ys = [p[0] for p in sh["poly"]], [p[1] for p in sh["poly"]]
                out.append({"ref": m["ref"], "number": str(sh.get("number") or ""), "net": sh["net"], "x": (min(xs) + max(xs)) / 2.0,
                            "y": (min(ys) + max(ys)) / 2.0})
    return out


def _turned(x, y, ox, oy, degrees):
    """(x, y) turned `degrees` about (ox, oy): a y-down frame, a positive turn counter-clockwise on screen as the plan's rotations are."""
    r = math.radians(degrees)
    c, s = math.cos(r), math.sin(r)
    dx, dy = x - ox, y - oy
    return ox + c * dx + s * dy, oy - s * dx + c * dy


def _edges(pads: list) -> list:
    nets: dict = {}
    for p in pads:
        nets.setdefault(p["net"], []).append(ratsnest.Anchor(p["ref"], p["number"], p["x"], p["y"]))
    out = []
    for net, anchors in sorted(nets.items()):
        out += ratsnest.mst(net, anchors)
    return out


def count(subject_pads: list, others: list, base=None) -> tuple:
    """(crossings, connections) of the subject's pads against the other placed pads. `base` are the edges among the others."""
    base = _edges(others) if base is None else base
    mine_refs = {(p["ref"], p["number"]) for p in subject_pads}
    nets = {p["net"] for p in subject_pads}
    withs = [p for p in others if p["net"] in nets] + subject_pads
    mine = [e for e in _edges(withs) if (e.a.ref, e.a.number) in mine_refs or (e.b.ref, e.b.number) in mine_refs]
    n = 0
    for e in mine:
        for f in base:
            if f.net != e.net and ratsnest.segments_cross((e.a.x, e.a.y), (e.b.x, e.b.y), (f.a.x, f.a.y), (f.b.x, f.b.y)):
                n += 1
    for i, e in enumerate(mine):
        for f in mine[i + 1:]:
            if f.net != e.net and ratsnest.segments_cross((e.a.x, e.a.y), (e.b.x, e.b.y), (f.a.x, f.a.y), (f.b.x, f.b.y)):
                n += 1
    return n, len(mine)


def turn_counts_of(items: list, key: str) -> dict:
    """The four turns of the item `key` of a plan's `items`, each with its crossings and connections, and the one marked: the fewest;
    on a tie the turn that is no `rotation=` at all (0) where it is among them, else the smallest. `tie` says there was one."""
    item = next((i for i in items if i["key"] == key), None)
    if item is None or item.get("at") is None:
        raise BuilderRefused("%s is not placed, so there is no place to turn it at" % key)
    mine = pads_of(item)
    if not mine:
        raise BuilderRefused("%s has no pad on a net: nothing connects to turn it by" % key)
    others = [p for i in items if i["key"] != key for p in pads_of(i)]
    base = _edges(others)
    ox, oy = item["at"]
    now = item.get("rotation") or 0.0
    turns = []
    for r in TURNS:
        moved = []
        for p in mine:
            x, y = _turned(p["x"], p["y"], ox, oy, r - now)
            moved.append(dict(p, x=x, y=y))
        crossings, connections = count(moved, others, base)
        turns.append({"rotation": r, "crossings": crossings, "connections": connections})
    fewest = min(t["crossings"] for t in turns)
    lows = [t["rotation"] for t in turns if t["crossings"] == fewest]
    best = 0 if 0 in lows else lows[0]
    return {"subject": key, "current": now, "turns": turns, "best": best, "tie": len(lows) > 1, "fewest": fewest, "why": TURN_WHY}


def turn_counts(ctx, key: str) -> dict:
    """`turn_counts_of` on the plan a request is answered in (the part must be placed, as a second step of its placement)."""
    if ctx.plan is None:
        raise BuilderRefused("there is no plan to count crossings on yet")
    return turn_counts_of(ctx.plan["items"], key)


def turn_edits(ctx, key: str, rotation: int, with_why: bool = True) -> Suggestion:
    """The edit that writes a chosen turn: `rotation=90` in the part's own call, with `why=` where it has none. A turn of 0 takes the
    keyword out (no `rotation=` at all is the part's own turn)."""
    from . import builder_intents as bi
    from .builder_parts import modifiers_of
    from . import script_edit as se
    row = ctx.rows.get(key)
    if row is None or row["status"] in ("unplaced",):
        raise BuilderRefused("%s is not placed by a statement of the script yet" % ctx.label(key))
    if rotation not in TURNS:
        raise BuilderRefused("a rotation is a quarter turn: 0, 90, 180 or 270", "rotation is a quarter turn")
    target = bi._target_of(ctx, row)
    mods = row.get("mods") or {}
    file = str(ctx.script)
    edits = []
    if rotation == 0:
        if "rotation" in mods:
            edits.append(Edit("remove_kwarg", target, {"name": "rotation"}, None, {}, file))
        else:
            raise BuilderRefused("%s has no rotation= to take out" % ctx.label(key))
    else:
        edits.append(Edit("set_kwarg", target, {"name": "rotation"}, rotation, {}, file))
        if with_why and "why" not in mods:
            edits.append(Edit("set_kwarg", target, {"name": "why"}, {"str": TURN_WHY}, {}, file))
    return bi._suggestion(ctx, "Turn %s %d degrees" % (ctx.label(key), rotation), edits)
