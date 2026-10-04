"""The lock file: decisions an explore run found and the agent accepted,
kept beside the script as `<script stem>.lock.json`. Each entry places one
item relative to the placed pad it depends on, in that pad's part's own
frame, so the item follows its anchor when the anchor moves or turns. A
run applies an entry at the item's turn; the declaration's digest says when
the script has changed under it."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from .placement import Placement
from .values import Face, Location

FORMAT = 1


@dataclass(frozen=True)
class LockEntry:
    key: str
    anchor: tuple | None            # (refdes, pad number) of the placed pad it hangs off; None: board-absolute
    anchor_face: str | None         # the anchor part's face when accepted: turned over, the entry is released
    offset: tuple                   # (dx, dy): in the anchor part's frame, or the board's when no anchor
    rotation: float                 # relative to the anchor part's rotation, or absolute
    face: str
    declaration: str                # digest of the item's declaration, links and footprint
    turn: int = 0                   # its place among the locked items in the accepted order
    release: str = ""               # the placemat release that accepted it, for the record
    run: str = ""                   # the run whose explore accepted it
    score: float | None = None      # that explore's best run score, mm


def path_for(script) -> Path:
    script = Path(script)
    return script.with_name(script.stem + ".lock.json")


def read(path) -> list:
    """The entries of a lock file; none when there is no file."""
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [LockEntry(e["key"], tuple(e["anchor"]) if e["anchor"] is not None else None, e["anchor_face"],
                      tuple(e["offset"]), e["rotation"], e["face"], e["declaration"], e.get("turn", 0),
                      e.get("release", ""), e.get("run", ""), e.get("score"))
            for e in data.get("entries", [])]


def write(path, entries) -> None:
    entries = sorted(entries, key=lambda e: e.key)
    doc = {"format": FORMAT, "entries": [asdict(e) for e in entries]}
    Path(path).write_text(json.dumps(doc, indent=1) + "\n")


def _turn(dx: float, dy: float, degrees: float) -> tuple:
    """(dx, dy) turned by `degrees` as placemat turns a part (Transform.rotate:
    y-down, positive counter-clockwise on screen), exactly for a quarter turn."""
    q = degrees % 360.0
    if abs(q) < 1e-9:
        return dx, dy
    if abs(q - 90.0) < 1e-9:
        return dy, -dx
    if abs(q - 180.0) < 1e-9:
        return -dx, -dy
    if abs(q - 270.0) < 1e-9:
        return -dy, dx
    a = math.radians(q)
    return dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)


# What a declaration says that can change where its item goes. Not where it
# sits in the script (index, line, file), what it waits for (derived), nor its prose.
_NOT_DECIDING = frozenset(("index", "line", "file", "needs", "why", "faces_note", "priority_source"))


def declaration_digest(board, intent, ordered: bool = True) -> str:
    """What an entry was accepted against: the item's declaration, the links
    on its pads and its footprint's shape, each part named by its instance
    path, which a renumbering of the board does not change, and a cell's
    members in order of it, not in the order the board file lists them (a
    re-stamped fragment lists them otherwise). `ordered=False`: members as read, as 0.47-0.48 wrote
    it; a run still accepts both."""
    import dataclasses
    from . import reuse as _reuse
    from .board_geometry import members_of
    names = {fp.ref: fp.inst for fp in board.geometry.footprints}
    # a Turned rotation is declared by `turned`; `rotation` holds what it settled to, which follows its part
    skip = _NOT_DECIDING | ({"rotation"} if getattr(intent, "turned", None) is not None else set())
    said = [(f.name, _reuse.canonical(getattr(intent, f.name), parts=names)) for f in dataclasses.fields(intent)
            if f.name not in skip and not _reuse.omitted(intent, f)]
    shape = [(fp.inst, round(fp.body_box.width, 4), round(fp.body_box.height, 4),
              round(fp.courtyard_box.width, 4), round(fp.courtyard_box.height, 4),
              sorted((p.number, p.net, round(p.box.width, 4), round(p.box.height, 4)) for p in fp.pads))
             for fp in members_of(intent.item)]
    if ordered:
        shape.sort(key=lambda t: t[0])
    links = _reuse.links_on(board, intent)
    links = [dataclasses.replace(l, a=(names.get(l.a[0], l.a[0]), l.a[1]), b=(names.get(l.b[0], l.b[0]), l.b[1]))
             for l in links]
    return _reuse._sha("lock", _reuse.canonical(said), _reuse.canonical(sorted(_reuse.canonical(l, parts=names)
                       for l in links)), _reuse.canonical(shape))[:16]


def ref_of(geometry, name: str) -> str:
    """The refdes a stored part name stands for now: an instance path
    (what the lock and the routes file write), or a refdes as 0.43-0.46
    wrote them."""
    for fp in geometry.footprints:
        if fp.inst == name:
            return fp.ref
    return name


def entry_from_turn(key: str, turn: dict, declaration: str, release: str) -> LockEntry:
    """An entry from what an item's turn recorded (Plan.turns)."""
    p = turn["placement"]
    if turn.get("anchor") is None:
        return LockEntry(key, None, None, (round(p.location.x, 6), round(p.location.y, 6)), p.rotation % 360.0,
                         p.face.value, declaration, turn["order"], release)
    a, theta = turn["anchor_at"], turn["anchor_rotation"]
    dx, dy = _turn(p.location.x - a.x, p.location.y - a.y, -theta)
    return LockEntry(key, tuple(turn["anchor"]), turn["anchor_face"], (round(dx, 6), round(dy, 6)),
                     round((p.rotation - theta) % 360.0, 6), p.face.value, declaration, turn["order"], release)


