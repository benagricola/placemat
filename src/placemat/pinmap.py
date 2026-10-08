"""The pin map study, end to end: from a placed board to its `pins.remap` and `setup.pins` findings.

Parts with `Pm.PinPool` generate candidate assignments from the study's
crossing and bend objective. With a current plan, complete physical finalists
are judged by common placement validity and score before advice is offered.
The standalone generator retains its diagnostic maps and gain, but offers no
executable map or turn without a common current-board judgment.

Plan-bound findings, explore summaries and longer advice rebuild that physical
context. Generator-only diagnostics may use `Board.pin_study_cache`; common
finalist judgments are never reused from it. Nothing here writes a board or
certifies routed terminal-contract equivalence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from .findings import Finding, FindingCause as C

from .pinmap_core import budget_of
from .pinmap_input import Placed, PlacedCell, PlacedPad, PlacedPart, build, cell_modules, stamp_counts
from .pinmap_rules import Problem, has_pools, natural
from .values import Box

CACHE_VERSION = 5
# `[pins]` settings a kept result does not depend on: the explore's and the probe's, and the wall-clock guard (a study
# that trips it is never kept, so a kept result is always complete)
_NOT_READ = ("pins_explore_top", "pins_probe_budget_steps", "pins_guard_ms")


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
        rec = {"ref": ref, "turn_deg": turn, "rotation_deg": rotation % 360.0, "face": face,
               "flip": bool(flip), "pivot": [part.cx, part.cy]}
        if part.cell:
            c = inp.cell(part.cell)
            rec.update(_cell_facts(inp, ref), cell_rotation_deg=(c.rotation + turn) % 360.0,
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
    """The `breaks` an assignment keeps. The core offers the present map only when it keeps every rule, so a row of
    its gives none."""
    return [b for b in breaks if (b["ref"], b["pin"]) in assign.get(b["net"], ())]


def _base(inp, refs, settings) -> dict:
    """The facts every `pins.remap` finding of a group has, its study's aside."""
    lead = inp.part(refs[0])
    at = lead.at or (lead.cx, lead.cy)
    return dict({"ref": refs[0], "refs": list(refs), "at": [round(at[0], 3), round(at[1], 3)],
                 "budget_steps": budget_of(settings, refs),
                 "held": [{"ref": r, "net": h.net, "pin": h.pin, "name": inp.names.get(r, {}).get(h.pin, ""), "why": h.why}
                          for r in refs for h in inp.part(r).slots.held],
                 "present_breaks": _breaks(inp, refs), "unplaced_ends": _waiting(inp, refs),
                 "in_cell": [{"net": net, "ref": m} for r, net, m in inp.inside if r in refs]},
                **_cell_facts(inp, _celled(inp, refs)))


def withheld_facts(inp, refs, settings) -> dict:
    """The facts of a group whose share of movable nets with a placed far end is below `pins.placed_share_min`: no
    study, no map, no turn; how many ends are missing."""
    share = placed_share(inp, refs)
    return dict(_base(inp, refs, settings), present=None, searched=0, of=0, budget_out=False, first_map=True, steps=0,
                rotations=[], best=0, routed=[], before=[],
                withheld=dict(share, share_min=settings.pins_placed_share_min))


def slow_facts(g) -> dict:
    """The facts of a `setup.pins` `study_slow` warning: the group's study ran past its wall-clock guard (`guard_ms`)
    after `steps` of its `budget_steps`, and gives no map."""
    return dict(Problem(g.refs[0], "", "", "study_slow", "").facts(), refs=list(g.refs), guard_ms=g.guard_ms,
                steps=g.steps, budget_steps=g.budget_steps)


def withheld(inp, refs, settings) -> bool:
    share = placed_share(inp, refs)
    return share["placed"] < share["of"] and share["placed"] < settings.pins_placed_share_min * share["of"]


