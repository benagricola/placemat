"""Retry what the search leaves unplaced (D27).

The search places items one at a time, so an item placed early can stand in the room a later one needs: no term of the
score knows a later item will need room. After the searched tier, each item left unplaced for want of room is tried
again: the placed items in the way of one room are lifted, and the item and then they are placed again, each by the
board's own search. The result is kept only when more is placed than before (on equal counts, when the run score
falls) and no other count of the validity tier rose; else the board goes back exactly as it was.

The board side is a `Host` (layout.py's `_RetryHost`): what is unplaced, the rooms, lifting, placing, the standing of
the board, and putting it back. `attempt` is one try with a given set lifted; refine's reconstruct move can call it
with the items it lifts, or replace `retry_unplaced`'s choice of rooms with its own region.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .placement import Placement
from .values import Location

# A run score lower by no more than this is the same score: the tie on equal placed counts is broken by a real fall.
_EPS = 1e-6


@dataclass(frozen=True)
class Room:
    """A spot an unplaced item could take once `lifted` (step keys, in the order they were placed) are off the board."""
    lifted: tuple
    at: Placement
    gap_mm: float           # from the item's hint: of rooms whose lifted items cover as much, the nearest ranks first


@dataclass(frozen=True)
class Standing:
    """What decides whether a try is kept: the validity tier's counts and the run score."""
    unplaced: tuple         # unplaced parts by priority (high, default, low), as score.Validity counts them
    rest: tuple             # the validity tier's other counts: (drc_new, widths_failed, critical)
    score: float

    def to_json(self) -> dict:
        return {"unplaced": list(self.unplaced), "rest": list(self.rest), "score": round(self.score, 6)}


def better(after: Standing, before: Standing) -> bool:
    """Whether a try's board is kept: fewer unplaced, or as many and a lower run score; and no other count of the
    validity tier higher."""
    if any(a > b for a, b in zip(after.rest, before.rest)):
        return False
    if after.unplaced != before.unplaced:
        return after.unplaced < before.unplaced
    return after.score < before.score - _EPS


def attempt(host, key: str, lifted, seed: int, at: Placement | None = None, before: Standing | None = None) -> dict:
    """One try for the unplaced item `key`: lift `lifted` (step keys), place `key` (searched round `at`, the room's
    spot, when given; else by its own search), then each of `lifted` by its own search in order, or where that finds
    nothing round the nearest spot no placed item stands in, and keep the board only when it is `better`; else put it
    back. `before`: the board's standing, when the caller has it. The try's record: the item, the seed, what was
    lifted, what was placed, whether it was kept, the standing before and after, and (`standing`) the board's
    standing now."""
    before = before or host.standing()
    saved = host.save()
    host.lift(lifted)
    placed = [key] if host.place(key, at) else []
    for k in lifted:
        if host.place(k, None):
            placed.append(k)
            continue
        free = host.rooms(k, 0, 1)          # its own search found nothing: the nearest spot nothing stands in
        if free and host.place(k, free[0].at):
            placed.append(k)
    after = host.standing()
    kept = better(after, before)
    if not kept:
        host.restore(saved)
    return {"item": key, "seed": seed, "lifted": list(lifted), "placed": placed, "kept": kept,
            "before": before.to_json(), "after": after.to_json(), "standing": after if kept else before}


def retry_unplaced(host, rounds: int, most: int) -> list:
    """Each item the host names as unplaced for want of room, in the order it was searched: tries, one per room the
    host finds with at most `most` placed items in the way, best room first, until one is kept, and no more than
    `rounds` for the item in all (its seed counts them from 0). An item a kept try left unplaced is tried in its turn
    after those before it, a room never twice for the same item. Every try is recorded by the host (`host.record`)
    and returned."""
    out = []
    if rounds <= 0:
        return out
    tried: dict = {}                    # step key -> the sets of items lifted for it
    now = None                          # the board's standing, once a try has measured it
    done: set = set()                   # items with no tries left, or no room to try
    while True:
        todo = [k for k in host.unplaced() if k not in done]
        if not todo:
            return out
        for key in todo:
            sets = tried.setdefault(key, set())
            kept = False
            for room in host.rooms(key, most, rounds - len(sets), skip=frozenset(sets)):
                rec = attempt(host, key, room.lifted, len(sets), room.at, now)
                now = rec.pop("standing")
                sets.add(frozenset(room.lifted))
                rec["room"] = {"at": [room.at.location.x, room.at.location.y], "rotation": room.at.rotation,
                               "face": room.at.face.value, "gap_mm": round(room.gap_mm, 6)}
                host.record(rec)
                out.append(rec)
                if rec["kept"]:
                    kept = True
                    break
            if not kept or len(sets) >= rounds:
                done.add(key)


# ------------------------------------------------------------------ rooms
_CLAIMS = ("courtyard", "body")


def _claims(shapes, owners=None) -> dict:
    """{owner: (box, faces)}: the union of each owner's courtyard and body shapes, and the faces they hold."""
    out = {}
    for s in shapes:
        if s.kind not in _CLAIMS or (owners is not None and s.owner not in owners):
            continue
        b, f = out.get(s.owner, (None, frozenset()))
        out[s.owner] = (s.box if b is None else b.union(s.box), f | s.faces)
    return out


