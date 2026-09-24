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
                      e.get("release", ""))
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
# sits in the script (index, line), what it waits for (derived), nor its prose.
_NOT_DECIDING = frozenset(("index", "line", "needs", "why", "faces_note", "priority_source"))


def declaration_digest(board, intent) -> str:
    """What an entry was accepted against: the item's declaration, the links
    on its pads and its footprint's shape."""
    import dataclasses
    from . import reuse as _reuse
    from .board_geometry import members_of
    said = [(f.name, _reuse.canonical(getattr(intent, f.name))) for f in dataclasses.fields(intent)
            if f.name not in _NOT_DECIDING]
    shape = [(fp.ref, round(fp.body_box.width, 4), round(fp.body_box.height, 4),
              round(fp.courtyard_box.width, 4), round(fp.courtyard_box.height, 4),
              sorted((p.number, p.net, round(p.box.width, 4), round(p.box.height, 4)) for p in fp.pads))
             for fp in members_of(intent.item)]
    return _reuse._sha("lock", _reuse.canonical(said), _reuse.canonical(sorted(_reuse.canonical(l)
                       for l in _reuse.links_on(board, intent))), _reuse.canonical(shape))[:16]


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
    """(placement, "") where the entry puts its item on `occ` as it stands,
    or (None, why) when it cannot say."""
    if entry.anchor is None:
        return Placement(Location(entry.offset[0], entry.offset[1]), entry.rotation, Face(entry.face)), ""
    ref, number = entry.anchor
    g = occ.items.get(ref)
    if g is None or ref in occ.pending:
        return None, "its anchor %s is not placed before it" % ref
    if g.reference.face.value != entry.anchor_face:
        return None, "its anchor %s is on the other face now" % ref
    try:
        a = occ.pad_location(ref, number)
    except KeyError:
        return None, "its anchor pad %s.%s is gone" % (ref, number)
    theta = g.reference.rotation
    dx, dy = _turn(entry.offset[0], entry.offset[1], theta)
    return Placement(Location(round(a.x + dx, 6), round(a.y + dy, 6)), round((entry.rotation + theta) % 360.0, 6),
                     Face(entry.face)), ""


def entries(board, plan, keys, release: str = "") -> list:
    """Entries for `keys` from a resolved plan, numbered in the order the
    plan placed them."""
    out = []
    for key in sorted(keys, key=lambda k: plan.turns[k]["order"] if k in plan.turns else 1 << 30):
        turn = plan.turns.get(key)
        intent = next((i for i in board._placements() if i.key == key), None)
        if turn is None or intent is None:
            continue
        e = entry_from_turn(key, turn, declaration_digest(board, intent), release)
        out.append(LockEntry(**{**asdict(e), "turn": len(out)}))
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