def placement_of(entry: LockEntry, occ) -> tuple:
    """(placement, None) where the entry puts its item on `occ` as it stands,
    or (None, why) when it cannot say: why is a record, {"form": "anchor_pending" | "anchor_face" | "anchor_pad_gone", "ref", ["pad"]}
    (step_text renders it)."""
    if entry.anchor is None:
        return Placement(Location(entry.offset[0], entry.offset[1]), entry.rotation, Face(entry.face)), None
    ref, number = ref_of(occ.geometry, entry.anchor[0]), entry.anchor[1]
    g = occ.items.get(ref)
    if g is None or ref in occ.pending:
        return None, {"form": "anchor_pending", "ref": ref}
    if g.reference.face.value != entry.anchor_face:
        return None, {"form": "anchor_face", "ref": ref}
    try:
        a = occ.pad_location(ref, number)
    except KeyError:
        return None, {"form": "anchor_pad_gone", "ref": ref, "pad": number}
    theta = g.reference.rotation
    dx, dy = _turn(entry.offset[0], entry.offset[1], theta)
    return Placement(Location(round(a.x + dx, 6), round(a.y + dy, 6)), round((entry.rotation + theta) % 360.0, 6),
                     Face(entry.face)), None


def entries(board, plan, keys, release: str = "", run: str = "", score: float | None = None) -> list:
    """Entries for `keys` from a resolved plan, numbered in the order the
    plan placed them, with the run and score that accepted them."""
    out = []
    for key in sorted(keys, key=lambda k: plan.turns[k]["order"] if k in plan.turns else 1 << 30):
        turn = plan.turns.get(key)
        intent = next((i for i in board._placements() if i.key == key), None)
        if turn is None or intent is None:
            continue
        e = entry_from_turn(key, turn, declaration_digest(board, intent), release)
        anchor = e.anchor
        if anchor is not None:          # the anchor by instance: a renumbering does not move it
            anchor = (next((fp.inst for fp in board.geometry.footprints if fp.ref == anchor[0]), anchor[0]), anchor[1])
        out.append(LockEntry(**{**asdict(e), "anchor": anchor, "turn": len(out), "run": run, "score": score}))
    return out


