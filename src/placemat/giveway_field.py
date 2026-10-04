"""A via field re-laid round a conflict (docs/superpowers/specs/2026-10-01-via-
field-relay-design.md).

A field is the vias of one net inside one pad of that net, a stamped cell's
own. Where another item's copper meets some of them and none of their own
steps (share, move) worked, `relay` generates candidate layouts of the whole
field inside the pad - vias shifted to the free sites of its lattice, a row
or column shifted, the pitch closed or made uneven, a row or column removed -
prices each (`score.via_relay*`), and takes the cheapest whose new sites are
legal. The result is a group of per-via actions (`FieldStep`) sharing a field
id, applied and undone as one.

giveway.py calls into this module from `_give` (the step, and the drop step's
count), the two loops of `resolve` (a relay handles every via of its field that
meets the item), `apply` (an added via moved again), `undo` and `report`; the
write (kicad/write.py) calls `write`.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math

from .geometry import point_segment_distance
from .giveway import FIELD_PREFIX, Action, _disc_inside, _radius, _shift, _Judge, field_key
from .values import Box

_LINE = 1e-3
"""Two coordinates this close along an axis are one line of a field (mm)."""

_SITE = 1e-4
"""Two sites this close are one site (mm)."""


@dataclass
class Ctx:
    """What a relay reads of the board: the carried vias as they stand (`members`, {id: Group}),
    the item being placed (`geom`), and the actions already decided in this resolution."""
    members: dict
    geom: object
    actions: list
    failed: set = field(default_factory=set)        # (field key, actions decided) of a relay that found nothing


@dataclass(frozen=True)
class FieldStep(Action):
    """One via's part in a field's relay: kind relay-move, relay-drop or relay-add."""
    field: str = ""             # the field's id, shared by every step of one relay
    way: str = ""               # what the relay did, as the report says it
    before: int = 0             # the vias the field held, shared ones included
    after: int = 0
    want: int = 0               # the count it was drawn with


@dataclass(frozen=True)
class Relaid(Action):
    """A relay as `_give` returns it: its steps, the shapes it leaves, the ids whose old shapes it
    takes away. `cost` is the whole field's, once."""
    parts: tuple = field(default=(), compare=False)
    gone: frozenset = field(default=frozenset(), compare=False)


@dataclass
class _Cand:
    way: str
    sites: list
    order: int
    cost: float = 0.0
    kept: int = 0
    keeps: list = field(default_factory=list)       # members that stay
    moves: list = field(default_factory=list)       # (member, site)
    drops: list = field(default_factory=list)       # members taken out
    adds: list = field(default_factory=list)        # sites that get a new via
    plain: bool = False                             # the vias that meet the item, taken out and nothing more


def relayable(occ, g) -> bool:
    """Whether the via `g` is one a relay may move: a stamped cell's own, or one of a part's grid
    (`board.vias()` at a pad)."""
    return g.home in occ.geometry.cells or g.id.startswith(FIELD_PREFIX)


def field_inset(occ, g) -> float:
    """The inset the grid of `g` was declared with, 0 for a cell's field."""
    if not g.id.startswith(FIELD_PREFIX):
        return 0.0
    k = int(g.id[len(FIELD_PREFIX):].split(" ")[0])
    return occ.field_decls.get(k, 0.0)


def _lines(vals) -> list:
    out: list = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= _LINE:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(l) / len(l) for l in out]


def _gaps_of(lines: list) -> list:
    return [b - a for a, b in zip(lines, lines[1:])]


