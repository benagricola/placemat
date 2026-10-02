"""Escape lanes: a pin row's routes out, laid out when the part is placed
(`Board.escape`, docs/superpowers/specs/2026-10-01-escape-lanes-design.md).

`lay_out` turns the placed (or candidate) pads of one row and an escape's
declaration into a `Layout`: for each pin its riser, its lane and its via.
It judges nothing about the rest of the board itself: what stands in a
lane's way is asked of an `env` (layout.py's `_LaneEnv`), so the same
function lays an escape out at a placed part and at every candidate of a
search. The handles a script holds (`Escape`, `Lane`, `LanePoint`) and the
declaration (`EscapeDecl`) are here too.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .copper import Via, chamfer_cuts, polyline_tracks
from .geometry import gap_texts, point_in_polygon, point_segment_distance
from .values import Box, Edge, Location, Part

_DIR = {Edge.NORTH: (0.0, -1.0), Edge.SOUTH: (0.0, 1.0), Edge.EAST: (1.0, 0.0), Edge.WEST: (-1.0, 0.0)}
_TOL = 1e-9             # the clearance checks' own tolerance (occupancy._conflict)
_SQ2 = math.sqrt(2.0)


class EscapeError(ValueError):
    """An escape that cannot be laid out whatever stands round it: a script
    error, named as such."""


# ------------------------------------------------------------------ handles
@dataclass(frozen=True)
class Escape:
    """What `board.escape()` returns: `esc[pin]` is that pin's `Lane`, and the
    escape itself is a `Beside` item (its risers, lanes and vias together)."""
    board: object = field(compare=False, repr=False, metadata={"reuse": False})
    index: int
    part: Part

    def __getitem__(self, pin) -> "Lane":
        return Lane(self.board, self.index, self.part, self.board._escape_pin(self, pin))


@dataclass(frozen=True)
class Lane:
    """One pin's route out: a track point (the first of a track, where it
    stands for the riser, the lane and the via), an `align=` target of
    `Beside`, and through `.via` and `.end` the references to the lane's
    via and its end."""
    board: object = field(compare=False, repr=False, metadata={"reuse": False})
    index: int
    part: Part
    number: str

    @property
    def via(self):
        """The lane's via, as `board.via()` returns one: a track point and a
        `Past` item, and a `Beside` item for the part standing off it."""
        return self.board._lane_via(self)

    @property
    def end(self) -> "LanePoint":
        """Where the lane ends (its via, or the end of its track): a point
        reference, as `X()`/`Y()` take."""
        return LanePoint(self, "end")


@dataclass(frozen=True)
class LanePoint:
    """A point of a lane: where its riser meets the lane ("corner") or where
    it ends ("end"). Resolved once the lane's part is placed."""
    lane: Lane
    which: str


@dataclass
class EscapeDecl:
    """One `board.escape()` declaration. What follows `why` is state of the
    run, kept out of the declaration's digest."""
    index: int
    part: Part
    ref: str
    pins: tuple             # pad numbers, as listed
    turn: object            # None, an Edge across the row, or a Corner
    vias: frozenset         # pad numbers whose lane ends in a via
    depth: float | None
    run: float | None
    widths: tuple           # ((pad number, width), ...)
    pairs: tuple            # ((pad number, pad number), ...)
    chamfer: float          # the cut at a lane's corners: the lanes are laid, reserved and (by default) drawn with it
    via_size: float         # the size and drill of the lanes' vias
    via_drill: float
    why: str
    via_intents: dict = field(default_factory=dict, compare=False, metadata={"reuse": False})
    chamfers: dict = field(default_factory=dict)    # pad number -> the chamfer= of the track that begins with its lane
    lands: tuple = ()       # ((pad number, 1-based land), ...): the land in the row, of a pin drawn as several
    drawn: set = field(default_factory=set, compare=False, metadata={"reuse": False})
    used_vias: set = field(default_factory=set, compare=False, metadata={"reuse": False})

    @property
    def key(self) -> str:
        return "escape %s" % self.ref

    def width_of(self, number: str):
        return dict(self.widths).get(number)

    def chamfer_of(self, number: str) -> float:
        """The cut at a lane's corner as it will be drawn: its track's own chamfer= where one
        says it, else the escape's."""
        return self.chamfers.get(number, self.chamfer)