def rooms(occ, item, turns, faces, hint: Location, movable: dict, order: dict, step: float, most: int, want: int,
          clearance=None, skip=frozenset()) -> list:
    """Up to `want` rooms for `item`, best first: spots on a `step` lattice over the board where its courtyards and
    bodies come within `clearance` of no placed item's but the `movable` ones' ({owner ref: step key}), and of at most `most` of
    those (a spot they meet none of, which the item's own search did not reach, is a room with nothing to lift); ranked by the area the items in the way cover (the least to place again first), then by distance from
    `hint`. One room per set of items in the way, at the nearest of its spots that is legal with them lifted
    (`Occupancy.legal`: a spot that needs carried vias to give way is passed over). `order`: {step key: the order it
    was placed in}, the order a room lifts them in. `skip`: sets of step keys (frozensets) not to lift again."""
    board = occ.board_box
    if board is None or want <= 0:
        return []
    geom = occ._geometry(item)
    gap = clearance or 0.0              # a spot nearer than the clearance to what stays is no room
    keys = sorted(set(movable.values()), key=lambda k: order.get(k, 0))
    bit = {k: 1 << n for n, k in enumerate(keys)}
    obstacles, area = [], {}
    for ref, g in occ.items.items():
        if ref in occ.pending or ref in geom.owners:
            continue
        claim = _claims(g.shapes, {ref}).get(ref)
        if claim is not None:
            obstacles.append((claim[0].inflate(gap), claim[1], bit.get(movable.get(ref), 0)))
            if ref in movable:
                area[movable[ref]] = area.get(movable[ref], 0.0) + claim[0].width * claim[0].height
    found = []
    for face in faces:
        for rot in turns:
            origin = Placement(Location(0.0, 0.0), rot, face)
            own = list(_claims(occ._origin_shapes(item, geom, origin)).values())
            body = occ.origin_body_box(item, rot, face)
            x0, x1 = board.left - body.left, board.right - body.right
            y0, y1 = board.top - body.top, board.bottom - body.bottom
            if x1 < x0 or y1 < y0 or not own:
                continue
            nx, ny = int((x1 - x0) / step + 1e-9) + 1, int((y1 - y0) / step + 1e-9) + 1
            fixed = bytearray(nx * ny)
            masks = [0] * (nx * ny)
            for o, ofaces in own:
                for b, bfaces, m in obstacles:
                    if not (ofaces & bfaces):
                        continue
                    # the shifts that make the two boxes overlap (touching is no overlap), as lattice indices
                    i0 = max(0, math.floor((b.left - o.right - x0) / step + 1e-9) + 1)
                    i1 = min(nx - 1, math.ceil((b.right - o.left - x0) / step - 1e-9) - 1)
                    j0 = max(0, math.floor((b.top - o.bottom - y0) / step + 1e-9) + 1)
                    j1 = min(ny - 1, math.ceil((b.bottom - o.top - y0) / step - 1e-9) - 1)
                    if i0 > i1 or j0 > j1:
                        continue
                    for j in range(j0, j1 + 1):
                        row = j * nx
                        if m:
                            for i in range(row + i0, row + i1 + 1):
                                masks[i] |= m
                        else:
                            fixed[row + i0:row + i1 + 1] = b"\x01" * (i1 - i0 + 1)
            for idx, m in enumerate(masks):
                if fixed[idx]:
                    continue
                if bin(m).count("1") > most:
                    continue
                x, y = x0 + (idx % nx) * step, y0 + (idx // nx) * step
                found.append((round(sum(area[k] for k in keys if m & bit[k]), 6), math.hypot(x - hint.x, y - hint.y), idx,
                              rot, face.value, face, x, y, m))
    found.sort(key=lambda f: f[:5])
    out, taken = [], set()
    cached = set(occ._native_obstacle_cache)
    try:
        for _, gap, _, rot, _, face, x, y, m in found:
            if m in taken:
                continue
            lifted = tuple(k for k in keys if m & bit[k])
            if frozenset(lifted) in skip:
                taken.add(m)
                continue
            p = Placement(Location(round(x, 6), round(y, 6)), rot, face)
            if _legal_without(occ, item, p, {r for r, k in movable.items() if k in lifted}, clearance):
                taken.add(m)
                out.append(Room(lifted, p, gap))
                if len(out) == want:
                    break
    finally:
        for k in [k for k in occ._native_obstacle_cache if k not in cached]:      # the lifted boards' indexes
            del occ._native_obstacle_cache[k]
    return out


def _legal_without(occ, item, placement: Placement, owners: set, clearance) -> bool:
    """Whether `item` may stand at `placement` with `owners` (refs and cell names) off the board, their cells' rule
    areas too. The board is as it was after."""
    pending, reservations = occ.pending, occ.reservations
    cells = {"cell:%s" % o for o in owners}
    occ.pending = pending | owners
    occ.reservations = [r for r in reservations if r.source not in cells]
    try:
        return occ.legal(item, placement, clearance) is None
    finally:
        occ.pending, occ.reservations = pending, reservations
