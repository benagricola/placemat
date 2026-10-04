"""A plan as JSON: what `placemat studio` streams to its page. Made from the
model preview.py draws - the same placed footprints, the same shapes per face,
the same copper, links and congestion grid - so the page and `placemat
preview` show one plan. Pure and deterministic: the same plan gives the same
document, numbers rounded to a micrometre.

Faces are named, never mirrored: the page mirrors the back."""
from __future__ import annotations

import math

from .board_geometry import members_of, stackup_order
from .geometry import native_status
from .copper import Pour, Text, Track, Via, Zone, arc_circle
from . import finding_text
from .refusals import reserved_by
from .preview import HEAT_MIN, _board_loops, _drawn_at, _extent, _face_of, _placed

VERSION = 3             # 3: records only, no sentences: a step has `notes` (step_text.py) not `note`, an unplaced entry its `reasons`, a reservation `by`, a finding no `text` and its facts no rendered texts (present.py makes them for a page)
                        # 2: members carry `models` and the plan `stackup` and `models` when a model context is given (model_plan.py); all additive
DIGITS = 3              # decimals kept: a micrometre, below any placement or copper tolerance


def _r(v: float) -> float:
    out = round(float(v), DIGITS)
    return 0.0 if out == 0 else out


def _pt(p) -> list:
    return [_r(p[0]), _r(p[1])] if not hasattr(p, "x") else [_r(p.x), _r(p.y)]


def _poly(points) -> list:
    return [_pt(p) for p in points]


def declared_sites(board) -> dict:
    """{item key: (file, line)}: where the script declared each item, from the
    board the script ran against."""
    out = {}
    for i in getattr(board, "_intents", ()):
        key = getattr(i, "key", None) or getattr(i, "name", None)
        line = getattr(i, "line", 0)
        if key and line:
            out[key] = (getattr(i, "file", ""), line)
    return out


def _shapes(plan, fp) -> list:
    """One footprint's shapes as the drawing has them: courtyard, fab body,
    silk, pads, each with the faces it is on."""
    g = plan.occupancy.items[fp.ref]
    out = []
    for s in g.shapes:
        if s.kind == "courtyard":
            out.append({"kind": "courtyard", "faces": sorted(f.value for f in s.faces), "poly": _poly(s.poly)})
    for kind, polys in (("body", fp.fab), ("silk", fp.silk)):
        for face, poly in _drawn_at(plan, fp, polys):
            out.append({"kind": kind, "faces": [face.value], "poly": _poly(poly)})
    for s in g.shapes:          # the footprint's own copper graphics (a printed winding): copper of no net, on its layer
        if s.kind == "copper" and s.owner == fp.ref and not getattr(s, "carried", ""):
            out.append({"kind": "copper", "faces": sorted(f.value for f in s.faces), "layers": sorted(l.value for l in s.layers),
                        "poly": _poly(s.poly)})
    for s in g.shapes:
        if s.kind in ("pad", "through"):
            out.append({"kind": s.kind, "faces": sorted(f.value for f in s.faces), "layers": sorted(l.value for l in s.layers),
                        "poly": _poly(s.poly), "net": s.net, "number": s.label})
    for s in g.shapes:          # a through pad's drill (cut through its copper) and a mounting hole: the page draws them over the pads
        if s.kind in ("hole", "npth"):
            out.append({"kind": s.kind, "faces": sorted(f.value for f in s.faces), "poly": _poly(s.poly), "number": s.label})
    return out


def _how(plan, step) -> str:
    if step.item in plan.pocketed:
        return "pocket"
    return "decided" if step.freedom is not None and step.freedom.decided else "searched"


def _secs(v):
    """A duration as the page reads it: seconds to a millisecond, None when there is none."""
    return None if v is None else round(v, 3)


def item_json(plan, step, sites: dict | None = None, models=None) -> dict:
    """One step's item as the page shows it: where it stands, how it was
    placed, its note and findings, the line that declared it and, when
    placed, its members' shapes."""
    file, line = (sites or {}).get(step.item, ("", 0))
    p = step.placement
    members = []
    if p is not None and step.item in plan._items:
        for fp in members_of(plan._items[step.item]):
            if fp.ref in plan.occupancy.items:
                m = {"ref": fp.ref, "inst": fp.inst, "value": fp.value, "cell": fp.cell or "", "shapes": _shapes(plan, fp)}
                if models is not None:                  # the 3D view's: each model entry resolved, with its placement matrix (model_plan.py)
                    m["models"] = models.members(plan, fp)
                members.append(m)
    return {
        "key": step.item, "kind": step.kind, "placed": p is not None, "members": members,
        "at": None if p is None else _pt(p.location), "rotation": None if p is None else _r(p.rotation),
        "face": None if p is None else p.face.value,
        "freedom": step.freedom.value if step.freedom is not None else None,
        "priority": step.priority.value if step.priority is not None else None,
        "how": _how(plan, step), "notes": list(step.notes), "unplaced": None if step.unplaced is None else list(step.unplaced), "why": step.why,
        "rank": step.rank, "rank_of": step.rank_of, "pocket": step.pocket, "lock": step.lock,
        "findings": [_finding(f, set(plan.occupancy.items), {step.item}) for f in plan.findings
                     if finding_text.subject(f.cause, f.facts) == step.item],
        "file": file, "line": line, "moved_mm": _r(step.moved_mm),
        "seconds": _secs(step.seconds), "first_seconds": _secs(step.first_seconds),
    }


