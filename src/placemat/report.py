"""Run records: what a run placed and measured, saved as JSON, and the
impact text that compares two of them."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
import math
from pathlib import Path
import re


@dataclass
class RunRecord:
    run_id: str
    board: str
    status: str
    placements: dict = field(default_factory=dict)
    cutouts: dict = field(default_factory=dict)      # where the board was milled, and which way each hole ran
    metrics: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    timing_s: dict = field(default_factory=dict)
    paths: dict = field(default_factory=dict)
    failure: dict | None = None

    def save(self, path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")
        return path

    @staticmethod
    def load(path) -> "RunRecord":
        return RunRecord.of(json.loads(Path(path).read_text()))

    @staticmethod
    def of(data: dict) -> "RunRecord":
        """A record from a document, ignoring keys this version does not know:
        a ledger outlives the field list that wrote it."""
        known = {f.name for f in fields(RunRecord)}
        return RunRecord(**{k: v for k, v in data.items() if k in known})


def run_id(script_text: str, board_bytes: bytes, tool_version: str, settings_json: str = "") -> str:
    """A run is named by a short hash of everything that decides its result:
    the script, the generated board it starts from, the tool version, and the
    resolved settings. Same inputs, same id; a label is only an alias for one.

    The settings are in the hash because a rerun whose id matches replaces its
    run directory, so a setting that changed the board without changing the id
    would destroy the previous run, `route/` and all."""
    import hashlib
    h = hashlib.sha256()
    for part in (tool_version.encode(), script_text.encode(), board_bytes, settings_json.encode()):
        h.update(part)
        h.update(b"\0")
    return h.hexdigest()[:8]


def resolve_run(runs_dir, ref: str) -> Path:
    """A run directory from an id, a unique id prefix, or a label alias."""
    runs_dir = Path(runs_dir)
    direct = runs_dir / ref
    if direct.exists():
        return direct.resolve() if direct.is_symlink() else direct
    matches = [d for d in runs_dir.iterdir() if d.is_dir() and not d.is_symlink() and d.name.startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError("no run %r in %s" % (ref, runs_dir))
    raise ValueError("%r matches %d runs in %s: %s" % (ref, len(matches), runs_dir, ", ".join(m.name for m in matches)))


def airwires_from_drc(drc: dict) -> dict:
    """The ratsnest KiCad reports as unconnected items: count, straight-line
    length, crossings between different nets, and length per net."""
    edges = []
    for u in drc.get("unconnected_items", []):
        items = u.get("items", [])
        if len(items) < 2:
            continue
        a, b = items[0].get("pos", {}), items[1].get("pos", {})
        m = re.search(r"\[([^\]]+)\]", items[0].get("description", ""))
        net = m.group(1) if m else "?"
        edges.append((net, (a.get("x", 0.0), a.get("y", 0.0)), (b.get("x", 0.0), b.get("y", 0.0))))

    def ccw(ax, ay, bx, by, cx, cy):
        return (cy - ay) * (bx - ax) > (by - ay) * (cx - ax)

    def cross(e, f):
        (ax, ay), (bx, by) = e[1], e[2]
        (cx, cy), (dx, dy) = f[1], f[2]
        if max(ax, bx) < min(cx, dx) or max(cx, dx) < min(ax, bx) or max(ay, by) < min(cy, dy) or max(cy, dy) < min(ay, by):
            return False
        return ccw(ax, ay, cx, cy, dx, dy) != ccw(bx, by, cx, cy, dx, dy) and ccw(ax, ay, bx, by, cx, cy) != ccw(ax, ay, bx, by, dx, dy)

    crossings = 0
    crossings_per_net: dict = {}
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            if edges[i][0] != edges[j][0] and cross(edges[i], edges[j]):
                crossings += 1
                for net in (edges[i][0], edges[j][0]):
                    crossings_per_net[net] = crossings_per_net.get(net, 0) + 1
    per_net: dict = {}
    total = 0.0
    for net, a, b in edges:
        d = math.hypot(a[0] - b[0], a[1] - b[1])
        total += d
        per_net[net] = round(per_net.get(net, 0.0) + d, 3)
    return {"count": len(edges), "total_mm": round(total, 3), "crossings": crossings, "per_net": per_net,
            "crossings_per_net": dict(sorted(crossings_per_net.items(), key=lambda kv: (-kv[1], kv[0])))}


def congestion(crossings: int, free_area_mm2: float):
    """Ratsnest crossings per square centimetre of free board: how much
    routing is being asked of how little room. None when there is no free
    board to speak of."""
    if free_area_mm2 <= 0:
        return None
    return round(crossings / (free_area_mm2 / 100.0), 2)


def _delta(label, was, now, fmt="%g", tol=0.0):
    if was == now or (isinstance(was, (int, float)) and isinstance(now, (int, float)) and abs(now - was) <= tol):
        return None
    return "%s %s -> %s" % (label, fmt % was, fmt % now)


def impact(before: RunRecord, after: RunRecord) -> str:
    """A few lines: what moved, by how much, and which metrics changed."""
    lines = ["impact %s -> %s" % (before.run_id, after.run_id)]
    moved = []
    for key, now in after.placements.items():
        was = before.placements.get(key)
        if was is None:
            moved.append("  %s: new at (%.2f, %.2f)" % (key, now["x"], now["y"]))
            continue
        d = math.hypot(now["x"] - was["x"], now["y"] - was["y"])
        rot = "" if now.get("rotation") == was.get("rotation") else "  rot %g -> %g" % (was["rotation"], now["rotation"])
        face = "" if now.get("face") == was.get("face") else "  face %s -> %s" % (was["face"], now["face"])
        if d > 1e-6 or rot or face:
            moved.append("  %s: moved %.2f mm%s%s" % (key, d, rot, face))
    for key in before.placements:
        if key not in after.placements:
            moved.append("  %s: gone" % key)
    if moved:
        lines.append("placements: %d changed" % len(moved))
        lines += moved[:20]
        if len(moved) > 20:
            lines.append("  ... and %d more" % (len(moved) - 20))
    else:
        lines.append("placements: nothing moved")
    cut = []
    for key, now in after.cutouts.items():
        was = before.cutouts.get(key)
        if was is None:
            cut.append("  %s: new at (%.2f, %.2f)" % (key, now["x"], now["y"]))
            continue
        d = math.hypot(now["x"] - was["x"], now["y"] - was["y"])
        rot = "" if now.get("rotation") == was.get("rotation") else "  rot %g -> %g" % (
            was.get("rotation", 0.0), now.get("rotation", 0.0))
        if d > 1e-6 or rot:
            cut.append("  %s: moved %.2f mm%s" % (key, d, rot))
    for key in before.cutouts:
        if key not in after.cutouts:
            cut.append("  %s: gone" % key)
    if cut:                                 # silent on a board with no holes
        lines.append("cutouts: %d changed" % len(cut))
        lines += cut[:10]
    a, b = before.metrics, after.metrics
    deltas = []
    for label, key, fmt, tol in (("unconnected", "unconnected", "%d", 0), ("airwire", "airwire_mm", "%.1f", 0.5),
                                 ("crossings", "crossings", "%d", 0), ("congestion", "congestion", "%.2f", 0.05),
                                 ("closure", "closure_clean", "%.3f", 0.0005), ("findings", "findings", "%d", 0)):
        if (key in a or key in b) and a.get(key) is not None and b.get(key) is not None:
            d = _delta(label, a.get(key, 0), b.get(key, 0), fmt, tol)
            if d:
                deltas.append("  " + d)
    for bucket in ("drc_real", "outstanding", "other"):
        was, now = a.get(bucket, {}) or {}, b.get(bucket, {}) or {}
        for kind in sorted(set(was) | set(now)):
            d = _delta(kind, was.get(kind, 0), now.get(kind, 0), "%d")
            if d:
                deltas.append("  " + d)
    ab, bb = a.get("board"), b.get("board")
    if (ab is None) != (bb is None) or (ab and bb and any(abs(x - y) > 0.005 for x, y in zip(ab, bb))):
        deltas.append("  board %s -> %s" % (ab, bb))
    if deltas:
        lines.append("metrics:")
        lines += deltas
    else:
        lines.append("metrics: no change")
    return "\n".join(lines)


@dataclass(frozen=True)
class Extent:
    """How big what was placed is, and how much of that box is air."""
    width: float
    height: float
    empty: float            # 1 - (courtyard area) / (extent area)


def extent_of(plan) -> "Extent | None":
    """The box round every placed item's courtyard and the fraction of it
    no courtyard covers: a fat cell shows as a high number."""
    from .values import Box
    boxes, area = [], 0.0
    for step in plan.steps:
        if step.placement is None or step.kind not in ("part", "cell"):
            continue
        item = plan._items.get(step.item)
        if item is None:
            continue
        members = item.members if hasattr(item, "members") else (item,)
        for fp in members:
            g = plan.occupancy.items.get(fp.ref)
            if g is None:
                continue
            for s in g.shapes:
                if s.kind == "courtyard":
                    boxes.append(s.box)
                    area += s.box.area
    if not boxes:
        return None
    box = Box.union(boxes)
    return Extent(box.width, box.height, max(0.0, 1.0 - area / box.area) if box.area else 0.0)


def family_of(rec: RunRecord) -> str:
    """Which runs this one is comparable with: those whose script asked to
    place the same things.

    Keyed on what was ASKED for - the steps - not on what landed. When `mcu`
    fails to place it drops out of `placements` but keeps its step, and keying
    on `placements` would give that run a family of its own where nothing is
    compared against it: the one run a regression gate exists for. Adding or
    removing a part starts a new family, since there is nothing meaningful to
    compare across a change in what the board carries."""
    import hashlib
    items = sorted({s.get("item", "") for s in rec.steps if s.get("item")}) or sorted(rec.placements)
    return hashlib.sha256("\n".join(items).encode()).hexdigest()[:8]


def _drc_total(metrics: dict) -> int:
    real = metrics.get("drc_real") or {}
    return sum(real.values()) if isinstance(real, dict) else int(real or 0)


def objective(metrics: dict) -> tuple:
    """How good a run is, lower first, compared left to right.

    Completeness leads because DRC does not mean anything without it: the
    middleweight ledger holds a run at 6 violations that placed 29 of 101
    items, and fewer parts is less copper is fewer ways to break a rule.
    Among runs that laid out the same amount of board, violations lead, then
    placemat's own findings, then how far the airwires have to go."""
    return (-int(metrics.get("placed") or 0),
            _drc_total(metrics),
            int(metrics.get("findings") or 0),
            round(float(metrics.get("airwire_mm") or 0.0), 3))


