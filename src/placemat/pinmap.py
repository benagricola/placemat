"""The pin map study, end to end: from a placed board to its `pins.remap` and `setup.pins` findings.

For each part whose capture gives it a `Pm.PinPool` (pinmap_rules), the study (pinmap_core: the native core, or its
Python twin) finds how many weighted
ratsnest crossings a better assignment of its nets to its pins would save, at its present rotation and at each pose in
`pins.rotations`; when the best saves at least `pins.gain_min` of the present total it is a `pins.remap` notice, whose
facts carry every pose's best map and the airwires before and after (finding_text renders the sentence; the suggestion
builder offers the map and the rotation). Nothing is written to the board or the capture.

It runs once on the finished board of a run or a preview (Board._report_pin_maps), on the best variants of an explore
(explore._pin_maps), and with a longer budget from `placemat apply <id> --search`. What it reads is digested; a study
whose digest matches the last one kept (`Board.pin_study_cache`) reuses its findings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from .findings import Finding, FindingCause as C

from .pinmap_input import Placed, PlacedCell, PlacedPad, PlacedPart, build, cell_modules, stamp_counts
from .pinmap_rules import Problem, has_pools, natural
from .values import Box

CACHE_VERSION = 2
_NOT_READ = ("pins_explore_top", "pins_probe_budget_ms")      # `[pins]` settings the explore and the probe read, not the study


def copper_nets(geometry, plan=None) -> frozenset:
    """The nets with copper on the board now: the generated board's tracks, vias and pours (a stamped cell's, an
    adopted route's), and the copper a plan lays."""
    nets = {c.net for c in geometry.copper if c.kind != "pad" and c.net}
    if plan is not None:
        from .copper import Text
        nets |= {op.net for op in plan.copper if getattr(op, "net", "") and not isinstance(op, Text)}
    return frozenset(nets)


def _rounded(path) -> list:
    return [[round(x, 3), round(y, 3)] for x, y in path]


def _paths(paths: dict) -> list:
    return [{"net": net, "path": _rounded(p)} for net in sorted(paths) for p in paths[net]]


def _turns(inp, poses) -> list:
    """Each part's pose as a turn from where it stands and as the rotation to declare. A flipped pose mirrors the
    present pads and turns them by `turn`; placemat's flip (geometry.pose_transform) mirrors and turns by the declared
    rotation plus the present one, so the rotation that gives the studied pads is `turn - rotation`.

    A part studied as its cell turns the cell, on its face, so the turn is taken one of two ways: the cell turned on the
    board to `cell_rotation_deg`, or the module re-laid with the part at `module_rotation_deg` in the module's frame.
    The part stands in its cell at its rotation less the cell's (layout's member placement: the cell's turn added to the
    member's own), or, in a cell on the other face from its stamp, at the cell's less its own, which a turn takes the
    other way."""
    out = []
    for ref, turn, flip in poses:
        part = inp.part(ref)
        face = part.face if not flip else ("back" if part.face == "front" else "front")
        rotation = (turn - part.rotation) if flip else (part.rotation + turn)
        rec = {"ref": ref, "turn_deg": round(turn, 3), "rotation_deg": round(rotation % 360.0, 3), "face": face,
               "flip": bool(flip)}
        if part.cell:
            c = inp.cell(part.cell)
            rec.update(_cell_facts(inp, ref), cell_rotation_deg=round((c.rotation + turn) % 360.0, 3),
                       module_rotation_deg=module_rotation(inp, ref, turn))
        out.append(rec)
    return out


def module_rotation(inp, ref, turn: float) -> float:
    """The rotation a part in a cell takes in its module's frame (the frame of the arrangement the cell stands in) when
    the cell turns `turn`: its rotation less the cell's, plus the turn; in a cell on the other face from its stamp the
    cell's less its own, less the turn."""
    part = inp.part(ref)
    c = inp.cell(part.cell)
    m = (c.rotation - part.rotation - turn) if c.flipped else (part.rotation - c.rotation + turn)
    return round(m % 360.0, 3)


def _celled(inp, refs):
    """The first of a group's parts that is in a cell, or None."""
    return next((r for r in refs if inp.part(r).cell), None)


def _cell_facts(inp, ref) -> dict:
    """A part in a cell: the cell, its module's name (None when the board does not say), how many stamps it has and
    the arrangement the cell stands in."""
    if ref is None or not inp.part(ref).cell:
        return {}
    c = inp.cell(inp.part(ref).cell)
    return {"cell": c.name, "module": c.module, "stamps": c.stamps, "arrangement": c.arrangement}


