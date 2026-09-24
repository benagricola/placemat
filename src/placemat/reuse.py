"""Replaying the previous run: what makes a step's result the same as last
time, and the record a run leaves for the next one.

A step's key is a hash chained from the step before it, over the item placed,
its declaration and the links on its pads; the first step's chain starts from
the context - everything that feeds every step. A step whose key matches the
previous run's key at the same position is replayed rather than searched.
Too cautious is the only way a key may be wrong: anything that can change a
step's result is in its key or the context."""
from __future__ import annotations

import dataclasses
from enum import Enum
import hashlib

from .board_geometry import CellGeom, Footprint, members_of
from .placement import Placement
from .values import Face, Freedom, Location, Priority

VERSION = 2                 # of the record's format: 2 records the items a step names (a block's members)


def canonical(obj, _seen=None) -> str:
    """A stable text form of a declaration value: equal values, equal text."""
    if _seen is None:
        _seen = set()
    if obj is None or isinstance(obj, (bool, int, str)):
        return repr(obj)
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, Enum):
        return "%s.%s" % (type(obj).__name__, obj.value)
    if isinstance(obj, Footprint):
        return "fp:%s" % obj.ref
    if isinstance(obj, CellGeom):
        return "cell:%s" % obj.name
    kind = type(obj).__name__
    if kind in ("Board", "Occupancy", "Plan"):
        return "<%s>" % kind                   # a back-reference, never the state it holds
    if id(obj) in _seen:
        return "<cycle>"
    _seen = _seen | {id(obj)}
    if isinstance(obj, (tuple, list)):
        return "[" + ",".join(canonical(v, _seen) for v in obj) + "]"
    if isinstance(obj, (set, frozenset)):
        return "{" + ",".join(sorted(canonical(v, _seen) for v in obj)) + "}"
    if isinstance(obj, dict):
        return "{" + ",".join(sorted("%s:%s" % (canonical(k, _seen), canonical(v, _seen)) for k, v in obj.items())) + "}"
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return "%s(%s)" % (kind, ",".join("%s=%s" % (f.name, canonical(getattr(obj, f.name), _seen))
                                          for f in dataclasses.fields(obj) if f.metadata.get("reuse", True)))
    if callable(obj) and not hasattr(obj, "__dict__"):
        return "fn:%s" % getattr(obj, "__qualname__", kind)
    if hasattr(obj, "__dict__") or hasattr(obj, "__slots__"):
        names = sorted(set(getattr(obj, "__dict__", {})) | set(getattr(obj, "__slots__", ())))
        return "%s(%s)" % (kind, ",".join("%s=%s" % (n, canonical(getattr(obj, n, None), _seen))
                                          for n in names if not n.startswith("_cached")))
    text = repr(obj)
    # A default repr names a memory address, which differs every run: say the type alone.
    return kind if " at 0x" in text else "%s:%s" % (kind, text)