def group_facts(inp, g, copper, settings, evaluator=None) -> dict | None:
    """The facts of a group's `pins.remap` finding, or None when no pose saves `pins.gain_min` of the present total
    (a study that ran out before a first map always has one, saying so). A group whose present map breaks a pin rule
    (`present_breaks`) always has one: its best map moves the barred nets, whatever that costs."""
    refs = g.refs
    base = dict(_base(inp, refs, settings), present=g.present.to_json(), searched=g.searched, of=g.of,
                budget_out=g.budget_out, first_map=g.first_map, steps=g.steps)
    if not g.first_map:
        return dict(base, rotations=[], best=0, routed=[], before=[])
    if not g.results:
        return None
    selection = evaluator.select(inp, g) if evaluator is not None else None
    if selection is not None:
        if not selection.actionable and selection.reason != 'unmeasured candidate':
            return None
        best = selection.best
        base.update(score_scope='placement', common=selection.record())
        base['present'] = dict(base['present'], generator=dict(base['present']), total=selection.baseline.record()['total'])
    else:
        best = min(range(len(g.results)), key=lambda i: (g.results[i].breakdown.total, i))
        gain = g.present.total - g.results[best].breakdown.total
        if (gain <= 1e-9 or gain < settings.pins_gain_min * g.present.total) and not base["present_breaks"]:
            return None
        base.update(score_scope='generator', generator_gain=gain, common_unavailable=True)
    rows = []
    for r in g.results:
        moved = _map(inp, refs, g.present_assign, r.assign)
        rows.append(dict(r.breakdown.to_json(), turns=_turns(inp, r.poses), map=moved,
                         routed=sorted({m["net"] for m in moved} & copper), paths=_paths(r.paths),
                         breaks=_still(base["present_breaks"], r.assign), groups=[x.to_json() for x in r.groups]))
        if selection is not None:
            rows[-1].update(generator=r.breakdown.to_json(), common=selection.finalists[len(rows) - 1].record(),
                            total=selection.finalists[len(rows) - 1].record()['total'])
    out = dict(base, rotations=rows, best=best, routed=rows[best]["routed"], before=_paths(g.present_paths),
               present_groups=[x.to_json() for x in g.present_groups])
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
        if facts is not None and (facts.get("withheld") or not facts["first_map"]
                                  or (facts.get("score_scope") == "placement"
                                      and not facts["common"]["actionable"])):
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
    shared generator weights, the release and the findings' schemas."""
    from . import __version__, finding_text, reuse
    keys = {k: v for k, v in json.loads(settings.json()).items()
            if (k.startswith("pins_") and k not in _NOT_READ) or k in ("score_crossing_plane", "score_crossing", "score_crossing_pair_net", "score_impedance")}
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
                   cells=None, unplaced=(), evaluator=None) -> tuple:
    """(findings, record) of the study of a placed board: `setup.pins` for each problem and for each net the present
    map puts on a pin its own rule bars (`present_breaks`), `pins.remap` for each group
    with a map worth having, and `setup.pins` `study_slow` for each group past its wall-clock guard (no map). `cache`, a
    path, holds the last study's digest and findings: a match is reused; a study with a group past its guard is not
    kept. Without `evaluator`, findings are explicitly generator-only diagnostics
    and cannot produce executable advice. An evaluator judges complete physical
    finalists in the current plan; those judgments bypass the findings cache.
    `record` is what a run keeps: {"seconds", "reused", "groups", "parts"}, empty when nothing was studied."""
    t0 = time.perf_counter()
    inp, problems = build(pads, parts, names, quiet, partners, netclasses, settings.pins_follow_series,
                          tuple(settings.pins_follow_prefixes), cells, unplaced)
    if inp is None and not problems:
        return [], {}
    d = digest(inp, problems, copper, settings)
    hit = _cached(cache, d) if cache is not None and evaluator is None else None
    n_parts = len(inp.parts) if inp is not None else 0
    if hit is not None:
        return hit, {"seconds": round(time.perf_counter() - t0, 3), "reused": True, "groups": None, "parts": n_parts}
    found = [Finding(C.SETUP_PINS, p.facts()) for p in problems]
    groups, slow = 0, False
    if inp is not None:
        from .pinmap_core import linked_groups, movable_count, problem_of, study_group
        for part in inp.parts:
            found += [Finding(C.SETUP_PINS, dict(Problem(part.ref, key, "", "present_breaks", net).facts(), pin=pin, rule=key))
                      for net, pin, key in part.slots.breaks]
        pb = problem_of(inp, settings.pins_exit_mm)
        kept = {}
        selected = []
        for refs in linked_groups(inp):
            if withheld(inp, refs, settings):
                facts = withheld_facts(inp, refs, settings)
            elif not movable_count(inp, refs):
                continue
            else:
                g = study_group(inp, refs, settings, pb=pb)
                if g.slow:
                    found.append(Finding(C.SETUP_PINS, slow_facts(g)))
                    groups += 1
                    slow = True
                    continue
                found += [Finding(C.SETUP_PINS, Problem(ref, "", "", "no_legal_map", net).facts()) for ref, net in g.problems]
                facts = group_facts(inp, g, copper, settings, evaluator)
                if evaluator is not None and facts is not None and facts.get("common", {}).get("actionable"):
                    selected.append((g.refs, g.results[facts["best"]]))
            groups += 1
            celled = _celled(inp, refs)
            if celled is not None:
                kept[celled] = facts
            if facts is not None:
                found.append(facts)
        facts_of = [f for f in found if isinstance(f, dict)]
        if evaluator is None:
            _stamp_maps(inp, facts_of, kept)
        else:
            baseline = evaluator.evaluate(inp)
            combined = evaluator.evaluate(inp, tuple(selected))
            proved = (bool(selected) and not baseline.refusals and not combined.refusals
                      and not baseline.validity.unmeasured and not combined.validity.unmeasured
                      and combined.key < baseline.key)
            if proved:
                _stamp_maps(inp, facts_of, kept)
            for facts in facts_of:
                if not facts.get("cell"):
                    continue
                facts["stamp_common"] = {"baseline": baseline.record(), "final": combined.record(),
                                          "actionable": proved}
                if not proved or facts.get("stamp_maps"):
                    facts["stamp_refusal"] = {"code": "module_stamp_proof_missing" if not proved else
                                               "module_stamp_choices_incompatible", "facts": {"cell": facts["cell"]}}

        found = [Finding(C.PINS_REMAP, f) if isinstance(f, dict) else f for f in found]
    if cache is not None and not slow and evaluator is None:
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
                                fp.cell or "", occ.courtyard_outline(ref))
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
                                 tuple(sorted(fp.ref for fp in cg.members if fp.ref not in parts)),
                                 tuple(p for r in members for p in parts[r].outline)
                                 + tuple(p for b in own for p in ((b.left, b.top), (b.right, b.top), (b.right, b.bottom),
                                                                  (b.left, b.bottom))))
    return Placed(pads, parts, cells, tuple(unplaced))