def _median(xs: list) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _axis(poly, pts) -> float:
    """The angle of the field's `u` axis, mod 90 degrees: of the directions the pad's edges run in and
    the one the closest pair of vias lie in, the one the vias fall on the fewest lines under (the longest
    edge's on a tie)."""
    n = len(poly)
    edges = []
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        length = math.hypot(bx - ax, by - ay)
        if length > 1e-9:
            edges.append((-length, math.atan2(by - ay, bx - ax) % (math.pi / 2.0)))
    angles: list = []
    for _, a in sorted(edges):
        if not any(abs(a - b) < 1e-6 for b in angles):
            angles.append(a)
    if len(pts) >= 2:
        _, p, q = min((math.dist(p, q), p, q) for i, p in enumerate(pts) for q in pts[i + 1:])
        angles.append(math.atan2(q[1] - p[1], q[0] - p[0]) % (math.pi / 2.0))
    if not angles:
        return 0.0

    def lines_under(a: float) -> int:
        c, s = math.cos(a), math.sin(a)
        return len(_lines([x * c + y * s for x, y in pts])) + len(_lines([-x * s + y * c for x, y in pts]))
    return min(angles, key=lambda a: (lines_under(a), angles.index(a)))


def _pad_of(who, m):
    """`who.pad_of(m)`, kept for the life of `who`: a field asks it of every via of its cell."""
    cache = who.__dict__.setdefault("_field_pads", {})
    key = (m.id, m.centre, m.far)
    hit = cache.get(key)
    if hit is None:
        hit = cache[key] = who.pad_of(m)
    return hit


def _hole_radius(g) -> float:
    if g.hole is None:
        return 0.0
    n = len(g.hole.poly)
    return min(point_segment_distance(g.centre, g.hole.poly[i], g.hole.poly[(i + 1) % n]) for i in range(n))


def _pool(occ, geom, region: Box):
    """The board's obstacles round `region` for the item `geom`, built once per board state."""
    token = occ.placed_groups()
    cache = occ.__dict__.setdefault("_relay_pools", {})
    if cache.get("token") is not token:
        cache.clear()
        cache["token"] = token
    key = (geom.owners, round(region.left, 4), round(region.top, 4), round(region.right, 4), round(region.bottom, 4))
    hit = cache.get(key)
    if hit is None:
        hit = cache[key] = occ.obstacles(geom, region)
    return hit


