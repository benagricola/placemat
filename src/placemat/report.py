"""Run records: what a run placed and measured, saved as JSON, and the
impact text that compares two of them."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
import math
from pathlib import Path
import re

from .ratsnest import segments_cross


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
    verdicts: list = field(default_factory=list)      # the design checks, as `Verdict` fields

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


def run_id(script_text: str, board_bytes: bytes, tool_version: str, settings_json: str = "",
           fab_json: str = "") -> str:
    """A run is named by a short hash of everything that decides its result:
    the script, the generated board it starts from, the tool version, the
    resolved settings and the fab profile's values. Same inputs, same id; a
    label is only an alias for one.

    The settings are in the hash because a rerun whose id matches replaces its
    run directory, so a setting that changed the board without changing the id
    would destroy the previous run, `route/` and all."""
    import hashlib
    h = hashlib.sha256()
    parts = [tool_version.encode(), script_text.encode(), board_bytes, settings_json.encode()]
    if fab_json:                    # absent, the id is what it was before the fab profile counted
        parts.append(fab_json.encode())
    for part in parts:
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


def airwires_from_drc(drc: dict, quiet=()) -> dict:
    """The ratsnest KiCad reports as unconnected items: count, straight-line
    length, crossings between different nets, and length per net.
    `crossings_quiet` counts the crossings with a `quiet` net's airwire (a
    plane's or a free net's), and `crossings_pair` those between a
    differential pair's two halves (pairs.pairs_of), which the score weighs
    apart."""
    from .pairs import pairs_of
    edges = []
    for u in drc.get("unconnected_items", []):
        items = u.get("items", [])
        if len(items) < 2:
            continue
        a, b = items[0].get("pos", {}), items[1].get("pos", {})
        m = re.search(r"\[([^\]]+)\]", items[0].get("description", ""))
        net = m.group(1) if m else "?"
        edges.append((net, (a.get("x", 0.0), a.get("y", 0.0)), (b.get("x", 0.0), b.get("y", 0.0))))

    def cross(e, f):
        return segments_cross(e[1], e[2], f[1], f[2])

    crossings = quiet_crossings = pair_crossings = 0
    quiet = set(quiet)
    partners = pairs_of({e[0] for e in edges})
    crossings_per_net: dict = {}
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            if edges[i][0] != edges[j][0] and cross(edges[i], edges[j]):
                crossings += 1
                if edges[i][0] in quiet or edges[j][0] in quiet:
                    quiet_crossings += 1
                elif partners.get(edges[i][0]) == edges[j][0]:
                    pair_crossings += 1
                for net in (edges[i][0], edges[j][0]):
                    crossings_per_net[net] = crossings_per_net.get(net, 0) + 1
    per_net: dict = {}
    total = 0.0
    for net, a, b in edges:
        d = math.hypot(a[0] - b[0], a[1] - b[1])
        total += d
        per_net[net] = round(per_net.get(net, 0.0) + d, 3)
    return {"count": len(edges), "total_mm": round(total, 3), "crossings": crossings,
            "crossings_quiet": quiet_crossings, "crossings_pair": pair_crossings, "per_net": per_net,
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
    was, now = a.get("airwire_per_net") or {}, b.get("airwire_per_net") or {}
    if was and now:
        grew = sorted(((now.get(n, 0.0) - was.get(n, 0.0), n) for n in set(was) | set(now)),
                      key=lambda dn: (-abs(dn[0]), dn[1]))
        grew = [(d, n) for d, n in grew if abs(d) >= 0.5][:8]
        if grew:
            deltas.append("  airwire by net:")
            deltas += ["    %s %.1f -> %.1f" % (n, was.get(n, 0.0), now.get(n, 0.0)) for _, n in grew]
    ab, bb = a.get("board"), b.get("board")
    if (ab is None) != (bb is None) or (ab and bb and any(abs(x - y) > 0.005 for x, y in zip(ab, bb))):
        deltas.append("  board %s -> %s" % (ab, bb))
    if deltas:
        lines.append("metrics:")
        lines += deltas
    else:
        lines.append("metrics: no change")
    lines += _verdict_changes(before.verdicts, after.verdicts)
    return "\n".join(lines)


def _verdict_changes(before: list, after: list) -> list:
    """Design checks whose verdict flipped, named. A check that went from a
    pass to a fail is the line a reader must not miss; one that came right is
    worth a line too. Silent when nothing changed."""
    was = {(v["check"], v["subject"]): v for v in before}
    out = []
    for v in after:
        prev = was.get((v["check"], v["subject"]))
        if prev is None or prev.get("ok") == v.get("ok"):
            continue
        state = {True: "ok", False: "FAIL", None: "not judged"}
        lim = "" if v.get("limit") is None else " (limit %g)" % v["limit"]
        out.append("  %s %s: %s -> %s, %g %s%s" % (
            v["check"], v["subject"], state[prev.get("ok")], state[v.get("ok")],
            v["value"], v["unit"], lim))
    return (["checks:"] + out) if out else []


@dataclass(frozen=True)
class Extent:
    """How big what was placed is, and how much of that box is air."""
    width: float
    height: float
    empty: float            # 1 - (courtyard area) / (extent area)


def extent_of(plan) -> "Extent | None":
    """The box round every placed item's courtyard and the fraction of it
    no courtyard covers: a fat cell shows as a high number."""
    from .board_geometry import members_of
    from .values import Box
    boxes, area = [], 0.0
    for step in plan.steps:
        if step.placement is None or step.kind not in ("part", "cell"):
            continue
        item = plan._items.get(step.item)
        if item is None:
            continue
        for fp in members_of(item):
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


# How far airwire may move, as a fraction, before it counts. kicad-cli reports
# a different set of ratsnest edges each run for a byte-identical board - four
# runs of the same inputs gave 2872.80, 2873.11, 2872.80 and 2868.87 mm - so an
# exact comparison fails an identical rerun. The default of `[best] airwire_noise`.
AIRWIRE_NOISE = 0.01


def _cfg(cfg):
    from .settings import Settings
    return cfg if cfg is not None else Settings()


def comparable(rec: RunRecord) -> bool:
    """Whether a run measured everything the score reads. A run made with
    --no-drc has no violations and no airwire, and reading those missing
    numbers as zero made it the best possible run - every real run after it
    then "regressed" against airwire 0. Presence is the test, not value: zero
    airwire after DRC means everything is joined, and is a real measurement.
    A run recorded before the score (0.32 and earlier) has no measures, so a
    stored best from then reads as absent and the next run takes its place."""
    return all(k in rec.metrics for k in ("drc_real", "airwire_mm", "measures"))


def is_better(now: RunRecord, best: RunRecord | None, cfg=None) -> bool:
    from . import score as _score
    if not comparable(now):
        return False
    if best is None:
        return True
    return _score.compare(now.metrics["measures"], best.metrics["measures"], _cfg(cfg))[0] < 0


def regression(now: RunRecord, best: RunRecord | None, cfg=None) -> str | None:
    """How this run's score is worse than the best's, said in numbers with
    the term that moved it most. None when the run is at least as good."""
    from . import score as _score
    if best is None or not comparable(now):
        return None
    cfg = _cfg(cfg)
    a, b = now.metrics["measures"], best.metrics["measures"]
    sign, term = _score.compare(a, b, cfg)
    if sign <= 0:
        return None
    ta, tb = _score.terms(a, cfg), _score.terms(b, cfg)
    return "score %.1f mm against %.1f in the best run (%s); most of it %s, %.1f -> %.1f mm" % (
        sum(ta.values()), sum(tb.values()), best.run_id, term, tb[term], ta[term])


def score_line(now: RunRecord, best: RunRecord | None, cfg=None) -> str:
    """The run's score by term, beside the best's where they differ."""
    from . import score as _score
    cfg = _cfg(cfg)
    ta = _score.terms(now.metrics["measures"], cfg)
    tb = _score.terms(best.metrics["measures"], cfg) if best is not None and comparable(best) else None
    parts = []
    for t in _score.TERMS:
        if tb is None:
            if ta[t]:
                parts.append("%s %.1f" % (t, ta[t]))
        elif abs(ta[t] - tb[t]) > 1e-6:
            parts.append("%s %.1f (best %.1f)" % (t, ta[t], tb[t]))
    head = "score %.1f mm" % sum(ta.values())
    if tb is not None:
        head += " (best %.1f)" % sum(tb.values())
    return head + (": " + ", ".join(parts) if parts else "")


def _best_table(path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def best_for(path, family: str) -> RunRecord | None:
    """The best run recorded for this family, or None. A stored run that
    measured nothing is no best at all - 0.15.0 could keep a --no-drc run - so
    it reads as absent and the next measured run takes its place."""
    row = _best_table(path).get(family)
    if not isinstance(row, dict):
        return None
    rec = RunRecord.of(row)
    return rec if comparable(rec) else None


def update_best(path, now: RunRecord, cfg=None) -> bool:
    """Record this run as its family's best when it is one. A run that did not
    finish is never the best, however good its numbers look."""
    if now.status != "ok":
        return False
    family = family_of(now)
    table = _best_table(path)
    if not is_better(now, best_for(path, family), cfg):
        return False
    table[family] = asdict(now)
    Path(path).write_text(json.dumps(table, indent=2, sort_keys=True) + "\n")
    return True


def against_best(path, now: RunRecord, cfg=None) -> tuple:
    """(regression, prior best) for this run, recording it as its family's best
    when it is one. The regression is a sentence naming the metric, or None."""
    prior = best_for(path, family_of(now))
    said = regression(now, prior, cfg)
    update_best(path, now, cfg)
    return said, prior
