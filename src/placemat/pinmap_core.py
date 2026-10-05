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
    slot, allowed pins, group or -1); `groups` (part, member movables or -1, windows of pins); `margin` the exit
    distance."""
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


@dataclass(frozen=True)
class Breakdown:
    """A score and its parts: crossings against the other airwires and among the studied nets (counts), their weighted
    sum, the airwire length in mm and the summed bend in degrees."""
    total: float
    against: int
    among: int
    weighted: float
    length_mm: float
    bend_deg: float

    def to_json(self) -> dict:
        return {"total": round(self.total, 3), "against": self.against, "among": self.among,
                "weighted": round(self.weighted, 3), "length_mm": round(self.length_mm, 3), "bend_deg": round(self.bend_deg, 1)}


@dataclass(frozen=True)
class PoseResult:
    """The best found at one pose of each part of a group: `poses` ((ref, turn, flip), ...), its score, `assign`
    {net: ends ((ref, pad number), ...)} for every studied net, and `paths` {net: [path, ...]} of the group's nets."""
    poses: tuple
    breakdown: Breakdown
    assign: dict
    paths: dict


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
    return Problem(parts, pins, nets, fixed, joined, ends, wires, movable, groups, margin, posed)


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


def params_of(settings, refs, step_ms: float = 0.0, budget_ms: float | None = None) -> dict:
    return {"weights": (settings.pins_pair_weight, settings.pins_impedance_weight, settings.score_crossing_plane,
                        settings.pins_length_weight, settings.pins_bend_weight),
            "seeds": int(settings.pins_seeds), "moves": int(settings.pins_anneal_moves),
            "t0": float(settings.pins_anneal_start), "t1": float(settings.pins_anneal_end),
            "budget_ms": float(settings.pins_budget_ms * len(refs) if budget_ms is None else budget_ms),
            "step_ms": float(step_ms), "seed_key": seed_key(refs)}


def native_core():
    """The native core when the native module is in use and has it, else None."""
    native = _geometry._native
    return native if native is not None and hasattr(native, "pinmap_search") else None


def search(pb: Problem, group_parts: list, combos: list, params: dict, native=True) -> tuple:
    """The one entry point: (present breakdown, present paths, [(combo, breakdown, assignment, paths)], budget_out,
    first_map, [(part, net)]), from the native core when it is in use (and `native`), else the Python twin."""
    core = native_core() if native else None
    if core is None:
        from . import pinmap_twin
        return pinmap_twin.search(pb, group_parts, combos, params)
    w = params["weights"]
    return core.pinmap_search(
        pb.parts, pb.pins, pb.nets, pb.fixed, pb.joined, pb.ends, pb.wires,
        [(k, [tuple(a) for a in pads], [tuple(j) for j in joined]) for k, pads, joined in pb.posed],
        [(n, s, list(a), g) for n, s, a, g in pb.movable], [(p, list(m), [list(x) for x in ws]) for p, m, ws in pb.groups],
        list(group_parts), [[(p, float(t), bool(f)) for p, t, f in c] for c in combos],
        tuple(w), (pb.margin, params["seeds"], params["moves"], params["t0"], params["t1"], params["budget_ms"],
                   params["step_ms"], params["seed_key"]))


def _breakdown(t) -> Breakdown:
    return Breakdown(t[0], int(t[1]), int(t[2]), t[3], t[4], t[5])


def study_group(inp, refs: tuple, settings, step_ms: float = 0.0, budget_ms: float | None = None, native=True,
                pb: Problem | None = None) -> GroupResult:
    """The study of one group of parts: every combination of their poses (the present first, at most
    `pins.joint_combinations`), each from its first map through the local search, in the core. Parts studied as one
    cell take one pose together."""
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
    base, base_paths, results, out, first, problems = search(pb, group_parts, combos, params_of(settings, refs, step_ms,
                                                                                                  budget_ms), native)

    def assign_of(pins) -> dict:
        return {pb.nets[n][0]: tuple((pb.parts[pb.ends[n][k][0]][0], pb.pins[pb.ends[n][k][0]][q][0])
                                     for k, q in enumerate(qs)) for n, qs in enumerate(pins)}

    def paths_of(ps) -> dict:
        return {pb.nets[n][0]: [[tuple(p) for p in path] for path in paths] for n, paths in ps}
    present = [[q for _, q in pb.ends[n]] for n in range(len(pb.nets))]
    rows = tuple(PoseResult(tuple((pb.parts[p][0], t, f) for p, t, f in combos[k]), _breakdown(b), assign_of(pins),
                            paths_of(ps)) for k, b, pins, ps in results)
    return GroupResult(tuple(refs), _breakdown(base), assign_of(present), paths_of(base_paths), rows, len(rows), total,
                       bool(out), bool(first), tuple((pb.parts[p][0], pb.nets[n][0]) for p, n in problems))


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


def study(inp, settings, step_ms: float = 0.0, native=True) -> list:
    """Every group's study (GroupResult), the arrays built once for all of them; a group with no net that may move (each
    one waiting on placement) is not searched."""
    pb = problem_of(inp, settings.pins_exit_mm)
    return [study_group(inp, refs, settings, step_ms=step_ms, native=native, pb=pb) for refs in linked_groups(inp)
            if movable_count(inp, refs)]