def _waiting(inp, refs) -> list:
    """Each pad not placed yet of a studied net, {net, ref}, or of the far net a series part takes it on to, with `via`
    and `far`; a cell member not placed that carries none of the nets has net ""."""
    return [dict({"net": net, "ref": r}, **({"via": via, "far": far} if via else {}))
            for p, net, r, via, far in inp.unplaced if p in refs]


def placed_share(inp, refs) -> dict:
    """{placed, of}: of the group's nets that would move, how many have a placed far end (the rest wait on placement)."""
    placed = sum(len(inp.part(r).slots.movable) for r in refs)
    waiting = sum(1 for r in refs for h in inp.part(r).slots.held if h.why == "unplaced")
    return {"placed": placed, "of": placed + waiting}


def _map(inp, refs, before: dict, after: dict) -> list:
    """Each studied end the assignment moves, on the group's parts: the net, the pin it leaves and the pin it takes."""
    out = []
    for net in sorted(after):
        old, new = set(before[net]), set(after[net])
        for ref, number in sorted(new - old):
            was = next((n for r, n in sorted(old - new) if r == ref), None)
            if ref in refs and was is not None:
                names = inp.names.get(ref, {})
                out.append({"ref": ref, "net": net, "from": {"pin": was, "name": names.get(was, "")},
                            "to": {"pin": number, "name": names.get(number, "")}})
    return sorted(out, key=lambda m: (m["ref"], natural(m["from"]["pin"]), m["net"]))


def _breaks(inp, refs) -> list:
    """Each net the capture as it stands puts on a pin its own `Pm.PinAllow` or `Pm.PinDeny` bars it from."""
    return [{"ref": r, "net": net, "pin": pin, "rule": key} for r in refs for net, pin, key in inp.part(r).slots.breaks]


def _still(breaks: list, assign: dict) -> list:
    """The `breaks` an assignment keeps: the core may keep the present map at the present pose without checking it
    against the rules."""
    return [b for b in breaks if (b["ref"], b["pin"]) in assign.get(b["net"], ())]


def _base(inp, refs, settings) -> dict:
    """The facts every `pins.remap` finding of a group has, its study's aside."""
    lead = inp.part(refs[0])
    at = lead.at or (lead.cx, lead.cy)
    return dict({"ref": refs[0], "refs": list(refs), "at": [round(at[0], 3), round(at[1], 3)],
                 "budget_ms": settings.pins_budget_ms * len(refs),
                 "held": [{"ref": r, "net": h.net, "pin": h.pin, "name": inp.names.get(r, {}).get(h.pin, ""), "why": h.why}
                          for r in refs for h in inp.part(r).slots.held],
                 "present_breaks": _breaks(inp, refs), "unplaced_ends": _waiting(inp, refs),
                 "in_cell": [{"net": net, "ref": m} for r, net, m in inp.inside if r in refs]},
                **_cell_facts(inp, _celled(inp, refs)))


def withheld_facts(inp, refs, settings) -> dict:
    """The facts of a group whose share of movable nets with a placed far end is below `pins.placed_share_min`: no
    study, no map, no turn; how many ends are missing."""
    share = placed_share(inp, refs)
    return dict(_base(inp, refs, settings), present=None, searched=0, of=0, budget_out=False, first_map=True,
                rotations=[], best=0, routed=[], before=[],
                withheld=dict(share, share_min=settings.pins_placed_share_min))


def withheld(inp, refs, settings) -> bool:
    share = placed_share(inp, refs)
    return share["placed"] < share["of"] and share["placed"] < settings.pins_placed_share_min * share["of"]


def group_facts(inp, g, copper, settings) -> dict | None:
    """The facts of a group's `pins.remap` finding, or None when no pose saves `pins.gain_min` of the present total
    (a study that ran out before a first map always has one, saying so)."""
    refs = g.refs
    base = dict(_base(inp, refs, settings), present=g.present.to_json(), searched=g.searched, of=g.of,
                budget_out=g.budget_out, first_map=g.first_map)
    if not g.first_map:
        return dict(base, rotations=[], best=0, routed=[], before=[])
    if not g.results:
        return None
    best = min(range(len(g.results)), key=lambda i: (g.results[i].breakdown.total, i))
    gain = g.present.total - g.results[best].breakdown.total
    if gain <= 1e-9 or gain < settings.pins_gain_min * g.present.total:
        return None
    rows = []
    for r in g.results:
        moved = _map(inp, refs, g.present_assign, r.assign)
        rows.append(dict(r.breakdown.to_json(), turns=_turns(inp, r.poses), map=moved,
                         routed=sorted({m["net"] for m in moved} & copper), paths=_paths(r.paths),
                         breaks=_still(base["present_breaks"], r.assign)))
    out = dict(base, rotations=rows, best=best, routed=rows[best]["routed"], before=_paths(g.present_paths))
    celled = _celled(inp, refs)
    if celled is not None:
        t = next(t for t in rows[best]["turns"] if t["ref"] == celled)
        out.update(cell_rotation_deg=t["cell_rotation_deg"], module_rotation_deg=t["module_rotation_deg"])
    return out