# ------------------------------------------------------------------ the layout
@dataclass
class LaneGeom:
    number: str
    net: str
    width: float
    order: int
    points: tuple           # pad centre, the corner (a turned lane), the end
    tracks: tuple           # the Track ops, chamfered as a track() draws them
    via: Via | None
    line: tuple | None      # ("x" | "y", coordinate): the line a part may stand its pad on; None for a 45
    blocked: list = field(default_factory=list)     # what stands in its way: a sentence each

    @property
    def end(self) -> Location:
        return self.points[-1]

    @property
    def corner(self) -> Location:
        return self.points[1] if len(self.points) > 2 else self.points[-1]


@dataclass
class Layout:
    lanes: dict             # pad number -> LaneGeom
    order: list             # pad numbers, innermost lane first (as listed without a turn)

    def blocked(self) -> list:
        return [(n, self.lanes[n]) for n in self.order if self.lanes[n].blocked]

    def box(self) -> Box:
        boxes = []
        for lane in self.lanes.values():
            boxes += [t.box for t in lane.tracks]
            if lane.via is not None:
                boxes.append(lane.via.box)
        return Box.union(boxes)

    def ops(self) -> list:
        return [op for n in self.order for op in (*self.lanes[n].tracks, *((self.lanes[n].via,) if self.lanes[n].via else ()))]


def _away(v: float, sign: float) -> float:
    """`v` to 1e-6 mm, rounded away from the row (up when `sign` is positive):
    rounding never eats a clearance. Float noise under 1e-9 mm is not rounded up."""
    q = v * 1e6
    return (math.ceil(q - 1e-3) if sign > 0 else math.floor(q + 1e-3)) / 1e6


