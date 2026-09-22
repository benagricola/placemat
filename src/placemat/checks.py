"""Design checks on a generated board.

The capture writes what each part is as `Pm.*` footprint fields (the
placemat-design skill lists them): the loop a part closes, whether its
copper is an aggressor, the net it senses, the current through it, its
dissipation and junction limit. This module reads those facts off the
board with its copper and reports, per check, a number, the limit it is
judged against and a verdict. A check whose fact is missing says so
instead of guessing.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from .board_geometry import BoardGeometry, CopperItem, Footprint
from .geometry import poly_distance, polys_overlap
from .values import Box

AMBIENT_C = 100.0
"""Board temperature the junction estimate starts from: a sealed driver
case at full load; a board states its own when it knows better.
The default for `[check] ambient_c` and `--ambient`."""

KEEP_OUT_MM = 2.0
"""How far sense copper stays from a switch node: a bare clearance still
couples the edge field, two millimetres is the datasheet "keep FB away
from SW" with room for the pour clearance.
The default for `[check] keep_out_mm` and `--keep-out`."""

TRACK_RISE_C = 10.0
"""Temperature rise a current path is sized for, on top of the board's
ambient: the IPC-2221 curve the fab tables quote.
The default for `[check] rise_c` and `--rise`."""

COPPER_OZ = 1.0
"""Outer copper weight the width is sized for, until the board's stackup
is read. The default for `[check] copper_oz` and `--copper-oz`."""

_IPC_K_OUTER = 0.048            # IPC-2221 external layer constant
_MIL_PER_OZ = 1.378             # copper thickness per ounce, in mil
_MM_PER_MIL = 0.0254

_PREFIX = {"": 1.0, "m": 1e-3, "u": 1e-6, "k": 1e3}


@dataclass(frozen=True)
class Facts:
    ref: str
    role: str | None = None
    loop: str | None = None
    aggressor: bool = False
    sensitive: str | None = None        # the net the part senses, by name
    current_a: float | None = None      # `Pm.I: 3A`, through every pad of the part
    currents: dict | None = None        # `Pm.I: vin:3A fb:1mA`, per net (lower-cased names)
    dissipation_w: float | None = None
    tj_max_c: float | None = None
    theta_ja_c_per_w: float | None = None       # junction to ambient, the datasheet's JEDEC-board figure
    theta_jb_c_per_w: float | None = None       # junction to board: the figure a board temperature wants


@dataclass(frozen=True)
class Loop:
    name: str
    parts: tuple[str, ...]
    nets: tuple[str, ...]               # the nets two or more of its parts share
    area_mm2: float                     # the hull of their pads on those nets
    longest_leg_mm: float               # the longest pad-to-pad reach on one shared net


@dataclass(frozen=True)
class SwitchNode:
    net: str
    parts: tuple[str, ...]
    area_mm2: float                     # every pad, track and pour on the net
    extent_mm: float                    # the longer side of its bounding box


@dataclass(frozen=True)
class Verdict:
    check: str
    subject: str
    value: float
    unit: str
    limit: float | None = None
    ok: bool | None = None              # None: not judged (no limit, or a fact is missing)
    note: str = ""

    def line(self) -> str:
        judged = "" if self.ok is None else (" ok" if self.ok else " FAIL")
        lim = "" if self.limit is None else " (limit %g)" % self.limit
        note = " - " + self.note if self.note else ""
        return "%-15s %-12s %8.3g %s%s%s%s" % (self.check, self.subject, self.value, self.unit, lim, judged, note)


# ----------------------------------------------------------------- facts

def _quantity(text: str) -> float:
    """`3A`, `250mA`, `0.6W`, `125C`, `80C/W` as a number in base units."""
    m = re.fullmatch(r"\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([mukMK]?)\s*[A-Za-z/]*\s*", text)
    if not m:
        raise ValueError("not a quantity: %r" % text)
    prefix = m.group(2)
    if prefix in ("M", "K"):
        prefix = prefix.lower() if prefix == "K" else "M"
    scale = _PREFIX.get(prefix, None)
    if scale is None:
        raise ValueError("unit prefix %r in %r" % (prefix, text))
    return float(m.group(1)) * scale


def _facts_of(fp: Footprint) -> Facts:
    low = {k.lower(): v for k, v in fp.fields.items() if k.lower().startswith("pm.")}

    def get(key):
        v = low.get("pm." + key)
        return v.strip() if v is not None and v.strip() else None

    def number(key):
        v = get(key)
        return _quantity(v) if v is not None else None

    current_a, currents = None, None
    if get("i") is not None:
        if ":" in get("i"):
            currents = {}
            for item in re.split(r"[\s,]+", get("i").strip()):
                net, _, amps = item.partition(":")
                currents[net.lower()] = _quantity(amps)
        else:
            current_a = _quantity(get("i"))
    return Facts(ref=fp.ref, role=get("role"), loop=get("loop"),
                 aggressor=(get("aggressor") or "").lower() in ("true", "yes", "1"),
                 sensitive=get("sensitive"), current_a=current_a, currents=currents, dissipation_w=number("pd"),
                 tj_max_c=number("tjmax"), theta_ja_c_per_w=number("thetaja"), theta_jb_c_per_w=number("thetajb"))


def facts(geometry: BoardGeometry) -> dict[str, Facts]:
    return {fp.ref: _facts_of(fp) for fp in geometry.footprints}


# -------------------------------------------------------------- geometry

def _area(poly) -> float:
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2.0


def _hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def neck_mm(poly) -> float:
    """A polygon's narrowest section: from points along each edge, the
    distance across the interior along the edge's inward normal to the
    boundary opposite. A rectangle's neck is its short side; a rounded
    corner, whose short edges sit close together, does not read as one."""
    n = len(poly)
    signed = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
    inward = 1.0 if signed > 0 else -1.0             # left of the edge when the ring is counter-clockwise
    best = math.inf
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        length = math.hypot(ex, ey)
        if length < 1e-9:
            continue
        nx, ny = -ey / length * inward, ex / length * inward
        for f in (0.25, 0.5, 0.75):
            mx, my = a[0] + ex * f, a[1] + ey * f
            for j in range(n):
                if j == i:
                    continue
                t = _ray_hits(mx, my, nx, ny, poly[j], poly[(j + 1) % n])
                if t is not None and t > 1e-6:
                    best = min(best, t)
    return best


def _ray_hits(px, py, dx, dy, c, d):
    """Distance along the ray (px, py) + t (dx, dy) to segment c-d, or None."""
    sx, sy = d[0] - c[0], d[1] - c[1]
    den = dx * sy - dy * sx
    if abs(den) < 1e-12:
        return None
    qx, qy = c[0] - px, c[1] - py
    t = (qx * sy - qy * sx) / den
    u = (qx * dy - qy * dx) / den
    return t if t >= 0 and -1e-9 <= u <= 1 + 1e-9 else None


def _copper_on(geometry: BoardGeometry, net: str, kinds=("pad", "track", "via", "poly")) -> list[CopperItem]:
    return [c for c in geometry.copper if c.net == net and c.kind in kinds]


def _fp_by_ref(geometry: BoardGeometry) -> dict[str, Footprint]:
    return {fp.ref: fp for fp in geometry.footprints}


# ------------------------------------------------------------- hot loops

def hot_loops(geometry: BoardGeometry) -> list[Loop]:
    f = facts(geometry)
    by_loop: dict[str, list[Footprint]] = {}
    for fp in geometry.footprints:
        if f[fp.ref].loop:
            by_loop.setdefault(f[fp.ref].loop, []).append(fp)
    loops = []
    for name, parts in sorted(by_loop.items()):
        owners: dict[str, set[str]] = {}
        for fp in parts:
            for p in fp.pads:
                owners.setdefault(p.net, set()).add(fp.ref)
        shared = sorted(n for n, refs in owners.items() if len(refs) >= 2)
        points = [(p.location.x, p.location.y) for fp in parts for p in fp.pads if p.net in shared]
        longest = 0.0
        for net in shared:
            pads = [p for fp in parts for p in fp.pads if p.net == net]
            for a in pads:
                for b in pads:
                    if a.owner != b.owner:
                        longest = max(longest, a.location.distance(b.location))
        hull = _hull(points)
        loops.append(Loop(name, tuple(fp.ref for fp in parts), tuple(shared),
                          _area(hull) if len(hull) >= 3 else 0.0, longest))
    return loops


# ---------------------------------------------------------- switch nodes

def switch_nodes(geometry: BoardGeometry) -> list[SwitchNode]:
    f = facts(geometry)
    owners: dict[str, set[str]] = {}
    for fp in geometry.footprints:
        for p in fp.pads:
            owners.setdefault(p.net, set()).add(fp.ref)
    nodes = []
    for net, refs in sorted(owners.items()):
        if len(refs) >= 2 and all(f[r].aggressor for r in refs):
            items = _copper_on(geometry, net)
            area = sum(_area(o) for c in items for o in c.outlines)
            box = Box.union([c.box for c in items]) if items else None
            extent = max(box.width, box.height) if box else 0.0
            nodes.append(SwitchNode(net, tuple(sorted(refs)), area, extent))
    return nodes


# -------------------------------------------------------- sensitive nets

def _sensitive_nets(geometry: BoardGeometry) -> dict[str, str]:
    """net -> how it was found. `Pm.Sensitive` names the net; when no pad
    of the part carries that name, the part's least-connected net is taken
    (the local node, not the rail) and the verdict says so."""
    f = facts(geometry)
    owners: dict[str, set[str]] = {}
    for fp in geometry.footprints:
        for p in fp.pads:
            owners.setdefault(p.net, set()).add(fp.ref)
    out = {}
    for fp in geometry.footprints:
        want = f[fp.ref].sensitive
        if not want:
            continue
        nets = {p.net for p in fp.pads}
        match = [n for n in nets if n.lower() == want.lower()]
        how = "sensed by %s" % fp.ref
        if not match:
            match = sorted(nets, key=lambda n: (len(owners[n]), n))[:1]
            how = "no pad of %s is on a net called %s; took its least-connected net" % (fp.ref, want)
        if match:
            out[match[0]] = how
    return out


def keep_out(geometry: BoardGeometry, limit_mm: float = KEEP_OUT_MM) -> list[Verdict]:
    sensitive = _sensitive_nets(geometry)
    out = []
    for node in switch_nodes(geometry):
        node_items = _copper_on(geometry, node.net)
        sense_items = [c for net in sensitive for c in _copper_on(geometry, net)]
        pairs = [(a, b) for a in node_items for b in sense_items
                 if not (a.kind == "pad" and b.kind == "pad" and a.owner == b.owner)]   # a part's own pins: package, not layout
        if not pairs:
            continue
        d = min(poly_distance(oa, ob) for a, b in pairs for oa in a.outlines for ob in b.outlines)
        out.append(Verdict("keep-out", node.net, d, "mm", limit_mm, d >= limit_mm,
                           "nearest copper of %s" % ", ".join(sorted(sensitive))))
    return out


def crossings_under(geometry: BoardGeometry) -> list[Verdict]:
    out = []
    for net, how in sorted(_sensitive_nets(geometry).items()):
        tracks = [c for c in geometry.copper if c.net == net and c.kind == "track"]
        count = 0
        for t in tracks:
            for c in geometry.copper:
                if c.net == net or c.kind in ("zone", "via") or c.layers & t.layers:
                    continue
                if t.box.overlaps(c.box) and any(polys_overlap(a, b) for a in t.outlines for b in c.outlines):
                    count += 1
        out.append(Verdict("crossings-under", net, count, "crossings", 0, count == 0,
                           "other nets' copper on the other face under %s's tracks (%s)" % (net, how)))
    return out


# --------------------------------------------------------- current paths

def ipc2221_width_mm(current_a: float, rise_c: float = TRACK_RISE_C, copper_oz: float = COPPER_OZ) -> float:
    """IPC-2221 external-layer width for a current at a temperature rise."""
    area_milsq = (current_a / (_IPC_K_OUTER * rise_c ** 0.44)) ** (1 / 0.725)
    return area_milsq / (_MIL_PER_OZ * copper_oz) * _MM_PER_MIL


def current_paths(geometry: BoardGeometry, rise_c: float = TRACK_RISE_C, copper_oz: float = COPPER_OZ) -> list[Verdict]:
    f = facts(geometry)
    current: dict[str, float] = {}
    for fp in geometry.footprints:
        fact = f[fp.ref]
        for p in fp.pads:
            amps = fact.current_a if fact.currents is None else fact.currents.get(p.net.lower())
            if amps is not None:
                current[p.net] = max(current.get(p.net, 0.0), amps)
    out = []
    for net, amps in sorted(current.items()):
        tracks = [c for c in geometry.copper if c.net == net and c.kind == "track"]
        pours = [c for c in geometry.copper if c.net == net and c.kind == "poly"]
        need = ipc2221_width_mm(amps, rise_c, copper_oz)
        sized = "for %g A at %g C rise on %g oz" % (amps, rise_c, copper_oz)
        if pours:
            neck = min(neck_mm(o) for c in pours for o in c.outlines)
            leads = "; the %d track(s) are pin leads, narrowest %.2f mm" % (
                len(tracks), min(c.width_mm for c in tracks)) if tracks else ""
            out.append(Verdict("current-path", net, neck, "mm", need, neck >= need,
                               "narrowest neck of the pour %s%s" % (sized, leads)))
            continue
        if not tracks:
            out.append(Verdict("current-path", net, 0.0, "mm", need, None, "no track on the net yet (%g A)" % amps))
            continue
        narrowest = min(c.width_mm for c in tracks)
        out.append(Verdict("current-path", net, narrowest, "mm", need, narrowest >= need, "narrowest track " + sized))
    return out


# ------------------------------------------------------------------ heat

def heat(geometry: BoardGeometry, ambient_c: float = AMBIENT_C) -> list[Verdict]:
    out = []
    for fp in geometry.footprints:
        fact = _facts_of(fp)
        if fact.dissipation_w is None:
            continue
        if fact.theta_jb_c_per_w is not None:
            theta, how = fact.theta_jb_c_per_w, "junction-to-board from a %g C board" % ambient_c
        elif fact.theta_ja_c_per_w is not None:
            theta, how = fact.theta_ja_c_per_w, "junction-to-ambient (the JEDEC board figure, pessimistic on a real board) from %g C" % ambient_c
        else:
            out.append(Verdict("heat", fp.ref, fact.dissipation_w, "W", fact.tj_max_c, None,
                               "no Pm.ThetaJb or Pm.ThetaJa on the part: junction rise not estimated"))
            continue
        tj = ambient_c + fact.dissipation_w * theta
        note = "%g W at %g C/W, %s" % (fact.dissipation_w, theta, how)
        if fact.tj_max_c is None:
            out.append(Verdict("heat", fp.ref, tj, "C", None, None, note + "; no Pm.TjMax to judge against"))
        else:
            out.append(Verdict("heat", fp.ref, tj, "C", fact.tj_max_c, tj <= fact.tj_max_c, note))
    return out


# ------------------------------------------------------------------- all

def run_checks(geometry: BoardGeometry, ambient_c: float = AMBIENT_C, keep_out_mm: float = KEEP_OUT_MM,
               rise_c: float = TRACK_RISE_C, copper_oz: float = COPPER_OZ,
               limits: dict[str, float] | None = None) -> list[Verdict]:
    """Every check the board's facts allow. `limits` may name a bound for
    `hot-loop` (mm2) and `switch-node` (mm2); without one they report."""
    limits = limits or {}
    out = []
    for loop in hot_loops(geometry):
        lim = limits.get("hot-loop")
        out.append(Verdict("hot-loop", loop.name, loop.area_mm2, "mm2", lim,
                           None if lim is None else loop.area_mm2 <= lim,
                           "longest leg %.2f mm on %s across %s" % (
                               loop.longest_leg_mm, ", ".join(loop.nets) or "no shared net", ", ".join(loop.parts))))
    for node in switch_nodes(geometry):
        lim = limits.get("switch-node")
        out.append(Verdict("switch-node", node.net, node.area_mm2, "mm2", lim,
                           None if lim is None else node.area_mm2 <= lim,
                           "extent %.2f mm, owned by %s" % (node.extent_mm, ", ".join(node.parts))))
    out += keep_out(geometry, keep_out_mm)
    out += crossings_under(geometry)
    out += current_paths(geometry, rise_c, copper_oz)
    out += heat(geometry, ambient_c)
    return out


def kwargs_from(settings) -> dict:
    """The arguments `run_checks` takes, from the resolved settings. One home,
    so `placemat check` and `placemat run` judge a board by the same numbers."""
    return {"ambient_c": settings.check_ambient_c, "keep_out_mm": settings.check_keep_out_mm,
            "rise_c": settings.check_rise_c, "copper_oz": settings.check_copper_oz,
            "limits": dict(settings.check_limits)}


def record(rec, verdicts) -> list:
    """Put a board's verdicts on its run record and return the lines to print.

    A verdict with `ok` None was not judged - no limit was set, or a fact the
    check needs is missing - and it is counted as such rather than as a pass:
    a check that passes because a footprint lacks `Pm.Pd` is worse than none."""
    rec.verdicts = [dict(v.__dict__) for v in verdicts]
    failed = [v for v in verdicts if v.ok is False]
    unjudged = [v for v in verdicts if v.ok is None]
    rec.metrics["checks_failed"] = len(failed)
    rec.metrics["checks_unjudged"] = len(unjudged)
    if not verdicts:
        return ["no Pm.* facts on this board: no design checks ran"]
    head = "%d check(s): %d failed, %d passed, %d not judged" % (
        len(verdicts), len(failed), len(verdicts) - len(failed) - len(unjudged), len(unjudged))
    return [head] + [v.line() for v in failed]