# What each component of the objective is called when it regresses, in order.
_PARTS = (("placed", "placed", False), ("drc_real", "DRC violations", True),
          ("findings", "findings", True), ("airwire_mm", "airwire", True))


# How far airwire may move, as a fraction, before it counts. kicad-cli reports
# a different set of ratsnest edges each run for a byte-identical board - four
# runs of the Breakout's same inputs gave 2872.80, 2873.11, 2872.80 and
# 2868.87 mm - so an exact comparison fails an identical rerun.
AIRWIRE_NOISE = 0.01


def _verdict(now: dict, best: dict, airwire_noise: float) -> tuple:
    """(sign, index) of the first component that differs: sign -1 when `now`
    is better, 1 when worse, 0 when every component ties. Airwire ties when
    the two are within `airwire_noise` of each other."""
    a, b = objective(now), objective(best)
    for i in range(len(a)):
        x, y = a[i], b[i]
        if _PARTS[i][0] == "airwire_mm":
            if abs(x - y) <= airwire_noise * max(abs(x), abs(y)):
                continue
        elif x == y:
            continue
        return (-1 if x < y else 1), i
    return 0, None


def is_better(now: RunRecord, best: RunRecord | None, airwire_noise: float = AIRWIRE_NOISE) -> bool:
    if best is None:
        return True
    return _verdict(now.metrics, best.metrics, airwire_noise)[0] < 0