def _moves(facts: dict, ref: str) -> list:
    """The pin moves of a finding's best map on part `ref`, by pin number: what a module's stamps compare."""
    rows = facts["rotations"]
    if not rows:
        return []
    return [{"from": m["from"]["pin"], "to": m["to"]["pin"]} for m in rows[facts["best"]]["map"] if m["ref"] == ref]


def _stamp_maps(inp, facts_of: list, kept: dict) -> None:
    """The facts (`facts_of`) of each `pins.remap` finding of a part in a cell whose module's other studied stamps have a
    different best map, or want the part at a different rotation in the module's frame (lever 2 re-lays every stamp),
    get `stamp_maps`: each stamp's cell, part, pin moves and `module_rotation_deg` (no moves and the present rotation
    for a stamp with no map worth having), by cell. `kept` {part in a cell: facts or None} of every studied group with a
    part in a cell; a stamp that ran out before a first map, or waits on placement, has no best map and is left out."""
    by_module: dict = {}
    for ref, facts in kept.items():
        if facts is not None and (facts.get("withheld") or not facts["first_map"]):
            continue
        c = inp.cell(inp.part(ref).cell)
        moves = _moves(facts, ref) if facts is not None else []
        rot = module_rotation(inp, ref, 0.0) if facts is None else \
            next(t for t in facts["rotations"][facts["best"]]["turns"] if t["ref"] == ref)["module_rotation_deg"]
        by_module.setdefault(c.module_key, []).append({"cell": c.name, "ref": ref, "moves": moves,
                                                       "module_rotation_deg": rot})
    for stamps in by_module.values():
        if len(stamps) < 2 or all((s["moves"], s["module_rotation_deg"]) == (stamps[0]["moves"], stamps[0]["module_rotation_deg"])
                                  for s in stamps):
            continue
        listed = sorted(stamps, key=lambda s: s["cell"])
        for f in facts_of:
            if f.get("cell") in {s["cell"] for s in listed}:
                f["stamp_maps"] = [dict(s, moves=list(s["moves"])) for s in listed]


def digest(inp, problems, copper, settings) -> str:
    """What a study's result depends on: the input, the problems, the nets with copper, the `[pins]` settings and the
    plane weight, the release and the findings' schemas."""
    from . import __version__, finding_text, reuse
    keys = {k: v for k, v in json.loads(settings.json()).items()
            if (k.startswith("pins_") and k not in _NOT_READ) or k == "score_crossing_plane"}
    text = "\0".join([str(CACHE_VERSION), __version__, finding_text.schemas_digest(), reuse.canonical(inp),
                      reuse.canonical(list(problems)), ",".join(sorted(copper)), json.dumps(keys, sort_keys=True)])
    return hashlib.sha256(text.encode()).hexdigest()


def _cached(path, d: str):
    from . import reuse
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    if doc.get("version") != CACHE_VERSION or doc.get("digest") != d:
        return None
    try:
        return [reuse.finding_from_json(v) for v in doc["findings"]]
    except (ValueError, KeyError, TypeError):
        return None


def _keep(path, d: str, findings) -> None:
    from . import reuse
    from .checkpoint import write_atomic
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, json.dumps({"version": CACHE_VERSION, "digest": d,
                                       "findings": [reuse.finding_to_json(f) for f in findings]}, separators=(",", ":")))
    except OSError:                         # a cache that cannot be written is not kept; the study's findings stand
        pass