def plan_findings(board, plan) -> list:
    """The study of a resolved plan's board, its record kept on the plan (`plan.pin_study`): what the end of a resolve
    adds to its findings. A board whose parts carry no `Pm.PinPool` is not read."""
    if not has_pools(board.geometry.footprints):
        return []
    from .pairs import board_pairs
    placed = placed_from_plan(board, plan)
    quiet = frozenset(board._plane_nets()) | frozenset(board._free_nets)
    from .pinmap_common import Finalists
    found, record = study_findings(placed.pads, placed.parts, board.geometry.pin_names, quiet,
                                   board_pairs(board.geometry.netclasses), board.geometry.netclasses, board.settings,
                                   copper_nets(board.geometry, plan), board.pin_study_cache, cells=placed.cells,
                                   unplaced=placed.unplaced, evaluator=Finalists(board, plan))
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


def _plan_input(board, plan, settings):
    from .pairs import board_pairs
    placed = placed_from_plan(board, plan)
    quiet = frozenset(board._plane_nets()) | frozenset(board._free_nets)
    inp, _ = build(placed.pads, placed.parts, board.geometry.pin_names, quiet, board_pairs(board.geometry.netclasses),
                   board.geometry.netclasses, settings.pins_follow_series, tuple(settings.pins_follow_prefixes),
                   placed.cells, placed.unplaced)
    return inp


def _plan_choices(board, plan, refs=None, settings=None):
    """Each studied group's present score and its best, with the pose and the map, for an explore's report and a longer
    study: no findings, nothing kept. A group past its wall-clock guard has no map: `slow` true, with `guard_ms`,
    `steps` and `budget_steps`. `before` and `paths` are the group's airwires under the present map and the best, as a
    `pins.remap` finding's `before` and its rotation's `paths` are, for the studio to draw. `refs` keeps the groups holding any of those parts; `settings` replaces the
    board's (a longer budget)."""
    if not has_pools(board.geometry.footprints):
        return []
    from .pinmap_core import linked_groups, movable_count, problem_of, study_group
    settings = settings or board.settings
    inp = _plan_input(board, plan, settings)
    if inp is None:
        return []
    pb = problem_of(inp, settings.pins_exit_mm)
    from .pinmap_common import Finalists
    evaluator = Finalists(board, plan, settings)
    out = []
    for group in linked_groups(inp):
        if refs and not set(group) & set(refs):
            continue
        if withheld(inp, group, settings) or not movable_count(inp, group):
            continue                # it waits on placement: no map to give
        g = study_group(inp, group, settings, pb=pb)
        if g.slow:
            out.append({"refs": list(g.refs), "slow": True, "guard_ms": g.guard_ms, "steps": g.steps,
                        "budget_steps": g.budget_steps})
            continue
        if not g.results:
            continue                # no matching: no map to give
        selection = evaluator.select(inp, g)
        out.append((g, selection))
    return inp, out


