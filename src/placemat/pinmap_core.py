"""The pin map study's core, as one entry point: a study as plain arrays (`Problem`), searched by the native core
(native/src/pinmap.rs, `placemat_native.pinmap_search`) when the native module is in use, else by its Python twin
(pinmap_twin.py), which gives the same answers. Around it: the arrays from a StudyInput, the poses a part is studied at,
and the core's answer turned back into names (`study_group`)."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import itertools

from . import geometry as _geometry
from .pinmap_rules import natural
from .ratsnest import _nm

KIND_CODES = {"plain": 0, "pair": 1, "impedance": 2, "plane": 3}


@dataclass(frozen=True)
class Problem:
    """A study as the core takes it. `parts` (ref, cx, cy, hw, hh) and `pins` per part (number, x, y, nx, ny) in
    natural pad order; `nets` (name, kind code), and per net its `fixed` anchors (x, y, ref, number), `joined` pairs of
    them and its `ends` (part, pin) as they stand, one per end slot; `wires` the other airwires (kind code, ax, ay, bx,
    by) in nm, but for `posed`: per background net with a pad on a studied part, (kind code, its pads (x, y, ref,
    number, part or -1, pin or -1), joined pairs), whose airwires the core works out again at each pose; `movable` (net,
    slot, allowed pins, group or -1); `groups` the hard groups (part, member movables or -1, windows of pins); `soft`
    the soft groups (part, pin pitch, members (slot in the group, movable or -1, pin or -1), windows of pins, one per
    slot): a movable's pin is where the assignment puts it, a held net's is `pin`, and the first map starts the group
    whole on a window when one fits; `margin` the exit distance; `frames` each part's frame (degrees its pins' frame
    is turned from the board's: a part standing off the axes keeps its own); `controlled` per net, whether its length
    counts `pins.impedance_weight` times over."""
    parts: list
    pins: list
    nets: list
    fixed: list
    joined: list
    ends: list
    wires: list
    movable: list
    groups: list
    margin: float
    posed: list = field(default_factory=list)
    soft: list = field(default_factory=list)
    frames: list = field(default_factory=list)          # per part, its frame's turn from the board's; [] for none
    controlled: list = field(default_factory=list)      # per net, whether it is a controlled impedance's; [] for none


@dataclass(frozen=True)
class Breakdown:
    """A score and its parts: crossings against the other airwires and among the studied nets (counts), their weighted
    sum, the airwire length in mm and the summed bend in degrees; the length in mm of the nets in a controlled
    impedance's class, which counts `pins.impedance_weight` times over; the soft groups' spread in mm and its term
    (`cohesion`)."""
    total: float
    against: int
    among: int
    weighted: float
    length_mm: float
    bend_deg: float
    impedance_length_mm: float = 0.0
    spread_mm: float = 0.0
    cohesion: float = 0.0

    def to_json(self) -> dict:
        return {"total": round(self.total, 3), "against": self.against, "among": self.among,
                "weighted": round(self.weighted, 3), "length_mm": round(self.length_mm, 3), "bend_deg": round(self.bend_deg, 1),
                "impedance_length_mm": round(self.impedance_length_mm, 3), "spread_mm": round(self.spread_mm, 3),
                "cohesion": round(self.cohesion, 3)}


@dataclass(frozen=True)
class Landing:
    """Where a `Pm.PinGroup` group's nets stand under an assignment: its part, whether it is hard, its spread (mm its
    neighbouring nets stand apart beyond the pin pitch, in the group's written order) and what that costs in the total
    (`pins.group_weight` times the spread for a soft group, 0 for a hard one), and its nets with their pins, in pin
    number order."""
    name: str
    ref: str
    hard: bool
    spread_mm: float
    cost: float
    nets: tuple
    pins: tuple

    def to_json(self) -> dict:
        return {"name": self.name, "ref": self.ref, "hard": self.hard, "spread_mm": round(self.spread_mm, 3),
                "cost": round(self.cost, 3), "nets": list(self.nets), "pins": list(self.pins)}


@dataclass(frozen=True)
class PoseResult:
    """The best found at one pose of each part of a group: `poses` ((ref, turn, flip), ...), its score, `assign`
    {net: ends ((ref, pad number), ...)} for every studied net, `paths` {net: [path, ...]} of the group's nets, and
    where its parts' `Pm.PinGroup` groups land (Landing)."""
    poses: tuple
    breakdown: Breakdown
    assign: dict
    paths: dict
    groups: tuple = ()


