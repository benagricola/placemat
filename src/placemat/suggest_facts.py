"""What a finding's raising site measures for its suggestions, from the occupancy it already holds: the sides of a
neighbour an item may stand beside, the parts that pull it, what refused it most. The facts are plain data (strings,
numbers, lists), so a finding carries them and suggestions.py builds the wording and the edit from them."""
from __future__ import annotations

import dataclasses
import functools
from collections import Counter

from .board_geometry import members_of
from .values import Beside, Edge, Face, Part


def safe(default):
    """A suggestion is best-effort: a measurement that fails for any reason gives `default` (no facts, so no
    suggestion), and the resolve it was made in goes on."""
    def wrap(fn):
        @functools.wraps(fn)
        def guarded(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception:
                return default() if callable(default) else default
        return guarded
    return wrap


def inst_of(board, ref: str) -> str:
    """A part's instance name from its refdes (what a place declaration's key is)."""
    try:
        return board.geometry.footprint(ref).inst
    except (KeyError, ValueError):
        return ref


def intent_of(board, key: str):
    """The PlaceIntent that declares item `key`, or None."""
    return next((i for i in board._intents if getattr(i, "key", None) == key and hasattr(i, "item")), None)


@safe(list)
def free_sides(board, occ, plan, i, around: str, near, rotation=None, face=None) -> list:
    """The sides of the part `around` (an instance name) where item `i` may stand `Beside` it, nearest to `near` (a
    Location) first, as Edge names ("NORTH"). Each side is judged as a firm placement is, with the item itself lifted
    off the board where it is placed."""
    refs = {fp.ref for fp in members_of(i.item)}
    lifted = sorted(r for r in refs if r not in occ.pending and r in occ.items)
    if lifted:
        occ.lift(lifted)
    found = []
    try:
        rot = rotation if rotation is not None else (i.rotation if i.rotation is not None else 0.0)
        for side in Edge:
            try:
                spec = board._beside_spec(i.key, i.item, i.kind, Beside(Part(around), side))
                cand = dataclasses.replace(i, beside=spec, rotation=rot, face=face or (Face.FRONT if i.either else i.face))
                p = board._beside_placement(occ, plan, cand)
                if occ.legal_giving_way(i.item, p, board.clearance, past_edge=False, by_corners=True)[0] is None:
                    found.append((p.location.distance(near) if near is not None else 0.0, side.name))
            except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                continue
    finally:
        if lifted:
            occ.unlift(lifted)
    return [s for _, s in sorted(found)]


@safe(list)
def partners(board, i, occ, placed, near=None, limit: int = 2) -> list:
    """The instance names of the placed parts that pull item `i` (a pad of theirs on a net one of its own pads is on,
    or a declared link), the strongest pull first, then the nearest to `near`."""
    own = {fp.ref for fp in members_of(i.item)}
    quiet = board._plane_nets() | board._free_nets
    weight: Counter = Counter()
    for fp in members_of(i.item):
        for p in fp.pads:
            if not p.net:
                continue
            for other in board.geometry.pads_on_net(p.net):
                if other.owner in own or other.owner not in placed:
                    continue
                link = board._declared_link((fp.ref, p.number), (other.owner, other.number))
                if p.net in quiet and link is None:
                    continue
                w = link.weight if link is not None else 1
                if w > 0:
                    weight[other.owner] += w
    def far(ref):
        try:
            return occ.items[ref].body.center.distance(near) if near is not None else 0.0
        except (KeyError, AttributeError):
            return 0.0
    order = sorted(weight, key=lambda r: (-weight[r], far(r), r))
    if not order and near is not None:         # nothing pulls it: the placed parts nearest where it was wanted
        order = sorted((r for r in placed if r not in own and board.geometry.has_footprint(r) and r in occ.items),
                       key=lambda r: (far(r), r))
    return [inst_of(board, r) for r in order if board.geometry.has_footprint(r)][:limit]


def dominant(result):
    """The bucket most candidates were refused by (ties: the order the refusals were counted, which is the order
    `_blame_text` lists them), or ""."""
    top = result.rejected.most_common(1)
    return top[0][0] if top else ""


def owners_of(result, bucket: str, buckets) -> list:
    """Who refused most candidates in `bucket`: the owners, most refusals first."""
    counts: Counter = Counter()
    for (kind, owner, _faces), n in result.blockers.items():
        if owner and (kind == bucket or kind in buckets.get(bucket, ())):
            counts[owner] += n
    return [o for o, _ in counts.most_common()]


def reservation_source(owner) -> dict:
    """What a reservation was made by, from the Owner a scan blamed: {"keepout": name}, {"label": key, "item": the item it is on} or
    {"fanout": item}; {} for anything else."""
    by = getattr(owner, "by", None)
    if by is None:
        return {}
    if by.kind == "keepout":
        return {"keepout": by.name}
    if by.kind == "label":
        return {"label": "label " + by.name, "item": by.item}
    if by.kind == "fanout":
        return {"fanout": by.name}
    return {}


def _item_facts(board, i) -> dict:
    return {"item": i.key, "kind": i.kind, "face": "either" if i.either else i.face.value,
            "priority": i.priority.value if i.priority_source == "script" else "",
            "step": i.step}


@safe(dict)
def unplaced_search(board, occ, plan, i, placed, result, hint, radius) -> dict:
    """The facts for a search that found no legal spot: what refused most candidates and who, the parts that pull the
    item and the sides of each it may stand beside, and what the declaration leaves the search."""
    from .blame import BLOCKED_BY, KNOWN_BUCKETS
    from .occupancy import VIA_BUCKET
    top = dominant(result)
    facts = _item_facts(board, i)
    facts.update(dominant=top, near=i.near is not None,
                 turns=len(board._turns(i)) if i.rotation is not None else 0, rotation_given=bool(i.rotation_given),
                 envelope=board.settings.place_envelope)
    facts["drawn"] = bool(top) and top not in KNOWN_BUCKETS and top != VIA_BUCKET and not top.startswith("rider ")
    facts["via"] = top == VIA_BUCKET
    owners = owners_of(result, top, BLOCKED_BY) if top else []
    facts["blockers"] = [o.to_json() for o in owners[:3]]
    if top == "reservation":
        facts["reservations"] = [s for s in (reservation_source(o) for o in owners[:3]) if s]
        for r in facts["reservations"]:
            name = r.get("keepout")
            k = board._keepouts.get(name) if name else None
            if k is not None:
                r["bars"] = bool(k.bars)
    free = {}
    for nb in partners(board, i, occ, placed, hint.location):
        sides = free_sides(board, occ, plan, i, nb, hint.location, hint.rotation, hint.face)
        if sides:
            free[nb] = sides
    facts["free_sides"] = free
    return facts


@safe(list)
def link_candidates(board, i, limit: int = 2) -> list:
    """Pairs of pads that could be linked to pull item `i` toward the part it shares a net with: [{"own": pad number,
    "partner": instance name, "pad": pad number}], the partner being a declared item other than `i`."""
    quiet = board._plane_nets() | board._free_nets
    declared = {x.key for x in board._intents if hasattr(x, "item")}
    out, seen = [], set()
    for fp in members_of(i.item):
        for p in fp.pads:
            if not p.net or p.net in quiet:
                continue
            for other in board.geometry.pads_on_net(p.net):
                partner = inst_of(board, other.owner)
                if other.owner == fp.ref or partner not in declared or partner == i.key or partner in seen:
                    continue
                seen.add(partner)
                out.append({"own": p.number, "partner": partner, "pad": other.number})
                break
    return out[:limit]


@safe(dict)
def unplaced_pocket(board, occ, plan, i) -> dict:
    """The facts for an item no pocket took: the pads it could be linked to a part by, and, for each such part that is
    already placed, the sides of it the item may stand beside."""
    facts = _item_facts(board, i)
    facts["links"] = link_candidates(board, i)
    free = {}
    for link in facts["links"]:
        try:
            ref = board.geometry.footprint(link["partner"]).ref
        except (KeyError, ValueError):
            continue
        if ref in occ.items and ref not in occ.pending:
            sides = free_sides(board, occ, plan, i, link["partner"], occ.items[ref].body.center)
            if sides:
                free[link["partner"]] = sides
    facts["free_sides"] = free
    return facts


@safe(dict)
def unplaced_slide(board, i) -> dict:
    facts = _item_facts(board, i)
    facts["edge"] = i.edge.name if i.edge is not None else ""
    return facts


@safe(dict)
def fixed_part(board, i) -> dict:
    facts = _item_facts(board, i)
    facts["freedom"] = i.freedom.value
    return facts


def escape_facts(board, occ, plan, ref, number, net, by) -> dict:
    """A pad closed or walled in: the part, the pin, what blocks it, and the side of the part its way out points at."""
    facts = {"ref": ref, "part": inst_of(board, ref), "pin": str(number), "net": net, "by": [o.to_json() for o in by]}
    try:
        from .placer import pad_way_out, way_out_side
        fp = board.geometry.footprint(ref)
        step = next((s for s in plan.steps if s.item == fp.inst and s.placement is not None), None)
        if step is not None:
            way = pad_way_out(occ, fp, [str(number)], step.placement.face)
            facts["side"] = way_out_side(way, step.placement.rotation).name
    except (ValueError, KeyError, AttributeError, IndexError):
        pass
    return facts


@safe(str)
def last_place(board) -> str:
    """The key of the last `place` the script made in its own file, where a declaration for an item it left out
    goes after; "" when none stands alone on its line."""
    own = [s for s in board._sites if s.kind == "place" and (not board.script_file or s.file == board.script_file)]
    alone = [s for s in own if board.shared_by(s) == 1]
    return max(alone, key=lambda s: s.line).key if alone else ""