def study_findings(pads, parts, names, quiet, partners, netclasses, settings, copper=frozenset(), cache=None,
                   step_ms: float = 0.0, cells=None, unplaced=()) -> tuple:
    """(findings, record) of the study of a placed board: `setup.pins` for each problem and for each net the present
    map puts on a pin its own rule bars (`present_breaks`), `pins.remap` for each group
    with a map worth having. `cache`, a path, holds the last study's digest and findings: a match is reused. `record` is
    what a run keeps: {"seconds", "reused", "groups", "parts"}, empty when nothing was studied. `step_ms` above 0 makes
    the core's clock a counted one (a test's)."""
    t0 = time.perf_counter()
    inp, problems = build(pads, parts, names, quiet, partners, netclasses, settings.pins_follow_series,
                          tuple(settings.pins_follow_prefixes), cells, unplaced)
    if inp is None and not problems:
        return [], {}
    d = digest(inp, problems, copper, settings)
    hit = _cached(cache, d) if cache is not None else None
    n_parts = len(inp.parts) if inp is not None else 0
    if hit is not None:
        return hit, {"seconds": round(time.perf_counter() - t0, 3), "reused": True, "groups": None, "parts": n_parts}
    found = [Finding(C.SETUP_PINS, p.facts()) for p in problems]
    groups = 0
    if inp is not None:
        from .pinmap_core import linked_groups, movable_count, problem_of, study_group
        for part in inp.parts:
            found += [Finding(C.SETUP_PINS, dict(Problem(part.ref, key, "", "present_breaks", net).facts(), pin=pin, rule=key))
                      for net, pin, key in part.slots.breaks]
        pb = problem_of(inp, settings.pins_exit_mm)
        kept = {}
        for refs in linked_groups(inp):
            if withheld(inp, refs, settings):
                facts = withheld_facts(inp, refs, settings)
            elif not movable_count(inp, refs):
                continue
            else:
                g = study_group(inp, refs, settings, step_ms=step_ms, pb=pb)
                found += [Finding(C.SETUP_PINS, Problem(ref, "", "", "no_legal_map", net).facts()) for ref, net in g.problems]
                facts = group_facts(inp, g, copper, settings)
            groups += 1
            celled = _celled(inp, refs)
            if celled is not None:
                kept[celled] = facts
            if facts is not None:
                found.append(facts)
        _stamp_maps(inp, [f for f in found if isinstance(f, dict)], kept)
        found = [Finding(C.PINS_REMAP, f) if isinstance(f, dict) else f for f in found]
    if cache is not None:
        _keep(cache, d, found)
    return found, {"seconds": round(time.perf_counter() - t0, 3), "reused": False, "groups": groups, "parts": n_parts}


def study_line(record: dict) -> str:
    """What a run or a preview says of the study, from its record."""
    if record.get("error"):
        return "the study failed with %s: %s" % (record["error"]["type"], record["error"]["message"])
    if record.get("reused"):
        return "%d part%s, the last study reused (%.2f s)" % (record["parts"], "" if record["parts"] == 1 else "s",
                                                                record["seconds"])
    return "%d part%s in %d group%s (%.2f s)" % (record["parts"], "" if record["parts"] == 1 else "s", record["groups"],
                                               "" if record["groups"] == 1 else "s", record["seconds"])


def placed_from_plan(board, plan) -> Placed:
    """The Placed of a resolved plan: every placed part where the placement put it (its pads at their airwire anchors,
    its courtyard's box), and whether its declaration lets it stand on the other face; every placed cell with its
    members as the occupancy holds them (an arranged cell's at their arranged places), its envelope (their courtyards and
    its own copper as committed), the rotation and face it was placed at (as stamped when the script does not place it),
    its module, its stamps and the arrangement it stands in (a member not placed is left out and named as missing); and
    the pads of the parts not placed."""
    occ = plan.occupancy
    either = {i.item.ref for i in board._placements() if i.kind == "part" and i.either}
    pads, parts, unplaced = [], {}, []
    for ref in sorted(occ.items):
        if not occ.geometry.has_footprint(ref):
            continue
        fp = occ.geometry.footprint(ref)
        if ref in occ.pending:
            unplaced += [(ref, p.number, p.net) for p in fp.pads if p.net and not p.no_connect]
            continue
        nc = {p.number for p in fp.pads if p.no_connect}
        for s in occ.items[ref].shapes:
            if s.kind in ("pad", "through") and s.owner == ref:
                pads.append(PlacedPad(ref, s.label, s.net, frozenset(s.layers), (tuple(s.poly),), s.box,
                                      occ.pad_anchor(ref, s.label), s.label in nc))
        g = occ.items[ref].reference
        parts[ref] = PlacedPart(ref, occ.courtyard_box(ref), g.rotation, g.face.value, ref in either, dict(fp.fields),
                                fp.cell or "")
    modules = cell_modules(occ.geometry)
    stamps = stamp_counts(modules)
    cells = {}
    for name, cg in sorted(occ.geometry.cells.items()):
        members = tuple(sorted(fp.ref for fp in cg.members if fp.ref in parts))
        if not members:
            continue
        own = [s.box for s in occ.copper if s.owner == name and s.kind not in ("viaban", "silk")]
        at = board._cell_placements.get(name)
        rotation, face = (at.rotation, at.face.value) if at is not None else (0.0, "front")
        arrangement = (at.arrangement if at is not None else "") or cg.arrangement or "default"
        module, key = modules[name]
        cells[name] = PlacedCell(name, members, Box.union([parts[r].courtyard for r in members] + own), float(rotation),
                                 face, face != "front", module, stamps[key], key, arrangement,
                                 tuple(sorted(fp.ref for fp in cg.members if fp.ref not in parts)))
    return Placed(pads, parts, cells, tuple(unplaced))