@dataclass(frozen=True)
class GroupResult:
    refs: tuple
    present: Breakdown
    present_assign: dict
    present_paths: dict
    results: tuple
    searched: int
    of: int
    budget_out: bool
    first_map: bool
    problems: tuple = ()        # (ref, net) a matching could not place
    present_groups: tuple = ()  # Landing of each group as it stands
    steps: int = 0              # the steps the search took (one step: one move of a local search)
    budget_steps: int = 0       # the steps it had
    slow: bool = False          # past its wall-clock guard: no poses, no map
    guard_ms: float = 0.0       # the guard it had (0 is off)


def problem_of(inp, margin: float) -> Problem:
    """The arrays of a StudyInput (pinmap_input)."""
    parts = [(p.ref, p.cx, p.cy, p.hw, p.hh) for p in inp.parts]
    part_at = {p.ref: i for i, p in enumerate(inp.parts)}
    pins, pin_at, pin_of = [], [], {}
    for i, p in enumerate(inp.parts):
        ordered = sorted(p.pins, key=lambda q: natural(q.number))
        pins.append([(q.number, q.x, q.y, q.nx, q.ny) for q in ordered])
        pin_at.append({q.number: k for k, q in enumerate(ordered)})
        pin_of.update({q.key(p.ref): (i, k) for k, q in enumerate(ordered)})       # a board pad -> (part, pin)
    nets = [(n.net, KIND_CODES[n.kind]) for n in inp.nets]
    net_at = {n.net: i for i, n in enumerate(inp.nets)}
    fixed = [[(a.x, a.y, a.ref, a.number) for a in n.fixed] for n in inp.nets]
    joined = [list(n.joined) for n in inp.nets]
    ends = [[(part_at[r], pin_at[part_at[r]][num]) for r, num in n.ends] for n in inp.nets]
    moving = {n.net for n in inp.posed}
    wires = [(KIND_CODES[w.kind], _nm(w.a[0]), _nm(w.a[1]), _nm(w.b[0]), _nm(w.b[1])) for w in inp.background
             if w.net not in moving]
    posed = [(KIND_CODES[n.kind], [(a.x, a.y, a.ref, a.number) + pin_of.get((a.ref, a.number), (-1, -1)) for a in n.anchors],
              [tuple(j) for j in n.joined]) for n in inp.posed]
    movable, groups, mv_at = [], [], {}
    for pi, p in enumerate(inp.parts):
        slots = p.slots
        group_of = {n: g for g, (_, gnets) in enumerate(slots.groups) for n in gnets if n}
        first_group = len(groups)
        for net in slots.movable:
            ni = net_at[net]
            slot = next(k for k, (r, _) in enumerate(ends[ni]) if r == pi)
            mv_at[(pi, net)] = len(movable)
            movable.append((ni, slot, [pin_at[pi][q] for q in slots.allowed[net]],
                            first_group + group_of[net] if net in group_of else -1))
        for name, gnets in slots.groups:
            wins = [[pin_at[pi][q] for q in w] for w in slots.windows.get(name, ())]
            here = [pin_at[pi][q] for q in slots.places.get(name, ())]
            # A group may always stay where it stands, though a pin of it whose net a rule holds (or a quiet net)
            # keeps that place out of the windows: first, so a tie keeps it there. Not when a rule moves a net of it.
            legal = all(not n or q in slots.allowed[n] for n, q in zip(gnets, slots.places.get(name, ())))
            if here and here not in wins and legal:
                wins.insert(0, here)
            groups.append((pi, [mv_at[(pi, n)] if n else -1 for n in gnets], wins))
    soft = []
    for pi, p in enumerate(inp.parts):
        held = {h.net: h.pin for h in p.slots.held}
        for name, gnets in p.slots.soft:
            members = [(k, mv_at[(pi, n)], -1) if (pi, n) in mv_at else (k, -1, pin_at[pi][held[n]])
                       for k, n in enumerate(gnets) if n]
            if len(members) >= 2:
                soft.append((pi, p.pitch, members, [[pin_at[pi][q] for q in w] for w in p.slots.windows.get(name, ())]))
    return Problem(parts, pins, nets, fixed, joined, ends, wires, movable, groups, margin, posed, soft,
                   [p.frame for p in inp.parts], [n.controlled for n in inp.nets])