class _Layouts:
    """The candidate layouts of one field, and the means to judge them."""

    def __init__(self, occ, g, judge, own, who, pad_key, pad, ctx: Ctx):
        self.occ, self.g, self.pad, self.pad_key, self.who = occ, g, pad, pad_key, who
        s = occ.settings
        self.s = s
        acted = {a.via: a for a in ctx.actions}
        members, self.fixed, self.rel = [], [], []
        shared_now = 0
        for m in ctx.members.values():
            if m.home != g.home or m.net != g.net:
                continue
            key, land, inside = _pad_of(who, m)
            if key != pad_key or not inside or land is not pad:
                continue
            members.append(m)
            a = acted.get(m.id)
            if a is not None:
                if a.kind == "share":
                    shared_now += 1
                elif a.kind != "drop":
                    self.fixed.append(tuple(a.to) if a.kind in ("move", "leave") and a.to else m.centre)
            elif m.tail is not None or m.routed or not relayable(occ, m):
                self.fixed.append(m.centre)         # a via the field's own steps hold: it keeps its site
            else:
                self.rel.append(m)
        self.members = members
        self.shared = shared_now + sum(1 for a in occ.given_way.values()
                                       if a.kind == "share" and a.pad == pad_key and a.home == g.home)
        self.ok = len(members) >= 2 and any(m.id == g.id for m in self.rel)
        if not self.ok:
            return
        self.r = _radius(g)
        self.rh = _hole_radius(g)
        if any(abs(_radius(m) - self.r) > 1e-6 or abs(_hole_radius(m) - self.rh) > 1e-6 for m in self.rel):
            self.ok = False                         # a field of one via is drawn at one size and drill
            return
        self.pmin = max(2.0 * self.r, 2.0 * self.rh + occ.geometry.hole_to_hole)
        self.inset = field_inset(occ, g)
        drawn = [d for d in who.drawn.values() if d.net == g.net and d.home == g.home
                 and _pad_of(who, d)[0] == pad_key and _pad_of(who, d)[2]]
        self.before = len(self.rel) + len(self.fixed) + self.shared
        self.want = max(len(drawn), self.before)
        if g.net in occ.plane_nets:
            self.floor = who.keeps(pad_key)[1]
        else:
            self.floor = self.want
        self.floor = min(self.floor, self.want)
        # the frame: u along the pad's longest edge, v across it, from the pad's middle
        poly = pad.poly
        box = Box.of_points(poly)
        self.o = (box.center.x, box.center.y)
        self.t = _axis(poly, [m.centre for m in members])
        self.c, self.sn = math.cos(self.t), math.sin(self.t)
        ext_u = [self.uv(p)[0] for p in poly]
        ext_v = [self.uv(p)[1] for p in poly]
        reach = self.r + self.inset         # a grid declared with inset= keeps it: the via's copper grown by it lies in the land
        self.ulo, self.uhi = min(ext_u) + reach, max(ext_u) - reach
        self.vlo, self.vhi = min(ext_v) + reach, max(ext_v) - reach
        self.rel_pos = [self.uv(m.centre) for m in self.rel]
        self.fix_pos = [self.uv(p) for p in self.fixed]
        # the board the new sites are judged against: the pad's neighbourhood, less the field's own vias
        self.rel_ids = {m.id for m in self.rel}
        local = _pool(occ, ctx.geom, box)
        self.judge = _Judge(occ, local, judge.clearance, judge.res)
        self.judge.hidden = set(judge.hidden) | self.rel_ids
        self.judge.extra = list(judge.extra)
        self.own = [o for o in own if o.carried not in self.rel_ids]
        self.cache: dict = {}
        self.under = {}
        for m in self.rel:
            what = self.meets(m)
            if what is not None:
                self.under[m.id] = what
        self.conflicts = [m for m in self.rel if m.id in self.under]

    # frame ----------------------------------------------------------
    def uv(self, p) -> tuple:
        x, y = p[0] - self.o[0], p[1] - self.o[1]
        return (round(x * self.c + y * self.sn, 6), round(-x * self.sn + y * self.c, 6))

    def xy(self, q) -> tuple:
        return (round(self.o[0] + q[0] * self.c - q[1] * self.sn, 6), round(self.o[1] + q[0] * self.sn + q[1] * self.c, 6))

    # judging --------------------------------------------------------
    def shapes_at(self, m, at: tuple) -> list:
        dx, dy = at[0] - m.centre[0], at[1] - m.centre[1]
        out = [replace(_shift(m.ring, dx, dy), given=m.id)]
        if m.hole is not None:
            out.append(replace(_shift(m.hole, dx, dy), given=m.id))
        return out

    def _hit(self, shapes):
        """What the first of `shapes` meets, as the report names it, or None."""
        found = self.judge.hit_board(shapes, self.own, say=False)
        if found is None:
            return None
        o = found[1]
        return "the edge" if o is None else self.occ.who(o.owner) if o.owner else \
            ("a via" if o.kind == "through" else "a track")

    def meets(self, m):
        return self._hit([m.ring] + ([m.hole] if m.hole is not None else []))

    def clear(self, q: tuple) -> bool:
        """Whether a via of the field's kind stands clear at site `q`, inside the pad."""
        key = (round(q[0], 5), round(q[1], 5))
        hit = self.cache.get(key)
        if hit is None:
            at = self.xy(q)
            hit = self.cache[key] = _disc_inside(self.pad.poly, at, self.r + self.inset - 1e-5) and \
                self._hit(self.shapes_at(self.g, at)) is None
        return hit

    # candidates -----------------------------------------------------
    def nodes(self) -> list:
        """The free sites of the field's lattice: its lines extended past its edges at its pitch."""
        allpos = self.rel_pos + self.fix_pos
        U, V = _lines([p[0] for p in allpos]), _lines([p[1] for p in allpos])
        eu = _median(_gaps_of(U)) if len(U) > 1 else None
        ev = _median(_gaps_of(V)) if len(V) > 1 else None
        self.eu = max(eu or ev or self.pmin, self.pmin)
        self.ev = max(ev or eu or self.pmin, self.pmin)
        self.U, self.V = U, V
        Ue, Ve = self._extend(U, self.eu, self.ulo, self.uhi), self._extend(V, self.ev, self.vlo, self.vhi)
        self.Ue, self.Ve = Ue, Ve
        out = []
        for u in Ue:
            for v in Ve:
                if all(math.dist((u, v), p) >= self.pmin - 1e-6 for p in allpos) and self.clear((u, v)):
                    out.append((u, v))
        return out

    @staticmethod
    def _extend(lines: list, e: float, lo: float, hi: float) -> list:
        out = list(lines)
        c = lines[0] - e
        while c >= lo - 1e-9:
            out.append(round(c, 6))
            c -= e
        c = lines[-1] + e
        while c <= hi + 1e-9:
            out.append(round(c, 6))
            c += e
        return sorted(out)

    def assign_free(self, movers: list, nodes: list, stay: list) -> list:
        """For each (u, v) of `movers`, the nearest free node that keeps the closest allowed from
        every site in `stay` and from the nodes taken, or None."""
        pairs = sorted((math.dist(m, n), i, j) for i, m in enumerate(movers) for j, n in enumerate(nodes))
        out: list = [None] * len(movers)
        used: set = set()
        chosen = list(stay)
        for _, i, j in pairs:
            if out[i] is not None or j in used:
                continue
            n = nodes[j]
            if any(math.dist(n, c) < self.pmin - 1e-6 for c in chosen):
                continue
            out[i] = n
            used.add(j)
            chosen.append(n)
        return out

    def generate(self, stage: int) -> list:
        """Stage 1: the vias, a row or column shifted to free sites, the lines that meet it taken
        out. Stage 2: the pitch closed or made uneven."""
        c_pos = [self.uv(m.centre) for m in self.conflicts]
        c_ids = {m.id for m in self.conflicts}
        keep_pos = [p for m, p in zip(self.rel, self.rel_pos) if m.id not in c_ids]
        nodes = self.nodes()
        cands: list = []

        def add(way, sites, plain=False):
            cands.append(_Cand(way, sites, len(cands), plain=plain))
        if stage == 2:
            if not self.fix_pos:
                self._pitches(cands, keep_pos)
            return cands

        # remove vias: what drop does, generated to compare
        add("remove vias", list(keep_pos), plain=True)
        # shift vias
        got = self.assign_free(c_pos, nodes, keep_pos + self.fix_pos)
        add("shift vias", keep_pos + [n for n in got if n is not None])
        # shift a row or column
        for axis, name, lines_, ext in ((1, "row", self.V, self.Ve), (0, "column", self.U, self.Ue)):
            hit_lines = sorted({round(p[axis], 3) for p in c_pos})
            for line in lines_:
                if not any(abs(line - h) <= _LINE * 2 for h in hit_lines):
                    continue
                others = [p for p in keep_pos if abs(p[axis] - line) > _LINE]
                mine = [p for p in self.rel_pos if abs(p[axis] - line) <= _LINE]
                if not mine:
                    continue
                for t in sorted((e for e in ext if all(abs(e - l) > _LINE for l in lines_)), key=lambda e: abs(e - line)):
                    moved = [((p[0], t) if axis == 1 else (t, p[1])) for p in mine]
                    moved = [q for q in moved if self.clear(q)]
                    stay = others + moved
                    rest = [p for p, m in zip(c_pos, self.conflicts) if abs(p[axis] - line) > _LINE]
                    more = self.assign_free(rest, [n for n in nodes if all(math.dist(n, q) >= self.pmin - 1e-6
                                                                          for q in moved)], stay + self.fix_pos)
                    add("shift a %s" % name, stay + [n for n in more if n is not None])
        # remove a row or column
        for axis, name in ((1, "row"), (0, "column")):
            hit_lines = {round(p[axis], 3) for p in c_pos}
            sites = [p for p in self.rel_pos if all(abs(p[axis] - h) > _LINE * 2 for h in hit_lines)]
            add("remove a %s" % name, sites)
        return cands

    def _pitches(self, cands: list, keep_pos: list) -> None:
        """Close the pitch, or make it uneven: only where every via of the field is free to move. Each
        way is walked from the smallest change up, and the first layout that is legal is the one that
        counts: a bigger change moves the same vias further, which only costs more."""
        step = self.s.place_via_move_step
        conflicts = [self.uv(m.centre) for m in self.conflicts]

        def found(way: str, move) -> bool:
            if not all(self.clear(move(p)) for p in conflicts):         # the vias that meet the item first
                return False
            c = _Cand(way, [move(p) for p in self.rel_pos], len(cands))
            if self._lay(c) and self.legal(c):
                cands.append(c)
                return True
            return False
        for axis, lines_, e in ((0, self.U, self.eu), (1, self.V, self.ev)):
            if len(lines_) < 2:
                continue

            def along(p, to, axis=axis):
                return (to, p[1]) if axis == 0 else (p[0], to)
            # close the pitch toward each end
            for anchor in (lines_[0], lines_[-1]):
                if any(abs(p[axis] - anchor) <= _LINE for p in conflicts):
                    continue                                            # the line that stays is one that meets it
                k = 1
                while e - k * step > 0:
                    f = (e - k * step) / e
                    if found("close the pitch", lambda p, f=f, anchor=anchor: along(p, anchor + (p[axis] - anchor) * f)):
                        break
                    k += 1
            # the lines on one side of a pivot move together, by what the pad and the gap beside the pivot allow
            lo, hi = (self.ulo, self.uhi) if axis == 0 else (self.vlo, self.vhi)
            for pivot in range(0, len(lines_)):
                gap = lines_[pivot] - lines_[pivot - 1] if pivot else math.inf
                for upper in (True, False):
                    if pivot == 0 and not upper:
                        continue
                    cut = lines_[pivot] - _LINE
                    if any((p[axis] >= cut) != upper for p in conflicts):
                        continue                                        # a via that meets it stays where it is
                    block = [c for c in lines_ if (c >= cut) == upper]
                    d_lo = max(lo - min(block), -gap if upper else -math.inf)
                    d_hi = min(hi - max(block), gap if not upper else math.inf)
                    way = "uneven pitch" if pivot else "shift the field"
                    for sign, room in ((1, d_hi), (-1, -d_lo)):
                        k = 1
                        while k * step <= room + 1e-9:
                            d = sign * k * step
                            if found(way, lambda p, d=d, cut=cut, upper=upper, axis=axis:
                                     along(p, p[axis] + d) if (p[axis] >= cut) == upper else p):
                                break
                            k += 1

    # scoring --------------------------------------------------------
    def _lay(self, c: _Cand) -> bool:
        """Map `c`'s sites onto the field's vias: stays, moves, drops, adds. False where it is not a layout."""
        c.keeps, c.moves, c.drops, c.adds = [], [], [], []
        sites, seen = [], set()
        for q in c.sites:
            if not (self.ulo - 1e-6 <= q[0] <= self.uhi + 1e-6 and self.vlo - 1e-6 <= q[1] <= self.vhi + 1e-6):
                return False                                # outside the pad
            key = (round(q[0] / _SITE), round(q[1] / _SITE))
            if key in seen:
                return False                                # two vias on one site: not a layout
            seen.add(key)
            sites.append((round(q[0], 6), round(q[1], 6)))
        fixed = self.fix_pos
        allp = sites + list(fixed)
        c.kept = len(sites) + len(fixed) + self.shared
        if c.kept < self.floor or c.kept > self.want:
            return False
        allp.sort()
        for i, a in enumerate(allp):
            for b in allp[i + 1:]:
                if b[0] - a[0] >= self.pmin:
                    break
                if math.dist(a, b) < self.pmin - 1e-6:
                    return False
        conflicting = {m.id for m in self.conflicts}
        left, free = [], list(sites)
        for m, p in zip(self.rel, self.rel_pos):
            j = next((k for k, q in enumerate(free) if math.dist(q, p) < _SITE), None)
            if j is not None:
                if m.id in conflicting:
                    return False                            # it would stay on what it meets
                c.keeps.append(m)
                free.pop(j)
            else:
                left.append((m, p))
        pairs = sorted((math.dist(p, q), i, j) for i, (_, p) in enumerate(left) for j, q in enumerate(free))
        used_m, used_s = set(), set()
        for _, i, j in pairs:
            if i in used_m or j in used_s:
                continue
            used_m.add(i)
            used_s.add(j)
            c.moves.append((left[i][0], free[j]))
        c.drops = [m for i, (m, _) in enumerate(left) if i not in used_m]
        c.adds = [q for j, q in enumerate(free) if j not in used_s]
        s = self.s
        base = 0.0 if c.plain else s.score_via_relay
        gaps = len(_lines([q[0] for q in allp])) * len(_lines([q[1] for q in allp])) - len(allp)
        gaps0 = len(self.U) * len(self.V) - len(self.rel_pos) - len(fixed)
        U, V = _lines([q[0] for q in allp]), _lines([q[1] for q in allp])
        pitch = sum(abs(d - self.eu) for d in _gaps_of(U)) + sum(abs(d - self.ev) for d in _gaps_of(V))
        c.cost = base + s.score_via_drop * (self.want - c.kept) \
            + s.score_via_relay_moved * (len(c.moves) + len(c.adds)) \
            + s.score_via_relay_gap * max(0, gaps - gaps0) + s.score_via_relay_pitch * pitch
        return True

    def legal(self, c: _Cand) -> bool:
        return all(self.clear(q) for _, q in c.moves) and all(self.clear(q) for q in c.adds)

    def _first(self, stage: int):
        """(the cheapest legal candidate of `stage`, or None, whether it is plain removal)."""
        cands = [c for c in self.generate(stage) if self._lay(c)]
        cands.sort(key=lambda c: (round(c.cost, 9), -c.kept, c.order))
        for c in cands:
            if self.legal(c):
                return c
        return None

    def best(self):
        """The cheapest legal layout, or None where plain removal of the vias that meet the item is it.
        The pitch ways are generated only when they could be cheaper than what the others found."""
        if not self.conflicts:
            return None
        s = self.s
        found = self._first(1)
        if not self.fix_pos:
            least = s.score_via_relay + min(s.score_via_relay_moved, s.score_via_drop) * len(self.conflicts)
            if found is None or found.cost > least + 1e-9:
                more = self._first(2)
                if more is not None and (found is None or (more.cost, -more.kept) < (found.cost, -found.kept)):
                    found = more
        return None if found is None or found.plain else found


