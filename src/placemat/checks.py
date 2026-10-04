"""Design checks on a generated board.

The capture writes what each part is as `Pm.*` footprint fields (the placemat
skill's references/capture.md lists them): the loop a part closes, whether its
copper is an aggressor, the net it senses, the current through it, its
dissipation and junction limit. This module reads those facts off the
board with its copper and reports, per check, a number, the limit it is
judged against and a verdict. A check whose fact is missing says so
instead of guessing.
"""
from __future__ import annotations

from collections import deque
import dataclasses
from dataclasses import dataclass
import bisect
import math
import re
import types

from . import exposure as _exposure
from . import geometry as _geometry_module
from .board_geometry import BoardGeometry, CopperItem, Footprint
from .geometry import poly_distance, polys_overlap
from .settings import active
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

ZONE_STEP = 0.05
"""The cell a zone fill is rasterised at to measure its width along a
load's route: a width reads within one step of the copper's own.
The default for `[check] zone_step`."""

_IPC_K_OUTER = 0.048            # IPC-2221 external layer constant
_IPC_K_INNER = 0.024            # IPC-2221 internal layer constant
_MIL_PER_OZ = 1.378             # copper thickness per ounce, in mil
_MM_PER_MIL = 0.0254
_MM_PER_OZ = _MIL_PER_OZ * _MM_PER_MIL   # ~0.035001 mm per copper ounce

_PREFIX = {"": 1.0, "m": 1e-3, "u": 1e-6, "k": 1e3}


@dataclass(frozen=True)
class Facts:
    ref: str
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
    accepted: str = ""                  # a failed verdict inside a script's acceptance: "accepted (>= 0.35): why"
    facts: dict = dataclasses.field(default_factory=dict, hash=False)
    """What the check measured, as fields (current-path: the route's ends, its current and neck, and per layer
    the width that carried it); `note` is rendered from them where the check has them."""

    @property
    def severity(self) -> str:
        """How much a failed verdict matters (CHECK_SEVERITY); "" for one that did not fail or was accepted."""
        if self.ok is not False or self.accepted:
            return ""
        return CHECK_SEVERITY.get(self.check, "warning")

    def line(self) -> str:
        judged = "" if self.ok is None else (" ok" if self.ok else " FAIL")
        if self.severity:
            judged += " [%s]" % self.severity
        if self.accepted:
            judged = " " + self.accepted
        lim = "" if self.limit is None else " (limit %g)" % self.limit
        note = " - " + self.note if self.note else ""
        return "%-15s %-12s %8.3g %s%s%s%s" % (self.check, self.subject, self.value, self.unit, lim, judged, note)


CHECK_SEVERITY = {"keep-out": "critical", "current-path": "critical",
                  "crossings-under": "warning", "heat": "warning", "exposure": "warning",
                  "hot-loop": "warning", "switch-node": "warning"}
"""The severity of a failed verdict, as a finding's (findings.SEVERITIES). A keep-out or a
current path that fails is copper the board cannot carry as drawn; the rest are quality limits
a person judges, and `board.accept` takes one with its reason."""


# ------------------------------------------------------------ acceptances

SIDES = {"keep-out": "at_least", "current-path": "at_least",
         "crossings-under": "at_most", "heat": "at_most", "exposure": "at_most",
         "hot-loop": "at_most", "switch-node": "at_most"}
"""Which way each check is judged: `at_least` where more is better,
`at_most` where less is."""


@dataclass(frozen=True)
class Acceptance:
    """`board.accept`: one verdict a script takes as it is, with the reason,
    up to a bound on the side the check judges."""
    check: str
    subject: str
    at_least: float | None = None
    at_most: float | None = None
    why: str = ""

    @property
    def side(self) -> str:
        return "at_least" if self.at_least is not None else "at_most"

    @property
    def bound(self) -> float:
        return self.at_least if self.at_least is not None else self.at_most

    def text(self) -> str:
        return "%s %g" % (">=" if self.side == "at_least" else "<=", self.bound)

    def holds(self, value: float) -> bool:
        return value >= self.bound - 1e-9 if self.side == "at_least" else value <= self.bound + 1e-9


@dataclass(frozen=True)
class Outcome:
    """What one acceptance met: accepted; past (the verdict is worse than the
    bound); unmatched (the run produced no such verdict); or not needed (the
    verdict passes, or is not judged, without it)."""
    acceptance: Acceptance
    outcome: str
    value: float | None = None
    why_not: str = ""                   # for "not needed": "passes" or "not_judged"

    def line(self) -> str:
        a = self.acceptance
        said = {"accepted": "accepted", "past": "past its bound, still FAIL",
                "unmatched": "matched no verdict", "not needed": "not needed"}[self.outcome]
        val = "" if self.value is None else " (%.4g)" % self.value
        return "%s %s %s%s: %s - %s" % (a.check, a.subject, a.text(), val, said, a.why)

    def record(self) -> dict:
        a = self.acceptance
        return {"check": a.check, "subject": a.subject, "side": a.side, "bound": a.bound, "why": a.why,
                "value": self.value, "outcome": self.outcome}


def accept(check: str, subject: str, at_least: float | None = None, at_most: float | None = None,
           why: str = "") -> Acceptance:
    """An acceptance, refused when malformed. See `Board.accept`."""
    if check not in SIDES:
        raise ValueError("unknown check %r: one of %s" % (check, ", ".join(sorted(SIDES))))
    if (at_least is None) == (at_most is None):
        raise ValueError("accept(%r, %r) takes exactly one of at_least= and at_most=" % (check, subject))
    side = "at_least" if at_least is not None else "at_most"
    if side != SIDES[check]:
        raise ValueError("%s is judged by %s: use %s=, not %s=" % (
            check, "a floor" if SIDES[check] == "at_least" else "a ceiling", SIDES[check], side))
    if not str(why).strip():
        raise ValueError("accept(%r, %r) says why: a verdict accepted without a reason is a loosened limit" % (check, subject))
    return Acceptance(check, str(subject), None if at_least is None else float(at_least),
                      None if at_most is None else float(at_most), why)


def judge(verdicts: list, acceptances) -> tuple[list, list]:
    """The verdicts as the script's acceptances read them, and what each
    acceptance met. A failed verdict inside its acceptance's bound is
    accepted; past the bound it still fails and its note names the
    acceptance. Other verdicts are returned as they were."""
    out = list(verdicts)
    outcomes = []
    for a in acceptances:
        at = [i for i, v in enumerate(out) if v.check == a.check and v.subject == a.subject]
        if not at:
            outcomes.append(Outcome(a, "unmatched"))
            continue
        i = at[0]
        v = out[i]
        if v.ok is not False:
            outcomes.append(Outcome(a, "not needed", v.value, "passes" if v.ok else "not_judged"))
        elif a.holds(v.value):
            out[i] = dataclasses.replace(v, accepted="accepted (%s): %s" % (a.text(), a.why))
            outcomes.append(Outcome(a, "accepted", v.value))
        else:
            past = "past its acceptance of %s: %s" % (a.text(), a.why)
            out[i] = dataclasses.replace(v, note=(v.note + "; " if v.note else "") + past)
            outcomes.append(Outcome(a, "past", v.value))
    return out, outcomes