def renumber(entries, plan) -> list:
    """The entries' turns renumbered in the order `plan` placed their items:
    entries accepted at different times keep one order among themselves."""
    from dataclasses import replace
    order = lambda e: (plan.turns[e.key]["order"] if e.key in plan.turns else 1 << 30, e.key)
    return [replace(e, turn=k) for k, e in enumerate(sorted(entries, key=order))]


def release(path, keys) -> list:
    """Drop the entries for `keys` (None: all of them) from a lock file;
    the keys dropped."""
    entries = read(path)
    gone = [e.key for e in entries if keys is None or e.key in keys]
    write(path, [e for e in entries if e.key not in gone])
    return gone


def current(board, plan, written: dict, existing, tolerance: float, keys=None, release: str = "",
            run: str = "", refused=None) -> tuple:
    """Lock each searched item (`keys` of them, or all) where the board
    stands: `written` is {(instance, pad number): (x, y)} of the board as
    it was written, and an item is locked only when every pad of it that
    the resolve placed lies within `tolerance` of there. (the lock's
    entries, the keys locked, {key: why} for the ones not). `refused`, when
    given, holds items already refused and gets the new ones: an item
    hanging off one of them is not locked, nor its anchor locked for it."""
    import math
    from .board_geometry import members_of
    items = dict(plan._items)
    locked = []
    refused = {} if refused is None else refused
    for key in sorted(plan.turns, key=lambda k: plan.turns[k]["order"]):
        if keys is not None and key not in keys:
            continue
        for fp in members_of(items[key]) if key in items else ():
            off = None
            for p in fp.pads:
                was = written.get((fp.inst, p.number))
                if was is None:
                    off = "%s pad %s is not on the board" % (fp.inst, p.number)
                    break
                now = plan.occupancy.pad_location(fp.ref, p.number)
                if math.dist(was, (now.x, now.y)) > tolerance:
                    off = "%s stands at (%.3f, %.3f) on the board and would be placed at (%.3f, %.3f) now" % (
                        fp.inst, was[0], was[1], now.x, now.y)
                    break
            if off:
                refused[key] = off
                break
        else:
            locked.append(key)
    # the items those lean on come too: an unlocked anchor goes back to its first spot, taking the item with it
    locked = _with_anchors(plan, locked, refused)
    new = _final_entries(board, plan, locked, release, run)
    kept = [e for e in existing if e.key not in set(locked)]
    return renumber(kept + new, plan), locked, refused


def _owner_of(plan, ref: str):
    """The key of the searched item a part belongs to, or None."""
    from .board_geometry import members_of
    for key in plan.turns:
        item = plan._items.get(key)
        if item is not None and any(fp.ref == ref for fp in members_of(item)):
            return key
    return None


def _with_anchors(plan, locked, refused) -> list:
    """`locked` and, transitively, the searched items their anchors belong
    to; an item whose anchor could not be locked is not locked either."""
    out, todo = list(locked), list(locked)
    while todo:
        key = todo.pop()
        anchor = plan.turns[key].get("anchor")
        owner = _owner_of(plan, anchor[0]) if anchor else None
        if owner is None or owner in out:
            continue
        if owner in refused:
            out.remove(key)
            refused[key] = "it hangs off %s, which stands elsewhere" % owner
            continue
        out.append(owner)
        todo.append(owner)
    return sorted(out, key=lambda k: plan.turns[k]["order"])


def _final_entries(board, plan, keys, release: str, run: str) -> list:
    """Entries for `keys` where the plan finally put them - after the
    cleanup, which moves a searched item after its turn - each off its
    anchor pad where that finally stands."""
    occ = plan.occupancy
    turns = {}
    for key in keys:
        turn = dict(plan.turns[key], placement=plan.step(key).placement)
        a = turn.get("anchor")
        if a is not None:
            g = occ.items[a[0]]
            turn.update(anchor_at=occ.pad_location(*a), anchor_rotation=g.reference.rotation,
                        anchor_face=g.reference.face.value)
        turns[key] = turn
    import types
    return entries(board, types.SimpleNamespace(turns=turns), keys, release=release, run=run)