def poses_of(part, settings) -> list:
    """The (turn, flip) a part is studied at: its present pose first, each of `pins.rotations` as a turn from where it
    stands (mod 360, each once), then the same on the other face when `pins.faces` is true and the part may stand
    there. A part studied as its cell turns the cell, on the face it stands on (build gives it no `may_flip`)."""
    turns = [0.0]
    for t in settings.pins_rotations:
        t = float(t) % 360.0
        if t not in turns:
            turns.append(t)
    out = [(t, False) for t in turns]
    if settings.pins_faces and part.may_flip:
        out += [(t, True) for t in turns]
    return out


def seed_key(refs) -> int:
    """The study's random streams' key: from the parts' refs, so a board gives the same map every time."""
    return int.from_bytes(hashlib.sha256(",".join(refs).encode()).digest()[:8], "little")


def budget_of(settings, refs, budget_steps: int | None = None) -> int:
    """A group's budget in steps: `pins.budget_steps` for each of its parts, unless given."""
    return int(settings.pins_budget_steps * len(refs) if budget_steps is None else budget_steps)


def guard_of(settings, refs, budget_steps: int | None = None) -> float:
    """A group's wall-clock guard in ms: `pins.guard_ms` for each of its parts, scaled with a budget given in place of
    `pins.budget_steps` (a longer study is given a longer guard); 0 is off."""
    return float(settings.pins_guard_ms) * budget_of(settings, refs, budget_steps) / float(settings.pins_budget_steps)


def params_of(settings, refs, budget_steps: int | None = None, guard_ms: float | None = None) -> dict:
    return {"weights": (settings.pins_pair_weight, settings.pins_impedance_weight, settings.score_crossing_plane,
                        settings.pins_length_weight, settings.pins_bend_weight, settings.pins_group_weight),
            "seeds": int(settings.pins_seeds), "moves": int(settings.pins_anneal_moves),
            "t0": float(settings.pins_anneal_start), "t1": float(settings.pins_anneal_end),
            "budget_steps": budget_of(settings, refs, budget_steps),
            "guard_ms": float(guard_of(settings, refs, budget_steps) if guard_ms is None else guard_ms),
            "seed_key": seed_key(refs)}


def native_core():
    """The native core when the native module is in use and has it, else None."""
    native = _geometry._native
    return native if native is not None and hasattr(native, "pinmap_search") else None


def search(pb: Problem, group_parts: list, combos: list, params: dict, native=True) -> tuple:
    """The one entry point: (present breakdown, present paths, [(combo, breakdown, assignment, paths)], budget_out,
    first_map, [(part, net)], steps taken, slow), from the native core when it is in use (and `native`), else the
    Python twin."""
    core = native_core() if native else None
    if core is None:
        from . import pinmap_twin
        return pinmap_twin.search(pb, group_parts, combos, params)
    w = params["weights"]
    return core.pinmap_search(
        pb.parts, pb.pins, pb.nets, pb.fixed, pb.joined, pb.ends, pb.wires,
        [(k, [tuple(a) for a in pads], [tuple(j) for j in joined]) for k, pads, joined in pb.posed],
        [(n, s, list(a), g) for n, s, a, g in pb.movable], [(p, list(m), [list(x) for x in ws]) for p, m, ws in pb.groups],
        [(p, float(pitch), [tuple(m) for m in ms], [list(x) for x in ws]) for p, pitch, ms, ws in pb.soft],
        [float(f) for f in pb.frames] or [0.0] * len(pb.parts), [bool(c) for c in pb.controlled] or [False] * len(pb.nets),
        list(group_parts), [[(p, float(t), bool(f)) for p, t, f in c] for c in combos],
        tuple(w), (pb.margin, params["seeds"], params["moves"], params["t0"], params["t1"], params["budget_steps"],
                   params["guard_ms"], params["seed_key"]))


def _breakdown(t) -> Breakdown:
    return Breakdown(t[0], int(t[1]), int(t[2]), t[3], t[4], t[5], t[6], t[7], t[8])


def landings(inp, refs, assign: dict, weight: float) -> tuple:
    """Where each `Pm.PinGroup` group of the parts `refs` lands under `assign` {net: ((ref, pad number), ...)}, in the
    order the groups are written (Landing). A hard group's nets are those that move with it; a soft group's are every
    net on its pins as captured, held ones too."""
    from .pinmap_twin import spread
    out = []
    for r in refs:
        part = inp.part(r)
        hard = dict(part.slots.groups)
        soft = dict(part.slots.soft)
        for name in part.slots.places:
            nets = hard[name] if name in hard else soft[name]
            members = []
            for k, net in enumerate(nets):
                at = next((n for rr, n in assign.get(net, ()) if rr == r), None) if net else None
                if at is not None:
                    members.append((k, net, at))
            pts = [(k, part.pin(at).x, part.pin(at).y) for k, _, at in members]
            mm = spread(part.pitch, pts)
            order = sorted(members, key=lambda m: natural(m[2]))
            out.append(Landing(name, r, name in hard, mm, 0.0 if name in hard else weight * mm,
                               tuple(n for _, n, _ in order), tuple(at for _, _, at in order)))
    return tuple(out)