def plan_summary(board, plan, refs=None, settings=None) -> list:
    """Independent group judgments in the current common placement context.

    Generator breakdowns are diagnostics; adoption of several groups requires
    a separate simultaneous judgment. No routed contract is certified here.
    """
    choices = _plan_choices(board, plan, refs, settings)
    if not choices:
        return []
    inp, groups = choices
    out = []
    for entry in groups:
        if isinstance(entry, dict):
            out.append(entry)
            continue
        g, selection = entry
        i = selection.best
        r = g.results[i]
        out.append({"refs": list(g.refs), "present": selection.baseline.record(),
                    "best": selection.finalists[i].record(), "common": selection.record(),
                    "score_scope": "placement", "independent": True,
                    "generator": {"present": g.present.to_json(), "best": r.breakdown.to_json()},
                    "rotation": i, "turns": _turns(inp, r.poses),
                    "map": _map(inp, g.refs, g.present_assign, r.assign),
                    "searched": g.searched, "of": g.of, "budget_out": g.budget_out, "steps": g.steps,
                    "budget_steps": g.budget_steps, "before": _paths(g.present_paths), "paths": _paths(r.paths)})
    return out


def plan_remap(board, plan):
    """Judge chosen independent finalists simultaneously before placement ranking.

    This is a placement proposal, not a routed writer or phase equivalence proof.
    No sum of independent gains certifies the combined physical candidate.
    """
    proposal = _plan_remap_proposal(board, plan)
    return proposal[0] if proposal is not None else None


def _plan_remap_proposal(board, plan):
    """Keep the exact combined finalist available to a live routing worker.

    The returned data is a placement proposal, never routing authority.
    Public callers receive only its diagnostic through ``plan_remap``.
    """
    choices = _plan_choices(board, plan)
    if not choices:
        return None
    inp, studies = choices
    from .pinmap_common import Finalists
    evaluator = Finalists(board, plan)
    baseline = evaluator.evaluate(inp)
    picked, groups = [], []
    for entry in studies:
        if isinstance(entry, dict):
            continue
        group, selection = entry
        if not selection.actionable:
            continue
        candidate = group.results[selection.best]
        picked.append((group.refs, candidate))
        groups.append({"refs": list(group.refs), "present": selection.baseline.total,
                       "best": selection.finalists[selection.best].total,
                       "map": _map(inp, group.refs, group.present_assign, candidate.assign),
                       "turns": _turns(inp, candidate.poses), "reason": selection.reason})
    final = evaluator.evaluate(inp, tuple(picked))
    measured = not (baseline.refusals or final.refusals or baseline.validity.unmeasured or final.validity.unmeasured)
    # Ranking's scalar shortcut is allowed only within the same validity tier.
    gain = baseline.total - final.total if measured else 0.0
    actionable = bool(picked) and measured and final.key < baseline.key
    scalar_gain = gain if actionable and final.validity.key() == baseline.validity.key() else 0.0
    diagnostic = {"scope": "placement", "saving": scalar_gain, "gain": gain,
            "baseline": baseline.record(), "final": final.record(),
            "actionable": actionable, "groups": groups,
            "reason": ("validity repair" if actionable and final.validity.key() < baseline.validity.key()
                       else "common objective gain" if actionable else "no certified combined improvement"),
            "routed_comparison": {"code": "logical_terminal_proof_missing", "facts": {}}}
    return diagnostic, inp, tuple(picked), final