def _copper(op) -> dict | None:
    face = _face_of(getattr(op, "layer", None))
    face = face.value if face is not None else "inner"
    layer = getattr(getattr(op, "layer", None), "value", "")
    if isinstance(op, Track):
        out = {"t": "track", "net": op.net, "layer": layer, "face": face, "width": _r(op.width),
               "a": _pt(op.start), "b": _pt(op.end), "arc": None}
        if op.mid is not None:
            circle = arc_circle(op.start, op.mid, op.end)
            if circle is not None:
                _, _, r, _, sweep = circle
                out["arc"] = [_r(r), 1 if abs(sweep) > math.pi else 0, 1 if sweep > 0 else 0]
                out["mid"] = _pt(op.mid)
        return out
    if isinstance(op, Via):
        return {"t": "via", "net": op.net, "at": _pt(op.at), "size": _r(op.size), "drill": _r(op.drill),
                "layers": [l.value for l in sorted(op.layers, key=stackup_order)]}
    if isinstance(op, (Zone, Pour)):
        return {"t": "plane" if isinstance(op, Zone) else "pour", "net": op.net, "layer": layer, "face": face,
                "points": _poly(op.points)}
    if isinstance(op, Text):
        return {"t": "text", "text": op.text, "at": _pt(op.at), "face": op.face.value, "size": _r(op.size),
                "rotation": _r(op.rotation), "hjust": op.hjust, "vjust": op.vjust, "mirrored": bool(op.mirrored),
                "thickness": _r(op.thickness), "knockout": bool(op.knockout)}
    return None


def step_extras(plan, step) -> dict:
    """What a copper or cutout step has to draw, for a viewer that is sent steps as they settle: the copper ops it laid
    (as plan_json writes them) and the hole it cut."""
    out = {}
    if step.kind == "copper":
        out["ops"] = [c for c in (_copper(plan.copper[i]) for i in step.laid if i < len(plan.copper)) if c is not None]
    elif step.kind == "cutout":
        placed = plan.cutouts_placed.get(step.item[len("cutout "):] if step.item.startswith("cutout ") else step.item)
        if placed is not None:
            loops = [_poly(l) for l in _board_loops(plan)]
            at = _cutout_loop(plan, step, loops)
            out["cutout"] = loops[at] if at is not None else None
    return out


def _weight_name(weight) -> str:
    """A link's weight as the script names it: FREE, DEFAULT, PREFER or SHORT, else the number."""
    from .values import LinkWeight
    try:
        return LinkWeight(int(weight)).name
    except ValueError:
        return str(int(weight))


def _links(plan) -> list:
    occ, placed, out = plan.occupancy, {fp.ref for _, fp in _placed(plan)}, []
    for l in plan.links:
        if l.a[0] not in placed or l.b[0] not in placed:
            continue
        try:
            a, b = occ.pad_location(*l.a), occ.pad_location(*l.b)
        except KeyError:
            continue
        d = a.distance(b)
        state = "free" if l.limit_mm is None else ("ok" if d <= l.limit_mm + 1e-9 else "over")
        out.append({"a": [l.a[0], str(l.a[1])], "b": [l.b[0], str(l.b[1])], "pa": _pt(a), "pb": _pt(b),
                    "length": _r(d), "limit": None if l.limit_mm is None else _r(l.limit_mm), "state": state,
                    "why": l.why, "weight": int(l.weight), "kind": _weight_name(l.weight)})
    return out


def _congestion(plan) -> dict | None:
    r = getattr(plan, "rudy", None)
    if r is None:
        return None
    cells = []
    if getattr(r, "util", None):
        for j, row in enumerate(r.util):
            for i, u in enumerate(row):
                if u > HEAT_MIN:
                    cells.append([i, j, round(u, 2)])
    return {"cell": _r(r.cell), "origin": _pt(r.origin) if r.origin is not None else [0.0, 0.0], "worst": _r(r.worst),
            "worst_at": _pt(r.worst_at), "cells": cells}


def _finding(f, refs: set, keys) -> dict:
    """One finding as a record: its kind, severity, cause and facts, where it is, the item it is about and its suggestions."""
    where = finding_text.locate(f.cause, f.facts, refs)
    first = finding_text.subject(f.cause, f.facts)
    return {"kind": f.kind.value, "severity": f.severity, "at": where["at"],
            "item": first if first in keys else "", "refs": where["refs"], "pads": where["pads"],
            "cause": f.cause.value if f.cause else None, "facts_v": f.facts_v, "facts": f.facts,
            "suggestions": [s.to_json() for s in getattr(f, "suggestions", ()) if s.id]}