def relay(occ, g, judge, own, who, pad_key, pad, met: str, ctx: Ctx | None):
    """A `Relaid` for the field of `g` re-laid round what `g` meets, or None where the step does not
    apply or no legal layout is cheaper than dropping the vias that meet it."""
    s = occ.settings
    if ctx is None or not s.place_via_relay or pad is None or pad_key is None or g.tail is not None or g.routed \
            or not relayable(occ, g):
        return None
    key = (g.home, pad_key, len(ctx.actions))
    if key in ctx.failed:
        return None
    lay = _Layouts(occ, g, judge, own, who, pad_key, pad, ctx)
    if not lay.ok or not any(m.id == g.id for m in lay.conflicts):
        ctx.failed.add(key)
        return None
    c = lay.best()
    if c is None:
        ctx.failed.add(key)
        return None
    return _action(occ, lay, g, c, met)


def _new_id(occ, lay: _Layouts, g, used: set) -> str:
    taken = {m.id for m in lay.members} | set(occ.given_way) | used
    base = field_key(g)
    k = 0
    while "%s relay %d" % (base, k) in taken:
        k += 1
    return "%s relay %d" % (base, k)


def _action(occ, lay: _Layouts, g, c: _Cand, met: str) -> Relaid:
    fid = "field %s %s.%s" % (g.home, lay.pad_key[0], lay.pad_key[1])
    before = lay.before
    after = c.kept
    common = dict(owner=g.owner, home=g.home, net=g.net, pad=lay.pad_key, field=fid, way=c.way,
                  before=before, after=after, want=lay.want)
    parts, shapes, gone = [], [], set()
    for m, q in c.moves:
        to = lay.xy(q)
        moved = tuple(lay.shapes_at(m, to))
        parts.append(FieldStep(kind="relay-move", via=m.id, at=m.centre, to=to, shapes=moved,
                               under=lay.under.get(m.id, met), **common))
        shapes += moved
        gone.add(m.id)
    for m in c.drops:
        parts.append(FieldStep(kind="relay-drop", via=m.id, at=m.centre, to=None, shapes=(),
                               under=lay.under.get(m.id, met), **common))
        gone.add(m.id)
    used: set = set()
    for q in c.adds:
        to = lay.xy(q)
        vid = _new_id(occ, lay, g, used)
        used.add(vid)
        new = tuple(replace(x, carried=vid, given=vid) for x in lay.shapes_at(g, to))
        parts.append(FieldStep(kind="relay-add", via=vid, at=to, to=to, shapes=new, under=met, **common))
        shapes += list(new)
    # the field's cost is the search's, once: shared out over its steps, so the cost of the actions on the plan
    # (plan.given_way) sums to what the search priced
    each = c.cost / len(parts) if parts else 0.0
    parts = [replace(x, cost=each) for x in parts]
    return Relaid(kind="relay", via=g.id, owner=g.owner, home=g.home, net=g.net, at=g.centre, pad=lay.pad_key,
                  under=met, cost=c.cost, shapes=tuple(shapes), parts=tuple(parts), gone=frozenset(gone))