def regression(now: RunRecord, best: RunRecord | None,
               airwire_noise: float = AIRWIRE_NOISE) -> str | None:
    """The first component of the objective this run is worse on, said in
    numbers. None when the run is at least as good."""
    if best is None:
        return None
    sign, i = _verdict(now.metrics, best.metrics, airwire_noise)
    if sign <= 0:
        return None
    a, b = objective(now.metrics)[i], objective(best.metrics)[i]
    return "%s %g against %g in the best run (%s)" % (_PARTS[i][1], abs(a), abs(b), best.run_id)


def _best_table(path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def best_for(path, family: str) -> RunRecord | None:
    """The best run recorded for this family, or None."""
    row = _best_table(path).get(family)
    return RunRecord.of(row) if isinstance(row, dict) else None


def update_best(path, now: RunRecord, airwire_noise: float = AIRWIRE_NOISE) -> bool:
    """Record this run as its family's best when it is one. A run that did not
    finish is never the best, however good its numbers look."""
    if now.status != "ok":
        return False
    family = family_of(now)
    table = _best_table(path)
    if not is_better(now, best_for(path, family), airwire_noise):
        return False
    table[family] = asdict(now)
    Path(path).write_text(json.dumps(table, indent=2, sort_keys=True) + "\n")
    return True


def against_best(path, now: RunRecord, airwire_noise: float = AIRWIRE_NOISE) -> tuple:
    """(regression, prior best) for this run, recording it as its family's best
    when it is one. The regression is a sentence naming the metric, or None."""
    prior = best_for(path, family_of(now))
    said = regression(now, prior, airwire_noise)
    update_best(path, now, airwire_noise)
    return said, prior