def _sha(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
        h.update(b"\0")
    return h.hexdigest()


def _geometry_digest(g) -> str:
    """What the generated board holds, as far as placement reads it. The
    runner adds the board file's own digest to the context as well."""
    return canonical([(fp.ref, fp.inst, fp.cell, fp.location, fp.rotation, fp.face, fp.body_box, fp.courtyard_box,
                       fp.phys_box, [(p.number, p.net, sorted(l.value for l in p.layers), p.box) for p in fp.pads])
                      for fp in g.footprints]) + canonical(sorted(g.rule_area_names())) + repr(len(g.copper))


# Settings that cannot change a placement: a change to one replays everything still.
_NOT_PLACEMENT = ("preview_", "timeout_", "route_", "best_", "noise_", "check_", "drc_")


def placement_settings(settings) -> str:
    """The settings as JSON, less those that cannot change a placement."""
    import json
    data = json.loads(settings.json())
    return json.dumps({k: v for k, v in data.items() if not k.startswith(_NOT_PLACEMENT)}, sort_keys=True)


def context_key(board, extra: str = "") -> str:
    """Everything that feeds every step: `extra` (the runner's tool version,
    board file digest, settings and fab profile), the generated board, and
    every declaration that is not a placement - or, with the solve on, every
    placement and link too, because the solve reads them all."""
    parts = [extra, _geometry_digest(board.geometry), placement_settings(board.settings),
             canonical([board.courtyard_excess, board.component_spacing, board.edge_margin, board.clearance,
                        board.via_drill, board.via_size, board.keep_going]),
             canonical([board._copper, board._labels, board._rules, sorted(board._free_nets), board._outline,
                        board._shape, board._cutouts, board._named_cutouts, board._keepouts, board.web,
                        board._draw_outline, board._chamfer, board._radius, board._faces,
                        board._fanouts])]
    if board.settings.solve_enabled:
        parts.append(canonical([board._intents, board._links]))
    return _sha("context", str(VERSION), *parts)


def _refs(intent) -> set:
    item = getattr(intent, "item", None)
    if item is None:
        return set()
    return {getattr(fp, "ref", "") for fp in members_of(item)}


def links_on(board, intent) -> list:
    """The declared links on the intent's own pads."""
    refs = _refs(intent)
    return [l for l in board._links if l.a[0] in refs or l.b[0] in refs]


def step_key(previous: str, intent, links, extra: str = "") -> str:
    """`extra` is what else decides this step: an explore variant's seed
    for a focused item."""
    parts = ["step", previous, canonical(intent), canonical(sorted(canonical(l) for l in links))]
    return _sha(*(parts + [extra] if extra else parts))


# ------------------------------------------------------------ the record
def placement_to_json(p):
    if p is None:
        return None
    return [p.location.x, p.location.y, p.rotation, p.face.value]


def placement_from_json(v):
    if v is None:
        return None
    return Placement(Location(v[0], v[1]), v[2], Face(v[3]))


def step_to_json(s) -> dict:
    return {"item": s.item, "kind": s.kind, "priority": s.priority.value if s.priority is not None else None,
            "placement": placement_to_json(s.placement), "moved_mm": s.moved_mm, "note": s.note, "why": s.why,
            "ops": s.ops, "freedom": s.freedom.value if s.freedom is not None else None,
            "rank": s.rank, "rank_of": s.rank_of}


def step_from_json(d):
    from .layout import Step
    return Step(d["item"], d["kind"], Priority(d["priority"]) if d["priority"] is not None else None,
                placement_from_json(d["placement"]), d["moved_mm"], d["note"], d["why"], d["ops"],
                Freedom(d["freedom"]) if d["freedom"] is not None else None, d["rank"], d["rank_of"])


# ------------------------------------------------------------ the run
_PART_NAMES = {"tool": "the tool version", "board": "the generated board", "settings": "the settings",
               "fab": "the fab profile"}


def summary(record: dict, previous: dict | None, source: str | None) -> str:
    """The line a run prints about what it reused, or "" with nothing to
    reuse. `source` names where the record came from: "run 1a2b3c4d"."""
    if not previous:
        return ""
    n = len(record["steps"])
    if record["context"] != previous.get("context"):
        mine, theirs = record.get("parts", {}), previous.get("parts", {})
        changed = [_PART_NAMES[k] for k in ("tool", "board", "settings", "fab") if mine.get(k) != theirs.get(k)]
        what = " and ".join([", ".join(changed[:-1]), changed[-1]] if len(changed) > 1 else changed) if changed \
            else "the script's board-wide declarations"
        return "reused 0 steps: %s changed since %s" % (what, source)
    if record["reused"] >= n:
        return "reused all %d steps from %s" % (n, source)
    return "reused %d of %d steps from %s (first change: %s)" % (record["reused"], n, source, record["first_change"])


def write(path, record: dict) -> None:
    import json
    path.write_text(json.dumps(record, separators=(",", ":")))


def read(path):
    """A run's record, or None when there is none or it cannot be read."""
    import json
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None