def take(res, judge, action: Relaid, keep=None) -> None:
    """Add a relay to `res`: its steps, its cost once, and what it leaves, in `judge` (the vias
    already placed) or, with `keep`, in the item's own shapes - less the old shapes of what it moved."""
    res.actions.extend(action.parts)
    res.cost += action.cost
    if keep is None:
        judge.hidden |= action.gone
        judge.extra += list(action.shapes)
    else:
        keep[:] = [x for x in keep if x.carried not in action.gone] + list(action.shapes)


def done(res, g) -> bool:
    """Whether a relay in `res` already handled via `g`."""
    return any(a.via == g.id and isinstance(a, FieldStep) for a in res.actions)


def relay_loss(ctx: Ctx | None, who, g, pad_key) -> int:
    """How many vias a pad's field holds fewer than it was drawn with, less the drops given way: what
    relays, not drops, took; negative where a relay brought dropped ones back."""
    if ctx is None or pad_key is None or g.net not in who.occ.plane_nets:
        return 0
    occ = who.occ
    present = sum(1 for m in ctx.members.values() if m.home == g.home and m.net == g.net
                  and _pad_of(who, m)[0] == pad_key and _pad_of(who, m)[2])
    shared = sum(1 for a in occ.given_way.values() if a.kind == "share" and a.pad == pad_key and a.home == g.home)
    n = who.counts.get(pad_key, 0)
    return n - present - shared - who.dropped.get(pad_key, 0)


