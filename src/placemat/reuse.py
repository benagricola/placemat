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

VERSION = 5                 # of the record's format: 2 records the items a step names (a block's members); 3 stores findings as facts; 4 stores a step's notes and unplaced reasons as records; 5 carries a cell's arrangement in a placement and in a commit


def omitted(obj, f) -> bool:
    """A field added after declarations were first digested, still at its
    default: left out, so the digest of a declaration that never set it is
    the one an earlier release wrote, and a lock accepted then still holds."""
    return f.metadata.get("omit_default", False) and getattr(obj, f.name) == f.default


def canonical(obj, _seen=None, parts=None) -> str:
    """A stable text form of a declaration value: equal values, equal text.
    `parts` maps a refdes to the name a footprint is given instead (the lock
    names parts by instance path, which a renumbering does not change)."""
    if _seen is None:
        _seen = set()
    if obj is None or isinstance(obj, (bool, int, str)):
        return repr(obj)
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, Enum):
        return "%s.%s" % (type(obj).__name__, obj.value)
    if isinstance(obj, Footprint):
        return "fp:%s" % (parts.get(obj.ref, obj.ref) if parts else obj.ref)
    if isinstance(obj, CellGeom):
        return "cell:%s" % obj.name
    kind = type(obj).__name__
    if kind in ("Board", "Occupancy", "Plan"):
        return "<%s>" % kind                   # a back-reference, never the state it holds
    if id(obj) in _seen:
        return "<cycle>"
    _seen = _seen | {id(obj)}
    if isinstance(obj, (tuple, list)):
        return "[" + ",".join(canonical(v, _seen, parts) for v in obj) + "]"
    if isinstance(obj, (set, frozenset)):
        return "{" + ",".join(sorted(canonical(v, _seen, parts) for v in obj)) + "}"
    if isinstance(obj, dict):
        return "{" + ",".join(sorted("%s:%s" % (canonical(k, _seen, parts), canonical(v, _seen, parts)) for k, v in obj.items())) + "}"
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return "%s(%s)" % (kind, ",".join("%s=%s" % (f.name, canonical(getattr(obj, f.name), _seen, parts))
                                          for f in dataclasses.fields(obj) if f.metadata.get("reuse", True)
                                          and not omitted(obj, f)))
    if callable(obj) and not hasattr(obj, "__dict__"):
        return "fn:%s" % getattr(obj, "__qualname__", kind)
    if hasattr(obj, "__dict__") or hasattr(obj, "__slots__"):
        names = sorted(set(getattr(obj, "__dict__", {})) | set(getattr(obj, "__slots__", ())))
        return "%s(%s)" % (kind, ",".join("%s=%s" % (n, canonical(getattr(obj, n, None), _seen, parts))
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
_NOT_PLACEMENT = ("preview_", "timeout_", "run_", "route_", "best_", "noise_", "check_", "drc_", "pins_", "explore_route_")


def placement_settings(settings) -> str:
    """The settings as JSON, less those that cannot change a placement."""
    import json
    data = json.loads(settings.json())
    return json.dumps({k: v for k, v in data.items() if not k.startswith(_NOT_PLACEMENT)}, sort_keys=True)


def arrangements_digest(g) -> str:
    """What the stamped cells' arrangements say, for the context: each one's id, its members' poses, its copper and its rule areas.
    Empty when no cell has any."""
    rows = [(name, [(a.id, [(m.ref, m.pose) for m in a.members], a.ops, a.rule_areas) for a in cell.arrangements])
            for name, cell in sorted(g.cells.items()) if cell.arrangements]
    return canonical(rows) if rows else ""


def context_key(board, extra: str = "") -> str:
    """Everything that feeds every step: `extra` (the runner's tool version,
    board file digest, settings and fab profile), the generated board, and
    every declaration that is not a placement - or, with the solve on, every
    placement and link too, because the solve reads them all."""
    from .finding_text import schemas_digest
    parts = [extra, schemas_digest(), _geometry_digest(board.geometry), placement_settings(board.settings),
             canonical([board.courtyard_excess, board.component_spacing, board.edge_margin, board.clearance,
                        board.via_drill, board.via_size, board.keep_going]),
             canonical([board._copper, board._labels, board._rules, sorted(board._free_nets), board._outline,
                        board._shape, board._cutouts, board._named_cutouts, board._keepouts, board.web,
                        board._draw_outline, board._chamfer, board._radius, board._faces,
                        board._fanouts])]
    if board._escapes:                  # left out when none is declared, so a script without one digests as before
        parts.append(canonical(board._escapes))
    arranged = arrangements_digest(board.geometry)
    if arranged:                        # likewise: a board whose cells carry no arrangement digests as before
        parts.append(arranged)
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
    out = [p.location.x, p.location.y, p.rotation, p.face.value]
    if p.arrangement:
        out.append(p.arrangement)           # a placement with no arrangement writes what it wrote before
    return out


def placement_from_json(v):
    if v is None:
        return None
    return Placement(Location(v[0], v[1]), v[2], Face(v[3]), v[4] if len(v) > 4 else "")


def step_to_json(s) -> dict:
    return {"item": s.item, "kind": s.kind, "priority": s.priority.value if s.priority is not None else None,
            "placement": placement_to_json(s.placement), "moved_mm": s.moved_mm, "notes": list(s.notes), "why": s.why,
            "ops": s.ops, "freedom": s.freedom.value if s.freedom is not None else None,
            "rank": s.rank, "rank_of": s.rank_of, "back_face": s.back_face, "laid": list(s.laid),
            "unplaced": None if s.unplaced is None else list(s.unplaced), "lock": s.lock, "pocket": s.pocket, "seconds": round(s.seconds, 6)}


def step_from_json(d):
    from .layout import Step
    return Step(d["item"], d["kind"], Priority(d["priority"]) if d["priority"] is not None else None,
                placement_from_json(d["placement"]), d["moved_mm"], tuple(d["notes"]), d["why"], d["ops"],
                Freedom(d["freedom"]) if d["freedom"] is not None else None, d["rank"], d["rank_of"],
                back_face=d.get("back_face", False), laid=tuple(d.get("laid", ())), unplaced=None if d.get("unplaced") is None else tuple(d["unplaced"]),
                lock=d.get("lock", ""), pocket=d.get("pocket"), first_seconds=d.get("seconds"))


# ------------------------------------------------------------ the run
_PART_NAMES = {"tool": "the tool version", "board": "the generated board", "settings": "the settings",
               "fab": "the fab profile"}


def summary_record(record: dict, previous: dict | None, source: str | None) -> dict | None:
    """What a resolve reused, as data, or None with nothing to reuse: `{"form": "none", "changed": [the parts of the context that
    changed: tool, board, settings, fab; none for the script's board-wide declarations], "source"}`, `{"form": "all", "n",
    "source"}` or `{"form": "some", "reused", "of", "first_change", "source"}`. `source` names where the record came from: "run
    1a2b3c4d"."""
    if not previous:
        return None
    n = len(record["steps"])
    if record["context"] != previous.get("context"):
        mine, theirs = record.get("parts", {}), previous.get("parts", {})
        return {"form": "none", "changed": [k for k in ("tool", "board", "settings", "fab") if mine.get(k) != theirs.get(k)], "source": source}
    if record["reused"] >= n:
        return {"form": "all", "n": n, "source": source}
    return {"form": "some", "reused": record["reused"], "of": n, "first_change": record["first_change"], "source": source}


def summary_text(rec: dict | None) -> str:
    """A `summary_record` as the line a run prints about what it reused, "" for none."""
    if not rec:
        return ""
    if rec["form"] == "none":
        names = [_PART_NAMES[k] for k in rec["changed"]]
        what = " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names) if names else "the script's board-wide declarations"
        return "reused 0 steps: %s changed since %s" % (what, rec["source"])
    if rec["form"] == "all":
        return "reused all %d steps from %s" % (rec["n"], rec["source"])
    return "reused %d of %d steps from %s (first change: %s)" % (rec["reused"], rec["of"], rec["source"], rec["first_change"])


def summary(record: dict, previous: dict | None, source: str | None) -> str:
    """The line a run prints about what it reused, or "" with nothing to reuse."""
    return summary_text(summary_record(record, previous, source))


def pack(data) -> str:
    """Planned copper and what it changed, for a record (layout `_plan_copper`, `_rooms_after_recorded`): the objects
    pickled, so a replay gets back exactly what was planned, compressed and as text for the JSON record. The record's
    context holds the tool version, so a build only reads what the same version packed. None when something in it cannot be
    pickled: that is left out of the record, and planned again next time."""
    import base64, pickle, zlib
    try:
        raw = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
    except (pickle.PicklingError, TypeError, AttributeError):
        return None
    return base64.b64encode(zlib.compress(raw, 1)).decode("ascii")


def unpack(text: str):
    import base64, pickle, zlib
    return pickle.loads(zlib.decompress(base64.b64decode(text)))


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


def finding_to_json(f) -> list:
    """[kind, cause, severity, facts_v, facts], the kind and the cause in their string forms. The suggestions are not kept:
    they are a function of the facts and the script, and are built again at the end of every resolve (suggestions.bind)."""
    return [f.kind.value, f.cause.value, f.severity, f.facts_v, f.facts]


def finding_from_json(v):
    """A stored finding: [kind, cause, severity, facts_v, facts]. A cause or a schema version this release does not
    have cannot be rendered, and reads as no finding: the record is under a context that holds the schema digest, so
    it is not loaded at all by a release whose schemas differ."""
    from . import finding_text
    from .findings import Finding, FindingCause
    kind, cause_text, severity, facts_v, facts = v
    cause = FindingCause.parse(cause_text)
    if cause is None or facts_v != finding_text.facts_version(cause):
        raise ValueError("a finding of %r under schema %r cannot be rendered by this release" % (cause_text, facts_v))
    return Finding(cause, facts, severity)


# ------------------------------------------------------------ the partial log
class PartialLog:
    """The reuse record of a resolve that is still going: the context, then
    each completed step's record as it is made, one JSON line each, flushed.
    A resolve that dies leaves what it had done; the next one replays it
    (the chained keys say which steps still hold). Removed once the whole
    record is written."""

    def __init__(self, path):
        from pathlib import Path
        self.path = Path(path)
        self._f = None

    def begin(self, context: str) -> None:
        import json
        self.close()
        self._f = open(self.path, "w")
        self._f.write(json.dumps({"kind": "header", "version": VERSION, "context": context}) + "\n")
        self._f.flush()

    def append(self, entry: dict) -> None:
        import json
        self._f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        self._f.flush()

    def close(self) -> None:
        if self._f is not None:
            self._f.close()
            self._f = None

    def remove(self) -> None:
        self.close()
        try:
            self.path.unlink()
        except OSError:
            pass


def read_partial(path):
    """A resolve's partial log as a record (`version`, `context`, the
    `steps` it completed), or None when there is none or no header. A line
    cut short by a kill ends it."""
    import json
    try:
        text = open(path).read()
    except OSError:
        return None
    lines = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            lines.append(json.loads(line))
        except ValueError:
            break
    if not lines or lines[0].get("kind") != "header" or lines[0].get("version") != VERSION:
        return None
    return {"version": VERSION, "context": lines[0]["context"], "steps": lines[1:]}


def better_of(previous, partial):
    """Of the previous run's record and a died resolve's partial one (the
    same inputs, so its steps are this run's), the one that replays more:
    the previous, when it holds every step the partial does and goes on;
    else the partial. Either may be None."""
    if partial is None or not partial["steps"]:
        return previous if previous is not None else partial
    if previous is None:
        return partial
    keys = [s["key"] for s in partial["steps"]]
    if previous.get("context") == partial["context"] and [s.get("key") for s in previous.get("steps", [])[:len(keys)]] == keys:
        return previous
    return partial