def _findings(plan, keys) -> list:
    refs = set(plan.occupancy.items)
    return [_finding(f, refs, keys) for f in plan.findings]


def _inside(pt, loop) -> bool:
    x, y, hit = pt[0], pt[1], False
    for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def _cutout_loop(plan, step, loops):
    """Which of the board's loops a cutout step cut, or None: the smallest loop round the place it was cut at."""
    if step.kind != "cutout":
        return None
    placed = plan.cutouts_placed.get(step.item[len("cutout "):] if step.item.startswith("cutout ") else step.item)
    if placed is None:
        return None
    def area(l):
        xs, ys = [p[0] for p in l], [p[1] for p in l]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))
    outer = max(range(len(loops)), key=lambda i: area(loops[i]), default=None)       # the board's own edge is never a hole
    around = [(i, l) for i, l in enumerate(loops) if i != outer and _inside(_pt(placed.centre), l)]
    return min(around, key=lambda il: area(il[1]))[0] if around else None


def board_json(plan) -> dict:
    """The board as drawn under the parts: its outline, keepouts and
    reservations. Known as soon as a resolve is under way, so a page can draw
    it before the first part settles."""
    keepouts = []
    for name in sorted(plan.keepouts):
        k = plan.keepouts[name]
        poly = getattr(k, "poly", None) or getattr(k, "polygon", None)
        if poly:
            keepouts.append({"name": name, "poly": _poly(poly), "why": getattr(k, "why", ""),
                             "layers": None if getattr(k, "layers", None) is None else [l.value for l in sorted(k.layers, key=stackup_order)],
                             "excludes": list(getattr(k, "excludes", ())), "allow": sorted(getattr(k, "allow", ())),
                             "max_height": getattr(k, "max_height", None)})
    reservations = []
    for r in plan.occupancy.reservations:
        face = _face_of(r.layer) if r.layer is not None else None
        reservations.append({"poly": _poly(r.poly), "by": reserved_by(r.why).to_json(), "face": face.value if face is not None else None,
                             "source": r.source, "allow": sorted(r.allow), "rule_area": bool(r.courtyard)})
    ext = _extent(plan)
    return {"board": {"loops": [_poly(l) for l in _board_loops(plan)], "drawn": bool(plan.draw_outline),
                      "extent": [_r(ext.left), _r(ext.top), _r(ext.right), _r(ext.bottom)]},
            "keepouts": keepouts, "reservations": reservations}


def plan_json(plan, sites: dict | None = None, score: dict | None = None, models=None) -> dict:
    """The whole plan: the board (outline, keepouts, reservations), every placed
    item with its shapes, copper, links, congestion, findings and the steps in
    order. `sites` is declared_sites(board); `score` the run score the caller
    worked out, which needs the board and is left to it."""
    items, seen = [], set()
    for step, _ in _placed(plan):
        if step.item not in seen:
            seen.add(step.item)
            items.append(item_json(plan, step, sites, models))
    copper = [c for c in (_copper(op) for op in plan.copper) if c is not None]
    at, k = {}, 0
    for n, op in enumerate(plan.copper):                  # a step's ops by where they are in the document's copper
        if _copper(op) is not None:
            at[n], k = k, k + 1
    loops = [_poly(l) for l in _board_loops(plan)]
    steps = []
    for n, s in enumerate(plan.steps):
        steps.append({"i": n, "item": s.item, "kind": s.kind, "placed": s.placement is not None, "notes": list(s.notes), "unplaced": None if s.unplaced is None else list(s.unplaced),
                      "why": s.why, "freedom": s.freedom.value if s.freedom is not None else None,
                      "rank": s.rank, "rank_of": s.rank_of, "pocket": s.pocket, "lock": s.lock,
                      "seconds": _secs(s.seconds), "first_seconds": _secs(s.first_seconds), "copper": [at[i] for i in s.laid if i in at], "loop": _cutout_loop(plan, s, loops)})
    unplaced = [{"item": s.item, "reasons": None if s.unplaced is None else list(s.unplaced), "notes": list(s.notes)}
                for s in plan.steps if s.placement is None and s.kind in ("part", "cell", "block")]
    extra = {} if models is None else {"stackup": models.stackup(plan.geometry), "models": models.table()}
    return {
        "version": VERSION, "native": native_status().facts(), **extra, **board_json(plan),
        "items": items, "copper": copper, "links": _links(plan),
        "congestion": _congestion(plan), "findings": _findings(plan, seen), "steps": steps, "unplaced": unplaced,
        "seconds": _secs(plan.seconds),
        "layers": [l.value for l in sorted(plan.geometry.layers, key=stackup_order)],
        "pocketed": list(plan.pocketed),
        "counts": {"placed": sum(1 for s in plan.steps if s.placement is not None), "findings": len(plan.findings),
                   "severities": plan.findings.by_severity(), "items": len(items), "copper": len(copper), "unplaced": len(unplaced)},
        "score": score,
    }