def chain(before, a):
    """`a`, an action on a via that already has `before` on it, as one action: a via a relay added
    that gives way again by moving is an add at its new place."""
    if before.kind == "relay-add" and a.kind in ("move", "leave", "relay-move") and a.to is not None:
        return replace(before, at=tuple(a.to), to=tuple(a.to), shapes=a.shapes, tail=a.tail)
    return a


def undo_field(occ, field_id: str, undo) -> None:
    """Undo every step of a field's relay, with `undo` (giveway.undo)."""
    ids = [v for v, a in occ.given_way.items() if getattr(a, "field", "") == field_id]
    busy = occ.__dict__.setdefault("_field_undoing", set())
    busy.update(ids)
    try:
        for v in ids:
            undo(occ, v)
    finally:
        busy.difference_update(ids)


def report(occ) -> dict:
    """{home: [(facts, severity), ...]} for each field a relay re-laid, from what is in
    `occ.given_way`: a warning where fewer vias were drawn than the field was declared with. The facts
    are the net, the pad, the way, the vias before and after, the vias wanted, and what it went under."""
    by: dict = {}
    for a in occ.given_way.values():
        if getattr(a, "field", ""):
            by.setdefault((a.home, a.field), []).append(a)
    out: dict = {}
    for (home, fid), steps in sorted(by.items()):
        a = steps[0]
        under = sorted({x.under for x in steps if x.under})
        out.setdefault(home, []).append(({"net": a.net, "pad": [a.pad[0], a.pad[1]], "way": a.way, "before": a.before,
                                          "after": a.after, "want": a.want, "under": under},
                                         "warning" if a.after < a.want else "notice"))
    return out


