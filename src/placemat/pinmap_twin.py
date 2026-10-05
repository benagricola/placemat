"""The pin map study's core in Python: the twin of the native core (native/src/pinmap.rs), used when the native module is
not in use. Same algorithm, same arrays, same answers to the last bit: every float is added in the same order, the random
stream is the same SplitMix64, `math.hypot` is CPython's (which the native side copies bit for bit), and the angles go
through `math.radians` and `math.degrees` as CPython defines them.

It takes a study as plain arrays (pinmap_core.Problem) and, for the parts of one group and each combination of their
poses, returns the best assignment of the movable nets to pins with its tallies:

- score: weighted crossings of the studied nets' airwires against the board's other airwires (a 2 mm grid of them)
  and among themselves, plus `length` times their length in mm, plus `bend` times their summed bend in degrees, plus
  the controlled impedances' extra length, plus `group` times the soft groups' spread. A net's airwires are the minimum spanning tree of its
  pads (ratsnest.mst), each studied pin at its exit point and each airwire to one taken round the body
  (pinmap_geom.route). Only the nets with an end on the group's parts count, and the pairs with one of them;
- a studied net in a controlled impedance's class (`controlled`, a differential pair's half too) counts its length
  `impedance` times over: `impedance_extra` on top of the plain term;
- cohesion: per soft group, the sum over its neighbouring members (in its written order) of how far their pins'
  anchors stand apart beyond the pin pitch times the slots between them; an intact group in order spreads 0;
- background: the board's other airwires. Those of a net with a pad on a studied part (a plane's, on the part's
  ground pins) are not fixed: `posed` carries such a net's pads, and at each pose its tree is worked out again with
  the part's pads turned with it, after the fixed wires in the order a segment meets its candidates;
- incremental: a net's airwires, its crossings with the background and its crossings with each other net are kept per
  placing of its ends, so a move recounts only the nets it touches;
- search: a first map (each hard group, then each soft group, on the cheapest run of pins that leaves the rest a
  matching, then a minimum-cost matching), then per seed `moves` moves, swaps and group moves (a soft group's too)
  under annealing from `t0` down to `t1`. A group's empty slots are reserved where it stands: no single net takes
  one. At the present pose the present map is a candidate too;
- budget: the search stops when it has taken `budget_steps` steps, a step being one move of a local search (tried
  whether or not a legal change came of it, and whether or not it was taken), checked before each move and before each
  pose. It never reads the time, so where it stops is the same on any machine and on either core;
- guard: a safety net on the time, `guard_ms` (0 is off), read every 32 moves and before each pose. Past it the study
  gives no map (`slow`): a map cut short by the time would differ from run to run."""
from __future__ import annotations

import math
import struct
import time

from .pinmap_geom import Pose, bend, exit_of, length, route
from .ratsnest import Anchor, _nm, mst

_INF = float("inf")
CELL_NM = 2_000_000          # the background's grid, 2 mm, in whole nanometres
PLAIN, PAIR, IMPEDANCE, PLANE = 0, 1, 2, 3
_MASK = (1 << 64) - 1
_AXES = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))


class SplitMix64:
    """The random stream both twins draw from (Steele, Lea and Flood's SplitMix64)."""

    def __init__(self, seed: int):
        self.state = seed & _MASK

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & _MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        return self.next() % n

    def unit(self) -> float:
        return (self.next() >> 11) * (1.0 / (1 << 53))


def stream_seed(seed_key: int, combo: int, seed: int) -> int:
    return (seed_key ^ (combo << 32) ^ seed) & _MASK


class Clock:
    """The search's budget in steps (one step: one move of a local search) and its wall-clock guard in ms (0 is off)."""

    def __init__(self, budget_steps: int, guard_ms: float = 0.0):
        self.budget, self.guard, self.steps = budget_steps, guard_ms, 0
        self.start = time.perf_counter()

    def take(self) -> bool:
        """Whether a step is left: if so it is taken."""
        if self.steps >= self.budget:
            return False
        self.steps += 1
        return True

    def spent(self) -> bool:
        return self.steps >= self.budget

    def slow(self) -> bool:
        """Whether the guard is on and the time is past it."""
        return self.guard > 0 and (time.perf_counter() - self.start) * 1000.0 >= self.guard


def total_order(x: float) -> int:
    """A key that sorts floats as Rust's `f64::total_cmp` orders them: -NaN, -inf, ..., -0.0, 0.0, ..., inf, NaN."""
    k = struct.unpack("<q", struct.pack("<d", x))[0]
    return k ^ 0x7FFFFFFFFFFFFFFF if k < 0 else k


SPREAD_SLACK_MM = 1e-3       # a gap this much past the pitch is the pitch: pad anchors are not placed to the nanometre


