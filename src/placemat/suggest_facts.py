"""What a finding's raising site measures for its suggestions, from the occupancy it already holds: the sides of a
neighbour an item may stand beside, the parts that pull it, what refused it most. The facts are plain data (strings,
numbers, lists), so a finding carries them and suggestions.py builds the wording and the edit from them."""
from __future__ import annotations

import dataclasses
import re
from collections import Counter

from .board_geometry import members_of
from .placement import Placement
from .values import Beside, Edge, Face, Part

_BUCKET_OWNER = re.compile(r"^(?:.* in )?(keepout|fanout of|label) ")


def inst_of(board, ref: str) -> str:
    """A part's instance name from its refdes (what a place declaration's key is)."""
    try:
        return board.geometry.footprint(ref).inst
    except (KeyError, ValueError):
        return ref


def intent_of(board, key: str):
    """The PlaceIntent that declares item `key`, or None."""
    return next((i for i in board._intents if getattr(i, "key", None) == key and hasattr(i, "item")), None)


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


def reservation_source(owner: str) -> dict:
    """What a reservation was made by, from the text that names it as a blocker: {"keepout": name}, {"label": key}
    or {"fanout": item}; {} for anything else."""
    m = re.search(r"keepout '([^']+)'", owner) or re.search(r'keepout "([^"]+)"', owner)
    if m:
        return {"keepout": m.group(1)}
    m = re.search(r"\blabel (\S+ .*)$", owner)
    if m:
        return {"label": "label " + m.group(1)}
    m = re.search(r"fanout of (\S+)", owner)
    if m:
        return {"fanout": m.group(1)}
    return {}