def held_pads(occ, home: str, acts: list) -> list:
    """[[ref, pad number, vias held, vias drawn], ...] for the pads of a field - two or more drops drawn - that `acts` (one
    net's actions of one item) dropped vias from; empty where there is none."""
    from .giveway import _home_owner
    pads = sorted({a.pad for a in acts if a.kind == "drop" and a.pad is not None})
    if not pads:
        return []
    who = _home_owner(occ, home)
    held = []
    for pad in pads:
        n = who.counts.get(pad, 0)
        if n >= 2:
            held.append([pad[0], pad[1], n - who.dropped.get(pad, 0), n])
    return held


def merged(out: list, occ) -> list:
    """`out` ((home, facts, severity), as `giveway.report` builds it) with each home's field
    facts joined to its own: one finding per item, as serious as its most serious part."""
    from .findings import RANK
    by = {home: (facts, sev) for home, facts, sev in out}
    for home, found in report(occ).items():
        fields = [f for f, _ in found]
        sev = max([s for _, s in found] + ([by[home][1]] if home in by else []), key=RANK.__getitem__)
        nets = by[home][0]["nets"] if home in by else []
        by[home] = ({"nets": nets, "fields": fields}, sev)
    return [(home, facts, sev) for home, (facts, sev) in sorted(by.items())]