def _point_poly_distance(p, poly) -> float:
    if point_in_polygon(p, poly):
        return 0.0
    return min(point_segment_distance(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


class _Lane:
    """One lane while it is being laid out."""

    def __init__(self, number, net, width, via, centre, s):
        self.number, self.net, self.width, self.via = number, net, width, via      # via: (size, drill) or None
        self.centre, self.s = centre, s
        self.copper = via[0] if via else width
        self.h = 0.0                    # the lane's offset past the tips
        self.corner = None
        self.a = 0.0                    # how far along its lane it ends (past its start)
        self.via_at = None
        self.end_at = None
        self.blocked_why = None


def turn_direction(turn, u: tuple, key: str) -> tuple:
    """((tx, ty), diagonal): the unit vector along the row toward the turn side, and whether
    the lanes run at 45, for a row whose way out is the unit vector `u`. A turn along the
    way out, or a corner that is not on it, is an EscapeError."""
    ux, uy = u
    way = {(0.0, -1.0): "north", (0.0, 1.0): "south", (1.0, 0.0): "east", (-1.0, 0.0): "west"}[(float(ux), float(uy))]
    if turn is None:
        return (-uy, ux), False
    if isinstance(turn, Edge):
        tx, ty = _DIR[turn]
        if abs(tx * ux + ty * uy) > 0.5:
            raise EscapeError("%s: turn=%s runs along the row's axis (the way out is %s); a row turns across "
                              "it" % (key, turn.name, way))
        return (tx, ty), False
    sx, sy = turn.signs
    out = sx * ux + sy * uy
    if out <= 0:
        raise EscapeError("%s: turn=%s turns back into the row; its corner must be on the way out (%s)" % (
            key, turn.value, way))
    return (sx - out * ux, sy - out * uy), True


_WAYS = {(0.0, -1.0): "north", (0.0, 1.0): "south", (1.0, 0.0): "east", (-1.0, 0.0): "west"}


def _way_name(way: tuple) -> str:
    return _WAYS.get(way, "(%.2f, %.2f)" % way)


def row_way(key: str, numbers: list, boxes: dict, way_of) -> tuple:
    """(the row's way out, {pad number: indices of its lands in the row}) for the pins `numbers` of
    a part whose pads' lands are `boxes` (pad number -> the box of each land); `way_of(box)` is the
    way out of one land. A pin drawn as several lands (a QFN's corner pin, one land in each of two
    rows) leads out along each; the row is the way out the pins have in common, and such a pin
    stands in it by the land that leads out that way. The pins' ways must have exactly one in
    common, else an EscapeError names the pins and the ways."""
    multi = [n for n, bs in boxes.items() if len(bs) > 1]
    ways = {n: [way_of(b) for b in boxes[n]] for n in dict.fromkeys([*numbers, *multi])}

    def said(n):
        return " or ".join(dict.fromkeys(_way_name(w) for w in ways[n]))
    common = set(ways[numbers[0]])
    for n in numbers[1:]:
        common &= set(ways[n])
    if not common:
        first = numbers[0]
        other = next(n for n in numbers[1:] if not set(ways[n]) & set(ways[first]))
        raise EscapeError("%s: pin %s is not on pin %s's row as the part stands (pin %s leads out %s, pin %s %s); an "
                          "escape is one row's" % (key, other, first, first, said(first), other, said(other)))
    if len(common) > 1:
        raise EscapeError("%s: the pins %s lead out %s alike (a pin drawn as several lands leads out along each); "
                          "name a pin of the row whose way out is one only" % (
                              key, ", ".join(numbers), " and ".join(sorted(_way_name(w) for w in common))))
    (axis,) = common
    return axis, {n: [i for i, w in enumerate(ways[n]) if w == axis] or list(range(len(boxes[n]))) for n in multi}


class Layouter:
    """The arithmetic of one escape. `pads` maps each pad number of the part
    to its shapes; `axis` is the row's outward unit vector; `env` answers
    what the rest of the board says (see layout.py's `_LaneEnv`)."""

    def __init__(self, decl: EscapeDecl, pads: dict, axis: tuple, env, lands: dict | None = None):
        self.decl, self.pads, self.env = decl, pads, env
        self.lands = lands or {}        # pad number -> indices of its lands in the row, for pads drawn as several
        ux, uy = axis
        if not (abs(abs(ux) - 1.0) < 1e-6 and abs(uy) < 1e-6 or abs(abs(uy) - 1.0) < 1e-6 and abs(ux) < 1e-6):
            raise EscapeError("%s: the row's way out is (%.3f, %.3f), not along a board axis; an escape's lanes "
                              "run along them, so turn the part to a quarter turn" % (decl.key, ux, uy))
        self.u = (float(round(ux)), float(round(uy)))
        self.t, self.diagonal = turn_direction(decl.turn, self.u, decl.key)

    # ---- the frame: s along the row toward the turn side, h out along the way out
    def s_of(self, p) -> float:
        return p[0] * self.t[0] + p[1] * self.t[1]

    def h_of(self, p) -> float:
        return p[0] * self.u[0] + p[1] * self.u[1]

    def at(self, s: float, h: float) -> Location:
        return Location(s * self.t[0] + h * self.u[0], s * self.t[1] + h * self.u[1])

    def _snap(self, p: Location) -> Location:
        """The point to 1e-6 mm, the way out rounded outward and the turn side along."""
        return Location(_away(p.x, self.u[0] + self.t[0]), _away(p.y, self.u[1] + self.t[1]))

    def _row_lands(self, number: str) -> list:
        """The shapes of a pad that stand in the row: all its lands, or of a pad drawn as several
        the ones whose way out is the row's."""
        return [self.pads[number][i] for i in self.lands[number]] if number in self.lands else self.pads[number]

    def _extent(self, number: str) -> tuple:
        pts = [p for sh in self._row_lands(number) for p in sh.poly]
        hs, ss = [self.h_of(p) for p in pts], [self.s_of(p) for p in pts]
        return min(hs), max(hs), min(ss), max(ss)

    def _centre(self, number: str) -> Location:
        return Box.union([sh.box for sh in self._row_lands(number)]).center

    # ---- the whole layout
    def lay_out(self) -> Layout:
        d, env = self.decl, self.env
        first = self._extent(d.pins[0])
        row = []
        for n in self.pads:
            lo, hi, _, _ = self._extent(n)
            overlap = min(hi, first[1]) - max(lo, first[0])
            if overlap > 0.5 * min(hi - lo, first[1] - first[0]) - 1e-9:
                row.append(n)
        for n in d.pins:
            if n not in row:
                raise EscapeError("%s: pin %s is not on the row of pin %s (a row's pads stand level, across the "
                                  "way out); an escape is one row's" % (d.key, n, d.pins[0]))
        self.row = row
        self.tips = max(self._extent(n)[1] for n in row)
        self.row_end = max(self._extent(n)[3] for n in row)
        nets = {n: self.pads[n][0].net for n in d.pins}
        lanes = {}
        for n in d.pins:
            net = nets[n]
            width = d.width_of(n) or env.width(net)
            via = (d.via_size, d.via_drill) if n in d.vias else None
            c = self._centre(n)
            lanes[n] = _Lane(n, net, width, via, c, self.s_of((c.x, c.y)))
        self.lanes = lanes
        self.order = sorted(d.pins, key=lambda n: -lanes[n].s) if d.turn is not None else list(d.pins)
        paired = {}
        for a, b in d.pairs:
            paired[a], paired[b] = b, a
            if d.turn is None:
                raise EscapeError("%s: pairs= runs two lanes together, and without turn= there are none" % d.key)
            if abs(self.order.index(a) - self.order.index(b)) != 1:
                raise EscapeError("%s: pins %s and %s are not neighbours in the lane order, so their lanes cannot "
                                  "run together" % (d.key, a, b))
        self.paired = paired
        self._offsets()
        self._place_vias()
        self._ends()
        return self._finish()

    def _tip_clearance(self, lane: _Lane) -> float:
        others = [self.pads[n][0] for n in self.row if self.pads[n][0].net != lane.net]
        return max([self.env.clearance(lane.net, sh.net, sh.owner) for sh in others] or [self.env.clearance(lane.net, "")])

    def _step(self, inner: _Lane, outer: _Lane) -> float:
        """From an inner lane's centreline to the next one out: half each one's copper
        plus the clearance, a lane with a via counting as its via where the other passes it."""
        gap = (self.env.pair_gap(inner.net) if self.paired.get(inner.number) == outer.number
               else self.env.clearance(inner.net, outer.net))
        need = inner.width / 2.0 + outer.width / 2.0
        if inner.via:
            need = max(need, inner.via[0] / 2.0 + outer.width / 2.0)
        if outer.via:
            need = max(need, inner.width / 2.0 + outer.via[0] / 2.0)
        return need + gap

    def _lane_step(self, lane: _Lane) -> float:
        """One step at a lane: from its inner neighbour, else to its outer one, else its own
        copper and the clearance past the tips."""
        k = self.order.index(lane.number)
        if k > 0:
            return self._step(self.lanes[self.order[k - 1]], lane)
        if len(self.order) > 1:
            return self._step(lane, self.lanes[self.order[1]])
        return lane.copper + self._tip_clearance(lane)

    def _offsets(self) -> None:
        d = self.decl
        ordered = [self.lanes[n] for n in self.order]
        if d.turn is None:
            return
        prev = None
        for lane in ordered:
            if prev is None:
                lane.h = d.depth if d.depth is not None else lane.copper + self._tip_clearance(lane)
            else:
                step = self._step(prev, lane)
                lane.h = prev.h + (step * _SQ2 - (prev.s - lane.s) if self.diagonal else step)
            # each lane is rounded outward from the one inside it as it stands, never short of its step
            lane.corner = self._snap_out(self.at(lane.s, self.tips + lane.h))
            lane.h = self.h_of((lane.corner.x, lane.corner.y)) - self.tips
            prev = lane

    def _snap_out(self, p: Location) -> Location:
        """A lane's corner: its coordinate along the way out rounded outward, the other kept."""
        if self.u[0]:
            return Location(_away(p.x, self.u[0]), round(p.y, 6))
        return Location(round(p.x, 6), _away(p.y, self.u[1]))

    # ---- the lane's own line
    def _direction(self) -> tuple:
        if self.decl.turn is None:
            return self.u
        if self.diagonal:
            return ((self.t[0] + self.u[0]) / _SQ2, (self.t[1] + self.u[1]) / _SQ2)
        return self.t

    def _end_at(self, lane: _Lane, a: float) -> Location:
        """The point `a` along the lane, rounded to the nanometre the way the lane runs; a lane
        at 45 moves a whole number of nanometres on both axes, so its leg stays a 45."""
        if self.decl.turn is None:
            return self._snap(self.at(lane.s, self.tips + a))
        dx, dy = self._direction()
        if self.diagonal:
            m = math.ceil(a / _SQ2 * 1e6 - 1e-3) / 1e6
            return Location(round(lane.corner.x + math.copysign(m, dx), 6), round(lane.corner.y + math.copysign(m, dy), 6))
        return self._snap(Location(lane.corner.x + a * dx, lane.corner.y + a * dy))

    def _a_min(self, lane: _Lane) -> float:
        """How far along its lane its first via may stand: level with the row's
        turn-side end; without a turn, the declared depth past the tips."""
        if self.decl.turn is None:
            return self.decl.depth or 0.0
        return max(0.0, (self.row_end - lane.s) * (_SQ2 if self.diagonal else 1.0))

    def _segments(self, lane: _Lane, a: float | None = None) -> list:
        """The lane's copper as it stands: the riser, and the lane out to `a`, chamfered as
        drawn. A lane whose via is not placed yet (`a` None) runs as far as a via is searched,
        and its corner is judged both ways: square, which comes nearest what lies outside the
        turn, and cut at the lane's chamfer, whose 45 runs across the inside of the turn, nearest
        what lies there (an inner lane's via). Where its via ends up the lane is cut no deeper
        than that (a short lane cuts less), so neither comes nearer than it is judged."""
        reach = self._a_min(lane) + self.env.reach if a is None else a
        pts = [lane.centre] + ([lane.corner] if self.decl.turn is not None else []) + [self._end_at(lane, reach)]
        chamfer = self.decl.chamfer_of(lane.number)
        cuts = [chamfer_cuts(pts, chamfer)[0]]
        if a is None and chamfer > 0:
            cuts.append(chamfer_cuts(pts, 0.0)[0])
        return [((p.x, p.y), (q.x, q.y)) for cut in cuts for p, q in zip(cut, cut[1:])]

    # ---- the vias
    def _via_why(self, lane: _Lane, q: Location, others: bool) -> str | None:
        size, drill = lane.via
        qp = (q.x, q.y)
        why = self._pads_why(lane, q)
        if why is not None:
            return why
        for other in self.lanes.values():
            if other is lane or other.net == lane.net:
                continue
            need = self.env.clearance(lane.net, other.net)
            segs = self._segments(other, other.a if other.via_at is not None else None)
            gap = min(point_segment_distance(qp, a, b) for a, b in segs) - other.width / 2.0 - size / 2.0
            if gap < need - _TOL:
                return "the lane of pin %s, %s mm off (needs %s)" % ((other.number,) + gap_texts(gap, need, 3))
            if other.via_at is not None:
                ov = other.via_at
                dist = math.hypot(q.x - ov.x, q.y - ov.y)
                if dist - (size + other.via[0]) / 2.0 < need - _TOL:
                    return "the via of pin %s, %s mm off (needs %s)" % (
                        (other.number,) + gap_texts(dist - (size + other.via[0]) / 2.0, need, 3))
        for other in self.lanes.values():
            if other is lane or other.via_at is None:
                continue
            ov = other.via_at
            hole = math.hypot(q.x - ov.x, q.y - ov.y) - (drill + other.via[1]) / 2.0
            if hole < self.env.hole_to_hole - _TOL:
                return "the hole of pin %s's via, %s mm off (hole to hole needs %s)" % (
                    (other.number,) + gap_texts(hole, self.env.hole_to_hole, 3))
        if others:
            return self.env.via_site(q, lane.net, size, drill)
        return None

    def _pads_why(self, lane: _Lane, q: Location) -> str | None:
        size = lane.via[0]
        for number, shapes in self.pads.items():
            for sh in shapes:
                need = self.env.clearance(lane.net, sh.net, sh.owner)
                gap = _point_poly_distance((q.x, q.y), sh.poly) - size / 2.0
                if gap < need - _TOL:
                    return "pad %s of its own part, %s mm off (needs %s)" % ((number,) + gap_texts(gap, need, 3))
        return None

    def _first(self, lane: _Lane, why, a_from: float) -> float | None:
        """The first `a` along the lane, from `a_from`, where `why(point)` finds nothing wrong:
        looked for at `env.step`, then bisected back to the nearest nanometre."""
        a, prev = a_from, None
        while a <= a_from + self.env.reach + 1e-9:
            if why(self._end_at(lane, a)) is None:
                if prev is None:
                    return a
                lo, hi = prev, a
                for _ in range(26):
                    mid = (lo + hi) / 2.0
                    if why(self._end_at(lane, mid)) is None:
                        hi = mid
                    else:
                        lo = mid
                hi = math.ceil(hi * 1e6 - 1e-3) / 1e6
                for _ in range(8):          # the point is rounded to the nanometre too: never short of legal
                    if why(self._end_at(lane, hi)) is None:
                        return hi
                    hi += 1e-6
                return a
            prev = a
            a += self.env.step
        return None

    def _scan(self, lane: _Lane, others: bool) -> float | None:
        """The first `a` along the lane with a legal via there. Searched from where the via
        first clears the part's own pads: a spot hemmed in between that and a neighbour's
        via is a point, and a grid would step over it."""
        a0 = self._a_min(lane)
        start = self._first(lane, lambda q: self._pads_why(lane, q), a0)
        if start is None:
            return None
        return self._first(lane, lambda q: self._via_why(lane, q, others), start)

    def _place_vias(self) -> None:
        d = self.decl
        for n in self.order:
            lane = self.lanes[n]
            if lane.via is None:
                continue
            a = self._scan(lane, True)
            if a is None:
                a = self._scan(lane, False)
                if a is None:
                    raise EscapeError("%s: pin %s's via has no legal spot within %.1f mm along its lane or axis: %s" % (
                        d.key, n, self.env.reach, self._via_why(lane, self._end_at(lane, self._a_min(lane)), False)))
                lane.blocked_why = "its via has no legal spot within %.1f mm: %s" % (
                    self.env.reach, self._via_why(lane, self._end_at(lane, a), True))
            lane.a = a
            lane.via_at = self._end_at(lane, a)

    def _ends(self) -> None:
        """A lane with no via ends level with the outermost via, or one step past the row's
        turn-side end where there is none; `run=` says it instead."""
        d = self.decl
        placed = [lane for lane in self.lanes.values() if lane.via_at is not None]
        for n in self.order:
            lane = self.lanes[n]
            if lane.via_at is not None:
                continue
            if d.turn is None:
                lane.a = d.depth if d.depth is not None else lane.copper + self._tip_clearance(lane)
            elif self.diagonal and d.run is not None:
                lane.a = d.run
            else:
                if d.run is not None:
                    level = self.row_end + d.run
                elif placed:
                    level = max(self.s_of((p.via_at.x, p.via_at.y)) for p in placed)
                else:
                    level = self.row_end + self._lane_step(lane)
                lane.a = max(0.0, (level - lane.s) * (_SQ2 if self.diagonal else 1.0))
            lane.end_at = self._end_at(lane, lane.a)
        for lane in placed:
            lane.end_at = lane.via_at

    def _finish(self) -> Layout:
        d, env = self.decl, self.env
        out = {}
        for k, n in enumerate(self.order):
            lane = self.lanes[n]
            pts = [lane.centre] + ([lane.corner] if d.turn is not None else []) + [lane.end_at]
            pts = [p for i, p in enumerate(pts) if i == 0 or (p.x, p.y) != (pts[i - 1].x, pts[i - 1].y)]
            cut = chamfer_cuts(pts, d.chamfer_of(n))[0]
            tracks = tuple(polyline_tracks(lane.net, env.layer, lane.width, cut))
            via = Via(lane.net, lane.via_at, lane.via[1], lane.via[0]) if lane.via_at is not None else None
            if d.turn is None:
                line = ("x" if self.u[1] else "y", lane.centre.x if self.u[1] else lane.centre.y)
            elif self.diagonal:
                line = None
            else:
                line = ("y" if self.t[0] else "x", lane.corner.y if self.t[0] else lane.corner.x)
            geom = LaneGeom(n, lane.net, lane.width, k, tuple(pts), tracks, via, line)
            if getattr(lane, "blocked_why", None):
                geom.blocked.append(lane.blocked_why)
            for op in (*tracks, *((via,) if via else ())):
                geom.blocked += env.hits(op)
            out[n] = geom
        return Layout(out, list(self.order))