def study_group(inp, refs: tuple, settings, budget_steps: int | None = None, guard_ms: float | None = None, native=True,
                pb: Problem | None = None) -> GroupResult:
    """The study of one group of parts: every combination of their poses (the present first, at most
    `pins.joint_combinations`), each from its first map through the local search, in the core, until it has taken its
    budget of steps (`budget_steps`, else `pins.budget_steps` a part). Parts studied as one cell take one pose
    together. Past its wall-clock guard (`guard_ms`, else guard_of) it gives no poses (`slow`)."""
    pb = pb or problem_of(inp, settings.pins_exit_mm)
    part_at = {p.ref: i for i, p in enumerate(inp.parts)}
    group_parts = [part_at[r] for r in refs]
    units: dict = {}                    # what turns as one: a cell's studied parts, else a part alone
    for r in refs:
        units.setdefault(inp.part(r).cell or r, []).append(r)
    lists = [[[(part_at[r], t, f) for r in unit] for t, f in poses_of(inp.part(unit[0]), settings)]
             for unit in units.values()]
    combos = [sorted((x for u in c for x in u), key=lambda x: refs.index(pb.parts[x[0]][0]))
              for c in itertools.islice(itertools.product(*lists), max(int(settings.pins_joint_combinations), 1))]
    total = 1
    for l in lists:
        total *= len(l)
    params = params_of(settings, refs, budget_steps, guard_ms)
    base, base_paths, results, out, first, problems, steps, slow = search(pb, group_parts, combos, params, native)

    def assign_of(pins) -> dict:
        return {pb.nets[n][0]: tuple((pb.parts[pb.ends[n][k][0]][0], pb.pins[pb.ends[n][k][0]][q][0])
                                     for k, q in enumerate(qs)) for n, qs in enumerate(pins)}

    def paths_of(ps) -> dict:
        return {pb.nets[n][0]: [[tuple(p) for p in path] for path in paths] for n, paths in ps}
    present = [[q for _, q in pb.ends[n]] for n in range(len(pb.nets))]
    w = settings.pins_group_weight
    rows = []
    for k, b, pins, ps in results:
        a = assign_of(pins)
        rows.append(PoseResult(tuple((pb.parts[p][0], t, f) for p, t, f in combos[k]), _breakdown(b), a, paths_of(ps),
                               landings(inp, refs, a, w)))
    here = assign_of(present)
    return GroupResult(tuple(refs), _breakdown(base), here, paths_of(base_paths), tuple(rows), len(rows), total,
                       bool(out), bool(first), tuple((pb.parts[p][0], pb.nets[n][0]) for p, n in problems),
                       landings(inp, refs, here, w), int(steps), params["budget_steps"], bool(slow), params["guard_ms"])


def linked_groups(inp) -> list:
    """The studied parts in groups to study together: two parts are linked when a net may move on both (its two ends
    free) or they are studied as one cell, and a group is every part linked to another of it. Sorted, each group's refs
    sorted."""
    parent = {p.ref: p.ref for p in inp.parts}

    def find(r):
        while parent[r] != r:
            parent[r] = parent[parent[r]]
            r = parent[r]
        return r
    links = [sorted({r for r, _ in n.ends if n.net in inp.part(r).slots.movable}) for n in inp.nets]
    links += [sorted(p.ref for p in inp.parts if p.cell == c.name) for c in inp.cells]
    for refs in links:
        for a, b in zip(refs, refs[1:]):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    groups: dict = {}
    for r in sorted(parent):
        groups.setdefault(find(r), []).append(r)
    return [tuple(g) for _, g in sorted(groups.items())]


def movable_count(inp, refs) -> int:
    return sum(len(inp.part(r).slots.movable) for r in refs)


def study(inp, settings, native=True) -> list:
    """Every group's study (GroupResult), the arrays built once for all of them; a group with no net that may move (each
    one waiting on placement) is not searched."""
    pb = problem_of(inp, settings.pins_exit_mm)
    return [study_group(inp, refs, settings, native=native, pb=pb) for refs in linked_groups(inp)
            if movable_count(inp, refs)]