def write(board, steps: list, groups: dict) -> None:
    """The relay's steps done to the cells' groups on the written board: every via found where it was
    drawn before any is changed, the added ones copied from the nearest via of their field, then the
    moves and the removals."""
    import pcbnew
    from .kicad.write import _unique_uuid, vec

    def on(v, at):
        return abs(v.x / 1e6 - at[0]) <= 0.001 and abs(v.y / 1e6 - at[1]) <= 0.001
    todo = []
    for a in steps:
        g = groups.get(a.home)
        if g is None:
            continue
        vias = [it for it in g.GetItems() if isinstance(it, pcbnew.PCB_VIA) and it.GetNetname() == a.net]
        if a.kind == "relay-add":
            if vias:
                near = min(vias, key=lambda v: math.hypot(v.GetPosition().x / 1e6 - a.at[0],
                                                          v.GetPosition().y / 1e6 - a.at[1]))
                todo.append((a, g, near))
            continue
        via = next((v for v in vias if on(v.GetPosition(), a.at)), None)
        if via is not None:
            todo.append((a, g, via))
    for a, g, via in todo:
        if a.kind == "relay-add":
            new = via.Duplicate()
            new.SetPosition(vec(*a.to))
            _unique_uuid(board, new)
            board.Add(new)
            g.AddItem(new)
    for a, g, via in todo:
        if a.kind == "relay-move":
            via.SetPosition(vec(*a.to))
        elif a.kind == "relay-drop":
            g.RemoveItem(via)
            board.Delete(via)