def plan_findings(board, plan) -> list:
    """The study of a resolved plan's board, its record kept on the plan (`plan.pin_study`): what the end of a resolve
    adds to its findings. A board whose parts carry no `Pm.PinPool` is not read."""
    if not has_pools(board.geometry.footprints):
        return []
    from .pairs import board_pairs
    placed = placed_from_plan(board, plan)
    quiet = frozenset(board._plane_nets()) | frozenset(board._free_nets)
    found, record = study_findings(placed.pads, placed.parts, board.geometry.pin_names, quiet,
                                   board_pairs(board.geometry.netclasses), board.geometry.netclasses, board.settings,
                                   copper_nets(board.geometry, plan), board.pin_study_cache, cells=placed.cells,
                                   unplaced=placed.unplaced)
    plan.pin_study = record
    return found


def contained(error: BaseException) -> bool:
    """Whether a study that raised `error` is a failed study rather than the end of the run: any Exception, and a panic
    in the native core. pyo3 raises a panic as pyo3_runtime.PanicException, a BaseException that no module exposes to
    import, so it is known by its type's name. A stop (stop.Stopped) and an interrupt are not contained."""
    return isinstance(error, Exception) or type(error).__name__ == "PanicException"


def study_failed(plan, error: BaseException) -> Finding:
    """A study that raised: its error kept on the plan's record (`plan.pin_study`) and said as a `setup.pins` finding.
    The study is advice; the resolve it ends stands without it."""
    plan.pin_study = {"error": {"type": type(error).__name__, "message": str(error)}}
    return Finding(C.SETUP_PINS, dict(Problem("", "", "", "study_failed", "").facts(), **plan.pin_study["error"]))


def plan_summary(board, plan, refs=None, settings=None) -> list:
    """Each studied group's present score and its best, with the pose and the map, for an explore's report and a longer
    study: no findings, nothing kept. `refs` keeps the groups holding any of those parts; `settings` replaces the
    board's (a longer budget)."""
    if not has_pools(board.geometry.footprints):
        return []
    from .pairs import board_pairs
    from .pinmap_core import linked_groups, movable_count, problem_of, study_group
    settings = settings or board.settings
    placed = placed_from_plan(board, plan)
    quiet = frozenset(board._plane_nets()) | frozenset(board._free_nets)
    inp, _ = build(placed.pads, placed.parts, board.geometry.pin_names, quiet, board_pairs(board.geometry.netclasses),
                   board.geometry.netclasses, settings.pins_follow_series, tuple(settings.pins_follow_prefixes),
                   placed.cells, placed.unplaced)
    if inp is None:
        return []
    pb = problem_of(inp, settings.pins_exit_mm)
    out = []
    for group in linked_groups(inp):
        if refs and not set(group) & set(refs):
            continue
        if withheld(inp, group, settings) or not movable_count(inp, group):
            continue                # it waits on placement: no map to give
        g = study_group(inp, group, settings, pb=pb)
        if not g.results:
            continue
        i = min(range(len(g.results)), key=lambda k: (g.results[k].breakdown.total, k))
        r = g.results[i]
        out.append({"refs": list(g.refs), "present": g.present.to_json(), "best": r.breakdown.to_json(), "rotation": i,
                    "turns": _turns(inp, r.poses), "map": _map(inp, g.refs, g.present_assign, r.assign),
                    "searched": g.searched, "of": g.of, "budget_out": g.budget_out})
    return out


def longer_advice(board, plan, advice: dict, budget_ms: int) -> tuple:
    """(better advice or None, the group's summary or None): the advice's parts studied again with `budget_ms` for each
    part (`placemat apply <id> --search`). The advice is better when its total is below the one it was given with.
    A study that raises raises here: the caller says so."""
    from dataclasses import replace
    s = replace(board.settings, pins_budget_ms=budget_ms)
    g = next((g for g in plan_summary(board, plan, refs=advice["refs"], settings=s)
              if set(g["refs"]) == set(advice["refs"])), None)
    if g is None or g["best"]["total"] >= advice["total"] - 1e-9:
        return None, g
    return {"refs": g["refs"], "rotation": g["rotation"], "turns": g["turns"], "map": g["map"],
            "total": g["best"]["total"], "weighted": g["best"]["weighted"]}, g