def findings_of(outcomes) -> list:
    """The `setup` findings for acceptances that matched nothing or were not needed."""
    from .findings import Finding, FindingCause as C
    out = []
    for o in outcomes:
        a = o.acceptance
        facts = {"check": a.check, "subject": a.subject, "key": "%s %s" % (a.check, a.subject)}
        if o.outcome == "unmatched":
            out.append(Finding(C.SETUP_ACCEPT, dict(facts, variant="unmatched")))
        elif o.outcome == "not needed":
            out.append(Finding(C.SETUP_ACCEPT, dict(facts, variant="not_needed", why_not=o.why_not), "notice"))
    return out


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
    return Facts(ref=fp.ref, loop=get("loop"),
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


def _copper_on(geometry: BoardGeometry, net: str, kinds=("pad", "track", "via", "poly")) -> list[CopperItem]:
    return [c for c in geometry.copper if c.net == net and c.kind in kinds]



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


@dataclass(frozen=True)
class _NamedCopper:
    """One piece of copper as a keep-out candidate: a pad by its part and
    number, a track or via by its net and ends (`_copper_on`'s items, with a
    pad's number recovered from its footprint, since `CopperItem` does not
    carry one)."""
    kind: str
    owner: str | None
    net: str
    outlines: tuple
    number: str | None = None
    anchors: tuple = ()
    layers: frozenset = frozenset()


def _keep_out_copper(geometry: BoardGeometry, net: str) -> list[_NamedCopper]:
    out = [_NamedCopper("pad", fp.ref, net, p.outlines, number=p.number, layers=p.layers)
           for fp in geometry.footprints for p in fp.pads if p.net == net]
    out += [_NamedCopper(c.kind, c.owner, net, c.outlines, anchors=c.anchors, layers=c.layers)
            for c in _copper_on(geometry, net, kinds=("track", "via", "poly"))]
    return out


def _closest_on_segment(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return a
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return (ax + t * dx, ay + t * dy)


def _nearest_points(a, b) -> tuple:
    """The point of polygon `a` nearest `b`, the point of `b` nearest `a`,
    and the gap between them - the pair of points `poly_distance` measures,
    recovered by the same walk (every vertex of one against every edge of
    the other), since `poly_distance` gives only the distance."""
    best = (math.inf, a[0], b[0])
    for p in a:
        for i in range(len(b)):
            n = _closest_on_segment(p, b[i], b[(i + 1) % len(b)])
            d = math.hypot(p[0] - n[0], p[1] - n[1])
            if d < best[0]:
                best = (d, p, n)
    for p in b:
        for i in range(len(a)):
            n = _closest_on_segment(p, a[i], a[(i + 1) % len(a)])
            d = math.hypot(p[0] - n[0], p[1] - n[1])
            if d < best[0]:
                best = (d, n, p)
    return best[1], best[2], best[0]


def _keep_out_text(item: _NamedCopper, point: tuple) -> str:
    if item.kind == "pad":
        return "%s pad %s (%s) at (%.2f, %.2f)" % (item.owner, item.number, item.net, point[0], point[1])
    if item.kind == "track" and len(item.anchors) >= 2:
        return "track %s (%.2f, %.2f)-(%.2f, %.2f)" % (
            item.net, item.anchors[0][0], item.anchors[0][1], item.anchors[-1][0], item.anchors[-1][1])
    if item.kind == "via" and item.anchors:
        return "via %s at (%.2f, %.2f)" % (item.net, item.anchors[0][0], item.anchors[0][1])
    return "%s %s at (%.2f, %.2f)" % (item.kind, item.net, point[0], point[1])


@dataclass(frozen=True)
class KeepOut:
    """One part's `Pm.KeepOut`, resolved against the board: the part's pads
    on `pads` (nets) keep `distance_mm` from the copper on `away` (nets),
    from the datasheet cited in `source`. A part's own pads are not judged
    against it (their spacing is the footprint's)."""
    ref: str
    distance_mm: float
    source: str
    pads: tuple
    away: tuple


def _net_named(name: str, net: str) -> bool:
    """Whether `net` is the net `name` (case-insensitive) names: the whole
    name, or its last part where the board's net carries the path of the
    cell it sits in (`BUCK1.SW`, `BUCK1/SW`), so one annotation reads in a
    module and in every parent that stamps it."""
    n, w = net.lower(), name.lower()
    return n == w or n.endswith("." + w) or n.endswith("/" + w)


def _net_names(fp: Footprint, names, what: str, key: str):
    """The nets of `fp`'s pads that `names` name (`_net_named`), as the board
    writes them, or a ValueError for a name no pad carries."""
    out = []
    for n in names:
        hit = sorted({p.net for p in fp.pads if p.net and _net_named(n, p.net)})
        if not hit:
            raise ValueError("%s: %s names %s %r, which no pad of %s carries" % (fp.ref, key, what, n, fp.ref))
        out += hit
    return tuple(dict.fromkeys(out))


def _keep_out_of(fp: Footprint, text: str, nodes: set) -> KeepOut:
    """`Pm.KeepOut: <distance>mm [pads=<nets>] [away=<nets>]; <citation>`: the
    part's pads on `pads` keep `distance` from the copper on `away`, both
    nets of the part's own pads. Raises ValueError, naming the part, for what
    does not read."""
    key = "Pm.KeepOut"
    head, semi, cite = text.partition(";")
    if not semi or not cite.strip():
        raise ValueError("%s: %s %r has no citation: write it after a ';', the datasheet and where in it the "
                         "distance is stated or drawn" % (fp.ref, key, text))
    words = head.split()
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)(?:mm)?", words[0]) if words else None
    if not m:
        raise ValueError("%s: %s %r does not begin with a distance in mm" % (fp.ref, key, text))
    distance = float(m.group(1))
    if distance <= 0:
        raise ValueError("%s: %s distance %g is not above zero" % (fp.ref, key, distance))
    given = {}
    for w in words[1:]:
        name, eq, value = w.partition("=")
        if not eq or name.lower() not in ("pads", "away") or not value or name.lower() in given:
            raise ValueError("%s: %s says %r: after the distance it takes pads=<nets> and away=<nets>" % (fp.ref, key, w))
        given[name.lower()] = [n for n in value.split(",") if n]
    if "pads" in given:
        pads = _net_names(fp, given["pads"], "a pad net", key)
    else:
        want = _facts_of(fp).sensitive
        pads = tuple(n for n in sorted({p.net for p in fp.pads}) if want and _net_named(want, n))
        if not pads:
            raise ValueError("%s: %s names no pads to keep clear: give pads=<nets>, or the part's Pm.Sensitive net" % (fp.ref, key))
    if "away" in given:
        away = _net_names(fp, given["away"], "a net", key)
    else:
        away = tuple(sorted(n for n in {p.net for p in fp.pads} if n in nodes))
        if not away:
            raise ValueError("%s: %s names no copper to keep away from: give away=<nets>; %s is on no switch node"
                             % (fp.ref, key, fp.ref))
    return KeepOut(fp.ref, distance, cite.strip(), pads, away)


def keep_outs(geometry: BoardGeometry) -> tuple:
    """The parts' `Pm.KeepOut` as ({ref: KeepOut}, [(ref, why it was refused)]).
    A refused one is not applied."""
    nodes = {n.net for n in switch_nodes(geometry)}
    out, refused = {}, []
    for fp in geometry.footprints:
        text = next((v for k, v in fp.fields.items() if k.lower() == "pm.keepout" and v.strip()), None)
        if text is None:
            continue
        try:
            out[fp.ref] = _keep_out_of(fp, text, nodes)
        except ValueError as e:
            refused.append((fp.ref, str(e)))
    return out, refused


class _KeepOutScope:
    """How a part's `Pm.KeepOut` judges a pair of copper, the nets it names as a pair: copper on one of its
    `away` nets and copper on one of its `pads` nets keep its distance, in place of the board-wide limit - the
    part's pads, and the tracks, vias and pours of those nets, but not another part's pads on them. Not judged
    at it: a pair of the part's own pads (the footprint sets that gap); a track or a via of an `away` net that
    is joined to the part's own pad on it (its pad escape, which leaves the package where the pins are: the
    plan holds no track or via of those nets either, `rules.Rule.of`); and the other nets of the part's pads
    against its `pads` nets, which the annotation does not name (the package's)."""

    def __init__(self, geometry: BoardGeometry, parts: dict):
        self.geometry = geometry
        self.parts = parts
        feet = {fp.ref: fp for fp in geometry.footprints}
        self.feet = {ref: feet[ref] for ref in parts if ref in feet}
        self.nets = {ref: {p.net for p in fp.pads if p.net} for ref, fp in self.feet.items()}
        self._joined = {}

    def escape(self, ref: str, item: _NamedCopper) -> bool:
        """`item`, a track or a via, is joined to a pad of the part on its own net through tracks and vias of
        that net (not through a pour, which is the layout's)."""
        if item.kind not in ("track", "via") or item.net not in self.nets.get(ref, ()):
            return False
        key = (ref, item.net)
        if key not in self._joined:
            wires = [c for c in _keep_out_copper(self.geometry, item.net) if c.kind in ("track", "via")]
            reached = [(p.outlines, p.layers) for p in self.feet[ref].pads if p.net == item.net]
            joined, grew = set(), True
            while grew:
                grew = False
                for w in wires:
                    if id(w.outlines) in joined:
                        continue
                    if any(w.layers & layers and any(poly_distance(o, q) < _JOIN_MM for o in w.outlines for q in outlines)
                           for outlines, layers in reached):
                        joined.add(id(w.outlines))
                        reached.append((w.outlines, w.layers))
                        grew = True
            self._joined[key] = joined
        return id(item.outlines) in self._joined[key]

    def verdict(self, a: _NamedCopper, b: _NamedCopper, node_net: bool, sensitive_net: bool):
        """How the pair is judged: ("limit", k, mm) at that distance, the part k's (less the footprint's own
        gap where `a` is one of its pads), ("own", None, None) not judged (the part's own copper), (None, None,
        None) at the board-wide limit, or ("skip", None, None) not judged by anything: a pair only a part's
        annotation could name and it does not. `a` is on a switch node or an `away` net, `b` on a sensitive or
        `pads` net; `node_net` and `sensitive_net` say they are such for the board-wide limit."""
        hit = None
        for k in self.parts.values():
            if k.ref not in self.feet or b.net not in k.pads:
                continue
            if a.net in k.away:
                own_pad = a.kind == "pad" and a.owner == k.ref
                if own_pad and b.kind == "pad" and b.owner == k.ref:
                    return "own", None, None
                if self.escape(k.ref, a):
                    return "own", None, None
                limit = k.distance_mm
                if own_pad:         # no nearer than the package already puts its pads
                    limit = min(limit, min(poly_distance(o, q) for p in self.feet[k.ref].pads if p.net == b.net
                                           for q in p.outlines for o in a.outlines))
                if hit is None or limit > hit[1]:
                    hit = (k, limit)
            elif a.net in self.nets[k.ref]:
                return "own", None, None                # a net of its own pads the annotation does not name
        if hit is not None:
            return "limit", hit[0], hit[1]
        if node_net and sensitive_net:
            return None, None, None
        return "skip", None, None


_JOIN_MM = 1e-3         # copper this close to other copper of its net is joined to it


@dataclass(frozen=True)
class KeepOutNotice:
    """A pair of copper on different layers inside a keep-out distance with no plane between: not a failure
    (KiCad's clearance judges only copper sharing a layer) but proximity a datasheet may care about. `away` is
    the copper of the away net, `pads` that of the pads net; `layers` the two layers (away's, pads') nearest each other."""
    kind: str
    net: str
    away: _NamedCopper
    pads: _NamedCopper
    layers: tuple
    distance_mm: float
    limit_mm: float
    points: tuple


def keep_out(geometry: BoardGeometry, limit_mm: float = KEEP_OUT_MM) -> list[Verdict]:
    """The keep-out verdicts: one per net, judging the pairs that share a copper layer (a through-hole pad or a
    via spans its layers), as KiCad's clearance does. A distance passes when it is not under the limit by more
    than the board's DRC epsilon, as KiCad's clearance providers subtract it from the clearance before comparing
    (DRC_TEST_PROVIDER_COPPER_CLEARANCE, `clearance - m_DRCEpsilon`; BOARD_DESIGN_SETTINGS::GetDRCEpsilon)."""
    return _keep_out_judged(geometry, limit_mm)[0]


def keep_out_notices(geometry: BoardGeometry, limit_mm: float = KEEP_OUT_MM) -> list[KeepOutNotice]:
    """Per net, the nearest pair on different layers inside its keep-out distance with no plane on a layer
    between them covering both nearest points (`_shielded`'s test). A pair a plane shields is not reported."""
    return _keep_out_judged(geometry, limit_mm)[1]


def _layer_gap(a: frozenset, b: frozenset) -> tuple:
    """The two layers, one from each set, nearest each other in the stackup."""
    from .board_geometry import stackup_order
    return min(((x, y) for x in a for y in b), key=lambda xy: abs(stackup_order(xy[0]) - stackup_order(xy[1])))


def _keep_out_judged(geometry: BoardGeometry, limit_mm: float) -> tuple:
    sensitive = _sensitive_nets(geometry)
    parts, refused = keep_outs(geometry)
    out = [Verdict("keep-out", "%s Pm.KeepOut" % ref, 0.0, "mm", None, False,
                   "refused, so the part is judged at the board-wide %g mm: %s" % (limit_mm, why)) for ref, why in refused]
    scope = _KeepOutScope(geometry, parts)
    notices = []
    nodes = {n.net for n in switch_nodes(geometry)}
    named = {n for k in parts.values() for n in k.away}
    for net in sorted(nodes | named):
        node_items = _keep_out_copper(geometry, net)
        sense_nets = sorted((set(sensitive) | {n for k in parts.values() for n in k.pads}) - {net})
        sense_items = [(c, n) for n in sense_nets for c in _keep_out_copper(geometry, n)]
        if not node_items or not sense_items:
            continue
        # a part's own pins are package, not layout: judged apart, and said when nearer
        best, own, across = None, None, []
        for a in node_items:
            for b, snet in sense_items:
                same = a.kind == "pad" and b.kind == "pad" and a.owner == b.owner
                how, k, kmm = scope.verdict(a, b, net in nodes, snet in sensitive)
                if how == "skip":
                    continue                    # a pair only a part's own limit names, and it holds none: not judged
                limit = kmm if k is not None else limit_mm
                shared = not a.layers or not b.layers or bool(a.layers & b.layers)
                for oa in a.outlines:
                    for ob in b.outlines:
                        d = poly_distance(oa, ob)
                        if not shared:
                            if how != "own" and not same and d < limit - geometry.drc_epsilon:
                                across.append((d, a, b, oa, ob, limit))
                            continue
                        if same:
                            if own is None or d < own[0]:
                                own = (d, a)
                        elif how == "own":
                            continue
                        elif best is None or (d - limit, d) < (best[0] - best[5], best[0]):
                            best = (d, a, b, oa, ob, limit, k)
        for d, a, b, oa, ob, limit in sorted(across, key=lambda t: t[0]):
            la, lb = _layer_gap(a.layers, b.layers)
            pa, pb, _ = _nearest_points(oa, ob)
            if not _plane_between(geometry, la, lb, (pa, pb), (oa, ob)):
                notices.append(KeepOutNotice("keep-out-cross-layer", net, a, b, (la, lb), d, limit, (pa, pb)))
                break
        if best is None:
            continue
        d, a, b, oa, ob, limit, k = best
        pa, pb, _ = _nearest_points(oa, ob)
        note = "%s to %s" % (_keep_out_text(a, pa), _keep_out_text(b, pb))
        if k is not None:
            note += "; limit %g mm from %s's Pm.KeepOut (%s), not the board-wide %g mm" % (
                limit, k.ref, k.source, limit_mm)
            if limit < k.distance_mm - 1e-9:
                note += ", and no nearer than its own pads stand to each other (%g mm)" % limit
        if own is not None and own[0] < d:
            note += "; %s's own pads are %.2f mm apart, a distance its footprint sets" % (own[1].owner, own[0])
        out.append(Verdict("keep-out", net, d, "mm", limit, d >= limit - geometry.drc_epsilon, note))
    return out, notices


def _shielded(geometry: BoardGeometry, track: CopperItem, other: CopperItem) -> bool:
    """Whether a plane fill on a copper layer between `track`'s and
    `other`'s covers where they cross: another net's copper behind a plane
    is not under the track, whatever layer it is on."""
    from .board_geometry import stackup_order
    a = min(stackup_order(l) for l in track.layers)
    b = min(stackup_order(l) for l in other.layers)
    lo, hi = min(a, b), max(a, b)
    overlaps = [(p, q) for p in track.outlines for q in other.outlines if polys_overlap(p, q)]
    points = [x for p, q in overlaps for x in _overlap_points(p, q)]
    return _plane_covers(geometry, lo, hi, points, (track.box, other.box))


def _plane_covers(geometry: BoardGeometry, lo: int, hi: int, points, boxes) -> bool:
    """A zone on a copper layer strictly between stackup positions `lo` and `hi`, over both boxes, covering
    every one of `points` (at least one)."""
    from .board_geometry import stackup_order
    for z in geometry.copper:
        if z.kind != "zone" or not any(lo < stackup_order(l) < hi for l in z.layers):
            continue
        if not all(z.box.overlaps(b) for b in boxes):
            continue
        if points and all(_covered(x, z.outlines) for x in points):
            return True
    return False


def _plane_between(geometry: BoardGeometry, la, lb, points, outlines) -> bool:
    """A plane between layers `la` and `lb` covering each of `points`: where `_shielded` asks it of a crossing,
    a keep-out pair that does not touch asks it of the two nearest points."""
    from .board_geometry import stackup_order
    from .values import Box
    lo, hi = sorted((stackup_order(la), stackup_order(lb)))
    return _plane_covers(geometry, lo, hi, list(points), [Box.of_points(o) for o in outlines])


def _overlap_points(p, q) -> list:
    """Points where two overlapping outlines meet: each one's vertices inside
    the other, and their edges' crossings; what a plane must cover to shield
    the crossing."""
    from .geometry import point_in_polygon, segments_intersect
    pts = [v for v in p if point_in_polygon(v, q)] + [v for v in q if point_in_polygon(v, p)]
    for i in range(len(p)):
        a1, a2 = p[i], p[(i + 1) % len(p)]
        for j in range(len(q)):
            b1, b2 = q[j], q[(j + 1) % len(q)]
            if segments_intersect(a1, a2, b1, b2):
                x = _segment_crossing(a1, a2, b1, b2)
                if x is not None:
                    pts.append(x)
    return pts


def _segment_crossing(a1, a2, b1, b2):
    dx1, dy1 = a2[0] - a1[0], a2[1] - a1[1]
    dx2, dy2 = b2[0] - b1[0], b2[1] - b1[1]
    den = dx1 * dy2 - dy1 * dx2
    if abs(den) < 1e-12:
        return None
    t = ((b1[0] - a1[0]) * dy2 - (b1[1] - a1[1]) * dx2) / den
    return (a1[0] + t * dx1, a1[1] + t * dy1)


def _covered(point, outlines) -> bool:
    from .geometry import point_in_polygon
    return any(point_in_polygon(point, o) for o in outlines)


def crossings_under(geometry: BoardGeometry) -> list[Verdict]:
    out = []
    for net, how in sorted(_sensitive_nets(geometry).items()):
        tracks = [c for c in geometry.copper if c.net == net and c.kind == "track"]
        count = 0
        for t in tracks:
            for c in geometry.copper:
                if c.net == net or c.kind in ("zone", "via") or c.layers & t.layers:
                    continue
                if t.box.overlaps(c.box) and any(polys_overlap(a, b) for a in t.outlines for b in c.outlines) \
                        and not _shielded(geometry, t, c):
                    count += 1
        out.append(Verdict("crossings-under", net, count, "crossings", 0, count == 0,
                           "other nets' copper on another layer under %s's tracks, with no plane between "
                           "covering the crossing (%s)" % (net, how)))
    return out


# --------------------------------------------------------- current paths

def ipc2221_width_mm(current_a: float, rise_c: float = TRACK_RISE_C, copper_oz: float = COPPER_OZ,
                     k: float = _IPC_K_OUTER) -> float:
    """IPC-2221 width for a current at a temperature rise, on a layer of
    this weight: k is 0.048 for an outer layer, 0.024 for an inner one."""
    area_milsq = (current_a / (k * rise_c ** 0.44)) ** (1 / 0.725)
    return area_milsq / (_MIL_PER_OZ * copper_oz) * _MM_PER_MIL


def _layer_oz(layer, copper_mm: dict, fallback_oz: float) -> float:
    mm_thickness = copper_mm.get(layer) if layer is not None else None
    return mm_thickness / _MM_PER_OZ if mm_thickness is not None else fallback_oz


def _layer_k(layer) -> float:
    from .values import CopperLayer
    return _IPC_K_OUTER if layer is None or layer in (CopperLayer.F, CopperLayer.B) else _IPC_K_INNER


def _need_mm(amps: float, rise_c: float, copper_oz: float, copper_mm: dict, layers) -> float:
    layer = next(iter(layers), None)
    return ipc2221_width_mm(amps, rise_c, _layer_oz(layer, copper_mm, copper_oz), _layer_k(layer))


_FILLED = ("zone", "poly")
"""The copper kinds `_pairs` measures along the route: a zone fill and a
drawn pour."""


def _net_graph(geometry: BoardGeometry, net: str):
    """A net's copper as a graph: (nodes, neighbours). A node is (label, the
    width current can pass through it, polygons, box, layers, its ends): a
    pad or via passes any, a track its width, a drawn pour or a zone fill
    any (`_pairs` measures each along the route). `ends`
    is a track's two endpoints, for the neck a current-path verdict names;
    other kinds carry none. Two nodes touch when their copper does on a
    layer they share."""
    nodes = []
    for fp in geometry.footprints:
        for p in fp.pads:
            if p.net == net and p.outlines:
                nodes.append(("%s.%s" % (fp.ref, p.number), math.inf, p.outlines, p.box, p.layers, (), 0.0))
    for c in geometry.copper:
        if c.net != net or not c.outlines:
            continue
        if c.kind in _FILLED:
            # a fill or pour passes any width here: its narrowest neck is a slit to a hole, a thermal spoke
            # to another part, or a sliver where a pad's corner meets its edge - not what the load passes
            # through. _pairs measures it along the route instead
            for o in c.outlines:
                nodes.append((c.kind, math.inf, (o,), Box.of_points(o), c.layers, (), 0.0))
            continue
        if c.kind not in ("track", "via"):
            continue
        cap = c.width_mm if c.kind == "track" else math.inf
        ends = c.anchors if c.kind == "track" and len(c.anchors) >= 2 else ()
        # a track's own length (an arc's along the arc, not its chord), for the neck's
        run = (c.length_mm or (math.hypot(ends[1][0] - ends[0][0], ends[1][1] - ends[0][1]) if ends else 0.0)) \
            if c.kind == "track" else 0.0
        nodes.append((c.kind, cap, c.outlines, c.box, c.layers, ends, run))
    near = {i: [] for i in range(len(nodes))}
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[j]
            if a[4] & b[4] and a[3].overlaps(b[3], gap=1e-6) and \
                    any(polys_overlap(x, y) or poly_distance(x, y) <= 1e-6 for x in a[2] for y in b[2]):
                near[i].append(j)
                near[j].append(i)
    return nodes, near


def _raster(polys, x0: float, y0: float, nx: int, ny: int, s: float) -> bytearray:
    """1 for each cell of the grid whose centre lies inside any of `polys`
    (even-odd within each). A slit to a hole - two coincident edges - is
    crossed twice at one x, so it leaves no gap."""
    inside = bytearray(nx * ny)
    for poly in polys:
        rows = {}
        n = len(poly)
        for k in range(n):
            (ax, ay), (bx, by) = poly[k], poly[(k + 1) % n]
            if ay == by:
                continue
            lo, hi = (ay, by) if ay < by else (by, ay)
            # the rows whose centre y lies in [lo, hi)
            for r in range(max(0, math.ceil((lo - y0) / s - 0.5)), min(ny, math.ceil((hi - y0) / s - 0.5))):
                y = y0 + (r + 0.5) * s
                rows.setdefault(r, []).append(ax + (y - ay) * (bx - ax) / (by - ay))
        for r, xs in rows.items():
            xs.sort()
            base = r * nx
            for a, b in zip(xs[0::2], xs[1::2]):
                c0 = max(0, math.ceil((a - x0) / s - 0.5))
                c1 = min(nx, math.ceil((b - x0) / s - 0.5))
                if c1 > c0:
                    inside[base + c0:base + c1] = b"\x01" * (c1 - c0)
    return inside


def _edt_line(f: list) -> list:
    """The squared distance transform of one line of samples (Felzenszwalb
    and Huttenlocher's lower envelope of parabolas): d[q] = min over p of
    (q - p)^2 + f[p]."""
    n = len(f)
    finite = [q for q in range(n) if f[q] != math.inf]
    if not finite:
        return [math.inf] * n
    v = [finite[0]]                  # the parabolas on the envelope, left to right
    z = [-math.inf, math.inf]        # where each takes over: v[k] from z[k] to z[k + 1]
    for q in finite[1:]:
        while True:
            p = v[-1]
            cut = ((f[q] + q * q) - (f[p] + p * p)) / (2.0 * (q - p))
            if cut > z[-2]:
                break
            v.pop()                  # q's parabola is under p's everywhere p ruled
            z.pop()
        v.append(q)
        z[-1] = cut
        z.append(math.inf)
    d = [0.0] * n
    k = 0
    for q in range(n):
        while z[k + 1] < q:
            k += 1
        p = v[k]
        d[q] = (q - p) * (q - p) + f[p]
    return d


def _distance_transform(inside, nx: int, ny: int) -> list:
    """The squared-distance-in-cells transform of a 0/1 raster (`inside`
    truthy = in), a two-pass exact Euclidean transform (Felzenszwalb and
    Huttenlocher): column-wise then row-wise. The same transform `_Fill`
    takes of its own polygon (its `self.sq`), reused for an arbitrary
    raster - the copper `touching` is asked about, on the fill's own
    grid."""
    cols = [0.0] * (nx * ny)
    for q in range(nx):
        d = _edt_line([math.inf if inside[r * nx + q] else 0.0 for r in range(ny)])
        for r in range(ny):
            cols[r * nx + q] = d[r]
    sq = [0.0] * (nx * ny)
    for r in range(ny):
        sq[r * nx:(r + 1) * nx] = _edt_line(cols[r * nx:(r + 1) * nx])
    return sq


_NATIVE_FILL = True
"""Whether a zone fill's width search uses NativeFill when it can: switched
off to compare against the pure-Python `_Fill` (tests/test_native_fill.py)."""


class _Fill:
    """One zone fill polygon rasterised at `step`: which cells are copper
    and, for each, its squared distance in cells to the nearest cell that is
    not (an exact Euclidean transform over the grid). A slit KiCad draws to
    a hole has no width, so it is no edge. The grid has a cell of margin
    round the polygon, so every edge has cells outside it.

    `touching`, `_reach` and the level search `width` drives are native
    (NativeFill, native/src/fill.rs) when the module has it and
    `_NATIVE_FILL` allows it; `width` itself is unchanged either way - it
    reads `self.sq`/`self.levels` and calls `touching`/`_reach`/`centre`/
    `radius`, whichever `_Fill` this is. Python always keeps the neck
    point and the "one step or less" sentence (docs/superpowers/specs/
    2026-09-30-performance-zone-width-give-way-sweep-design.md
    section 1)."""

    def __init__(self, poly, step: float):
        native = _geometry_module._native
        if _NATIVE_FILL and native is not None and hasattr(native, "NativeFill"):
            self._native = native.NativeFill(poly, step)
            self.s = self._native.s
            self.x0, self.y0 = self._native.x0, self._native.y0
            self.nx, self.ny = self._native.nx, self._native.ny
            self.sq = self._native.sq
            self.levels = self._native.levels
            self._native_polys: dict = {}          # id(polys) -> polys, keeping it alive so id() cannot be reused
            self._paths = {}                       # (id(entry), id(exit_)) -> the path `width` found, for neck_length
            return
        self._native = None
        self._paths = {}
        box = Box.of_points(poly)
        self.s = step
        self.x0, self.y0 = box.left - step, box.top - step
        self.nx = int(math.ceil(box.width / step)) + 2
        self.ny = int(math.ceil(box.height / step)) + 2
        self.inside = _raster([poly], self.x0, self.y0, self.nx, self.ny, step)
        self.sq = _distance_transform(self.inside, self.nx, self.ny)
        inside = self.inside
        # the fill's cells deepest first, so the cells at least some distance in are a prefix
        self.deep = sorted((c for c in range(self.nx * self.ny) if inside[c]), key=lambda c: -self.sq[c])
        self.depths = [-self.sq[c] for c in self.deep]
        self.levels = sorted(set(self.sq[c] for c in self.deep))
        self._copper_sq: dict = {}

    def _copper_distance(self, polys) -> list:
        """The squared-distance-in-cells transform of `polys`, read back at
        this fill's own cells, cached by `polys`'s identity: `width`'s
        binary search over levels calls `touching` with the SAME
        `entry`/`exit_` tuple at every level, so one raster and one
        transform per copper item serves the whole search, replacing a
        per-cell edge scan at every level (docs/superpowers/specs/
        2026-09-30-performance-zone-width-give-way-sweep-design.md
        section 1).

        Rasterised on a grid grown, cell-aligned, past the fill's own
        wherever `polys` reaches further than it: copper the fill only
        touches at a distance (a thermal spoke's pad short of a wide pour's
        real edge) can lie outside the fill's own bounding box by more than
        its one-step margin, and a transform clipped to the fill's grid
        would then understate the distance - reading as not touching where
        the edge-exact test would still call it touching, past what a
        single `check.zone_step` excuses."""
        key = id(polys)
        hit = self._copper_sq.get(key)
        if hit is not None and hit[0] is polys:
            return hit[1]
        s, x0, y0, nx, ny = self.s, self.x0, self.y0, self.nx, self.ny
        cbox = Box.union([Box.of_points(p) for p in polys])
        dq = max(0, int(math.ceil((x0 - (cbox.left - s)) / s - 1e-9)))
        dr = max(0, int(math.ceil((y0 - (cbox.top - s)) / s - 1e-9)))
        gx0, gy0 = x0 - dq * s, y0 - dr * s
        extra_c = max(0, int(math.ceil(((cbox.right + s) - (x0 + nx * s)) / s - 1e-9)))
        extra_r = max(0, int(math.ceil(((cbox.bottom + s) - (y0 + ny * s)) / s - 1e-9)))
        gnx, gny = nx + dq + extra_c, ny + dr + extra_r
        # `_distance_transform`'s seeds (distance 0) are where its raster is
        # FALSE - right for the fill's own `self.sq` (seeded from outside
        # the fill), backwards here: a query cell needs its distance TO the
        # copper, so the copper cells are the seeds, and the raster is
        # inverted before the transform.
        if dq == 0 and dr == 0 and extra_c == 0 and extra_r == 0:
            inside = _raster(polys, x0, y0, nx, ny, s)
            sq = _distance_transform([not b for b in inside], nx, ny)
        else:
            inside = _raster(polys, gx0, gy0, gnx, gny, s)
            grid = _distance_transform([not b for b in inside], gnx, gny)
            sq = [grid[(r + dr) * gnx + (q + dq)] for r in range(ny) for q in range(nx)]
        hit = (polys, sq)
        self._copper_sq[key] = hit
        return hit[1]

    def centre(self, c: int) -> tuple:
        r, q = divmod(c, self.nx)
        return (self.x0 + (q + 0.5) * self.s, self.y0 + (r + 0.5) * self.s)

    def radius(self, tau: float) -> float:
        """How far a cell `tau` squared cells from the nearest cell outside
        the fill stands from the fill's edge: the edge lies somewhere between
        the two centres, half a step short of the outside one taken."""
        return self.s * (math.sqrt(tau) - 0.5)

    def touching(self, polys, tau: float) -> set:
        """The fill's cells at least `tau` from its edge whose disc of that
        radius (`radius(tau)`) reaches `polys`, within half a step: where a
        path that wide can start from copper the fill meets, whether the
        copper overlaps the fill or only touches it (a thermal spoke's end
        at a pad).

        `polys` is rasterised and distance-transformed on the fill's own
        grid (cached per copper item, `_copper_distance`), not walked edge
        by edge: exact to half a cell rather than to the edge. A width may
        differ from the edge-exact answer by at most one `check.zone_step`
        (docs/superpowers/specs/2026-09-30-performance-zone-width-give-way-
        sweep-design.md section 1)."""
        if self._native is not None:
            key = id(polys)
            new = key not in self._native_polys
            if new:
                self._native_polys[key] = polys          # keeps polys alive: id() cannot be reused while cached
            return set(self._native.touching(key, polys if new else None, tau))
        s, nx, ny, sq, inside = self.s, self.nx, self.ny, self.sq, self.inside
        box = Box.union([Box.of_points(p) for p in polys])
        far = self.radius(tau) + s / 2.0
        q0 = max(0, int((box.left - far - self.x0) / s))
        r0 = max(0, int((box.top - far - self.y0) / s))
        q1 = min(nx, int(math.ceil((box.right + far - self.x0) / s)) + 1)
        r1 = min(ny, int(math.ceil((box.bottom + far - self.y0) / s)) + 1)
        deep = bisect.bisect_right(self.depths, -tau)          # how many cells are at least tau in
        if deep < max(0, q1 - q0) * max(0, r1 - r0):
            cells = [c for c in self.deep[:deep] if q0 <= c % nx < q1 and r0 <= c // nx < r1]
        else:
            cells = [r * nx + q for r in range(r0, r1) for q in range(q0, q1)
                     if inside[r * nx + q] and sq[r * nx + q] >= tau]
        copper_sq = self._copper_distance(polys)
        limit = (far / s) ** 2
        return {c for c in cells if copper_sq[c] <= limit + 1e-9}

    def _reach(self, start: set, goal: set, tau: float):
        """A path of fill cells from `start` to `goal`, 8-connected, every
        cell on it in either set or at least `tau` (squared cells) from the
        fill's edge: (the goal cell it reached, or None, and each cell
        reached's parent). Breadth first, so it stops as soon as it
        arrives."""
        if self._native is not None:
            hit, parent = self._native.reach(list(start), list(goal), tau)
            return hit, parent
        nx, ny, inside, sq = self.nx, self.ny, self.inside, self.sq
        parent = {c: None for c in start}
        todo = deque(start)
        while todo:
            c = todo.popleft()
            if c in goal:
                return c, parent
            r, q = divmod(c, nx)
            for rr in (r - 1, r, r + 1):
                if not 0 <= rr < ny:
                    continue
                for qq in (q - 1, q, q + 1):
                    if not 0 <= qq < nx:
                        continue
                    n = rr * nx + qq
                    if n in parent or not inside[n]:
                        continue
                    if sq[n] >= tau or n in goal:
                        parent[n] = c
                        todo.append(n)
        return None, parent

    def width(self, entry, exit_) -> tuple | None:
        """The fill's width along the widest path between the copper the
        route enters it by and leaves it by (each a tuple of polygons): the
        widest disc that can travel through the fill from touching the one
        to touching the other, its centre from cell to cell. (width, the
        neck's point, whether the fill is one step wide or less there), or
        None when the two copper items touch each other. The width is twice
        the radius of the narrowest cell on the path (`radius`); a neck no
        cell centre falls in reads as one step."""
        if any(polys_overlap(a, b) or poly_distance(a, b) <= 1e-6 for a in entry for b in exit_):
            return None
        sq = self.sq

        def attempt(tau):
            start, goal = self.touching(entry, tau), self.touching(exit_, tau)
            if not start or not goal:
                return None, {}, start, goal
            hit, parent = self._reach(start, goal, tau)
            return hit, parent, start, goal
        # the widest level at which a path still joins them: a narrower disc passes wherever a
        # wider one does, so the levels that join them are the lower ones
        levels = self.levels
        lo, hi, found = 0, len(levels) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            got = attempt(levels[mid])
            if got[0] is None:
                hi = mid - 1
            else:
                found, lo = (levels[mid],) + got, mid + 1
        if found is None:
            # no path of cells at all: the fill narrows below one cell. Name where the
            # cells reached from the entry stop nearest the exit.
            start = self.touching(entry, 1.0)
            if not start:
                return self.s, (Box.union([Box.of_points(p) for p in entry]).center.x,
                                Box.union([Box.of_points(p) for p in entry]).center.y), True
            _, seen = self._reach(start, set(), 1.0)
            ex = Box.union([Box.of_points(p) for p in exit_]).center
            stop = min(seen, key=lambda c: (self.centre(c)[0] - ex.x) ** 2 + (self.centre(c)[1] - ex.y) ** 2)
            return self.s, self.centre(stop), True
        b, hit, parent, start, goal = found
        path = []
        c = hit
        while c is not None:
            path.append(c)
            c = parent[c]
        path.reverse()                                          # entry to exit
        # many cells may be that narrow (a path hugs a wall at that distance); the neck is where
        # the path has to be: between what the entry and the exit each reach at the next level
        from_entry = from_exit = {}
        if lo < len(levels):
            wider = levels[lo]
            _, from_entry = self._reach(self.touching(entry, wider), set(), wider)
            _, from_exit = self._reach(self.touching(exit_, wider), set(), wider)
        last = max((k for k, c in enumerate(path) if c in from_entry), default=-1)
        first = min((k for k, c in enumerate(path) if c in from_exit and k > last), default=len(path))
        stretch = path[last + 1:first] or path
        mid = (len(stretch) - 1) / 2.0
        neck = min((k for k, c in enumerate(stretch) if sq[c] == b), key=lambda k: abs(k - mid), default=None)
        neck = stretch[neck] if neck is not None else min(path, key=lambda c: sq[c])
        w = 2.0 * self.radius(b)
        self._paths[(id(entry), id(exit_))] = (entry, exit_, path)      # for neck_length; the polys kept so id() cannot be reused
        return w, self.centre(neck), w <= self.s + 1e-9

    def widest_touching(self, polys) -> float | None:
        """The width of the widest disc in the fill that reaches `polys` (as
        `touching` reads it): no route entering or leaving the fill by that
        copper is wider than this. None when no cell of the fill reaches it."""
        levels = self.levels
        lo, hi, found = 0, len(levels) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.touching(polys, levels[mid]):
                found, lo = levels[mid], mid + 1
            else:
                hi = mid - 1
        return None if found is None else 2.0 * self.radius(found)

    def neck_length(self, entry, exit_, need: float) -> float | None:
        """How far the route `width` found between `entry` and `exit_` runs
        through fill narrower than `need`: along its path of cells, from the
        last cell the entry copper reaches through fill at least `need` wide
        to the first the exit copper reaches that way (an end the path starts
        or stops short of is the path's own end). Read within a step or two
        of the true length. None when `width` found no path of cells (the
        fill is narrower than a step), or has not been asked this pair."""
        got = self._paths.get((id(entry), id(exit_)))
        if got is None or got[0] is not entry or got[1] is not exit_:
            return None
        path = got[2]
        tau = (need / (2.0 * self.s) + 0.5) ** 2
        from_entry = self._reach(self.touching(entry, tau), set(), tau)[1]
        from_exit = self._reach(self.touching(exit_, tau), set(), tau)[1]
        last = max((k for k, c in enumerate(path) if c in from_entry), default=-1)
        first = min((k for k, c in enumerate(path) if c in from_exit and k > last), default=len(path))
        lo, hi = max(last, 0), min(first, len(path) - 1)
        total = 0.0
        for k in range(lo, hi):
            (r0, q0), (r1, q1) = divmod(path[k], self.nx), divmod(path[k + 1], self.nx)
            total += self.s * (math.sqrt(2.0) if (r0 != r1 and q0 != q1) else 1.0)
        return total


def _crossing_key(z: int, a: int, b: int) -> tuple:
    """The key a fill's crossing is measured under: the fill, then the copper
    the route enters and leaves it by, in either order."""
    return (z,) + tuple(sorted((a, b)))


def _widest_routes(nodes, near, sources, targets, measured: dict, bounds: dict, fill_widest) -> dict:
    """{target: (the widest bottleneck of any route to it from `sources`,
    the route's nodes, source first)}: the route current would take, judged
    by its narrowest point. A pad, via or track passes its own width; a fill
    or pour passes the width `_fill_on` measured between the copper a route
    enters and leaves it by (`measured`, keyed by `_crossing_key`); where
    that crossing has not been measured yet, the widest disc anywhere in the
    fill (`fill_widest(node)`) and the widest disc in it that reaches each
    of the two where that is known (`bounds`, {(fill, copper): width},
    `_Fill.widest_touching`) - so a route's bottleneck here is at least its
    true one, and equal to it once every crossing on it is measured
    (`_pairs` measures and searches again).

    A route is searched as (the node before, the node): the node before
    counts only at a fill some crossing of which from it is measured, and is
    None elsewhere, so the search grows only with what has been measured."""
    import heapq
    entries: dict = {}
    for key in measured:
        entries.setdefault(key[0], set()).update(key[1:])

    def state(prev, node):
        return (prev, node) if prev in entries.get(node, ()) else (None, node)
    best = {}
    for i in sources:
        best[(None, i)] = (nodes[i][1], None, i)
    heap = [(-v[0], n, s) for n, (s, v) in enumerate(best.items())]
    heapq.heapify(heap)
    tick = len(heap)
    while heap:
        w, _, st = heapq.heappop(heap)
        w = -w
        if w < best[st][0]:
            continue
        prev, j = st
        fill = nodes[j][0] in _FILLED
        for k in near[j]:
            if k == prev:
                continue
            cand = w
            if fill:
                got = measured.get(_crossing_key(j, prev, k)) if prev is not None else None
                if got is not None:
                    cand = min(cand, got[0])
                cand = min(cand, bounds.get((j, k), math.inf))
            if nodes[k][0] in _FILLED:
                cand = min(cand, bounds.get((k, j), math.inf), fill_widest(k))
            else:
                cand = min(cand, nodes[k][1])
            nxt = state(j, k)
            if cand > best.get(nxt, (-1.0,))[0]:
                best[nxt] = (cand, st, k)
                tick += 1
                heapq.heappush(heap, (-cand, tick, nxt))
    out = {}
    for t in targets:
        got = best.get((None, t))
        if got is None:
            continue
        path, st = [], (None, t)
        while st is not None:
            path.append(st[1])
            st = best[st][1]
        out[t] = (got[0], path[::-1])
    return out


def _neck(nodes, path: list, w: float, need_of) -> tuple:
    """The bottleneck's point, how far the route stays narrower than the
    width the current needs - the run of consecutive track nodes around the
    bottleneck narrower than `need_of(its layers)`, stopped each way by a
    pad, via, pour or a track that wide - and the bottleneck node's own
    layers (for the current-path check's per-layer weight). `path` is the
    route's nodes, source first; `w` the narrowest width of its pads, vias
    and tracks."""
    pos = next(k for k, idx in enumerate(path) if nodes[idx][0] not in _FILLED and abs(nodes[idx][1] - w) < 1e-6)
    neck_i = path[pos]
    need = need_of(nodes[neck_i][4])

    def length(idx):
        return nodes[idx][6]

    def narrow(idx):
        return nodes[idx][0] == "track" and nodes[idx][1] < need - 1e-9
    total = length(neck_i)
    k = pos - 1
    while k >= 0 and narrow(path[k]):
        total += length(path[k])
        k -= 1
    k = pos + 1
    while k < len(path) and narrow(path[k]):
        total += length(path[k])
        k += 1
    ends = nodes[neck_i][5]
    point = ((ends[0][0] + ends[1][0]) / 2.0, (ends[0][1] + ends[1][1]) / 2.0) if ends \
        else (nodes[neck_i][3].center.x, nodes[neck_i][3].center.y)
    return point, total, nodes[neck_i][4]


def _fill_on(nodes, path: list, fills: dict, measured: dict, step: float):
    """The narrowest zone fill or drawn pour along a route, each measured
    between the copper the route enters and leaves it by: (width, point,
    one step or less, the node's own layers, whether it is a pour, the fill's
    `_Fill`, the copper the route enters it by, the copper it leaves it by),
    or None when the route passes no fill that narrows it."""
    worst = None
    for k in range(1, len(path) - 1):
        z = path[k]
        if nodes[z][0] not in _FILLED:
            continue
        got = _crossing(nodes, z, path[k - 1], path[k + 1], fills, measured, step)
        if got is not None and (worst is None or got[0] < worst[0]):
            worst = got
    return worst


def _crossing(nodes, z: int, a: int, b: int, fills: dict, measured: dict, step: float):
    """Fill or pour `z` measured between the copper `a` and `b` (`_Fill.width`), cached in `measured` under
    `_crossing_key`: (width, point, one step or less, the fill's layers, whether it is a pour, its `_Fill`, a's
    polygons, b's polygons), or None where a and b touch."""
    key = _crossing_key(z, a, b)
    if key not in measured:
        if z not in fills:
            fills[z] = _Fill(nodes[z][2][0], step)
        got = fills[z].width(nodes[a][2], nodes[b][2])
        measured[key] = None if got is None else got + (nodes[z][4], nodes[z][0] == "poly", fills[z],
                                                         nodes[a][2], nodes[b][2])
    return measured[key]


@dataclass(frozen=True)
class LayerShare:
    """One layer's copper across the stretch of a load's route a current-path
    verdict judges: its width there, the factor that turns that width into
    the route layer's (the route layer's IPC-2221 need over this layer's, at
    the same current; 1 on the route's own layer), where it is narrowest,
    and whether it is the route's own copper or a parallel layer's."""
    layer: object                       # CopperLayer
    width: float
    scale: float
    point: tuple
    route: bool

    def record(self) -> dict:
        return {"layer": getattr(self.layer, "value", str(self.layer)), "width_mm": self.width,
                "scale": self.scale, "at": [round(self.point[0], 3), round(self.point[1], 3)], "route": self.route}


def _plated(node) -> bool:
    """A via or a through-hole pad: copper on more than one layer, joining them."""
    return node[0] not in _FILLED and node[0] != "track" and len(node[4]) > 1


def _stretches(nodes, path: list, fills: dict, measured: dict, step: float) -> list:
    """The route cut at its plated holes (`_plated`): for each run of its
    copper between two of them, or between one and an end of the route,
    (the path positions of the run's two ends, its layer, its width - its
    narrowest track or fill crossing -, the path position of that copper).
    Between two holes the route stays on one layer: only a hole changes it.
    A run with no copper of its own (copper that touches) is left out."""
    cut = [0] + [k for k in range(1, len(path) - 1) if _plated(nodes[path[k]])] + [len(path) - 1]
    out = []
    for p, q in zip(cut, cut[1:]):
        best = None
        for k in range(p + 1, q):
            i = path[k]
            if nodes[i][0] in _FILLED:
                got = _crossing(nodes, i, path[k - 1], path[k + 1], fills, measured, step)
                w = math.inf if got is None else got[0]
            elif nodes[i][0] == "track":
                w = nodes[i][1]
            else:
                continue
            if best is None or w < best[0]:
                best = (w, k)
        if best is not None and not math.isinf(best[0]):
            out.append((p, q, next(iter(nodes[path[best[1]]][4])), best[0], best[1]))
    return out


def _alongside(nodes, near, a: int, b: int, layer) -> list:
    """The net's fills and pours on layers other than `layer` that touch
    both plated holes `a` and `b`, on a layer both are on: copper in parallel
    with the route's own between the two holes."""
    if not (_plated(nodes[a]) and _plated(nodes[b])):
        return []
    common = (nodes[a][4] & nodes[b][4]) - {layer}
    if not common:
        return []
    at_b = set(near[b])
    return [z for z in near[a] if z in at_b and nodes[z][0] in _FILLED and nodes[z][4] & common]


def _parallel(nodes, near, path: list, fills: dict, measured: dict, step: float, need_of):
    """The route judged with its parallel layers: each stretch between two
    plated holes (`_stretches`) carries the current on its own copper and on
    every fill or pour of the net on another layer that touches both holes
    (`_alongside`), each such fill measured between the two holes as the
    route's own are (`_Fill.width`). The stretch's width is the layers'
    widths added, each scaled to the route's layer (`LayerShare.scale`), and
    the route is judged at the stretch with the least width for its need.
    (that width, the need on the stretch's layer, the stretch as
    `_stretches` gives it, the other layers' `LayerShare`s), or None when no
    stretch of the route has copper alongside it. Stretches are measured in
    the order of their own width for their need, and stop once one cannot be
    the least."""
    runs = _stretches(nodes, path, fills, measured, step)
    side = {r: _alongside(nodes, near, path[r[0]], path[r[1]], r[2]) for r in runs}
    if not any(side.values()):
        return None
    best = None
    for r in sorted(runs, key=lambda r: r[3] / need_of(frozenset([r[2]]))):
        need = need_of(frozenset([r[2]]))
        if best is not None and r[3] / need >= best[0] / best[1] - 1e-12:
            break
        a, b = path[r[0]], path[r[1]]
        width, shares = r[3], []
        for z in side[r]:
            got = _crossing(nodes, z, a, b, fills, measured, step)
            if got is None:
                continue
            scale = need / need_of(nodes[z][4])
            width += got[0] * scale
            shares.append(LayerShare(next(iter(nodes[z][4])), got[0], scale, tuple(got[1]), False))
        if best is None or width / need < best[0] / best[1]:
            best = (width, need, r, shares)
    return best


@dataclass(frozen=True)
class _Basis:
    """What a neck narrower than the need is judged by besides its width:
    its length and whether conduction to the copper at its ends carries the
    heat of its current (`_neck_credit`)."""
    length: float | None        # mm; None where the route's length there could not be measured
    credited: bool
    rise_c: float               # the neck's own peak rise above its ends
    budget_c: float             # the share of the rise the neck may use
    max_mm: float               # the longest a neck of this width passes
    width: float
    amps: float


def _neck_credit(w: float, need: float, amps: float, length, layers, copper_mm: dict, rise_c: float,
                 copper_oz: float) -> _Basis:
    """A neck narrower than `need` and `length` mm long, credited when its
    peak rise from conduction to the copper at both ends alone,
    rho I^2 L^2 / (8 k A^2) (one-dimensional conduction, uniform heat
    generation, ends held cool; no loss to board or air), stays within the
    share of `rise_c` `check.neck_end_share` leaves it. Where the length is
    unknown, or the share leaves none, nothing is credited
    (docs/superpowers/specs/2026-10-01-neck-length-and-part-keep-out-design.md)."""
    cfg = active()
    thickness_m = _layer_oz(next(iter(layers), None), copper_mm, copper_oz) * _MM_PER_OZ * 1e-3
    area = w * 1e-3 * thickness_m
    budget = (1.0 - cfg.check_neck_end_share) * rise_c
    rho, k = cfg.check_neck_resistivity, cfg.check_neck_conductivity
    longest = (area / amps) * math.sqrt(8.0 * k * budget / rho) * 1e3 if amps > 0 and budget > 0 else 0.0
    if length is None:
        return _Basis(None, False, math.inf, budget, longest, w, amps)
    rise = rho * amps * amps * (length * 1e-3) ** 2 / (8.0 * k * area * area)
    return _Basis(length, budget > 0 and rise <= budget + 1e-12, rise, budget, longest, w, amps)


def _meets(nodes, reading, need_of) -> bool:
    """Whether a route's reading in `_pairs` (width, the width of its pads,
    vias and tracks, ..., the route, its narrowest fill, whether the fill is
    its neck) is as wide as the current needs at its neck."""
    width, w, path, fill, narrows = reading[0], reading[1], reading[5], reading[6], reading[7]
    if math.isinf(width):
        return True
    layers = fill[3] if narrows else _neck(nodes, path, w, need_of)[2]
    return width >= need_of(layers) - 1e-9


def _pairs(geometry: BoardGeometry, net: str, carriers: dict, rise_c: float, copper_oz: float,
           zone_step: float = ZONE_STEP, measure_necks: bool = True):
    """The routes the load takes on `net`, carriers being {ref: amps}: for
    each two carriers, the widest route from any pad of one to any pad of the
    other, at the lesser current - what can flow between them; with one
    carrier, its widest route to any other part's pad at its own current.
    A zone fill or drawn pour on the route is measured between the copper the route
    enters and leaves it by (`_Fill.width`); its width is the route's there
    when it is narrower than the rest of the route by more than one
    `zone_step`, closer than which the grid cannot tell the two apart.
    A route narrower than its need has its neck's length measured, and the
    neck credited when it is short (`_neck_credit`), unless `measure_necks`
    is off (a caller that wants widths only).
    A route narrower than its need is judged again with its parallel
    layers (`_parallel`): where fills of the net on other layers join the
    same two plated holes as a stretch of the route, the stretch's width is
    the layers' widths added, each scaled to the route's layer.
    Returns (judged: [(width, need, amps, from, to, the fill: None when the
    route passes none, else (its width, one step or less, whether it is the
    neck, whether it is a pour), the neck's point, how far the route stays
    narrower than the need (None where not measured), the `_Basis` of a neck
    narrower than its need, else None, the `LayerShare`s that carry it, the
    route's own first)], unmeasured: [(from, to, why: a key of
    `_UNMEASURED`)] - a route through pads and vias alone, which has no
    copper width to judge - and apart: the pairs no copper joins yet)."""
    nodes, near = _net_graph(geometry, net)
    owner = {i: n[0].split(".")[0] for i, n in enumerate(nodes) if n[0] != "zone" and "." in n[0]
             and math.isinf(n[1])}
    pads = {ref: [i for i, o in owner.items() if o == ref] for ref in set(owner.values())}
    refs = sorted(carriers)
    pairs = [(a, b) for k, a in enumerate(refs) for b in refs[k + 1:]] if len(refs) > 1 else \
        [(refs[0], None)]
    fills, measured, lengths, bounds = {}, {}, {}, {}
    on_layers = set().union(*(n[4] for n in nodes)) or {None}

    def fill_widest(z):
        if z not in fills:
            fills[z] = _Fill(nodes[z][2][0], zone_step)
        levels = fills[z].levels
        return 2.0 * fills[z].radius(levels[-1]) if len(levels) else zone_step
    tries = max(1, int(active().check_route_tries))
    judged, unmeasured, apart = [], [], []
    for a, b in pairs:
        if not pads.get(a):
            apart.append((a, b))
            continue
        ends = pads.get(b, ()) if b is not None else [i for r, ii in pads.items() if r != a for i in ii]
        amps = carriers[a] if b is None else min(carriers[a], carriers[b])

        def need_of(layers):
            return _need_mm(amps, rise_c, copper_oz, geometry.copper_mm, layers)
        least = min(need_of((layer,)) for layer in on_layers)        # no route needs less than this
        # the search reads a fill as passing any width until its crossing is measured: measure the fills on
        # the routes it found and search again, until the widest-joined end's route is as wide as the search
        # read it, or meets its need, or no route is left that could, or nothing new was measured
        # (`check.route_tries` searches at most)
        pick = None
        for _ in range(tries):
            before = len(measured)
            found = _widest_routes(nodes, near, pads[a], ends, measured, bounds, fill_widest)
            reach = []
            # the ends widest as the search reads them first: an end it reads no wider than one already
            # measured cannot be the widest-joined, and is left unmeasured
            for i, (opt, path) in sorted(found.items(), key=lambda kv: -kv[1][0]):
                if reach and max(r[0] for r in reach) >= opt - 1e-9:
                    break
                w = min((nodes[k][1] for k in path if nodes[k][0] not in _FILLED), default=math.inf)
                zoned = any(nodes[k][0] in _FILLED for k in path)
                fill = _fill_on(nodes, path, fills, measured, zone_step) if zoned else None
                narrows = fill is not None and fill[0] < w - zone_step
                reach.append((fill[0] if narrows else w, w, nodes[i][0], nodes[path[0]][0], zoned, path, fill,
                              narrows))
            if not reach:
                break
            got = max(reach, key=lambda r: r[0])                       # the widest-joined end
            if pick is None or got[0] > pick[0]:
                pick = got
            widest = max(v for v, _ in found.values())
            if len(measured) == before or pick[0] >= widest - 1e-9 or _meets(nodes, pick, need_of) \
                    or widest < least - 1e-9:
                break
            # no route in or out of a fill by copper it was just crossed from is wider than the widest
            # disc that reaches that copper: what keeps the next search off the other ways to that copper
            for key in list(measured)[before:]:
                for x in key[1:]:
                    if (key[0], x) not in bounds:
                        bounds[(key[0], x)] = fills[key[0]].widest_touching(nodes[x][2]) or math.inf
        if pick is None:
            apart.append((a, b))
            continue
        width, w, to, start, zoned, path, fill, narrows = pick
        if math.isinf(width):
            unmeasured.append((start, to, "pads_vias_fill" if zoned else "pads_vias"))
            continue
        if narrows:
            need = need_of(fill[3])
            if width < need - 1e-9:
                par = _parallel(nodes, near, path, fills, measured, zone_step, need_of)
                if par is not None:
                    judged.append(_judged_parallel(nodes, path, par, amps, start, to, need_of, measured,
                                                   measure_necks, lengths, geometry.copper_mm, rise_c, copper_oz))
                    continue
            length, basis = None, None
            if measure_necks and width < need - 1e-9:
                key = (id(fill[5]), id(fill[6]), id(fill[7]), round(need, 6))
                if key not in lengths:
                    lengths[key] = fill[5].neck_length(fill[6], fill[7], need)
                length = lengths[key]
                basis = _neck_credit(width, need, amps, length, fill[3], geometry.copper_mm, rise_c, copper_oz)
            judged.append((width, need, amps, start, to, (fill[0], fill[2], True, fill[4]), fill[1], length, basis,
                           (LayerShare(next(iter(fill[3])), width, 1.0, tuple(fill[1]), True),)))
            continue
        point, length, neck_layers = _neck(nodes, path, w, need_of)
        need = need_of(neck_layers)
        if w < need - 1e-9:
            par = _parallel(nodes, near, path, fills, measured, zone_step, need_of)
            if par is not None:
                judged.append(_judged_parallel(nodes, path, par, amps, start, to, need_of, measured,
                                               measure_necks, lengths, geometry.copper_mm, rise_c, copper_oz))
                continue
        basis = None
        if measure_necks and w < need - 1e-9:
            basis = _neck_credit(w, need, amps, length, neck_layers, geometry.copper_mm, rise_c, copper_oz)
        judged.append((w, need, amps, start, to, None if fill is None else (fill[0], fill[2], False, fill[4]), point,
                       length, basis, (LayerShare(next(iter(neck_layers)), w, 1.0, tuple(point), True),)))
    return judged, unmeasured, apart


def _judged_parallel(nodes, path: list, par, amps: float, start: str, to: str, need_of, measured: dict,
                     measure_necks: bool, lengths: dict, copper_mm: dict, rise_c: float, copper_oz: float) -> tuple:
    """`_pairs`'s reading of a route judged with its parallel layers
    (`_parallel`): the stretch's added width against the need on its layer.
    Its neck is the route's own narrowest copper on the stretch, and its
    length the run where the route's own copper is narrower than that need
    alone; a neck credited as short (`_neck_credit`) is credited on that
    length at the added width."""
    width, need, (p, q, layer, own, k), shares = par
    i = path[k]
    layers = frozenset([layer])
    length, basis = None, None
    if nodes[i][0] in _FILLED:
        got = measured[_crossing_key(i, path[k - 1], path[k + 1])]
        fill, point = (got[0], got[2], True, got[4]), tuple(got[1])
        if measure_necks and width < need - 1e-9:
            key = (id(got[5]), id(got[6]), id(got[7]), round(need, 6))
            if key not in lengths:
                lengths[key] = got[5].neck_length(got[6], got[7], need)
            length = lengths[key]
    else:
        fill = None
        point, length, _ = _neck(nodes, path[p:q + 1], own, need_of)
    if measure_necks and width < need - 1e-9:
        basis = _neck_credit(width, need, amps, length, layers, copper_mm, rise_c, copper_oz)
    return (width, need, amps, start, to, fill, point, length, basis,
            (LayerShare(layer, own, 1.0, tuple(point), True),) + tuple(shares))


def carriers_of(geometry: BoardGeometry) -> dict[str, dict[str, float]]:
    """The parts that carry current on each net, {net: {ref: amps}}, from their
    `Pm.I` facts."""
    f = facts(geometry)
    carriers: dict[str, dict] = {}
    for fp in geometry.footprints:
        fact = f[fp.ref]
        for p in fp.pads:
            amps = fact.current_a if fact.currents is None else fact.currents.get(p.net.lower())
            if amps is not None and amps > 0:          # a net given no current, or 0, is not one it carries
                on = carriers.setdefault(p.net, {})
                on[fp.ref] = max(on.get(fp.ref, 0.0), amps)
    return carriers


@dataclass(frozen=True)
class PourReading:
    """What `current-path` reads on a pour joining carriers: the width of its
    narrowest route, the width the current needs there, and where."""
    width: float
    need: float
    amps: float
    start: str
    to: str
    point: tuple

    @property
    def ok(self) -> bool:
        return self.width >= self.need


def pour_current(net: str, layer, pads, vias, copper, carriers: dict, copper_mm: dict, rise_c: float,
                 copper_oz: float, zone_step: float):
    """`current-path`'s reading of a drawn pour as the plan holds it, by the
    check's own route search (`_pairs`): `pads` are (ref, number, outline) of
    the pour's members, `vias` the outlines of its via members, `copper` the
    outlines of the pour (one polygon each), `carriers` {ref: amps} of the
    parts carrying current on `net`. The worst route, as a PourReading, or
    None where no route is narrowed by the pour (its pads touch). A pour
    that joins no two carriers reads width 0."""
    layers = frozenset([layer])
    stand_in = types.SimpleNamespace(
        copper_mm=copper_mm,
        footprints=[types.SimpleNamespace(ref=ref, pads=[types.SimpleNamespace(
            net=net, number=number, outlines=(outline,), box=Box.of_points(outline), layers=layers)])
            for ref, number, outline in pads],
        copper=[CopperItem("via", net, layers, (o,), Box.of_points(o)) for o in vias]
        + [CopperItem("poly", net, layers, (o,), Box.of_points(o)) for o in copper])
    judged, _, apart = _pairs(stand_in, net, carriers, rise_c, copper_oz, zone_step, measure_necks=False)
    if not judged:
        return PourReading(0.0, 0.0, 0.0, "", "", (0.0, 0.0)) if apart else None
    w, need, amps, a, b, _, point = min(judged, key=lambda j: j[0] / j[1])[:7]
    return PourReading(w, need, amps, a, b, tuple(point))


def current_paths(geometry: BoardGeometry, rise_c: float = TRACK_RISE_C, copper_oz: float = COPPER_OZ,
                  zone_step: float = ZONE_STEP) -> list[Verdict]:
    carriers = carriers_of(geometry)
    out = []
    for net, on in sorted(carriers.items()):
        if len(on) == 1:
            # one carrier cannot say where its load goes: the widest-joined other pad is as
            # often a capacitor carrying ripple as the load, so no route is judged at its current
            (ref, amps), = on.items()
            out.append(Verdict("current-path", net, 0.0, "mm", ipc2221_width_mm(amps, rise_c, copper_oz), None,
                               "not judged (%g A): only %s carries current on %s, so where its load goes is "
                               "not known; give the part that takes the load its Pm.I" % (amps, ref, net)))
            continue
        judged, unmeasured, apart = _pairs(geometry, net, on, rise_c, copper_oz, zone_step)
        said = _unjoined_text(apart, unmeasured, net)
        if not judged:
            amps = max(on.values())
            out.append(Verdict("current-path", net, 0.0, "mm", ipc2221_width_mm(amps, rise_c, copper_oz), None,
                               "not judged (%g A): %s" % (amps, "; ".join(said))))
            continue
        def passes(j):
            return j[0] >= j[1] or (j[8] is not None and j[8].credited)
        # the worst route: one that fails, then the narrowest against its need
        worst = min(judged, key=lambda j: (passes(j), j[0] / j[1]))
        w, need, amps, a, b, fill, point, length, basis, shares = worst
        facts = {"net": net, "from": a, "to": b, "amps": amps, "rise_c": rise_c, "copper_oz": copper_oz, "zone_step": zone_step,
                 "width_mm": w, "need_mm": need, "neck": [point[0], point[1]],
                 "fill": None if fill is None else {"width_mm": fill[0], "one_step": bool(fill[1]),
                                                    "is_neck": bool(fill[2]), "pour": bool(fill[3])},
                 "layers": [s.record() for s in shares],
                 "basis": None if basis is None else {k: None if isinstance(v, float) and math.isinf(v) else v
                                                      for k, v in dataclasses.asdict(basis).items()},
                 "apart": [[x, y] for x, y in apart], "unmeasured": [[x, y, why] for x, y, why in unmeasured]}
        out.append(Verdict("current-path", net, w, "mm", need, passes(worst), current_path_text(facts), facts=facts))
    return out


_UNMEASURED = {"pads_vias": "joined only through pads and vias",
               "pads_vias_fill": "joined only through pads, vias and a zone fill or pour where their copper meets"}
"""Why `_pairs` could not measure a route, by the reason it gives."""


def _unjoined_text(apart, unmeasured, net: str) -> list:
    """The sentences naming the carriers no copper joins yet and the routes with no copper width to judge."""
    said = ["no copper joins %s %s on %s yet" % (a, "and %s" % b if b else "to another part", net) for a, b in apart]
    return said + ["%s to %s: %s" % (a, b, _UNMEASURED[why]) for a, b, why in unmeasured]


def current_path_text(facts: dict) -> str:
    """A judged current-path verdict's note, rendered from its facts."""
    f = facts
    note = "narrowest point of the load's widest route, %s to %s, for %g A at %g C rise on %g oz" % (
        f["from"], f["to"], f["amps"], f["rise_c"], f["copper_oz"])
    fill, (x, y) = f["fill"], f["neck"]
    if fill is not None and fill["is_neck"]:
        note += "; neck at (%.2f, %.2f), the %s's narrowest point" % (x, y, "pour" if fill["pour"] else "fill")
        if fill["one_step"]:
            note += " (one %g mm step or less wide there, read as one step)" % f["zone_step"]
    else:
        note += "; neck at (%.2f, %.2f)" % (x, y)
        if fill is not None:
            note += "; through a %s %.2f mm wide at its narrowest" % ("pour" if fill["pour"] else "zone fill",
                                                                      fill["width_mm"])
    if len(f["layers"]) > 1:
        route = f["layers"][0]
        note += "; %.2f mm as %s copper, on %s in parallel: %s" % (
            f["width_mm"], route["layer"], ", ".join(d["layer"] for d in f["layers"]),
            ", ".join("%s %.2f mm%s" % (d["layer"], d["width_mm"], "" if abs(d["scale"] - 1.0) < 1e-9
                                         else " (x%.2f)" % d["scale"]) for d in f["layers"]))
    if f["basis"] is not None:
        note += "; " + _basis_text(_Basis(**f["basis"]), f["rise_c"])
    said = _unjoined_text(f["apart"], f["unmeasured"], f["net"])
    return note + ("; " + "; ".join(said) if said else "")


def _basis_text(basis: _Basis, rise_c: float) -> str:
    """The sentence naming a neck's width, length and what its verdict rests on."""
    if basis.length is None:
        return "a neck %.2f mm wide, its length not measured (the fill is under one step wide there), so not credited" % basis.width
    head = "a %.2f mm long neck at %.2f mm" % (basis.length, basis.width)
    if basis.budget_c <= 0:
        return "%s, not credited as short: check.neck_end_share leaves it no share of the %g C rise" % (head, rise_c)
    return ("%s, %s: %.2g C of its %.2g C share of the %g C rise by conduction to the copper at each end "
            "(a %.2f mm wide neck passes up to %.2f mm at %g A)" % (
                head, "credited as short" if basis.credited else "too long", basis.rise_c, basis.budget_c, rise_c,
                basis.width, basis.max_mm, basis.amps))


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


# -------------------------------------------------------------- exposure

def _pad_centre(fp: Footprint, number: str):
    return next(p.box.center for p in fp.pads if p.number == number)


def exposures(geometry: BoardGeometry) -> list[Verdict]:
    """Each sensitive part's modelled value per kind at its final place
    against its `Pm.Limit`, naming the sources that contribute (`Pm.Emits`,
    value(r) = v_ref * (r_ref / r) ** falloff; sources of a kind add). A
    part is not exposed to itself. A part whose annotations do not read is
    reported once, not judged."""
    try:
        ann = _exposure.read(geometry)
    except ValueError as e:
        return [Verdict("exposure", "annotations", 0.0, "", None, None, "not judged: %s" % e)]
    out = []
    for ref, sens in sorted(ann.sensitives.items()):
        fp = geometry.footprint(ref)
        at = _pad_centre(fp, sens.senses) if sens.senses is not None else fp.body_box.center
        for kind, limit, unit in sens.limits:
            total, parts = 0.0, []
            for src_ref, src in sorted(ann.sources.items()):
                if src_ref == ref:
                    continue
                sfp = geometry.footprint(src_ref)
                if src.at is not None and src.at[0] == "pad":
                    point = _pad_centre(sfp, src.at[1])
                else:
                    x, y = (src.at[1], src.at[2]) if src.at is not None else (0.0, 0.0)
                    point = _exposure.local_to_board(sfp.location, sfp.rotation, sfp.face, x, y)
                r = point.distance(at)
                value = sum(e.at(r) for e in src.emissions if e.kind == kind)
                if any(e.kind == kind for e in src.emissions):
                    total += value
                    parts.append((value, src_ref, r))
            if parts:
                said = ", ".join("%s %.3g %s at %.1f mm" % (n, v, unit, r) for v, n, r in sorted(parts, reverse=True))
                note = "%s at %s: %s" % (kind, "pad %s" % sens.senses if sens.senses is not None else "the body centre", said)
            else:
                note = "no source of %s on the board" % kind
            out.append(Verdict("exposure", "%s %s" % (ref, kind), total, unit, limit, total <= limit + 1e-9, note))
    return out


# ------------------------------------------------------------------- all

def run_checks(geometry: BoardGeometry, ambient_c: float = AMBIENT_C, keep_out_mm: float = KEEP_OUT_MM,
               rise_c: float = TRACK_RISE_C, copper_oz: float = COPPER_OZ,
               limits: dict[str, float] | None = None, zone_step: float = ZONE_STEP) -> list[Verdict]:
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
    out += current_paths(geometry, rise_c, copper_oz, zone_step)
    out += heat(geometry, ambient_c)
    out += exposures(geometry)
    return out


def _item_facts(item: _NamedCopper, point: tuple) -> dict:
    return {"kind": item.kind, "owner": item.owner, "number": item.number, "net": item.net,
            "at": [round(point[0], 3), round(point[1], 3)]}


def keep_out_findings(geometry: BoardGeometry, limit_mm: float = KEEP_OUT_MM) -> list:
    """`keep_out_notices` as `keep_out.cross_layer` findings (notice severity), for a run to record."""
    from .findings import Finding, FindingCause as C
    return [Finding(C.KEEP_OUT_CROSS_LAYER,
                    {"net": n.net, "distance_mm": round(n.distance_mm, 4), "limit_mm": n.limit_mm,
                     "layers": [l.value for l in n.layers],
                     "away": _item_facts(n.away, n.points[0]), "pads": _item_facts(n.pads, n.points[1])})
            for n in keep_out_notices(geometry, limit_mm)]


def kwargs_from(settings) -> dict:
    """The arguments `run_checks` takes, from the resolved settings. One home,
    so `placemat check` and `placemat run` judge a board by the same numbers."""
    return {"ambient_c": settings.check_ambient_c, "keep_out_mm": settings.check_keep_out_mm,
            "rise_c": settings.check_rise_c, "limits": dict(settings.check_limits),
            "zone_step": settings.check_zone_step}


def record(rec, verdicts, outcomes=()) -> list:
    """Put a board's verdicts on its run record and return the lines to print.
    `verdicts` and `outcomes` are what `judge` returned.

    A verdict with `ok` None was not judged - no limit was set, or a fact the
    check needs is missing - and it is counted as such rather than as a pass:
    a check that passes because a footprint lacks `Pm.Pd` is worse than none.
    An accepted verdict is counted as accepted, not as failed."""
    rec.verdicts = [{**v.__dict__, "severity": v.severity} for v in verdicts]
    rec.acceptances = [o.record() for o in outcomes]
    accepted = [v for v in verdicts if v.accepted]
    failed = [v for v in verdicts if v.ok is False and not v.accepted]
    unjudged = [v for v in verdicts if v.ok is None]
    rec.metrics["checks_failed"] = len(failed)
    rec.metrics["checks_accepted"] = len(accepted)
    rec.metrics["checks_unjudged"] = len(unjudged)
    held = [o.line() for o in outcomes]
    if not verdicts:
        return ["no Pm.* facts on this board: no design checks ran"] + held
    head = "%d check(s): %d failed, %s%d passed, %d not judged" % (
        len(verdicts), len(failed), "%d accepted, " % len(accepted) if accepted else "",
        len(verdicts) - len(failed) - len(accepted) - len(unjudged), len(unjudged))
    return [head] + [v.line() for v in failed] + held