def _incoming_advice_problem(advice):
    """Validate persisted data before reconstructing any physical proposal."""
    import math
    def refusal(field, code):
        return {"code": code, "facts": {"field": field}}
    if not isinstance(advice, dict):
        return refusal("advice", "incoming_advice_invalid")
    refs = advice.get("refs")
    if (not isinstance(refs, (list, tuple)) or not refs
            or any(not isinstance(ref, str) or not ref for ref in refs) or len(set(refs)) != len(refs)):
        return refusal("refs", "incoming_refs_invalid")
    maps = advice.get("map")
    if not isinstance(maps, (list, tuple)):
        return refusal("map", "incoming_map_invalid")
    for move in maps:
        if (not isinstance(move, dict) or not isinstance(move.get("net"), str) or not move["net"]
                or move.get("ref") not in refs or not isinstance(move.get("to"), dict)
                or not isinstance(move["to"].get("pin"), str) or not move["to"]["pin"]):
            return refusal("map", "incoming_map_invalid")
    turns = advice.get("turns")
    if not isinstance(turns, (list, tuple)):
        return refusal("turns", "incoming_pose_invalid")
    seen = set()
    for turn in turns:
        if not isinstance(turn, dict):
            return refusal("turns", "incoming_pose_invalid")
        rotation = turn.get("rotation_deg")
        try:
            finite = (not isinstance(rotation, bool) and isinstance(rotation, (int, float))
                      and math.isfinite(rotation))
        except OverflowError:
            finite = False
        ref = turn.get("ref")
        if (ref not in refs or ref in seen or turn.get("face") not in ("front", "back")
                or not finite):
            return refusal("turns", "incoming_pose_invalid")
        seen.add(ref)
    return None


def longer_advice(board, plan, advice: dict, budget_steps: int) -> tuple:
    """(better advice or None, the group's summary or None): the advice's parts studied again with `budget_steps` for
    each part (`placemat apply <id> --search`), its wall-clock guard scaled with it. The advice is better when its total
    is below the incoming map rejudged in this same current context, never its
    stored total. Legacy generator advice and unsupported cell pose rebasing
    carry structured refusal codes. A study that raises raises here: the caller says so."""
    problem = _incoming_advice_problem(advice)
    if problem is not None:
        return None, {"incoming_refusal": problem}
    from dataclasses import replace
    was = board.settings
    s = replace(was, pins_budget_steps=budget_steps, pins_guard_ms=was.pins_guard_ms * budget_steps / was.pins_budget_steps)
    g = next((g for g in plan_summary(board, plan, refs=advice["refs"], settings=s)
              if set(g["refs"]) == set(advice["refs"])), None)
    if g is None or g.get("slow") or not g["common"]["actionable"]:
        return None, g
    if advice.get("score_scope") != "placement":
        g["incoming_refusal"] = {"code": "common_proof_missing", "facts": {}}
        return None, g
    inp = _plan_input(board, plan, s)
    if inp is None:
        return None, g
    from types import SimpleNamespace
    from .pinmap_common import Finalists
    assign = {net.net: tuple(net.ends) for net in inp.nets}
    for move in advice.get("map", ()):
        if not {"net", "ref", "to"} <= move.keys() or "pin" not in move["to"] or move["ref"] not in advice["refs"]:
            g["incoming_refusal"] = {"code": "incoming_map_invalid", "facts": {}}
            return None, g
        net, ref = move["net"], move["ref"]
        if net not in assign:
            g["incoming_refusal"] = {"code": "undeclared_net", "facts": {"net": net}}
            return None, g
        assign[net] = tuple((owner, move["to"]["pin"] if owner == ref else number)
                            for owner, number in assign[net])
    poses = []
    by_ref = {part.ref: part for part in inp.parts}
    for pose in advice.get("turns", ()):
        if (pose.get("ref") not in by_ref or not {"face", "rotation_deg"} <= pose.keys()
                or pose["face"] not in ("front", "back")):
            g["incoming_refusal"] = {"code": "incoming_pose_invalid", "facts": {"ref": pose.get("ref")}}
            return None, g
        part = by_ref[pose["ref"]]
        if part.cell:
            g["incoming_refusal"] = {"code": "cell_advice_rebase_unavailable", "facts": {"ref": part.ref}}
            return None, g
        flip = pose["face"] != part.face
        turn = pose["rotation_deg"] + part.rotation if flip else pose["rotation_deg"] - part.rotation
        poses.append((part.ref, turn, flip))
    incoming = Finalists(board, plan, s).evaluate(inp, ((tuple(advice["refs"]),
                                                       SimpleNamespace(assign=assign, poses=tuple(poses))),))
    g["incoming"] = incoming.record()
    if incoming.refusals or incoming.validity.unmeasured:
        g["incoming_refusal"] = (incoming.refusals[0] if incoming.refusals else
                                 {"code": "common_judgment_unmeasured",
                                  "facts": {"subjects": list(incoming.validity.unmeasured)}})
        return None, g
    from .score import Validity
    best = g["best"]
    if (Validity(**best["validity"]).key(), best["total"]) >= incoming.key:
        return None, g
    return {"refs": g["refs"], "rotation": g["rotation"], "turns": g["turns"], "map": g["map"],
            "total": best["total"], "score_scope": "placement", "common": best,
            "generator": g["generator"]["best"]}, g