def crossing(w, a: int, b: int) -> float:
    """What a crossing of classes `a` and `b` counts: `w` (pair, impedance, plane, length, bend, group)."""
    if a == PLANE or b == PLANE:
        return w[2]
    x = w[0] if a == PAIR else w[1] if a == IMPEDANCE else 1.0
    y = w[0] if b == PAIR else w[1] if b == IMPEDANCE else 1.0
    return x if x >= y else y


def _seg(ax: int, ay: int, bx: int, by: int) -> tuple:
    return (ax, ay, bx, by, min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def segments(paths) -> list:
    """Each path's segments in whole nanometres with their boxes: (ax, ay, bx, by, minx, miny, maxx, maxy)."""
    out = []
    for path in paths:
        for p, q in zip(path, path[1:]):
            out.append(_seg(_nm(p[0]), _nm(p[1]), _nm(q[0]), _nm(q[1])))
    return out


def cells(s) -> list:
    """The grid cells segment `s` passes through, column by column (a cell is [k, k + 1) * CELL_NM each way): in each
    column the cells between the segment's lowest and highest y over the column, rounded outward to the nanometre. Two
    segments that cross share the cell their crossing point is in, so the grid meets every crossing a whole scan
    meets."""
    (ax, ay), (bx, by) = ((s[0], s[1]), (s[2], s[3])) if s[0] <= s[2] else ((s[2], s[3]), (s[0], s[1]))
    out = []
    for cx in range(ax // CELL_NM, bx // CELL_NM + 1):
        if ax == bx:
            lo, hi = s[5], s[7]
        else:
            x0, x1 = max(ax, cx * CELL_NM), min(bx, (cx + 1) * CELL_NM)
            den = bx - ax
            n0, n1 = (by - ay) * (x0 - ax), (by - ay) * (x1 - ax)
            lo = min(ay + n0 // den, ay + n1 // den)
            hi = max(ay - (-n0) // den, ay - (-n1) // den)
        for cy in range(lo // CELL_NM, hi // CELL_NM + 1):
            out.append((cx, cy))
    return out


class Background:
    """The board's other airwires, (kind, ax, ay, bx, by) in nm, each filed in the 2 mm cells it passes through; a
    plane's are left out when they weigh nothing."""

    def __init__(self, wires, w):
        self.w = w
        kept = [x for x in wires if not (x[0] == PLANE and w[2] <= 0)]
        self.kinds = [x[0] for x in kept]
        self.segs = [_seg(x[1], x[2], x[3], x[4]) for x in kept]
        self.grid: dict = {}
        for k, s in enumerate(self.segs):
            for c in cells(s):
                self.grid.setdefault(c, []).append(k)

    def cross(self, kind: int, segs, extra=()) -> tuple:
        """(weighted, count): crossings of `segs` (class `kind`) with the fixed wires, then with `extra`, the posed
        nets' wires at this pose ((kind, seg) each)."""
        total, count = 0.0, 0
        grid, mine, w = self.grid, self.segs, self.w
        for s in segs:
            near = set()
            for c in cells(s):
                v = grid.get(c)
                if v is not None:
                    near.update(v)
            for k in sorted(near):
                t = mine[k]
                if t[6] < s[4] or s[6] < t[4] or t[7] < s[5] or s[7] < t[5]:
                    continue
                if _crosses(s, t):
                    total += crossing(w, kind, self.kinds[k])
                    count += 1
            for k2, t in extra:
                if t[6] < s[4] or s[6] < t[4] or t[7] < s[5] or s[7] < t[5]:
                    continue
                if _crosses(s, t):
                    total += crossing(w, kind, k2)
                    count += 1
        return total, count


def _tree(at, joined) -> list:
    """ratsnest.mst over (x, y, ref, number) anchors, as index pairs into them."""
    anchors = [Anchor(r, num, x, y) for x, y, r, num in at]
    index = {id(a): i for i, a in enumerate(anchors)}
    return [(index[id(e.a)], index[id(e.b)]) for e in mst("", anchors, joined)]


def posed_wires(pb, poses: list, w) -> list:
    """The posed nets' airwires at `poses` (one per part), (kind, seg) each: each net's tree over its pads, a pad of a
    part at a pose other than its present one turned with the part about its centre, the rest where they stand. A
    plane's are left out when its crossings weigh nothing, as the fixed wires' are."""
    out = []
    for kind, pads, joined in pb.posed:
        if kind == PLANE and w[2] <= 0:
            continue
        at = []
        for x, y, ref, num, part, pin in pads:
            if part >= 0:
                pose = poses[part]
                if not _present(pb, part, pose):
                    row = pb.pins[part][pin]
                    x, y = pose.to_board(row[1], row[2])
            at.append((x, y, ref, num))
        for i, j in _tree(at, joined):
            out.append((kind, _seg(_nm(at[i][0]), _nm(at[i][1]), _nm(at[j][0]), _nm(at[j][1]))))
    return out


def _frame(pb, part: int) -> float:
    return pb.frames[part] if pb.frames else 0.0


def _present(pb, part: int, pose) -> bool:
    """Whether `pose` is the part's present one: its pads where they stand."""
    return pose.turn == _frame(pb, part) and not pose.flip


def pose_at(pb, part: int, turn: float, flip: bool) -> Pose:
    """Part `part` turned `turn` degrees from where it stands, flipped first when `flip`: its frame's turn added; a flip
    mirrors the pads as they stand, so a part whose frame is turned has it taken off (turn - frame), as the twin of
    a mirror in the board's frame."""
    f = _frame(pb, part)
    return Pose(pb.parts[part][1], pb.parts[part][2], f + turn if not flip else turn - f, flip)


def impedance_extra(w, mm: float) -> float:
    """What `mm` of a controlled impedance's airwire adds to the plain `length` a mm: `length` times
    (`impedance` - 1), so it counts `length` times `impedance` in all."""
    return w[3] * (w[1] - 1.0) * mm


def spread_at(pb, g: int, pin_of, held_only: bool = False) -> float:
    """Soft group `g`'s spread with each movable member on `pin_of(movable)` and each held one on its pin: `spread`,
    member by member; with `held_only`, only the gaps beside a held member count."""
    part, pitch, members, _ = pb.soft[g]
    out, prev = 0.0, None
    for slot, mv, pin in members:
        row = pb.pins[part][pin_of(mv) if mv >= 0 else pin]
        if prev is not None and (not held_only or mv < 0 or prev[3] < 0):
            d = math.hypot(row[1] - prev[1], row[2] - prev[2]) - (slot - prev[0]) * pitch
            if d > SPREAD_SLACK_MM:
                out += d
        prev = (slot, row[1], row[2], mv)
    return out


def spread(pitch: float, pts) -> float:
    """How far a group's members stand apart beyond the pitch, in mm: `pts` (slot in the group, x, y) in slot order;
    each neighbouring pair may stand the pitch times the slots between them apart, and a gap within SPREAD_SLACK_MM
    of that counts nothing."""
    out = 0.0
    for (sa, xa, ya), (sb, xb, yb) in zip(pts, pts[1:]):
        d = math.hypot(xb - xa, yb - ya) - (sb - sa) * pitch
        if d > SPREAD_SLACK_MM:
            out += d
    return out


def _crosses(s, t) -> bool:
    """ratsnest._cross_nm of two segments whose boxes meet (the caller has checked): each one's ends strictly either
    side of the other's line. Inlined here, the hot path of the score, on the same whole nanometres."""
    ax, ay, bx, by = s[0], s[1], s[2], s[3]
    cx, cy, dx, dy = t[0], t[1], t[2], t[3]
    ex, ey = bx - ax, by - ay
    v1, v2 = ex * (cy - ay) - ey * (cx - ax), ex * (dy - ay) - ey * (dx - ax)
    if not ((v1 > 0 and v2 < 0) or (v1 < 0 and v2 > 0)):
        return False
    fx, fy = dx - cx, dy - cy
    w1, w2 = fx * (ay - cy) - fy * (ax - cx), fx * (by - cy) - fy * (bx - cx)
    return (w1 > 0 and w2 < 0) or (w1 < 0 and w2 > 0)


def segments_crossing(a, b) -> int:
    n = 0
    for s in a:
        for t in b:
            if s[6] < t[4] or t[6] < s[4] or s[7] < t[5] or t[7] < s[5]:
                continue
            if _crosses(s, t):
                n += 1
    return n


class Scorer:
    """Scores assignments at one set of poses, for the group of `group_parts`. An assignment is a list, per net, of a
    tuple of pin indexes, one per end slot (the part of slot k is `ends[net][k][0]`). Only the nets with an end on the
    group's parts count, and the pairs with one of them."""

    def __init__(self, pb, poses: list, w, bg: Background, group_parts):
        self.pb, self.poses, self.w, self.bg = pb, poses, w, bg
        self.extra = posed_wires(pb, poses, w)
        gp = set(group_parts)
        self.mine = [any(p in gp for p, _ in e) for e in pb.ends]
        self.controlled = list(pb.controlled) or [False] * len(pb.ends)
        self.soft = [g for g in range(len(pb.soft)) if pb.soft[g][0] in gp]
        self.soft_of: dict = {}
        for g in self.soft:
            for _, mv, _ in pb.soft[g][2]:
                if mv >= 0:
                    self.soft_of.setdefault(pb.movable[mv][0], []).append(g)
        self._exits: dict = {}
        self._wires: dict = {}
        self._single: dict = {}
        self._pair: dict = {}

    def exit(self, part: int, pin: int):
        k = (part, pin)
        e = self._exits.get(k)
        if e is None:
            ref, _, _, hw, hh = self.pb.parts[part]
            _, x, y, nx, ny = self.pb.pins[part][pin]
            e = exit_of(ref, self.poses[part], x, y, (nx, ny), hw, hh, self.pb.margin)
            self._exits[k] = e
        return e

    def wires(self, net: int, pins: tuple):
        """(paths, length, bend, segments, box) of `net` with its ends on `pins`."""
        k = (net, pins)
        hit = self._wires.get(k)
        if hit is not None:
            return hit
        pb = self.pb
        anchors = list(pb.fixed[net])
        exits = []
        for slot, pin in enumerate(pins):
            part = pb.ends[net][slot][0]
            e = self.exit(part, pin)
            exits.append(e)
            anchors.append((e.at[0], e.at[1], pb.parts[part][0], pb.pins[part][pin][0]))
        first = len(pb.fixed[net])
        end_of = lambda i: exits[i - first] if i >= first else (anchors[i][0], anchors[i][1])
        paths, bends = [], {}
        for i, j in _tree(anchors, pb.joined[net]):
            paths.append(route(end_of(i), end_of(j)))
            for me, other in ((i, j), (j, i)):
                if me >= first:
                    e = exits[me - first]
                    d = bend(e.normal, e.at, (anchors[other][0], anchors[other][1]))
                    v = bends.get(me)
                    if v is None or d < v:
                        bends[me] = d
        ln = 0.0
        for p in paths:
            ln += length(p)
        bd = 0.0
        for me in sorted(bends):                # anchor-index order, as the native BTreeMap holds them
            bd += bends[me]
        segs = segments(paths)
        box = (min(s[4] for s in segs), min(s[5] for s in segs), max(s[6] for s in segs), max(s[7] for s in segs)) \
            if segs else (0, 0, 0, 0)
        hit = (paths, ln, bd, segs, box)
        self._wires[k] = hit
        return hit

    def single(self, net: int, pins: tuple) -> tuple:
        """(term, weighted, count): the net's own term, its weighted crossings with the background and their count."""
        k = (net, pins)
        hit = self._single.get(k)
        if hit is None:
            _, ln, bd, segs, _ = self.wires(net, pins)
            weighted, count = self.bg.cross(self.pb.nets[net][1], segs, self.extra)
            term = weighted + self.w[3] * ln + self.w[4] * bd
            if self.controlled[net]:
                term += impedance_extra(self.w, ln)
            hit = (term, weighted, count)
            self._single[k] = hit
        return hit

    def pair(self, a: int, ea: tuple, b: int, eb: tuple) -> tuple:
        if b < a:
            a, ea, b, eb = b, eb, a, ea
        k = (a, ea, b, eb)
        hit = self._pair.get(k)
        if hit is None:
            wa, wb = self.wires(a, ea), self.wires(b, eb)
            ba, bb = wa[4], wb[4]
            if ba[2] < bb[0] or bb[2] < ba[0] or ba[3] < bb[1] or bb[3] < ba[1]:
                hit = (0.0, 0)
            else:
                n = segments_crossing(wa[3], wb[3])
                hit = (n * crossing(self.w, self.pb.nets[a][1], self.pb.nets[b][1]), n)
            self._pair[k] = hit
        return hit

    def spread(self, g: int, assign: list, changes: dict | None = None) -> float:
        """Soft group `g`'s spread with its movables where `assign` puts them, but the nets in `changes` where it
        puts them."""
        pb = self.pb

        def pin_of(mv):
            net, slot = pb.movable[mv][0], pb.movable[mv][1]
            pins = changes.get(net) if changes else None
            return (assign[net] if pins is None else pins)[slot]
        return spread_at(pb, g, pin_of)

    def total(self, assign: list) -> tuple:
        """(total, against, among, weighted, length, bend, controlled impedances' length, spread, cohesion)."""
        weighted, against, among, ln, bd, im, xi = 0.0, 0, 0, 0.0, 0.0, 0.0, 0.0
        mine = self.mine
        for n, pins in enumerate(assign):
            if not mine[n]:
                continue
            _, w, c = self.single(n, pins)
            _, l, b, _, _ = self.wires(n, pins)
            weighted += w
            against += c
            ln += l
            bd += b
            if self.controlled[n]:
                im += l
                xi += impedance_extra(self.w, l)
        for a in range(len(assign)):
            for b in range(a + 1, len(assign)):
                if not mine[a] and not mine[b]:
                    continue
                w, c = self.pair(a, assign[a], b, assign[b])
                weighted += w
                among += c
        sp = 0.0
        for g in self.soft:
            sp += self.spread(g, assign)
        co = self.w[5] * sp
        return (weighted + self.w[3] * ln + self.w[4] * bd + xi + co, against, among, weighted, ln, bd, im, sp, co)

    def paths(self, assign: list) -> list:
        """[(net, [path, ...])] of the group's nets."""
        return [(n, [list(p) for p in self.wires(n, pins)[0]]) for n, pins in enumerate(assign) if self.mine[n]]


class Tally:
    """An assignment and its running total."""

    def __init__(self, scorer: Scorer, assign: list):
        self.s, self.assign = scorer, list(assign)
        self.value = scorer.total(self.assign)[0]

    def delta(self, changes: dict) -> float:
        """The change in the total when the nets in `changes` take those pins. A move only touches nets with an end on
        the group, so every pair it changes counts."""
        s, now = self.s, self.assign
        moved = sorted(changes)
        d = 0.0
        for n in moved:
            d += s.single(n, changes[n])[0] - s.single(n, now[n])[0]
        for n in moved:
            for m in range(len(now)):
                if m in changes:
                    continue
                d += s.pair(n, changes[n], m, now[m])[0] - s.pair(n, now[n], m, now[m])[0]
        for i, n in enumerate(moved):
            for m in moved[i + 1:]:
                d += s.pair(n, changes[n], m, changes[m])[0] - s.pair(n, now[n], m, now[m])[0]
        for g in sorted({g for n in moved for g in s.soft_of.get(n, ())}):
            d += s.w[5] * s.spread(g, now, changes) - s.w[5] * s.spread(g, now)
        return d

    def apply(self, changes: dict, d: float) -> None:
        for n in sorted(changes):
            self.assign[n] = changes[n]
        self.value += d


def hungarian(cost) -> list | None:
    """The minimum-cost assignment of every row to a different column (rows <= columns), or None when every assignment
    meets an infinite cost. Kuhn-Munkres with potentials; ties go to the lower column."""
    n = len(cost)
    if n == 0:
        return []
    m = len(cost[0])
    a = [[c if c < 1e12 else 1e12 for c in row] for row in cost]
    u, v, p, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [_INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], _INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = a[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    out = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    for i in range(n):
        if cost[i][out[i]] == _INF:
            return None
    return out


def _with(assign: list, net: int, slot: int, pin: int) -> tuple:
    pins = list(assign[net])
    pins[slot] = pin
    return tuple(pins)


def _part_of(pb, mv: int) -> int:
    return pb.ends[pb.movable[mv][0]][pb.movable[mv][1]][0]


def _target_cost(sc: Scorer, mv: int, pin: int, assign: list) -> float:
    """How far `pin`'s exit point is from what movable `mv` heads for: its net's nearest fixed anchor, else the exit
    points of its other ends."""
    pb = sc.pb
    net, slot = pb.movable[mv][0], pb.movable[mv][1]
    e = sc.exit(_part_of(pb, mv), pin)
    pts = [(a[0], a[1]) for a in pb.fixed[net]]
    if not pts:
        pts = [sc.exit(pb.ends[net][k][0], q).at for k, q in enumerate(assign[net]) if k != slot]
    best = None
    for x, y in pts:
        d = math.hypot(e.at[0] - x, e.at[1] - y)
        if best is None or d < best:
            best = d
    return 0.0 if best is None else best


def _matching(sc: Scorer, singles: list, used: set, assign: list) -> tuple:
    """(free pins, each single's index into them or None): the minimum-cost matching of `singles` to the pins they may
    take but `used`."""
    pb = sc.pb
    pins = sorted({q for k in singles for q in pb.movable[k][2]} - used)
    if len(pins) < len(singles):
        return pins, None
    cost = [[_target_cost(sc, k, q, assign) if q in pb.movable[k][2] else _INF for q in pins] for k in singles]
    return pins, hungarian(cost)


def first_map(sc: Scorer, group_parts, start: list) -> tuple:
    """(assignment, [(part, net)] that no matching places): per part, each hard group on its cheapest window that
    leaves the singles a matching (its empty slots' pins reserved with it), then each soft group's movables whole on
    its cheapest window that leaves the rest a matching (its target costs and `group` times the gaps there beside its
    held members, which stay on their pins; when none fits, they stay singles), then the singles by minimum-cost
    matching."""
    pb = sc.pb
    assign = list(start)
    problems = []
    for part in group_parts:
        singles = [k for k in range(len(pb.movable)) if _part_of(pb, k) == part and pb.movable[k][3] < 0]
        used, changes = set(), {}
        for gpart, members, windows in pb.groups:
            if gpart != part:
                continue
            ranked = []
            for wi, win in enumerate(windows):
                if any(q in used for q in win):
                    continue
                c = 0.0
                for m, q in zip(members, win):
                    if m >= 0:
                        c += _target_cost(sc, m, q, assign)
                ranked.append((c, wi))
            ranked.sort(key=lambda t: (total_order(t[0]), t[1]))
            chosen = None
            for _, wi in ranked:
                if _matching(sc, singles, used | set(windows[wi]), assign)[1] is not None:
                    chosen = windows[wi]
                    break
            if chosen is None:
                for m in members:
                    if m >= 0:
                        mv = pb.movable[m]
                        used.add(assign[mv[0]][mv[1]])
                continue
            used |= set(chosen)
            for m, q in zip(members, chosen):
                if m >= 0:
                    changes[m] = q
        placed = set()
        for g, (gpart, _, members, windows) in enumerate(pb.soft):
            if gpart != part:
                continue
            mine = [(slot, mv) for slot, mv, _ in members if mv >= 0 and mv not in placed]
            rest = [k for k in singles if k not in placed and k not in {mv for _, mv in mine}]
            ranked = []
            for wi, win in enumerate(windows):
                if any(win[slot] in used for slot, _ in mine):
                    continue
                c = 0.0
                for slot, mv in mine:
                    c += _target_cost(sc, mv, win[slot], assign)
                slot_of = {mv: slot for slot, mv in mine}
                c += sc.w[5] * spread_at(pb, g, lambda mv: win[slot_of[mv]] if mv in slot_of else
                                         assign[pb.movable[mv][0]][pb.movable[mv][1]], held_only=True)
                ranked.append((c, wi))
            ranked.sort(key=lambda t: (total_order(t[0]), t[1]))
            for _, wi in ranked:
                taken = {windows[wi][slot] for slot, _ in mine}
                if _matching(sc, rest, used | taken, assign)[1] is not None:
                    used |= taken
                    for slot, mv in mine:
                        changes[mv] = windows[wi][slot]
                        placed.add(mv)
                    break
        singles = [k for k in singles if k not in placed]
        if singles:
            pins, got = _matching(sc, singles, used, assign)
            if got is None:
                bad = next((k for k in singles if not any(q in pb.movable[k][2] for q in pins)), singles[0])
                problems.append((part, pb.movable[bad][0]))
                continue
            for k, j in zip(singles, got):
                changes[k] = pins[j]
        for k in sorted(changes):
            net, slot = pb.movable[k][0], pb.movable[k][1]
            assign[net] = _with(assign, net, slot, changes[k])
    return assign, problems


class _State:
    """Which pin each movable stands on, and which movable each pin of each part holds."""

    def __init__(self, pb, assign):
        self.pb = pb
        self.pin = [assign[mv[0]][mv[1]] for mv in pb.movable]
        self.who = {}
        for k, q in enumerate(self.pin):
            self.who[(_part_of(pb, k), q)] = k

    def commit(self, changes: dict) -> None:
        pb = self.pb
        for k in sorted(changes):
            key = (_part_of(pb, k), self.pin[k])
            if self.who.get(key) == k:
                del self.who[key]
        for k in sorted(changes):
            self.pin[k] = changes[k]
            self.who[(_part_of(pb, k), changes[k])] = k


def _units(pb, group_parts) -> list:
    out = []
    for part in group_parts:
        out += [("m", k) for k in range(len(pb.movable)) if pb.movable[k][3] < 0 and _part_of(pb, k) == part]
        out += [("g", g) for g, gr in enumerate(pb.groups) if gr[0] == part and gr[2]]
        out += [("s", g) for g, gr in enumerate(pb.soft) if gr[0] == part and gr[3]]
    return out


def _window_of(pb, st: _State, g: int):
    """The window group `g` stands on, if it stands on one."""
    _, members, windows = pb.groups[g]
    for w in windows:
        if all(m < 0 or st.pin[m] == q for m, q in zip(members, w)):
            return w
    return None


def _gaps(pb, st: _State, part: int, except_: int) -> set:
    """The pins of the empty slots of the groups on `part` (but `except_`) where they stand: reserved, as the first
    map reserves them, so no other net takes one."""
    out = set()
    for g, gr in enumerate(pb.groups):
        if gr[0] != part or g == except_:
            continue
        win = _window_of(pb, st, g)
        if win is not None:
            out.update(q for m, q in zip(gr[1], win) if m < 0)
    return out


def _propose(rng: SplitMix64, st: _State, pb, units) -> dict | None:
    """A random legal change, {movable: new pin}, or None."""
    if not units:
        return None
    what, i = units[rng.below(len(units))]
    if what == "m":
        mv = pb.movable[i]
        part = _part_of(pb, i)
        here = st.pin[i]
        reserved = _gaps(pb, st, part, -1)
        choices = [q for q in mv[2] if q != here and q not in reserved]
        if not choices:
            return None
        to = choices[rng.below(len(choices))]
        other = st.who.get((part, to))
        if other is None:
            return {i: to}
        if pb.movable[other][3] < 0 and here in pb.movable[other][2]:
            return {i: to, other: here}
        return None
    if what == "s":
        return _propose_soft(rng, st, pb, i)
    gpart, members, windows = pb.groups[i]
    now = [st.pin[m] for m in members if m >= 0]
    wins = [w for w in windows if [q for m, q in zip(members, w) if m >= 0] != now]
    if not wins:
        return None
    win = wins[rng.below(len(wins))]
    reserved = _gaps(pb, st, gpart, i)
    if any(q in reserved for q in win):
        return None
    changes = {m: q for m, q in zip(members, win) if m >= 0}
    # the pins it leaves, its empty slots' among them, go to the nets standing where it lands, in pin order
    was = _window_of(pb, st, i)
    if was is None:
        was = now
    left = sorted(set(was) - set(win))
    taken = [q for q in sorted(win) if st.who.get((gpart, q)) is not None and st.who[(gpart, q)] not in members]
    if len(taken) > len(left):
        return None
    for q, r in zip(taken, left):
        other = st.who[(gpart, q)]
        if pb.movable[other][3] >= 0 or r not in pb.movable[other][2]:
            return None
        changes[other] = r
    return changes


def _propose_soft(rng: SplitMix64, st: _State, pb, g: int) -> dict | None:
    """Soft group `g`'s movables moved whole, in order, to another of its windows; the nets standing where they land
    take the pins they leave, in pin order."""
    part, _, members, windows = pb.soft[g]
    mine = [(slot, mv) for slot, mv, _ in members if mv >= 0]
    now = [st.pin[mv] for _, mv in mine]
    wins = [w for w in windows if [w[slot] for slot, _ in mine] != now]
    if not wins:
        return None
    win = wins[rng.below(len(wins))]
    target = [win[slot] for slot, _ in mine]
    reserved = _gaps(pb, st, part, -1)
    if any(q in reserved for q in target):
        return None
    changes = {mv: q for (_, mv), q in zip(mine, target)}
    left = sorted(set(now) - set(target))
    taken = [q for q in sorted(target) if st.who.get((part, q)) is not None and st.who[(part, q)] not in changes]
    if len(taken) > len(left):
        return None
    for q, r in zip(taken, left):
        other = st.who[(part, q)]
        if pb.movable[other][3] >= 0 or r not in pb.movable[other][2]:
            return None
        changes[other] = r
    return changes


def _exp(x: float) -> float:
    """`f64::exp`: infinity where CPython's raises on overflow."""
    try:
        return math.exp(x)
    except OverflowError:
        return _INF


def anneal(sc: Scorer, group_parts, start: list, params, combo: int, clock: Clock, present: list | None = None) -> tuple:
    """(best assignment, its total, why it stopped early: None, "budget" or "slow") from `start`, over the seeds. The
    best starts as `start`, or as `present` when that scores lower: at the present pose the study never reports a map
    worse than the one the part has."""
    pb = sc.pb
    seeds, moves, t0, t1, seed_key = params["seeds"], params["moves"], params["t0"], params["t1"], params["seed_key"]
    best, best_v = list(start), sc.total(start)[0]
    if present is not None:
        v = sc.total(present)[0]
        if v < best_v - 1e-9:
            best, best_v = list(present), v
    units = _units(pb, group_parts)
    n = max(moves, 1)
    span = float(max(n - 1, 1))
    for s in range(max(seeds, 1)):
        rng = SplitMix64(stream_seed(seed_key, combo, s))
        tally, st = Tally(sc, start), _State(pb, start)
        for k in range(n):
            if k % 32 == 0 and clock.slow():
                return best, best_v, "slow"
            if not clock.take():
                return best, best_v, "budget"
            temp = t0 * (t1 / t0) ** (k / span) if t0 > 0 and t1 > 0 else 0.0
            got = _propose(rng, st, pb, units)
            if got is None:
                continue
            changes = {}
            for m in sorted(got):
                net, slot = pb.movable[m][0], pb.movable[m][1]
                changes[net] = _with(tally.assign, net, slot, got[m])
            d = tally.delta(changes)
            if d < -1e-12 or (temp > 0 and rng.unit() < _exp(-d / temp)):
                tally.apply(changes, d)
                st.commit(got)
                if tally.value < best_v - 1e-9:
                    best, best_v = list(tally.assign), tally.value
    return best, best_v, None


def _indexes(pb, group_parts, combos) -> str | None:
    """The first index `search` is given that points at nothing, named; None when every one points at something. The
    native core's check (lib.rs, pinmap_indexes), with a negative index out of range too."""
    n = len(pb.nets)
    parts, pins = pb.parts, pb.pins
    if len(pins) != len(parts) or len(pb.fixed) != n or len(pb.joined) != n or len(pb.ends) != n:
        return "a part's or net's array: its length"
    ok = lambda i, size: 0 <= i < size
    pin = lambda part, q: ok(part, len(parts)) and ok(q, len(pins[part]))
    for k in range(n):
        if any(not ok(a, len(pb.fixed[k])) or not ok(b, len(pb.fixed[k])) for a, b in pb.joined[k]):
            return "net %d's joined anchor" % k
        if any(not pin(p, q) for p, q in pb.ends[k]):
            return "net %d's end" % k
    for k, (_, pads, pairs) in enumerate(pb.posed):
        if any(a[4] >= 0 and (a[5] < 0 or not pin(a[4], a[5])) for a in pads):
            return "posed net %d's pad" % k
        if any(not ok(a, len(pads)) or not ok(b, len(pads)) for a, b in pairs):
            return "posed net %d's joined pad" % k
    for k, (net, slot, allowed, group) in enumerate(pb.movable):
        if not ok(net, n) or not ok(slot, len(pb.ends[net])):
            return "movable %d's net or slot" % k
        part = pb.ends[net][slot][0]
        if any(not pin(part, q) for q in allowed) or group >= len(pb.groups) or group < -1:
            return "movable %d's pin or group" % k
    for k, (part, members, windows) in enumerate(pb.groups):
        if not ok(part, len(parts)) or any(m < -1 or m >= len(pb.movable) for m in members):
            return "group %d's part or member" % k
        if any(len(w) != len(members) or any(not pin(part, q) for q in w) for w in windows):
            return "group %d's window" % k
    for k, (part, _, members, windows) in enumerate(pb.soft):
        if not ok(part, len(parts)) or any(mv < -1 or mv >= len(pb.movable) or (mv < 0 and not pin(part, q))
                                           or (mv >= 0 and pb.ends[pb.movable[mv][0]][pb.movable[mv][1]][0] != part)
                                           for _, mv, q in members):
            return "soft group %d's part or member" % k
        if any(any(slot >= len(w) for slot, _, _ in members) or any(not pin(part, q) for q in w) for w in windows):
            return "soft group %d's window" % k
    if pb.frames and len(pb.frames) != len(parts) or pb.controlled and len(pb.controlled) != n:
        return "a part's frame or a net's impedance flag: its length"
    if any(not ok(p, len(parts)) for p in group_parts) or any(not ok(c[0], len(parts)) for combo in combos for c in combo):
        return "a group part or a pose's part"
    return None


def _as_native(pb):
    """`pb` with its coordinates as floats, as the native core takes them: a point given as whole numbers comes back
    as floats from both."""
    from dataclasses import replace
    f = float
    return replace(pb, parts=[(r, f(cx), f(cy), f(hw), f(hh)) for r, cx, cy, hw, hh in pb.parts],
                   pins=[[(num, f(x), f(y), f(nx), f(ny)) for num, x, y, nx, ny in row] for row in pb.pins],
                   fixed=[[(f(x), f(y), r, num) for x, y, r, num in net] for net in pb.fixed],
                   posed=[(kind, [(f(x), f(y), r, num, part, pin) for x, y, r, num, part, pin in pads], joined)
                          for kind, pads, joined in pb.posed],
                   soft=[(part, f(pitch), members, windows) for part, pitch, members, windows in pb.soft],
                   frames=[f(x) for x in pb.frames] or [0.0] * len(pb.parts),
                   controlled=[bool(c) for c in pb.controlled] or [False] * len(pb.ends),
                   margin=f(pb.margin))


def search(pb, group_parts, combos, params) -> tuple:
    """The study of one group, as the native core's `pinmap_search` returns it: (present tallies, present paths,
    [(combo, tallies, assignment, paths)], budget_out, first_map, [(part, net)] no matching placed, steps taken, slow).
    A study past its guard (`slow`) gives no poses and no problems. An index out of range, or a pin normal off the four axes, is refused
    with ValueError, as the native core refuses it."""
    what = _indexes(pb, group_parts, combos)
    if what is not None:
        raise ValueError("%s out of range" % what)
    for k, row in enumerate(pb.pins):
        for number, _, _, nx, ny in row:
            if (nx, ny) not in _AXES:
                raise ValueError("pin %r of part %d has normal (%r, %r), not one of the four axis directions"
                                 % (number, k, nx, ny))
    pb = _as_native(pb)
    w = tuple(float(x) for x in params["weights"])
    bg = Background(pb.wires, w)
    clock = Clock(params["budget_steps"], params["guard_ms"])
    present = [tuple(q for _, q in e) for e in pb.ends]
    present_poses = [Pose(p[1], p[2], _frame(pb, k)) for k, p in enumerate(pb.parts)]
    sc0 = Scorer(pb, present_poses, w, bg, group_parts)
    base = sc0.total(present)
    base_paths = sc0.paths(present)
    results, out, first, problems = [], False, True, []
    for k, combo in enumerate(combos):
        if clock.slow():
            return base, base_paths, [], out, first, [], clock.steps, True
        if clock.spent():
            out = True
            if k == 0:
                first = False
            break
        poses = list(present_poses)
        for part, turn, flip in combo:
            poses[part] = pose_at(pb, part, float(turn), bool(flip))
        sc = sc0 if k == 0 else Scorer(pb, poses, w, bg, group_parts)
        start, said = first_map(sc, group_parts, present)
        for p in said:
            if p not in problems:
                problems.append(p)
        if said and k == 0:
            return base, base_paths, [], False, True, problems, clock.steps, False
        at_present = all(float(turn) % 360.0 == 0.0 and not flip for _, turn, flip in combo)
        best, _, stop = anneal(sc, group_parts, start, params, k, clock, present if at_present else None)
        if stop == "slow":
            return base, base_paths, [], out, first, [], clock.steps, True
        results.append((k, sc.total(best), [list(x) for x in best], sc.paths(best)))
        if stop == "budget":
            out = True
            break
    return base, base_paths, results, out, first, problems, clock.steps, False
