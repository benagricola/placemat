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

from .pinmap_core import study
from .pinmap_input import PlacedPad, PlacedPart, build, placed_from_geometry
from .pinmap_rules import Problem, has_pools, natural

CACHE_VERSION = 1
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
    out = []
    for ref, turn, flip in poses:
        part = inp.part(ref)
        face = part.face if not flip else ("back" if part.face == "front" else "front")
        out.append({"ref": ref, "turn_deg": round(turn, 3), "rotation_deg": round((part.rotation + turn) % 360.0, 3),
                    "face": face, "flip": bool(flip)})
    return out


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


def group_facts(inp, g, copper, settings) -> dict | None:
    """The facts of a group's `pins.remap` finding, or None when no pose saves `pins.gain_min` of the present total
    (a study that ran out before a first map always has one, saying so)."""
    refs = g.refs
    lead = inp.part(refs[0])
    base = {"ref": refs[0], "refs": list(refs), "at": [round(lead.cx, 3), round(lead.cy, 3)],
            "present": g.present.to_json(), "searched": g.searched, "of": g.of, "budget_out": g.budget_out,
            "first_map": g.first_map, "budget_ms": settings.pins_budget_ms * len(refs),
            "held": [{"ref": r, "net": h.net, "pin": h.pin, "name": inp.names.get(r, {}).get(h.pin, ""), "why": h.why}
                     for r in refs for h in inp.part(r).slots.held],
            "present_breaks": _breaks(inp, refs)}
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
    return dict(base, rotations=rows, best=best, routed=rows[best]["routed"], before=_paths(g.present_paths))


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
                   step_ms: float = 0.0) -> tuple:
    """(findings, record) of the study of a placed board: `setup.pins` for each problem and for each net the present
    map puts on a pin its own rule bars (`present_breaks`), `pins.remap` for each group
    with a map worth having. `cache`, a path, holds the last study's digest and findings: a match is reused. `record` is
    what a run keeps: {"seconds", "reused", "groups", "parts"}, empty when nothing was studied. `step_ms` above 0 makes
    the core's clock a counted one (a test's)."""
    t0 = time.perf_counter()
    inp, problems = build(pads, parts, names, quiet, partners, netclasses, settings.pins_follow_series,
                          tuple(settings.pins_follow_prefixes))
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
        results = study(inp, settings, step_ms)
        groups = len(results)
        for part in inp.parts:
            found += [Finding(C.SETUP_PINS, dict(Problem(part.ref, key, "", "present_breaks", net).facts(), pin=pin, rule=key))
                      for net, pin, key in part.slots.breaks]
        for g in results:
            found += [Finding(C.SETUP_PINS, Problem(ref, "", "", "no_legal_map", net).facts()) for ref, net in g.problems]
            facts = group_facts(inp, g, copper, settings)
            if facts is not None:
                found.append(Finding(C.PINS_REMAP, facts))
    if cache is not None:
        _keep(cache, d, found)
    return found, {"seconds": round(time.perf_counter() - t0, 3), "reused": False, "groups": groups, "parts": n_parts}


def geometry_findings(geometry, settings, quiet=frozenset(), either=frozenset(), cache=None, step_ms: float = 0.0) -> tuple:
    """`study_findings` of a board where its file has its parts (a laid board read from disk, a bench case)."""
    if not has_pools(geometry.footprints):
        return [], {}
    from .pairs import board_pairs
    pads, parts = placed_from_geometry(geometry, either)
    return study_findings(pads, parts, geometry.pin_names, quiet, board_pairs(geometry.netclasses), geometry.netclasses,
                          settings, copper_nets(geometry), cache, step_ms)


def study_line(record: dict) -> str:
    """What a run or a preview says of the study, from its record."""
    if record.get("error"):
        return "the study failed with %s: %s" % (record["error"]["type"], record["error"]["message"])
    if record.get("reused"):
        return "%d part%s, the last study reused (%.2f s)" % (record["parts"], "" if record["parts"] == 1 else "s",
                                                                record["seconds"])
    return "%d part%s in %d group%s (%.2f s)" % (record["parts"], "" if record["parts"] == 1 else "s", record["groups"],
                                               "" if record["groups"] == 1 else "s", record["seconds"])


def placed_from_plan(board, plan) -> tuple:
    """(pads, {ref: PlacedPart}) of a resolved plan: every placed part where the placement put it (its pads at their
    airwire anchors, its courtyard's box), and whether its declaration lets it stand on the other face."""
    occ = plan.occupancy
    either = {i.item.ref for i in board._placements() if i.kind == "part" and i.either}
    pads, parts = [], {}
    for ref in sorted(occ.items):
        if ref in occ.pending or not occ.geometry.has_footprint(ref):
            continue
        fp = occ.geometry.footprint(ref)
        nc = {p.number for p in fp.pads if p.no_connect}
        for s in occ.items[ref].shapes:
            if s.kind in ("pad", "through") and s.owner == ref:
                pads.append(PlacedPad(ref, s.label, s.net, frozenset(s.layers), (tuple(s.poly),), s.box,
                                      occ.pad_anchor(ref, s.label), s.label in nc))
        g = occ.items[ref].reference
        parts[ref] = PlacedPart(ref, occ.courtyard_box(ref), g.rotation, g.face.value, ref in either, dict(fp.fields))
    return pads, parts


def plan_findings(board, plan) -> list:
    """The study of a resolved plan's board, its record kept on the plan (`plan.pin_study`): what the end of a resolve
    adds to its findings. A board whose parts carry no `Pm.PinPool` is not read."""
    if not has_pools(board.geometry.footprints):
        return []
    from .pairs import board_pairs
    pads, parts = placed_from_plan(board, plan)
    quiet = frozenset(board._plane_nets()) | frozenset(board._free_nets)
    found, record = study_findings(pads, parts, board.geometry.pin_names, quiet, board_pairs(board.geometry.netclasses),
                                   board.geometry.netclasses, board.settings, copper_nets(board.geometry, plan),
                                   board.pin_study_cache)
    plan.pin_study = record
    return found


def study_failed(plan, error: Exception) -> Finding:
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
    from .pinmap_core import linked_groups, problem_of, study_group
    settings = settings or board.settings
    pads, parts = placed_from_plan(board, plan)
    quiet = frozenset(board._plane_nets()) | frozenset(board._free_nets)
    inp, _ = build(pads, parts, board.geometry.pin_names, quiet, board_pairs(board.geometry.netclasses),
                   board.geometry.netclasses, settings.pins_follow_series, tuple(settings.pins_follow_prefixes))
    if inp is None:
        return []
    pb = problem_of(inp, settings.pins_exit_mm)
    out = []
    for group in linked_groups(inp):
        if refs and not set(group) & set(refs):
            continue
        g = study_group(inp, group, settings, pb=pb)
        if not g.results:
            continue
        i = min(range(len(g.results)), key=lambda k: (g.results[k].breakdown.total, k))
        r = g.results[i]
        out.append({"refs": list(g.refs), "present": g.present.to_json(), "best": r.breakdown.to_json(), "rotation": i,
                    "turns": _turns(inp, r.poses), "map": _map(inp, g.refs, g.present_assign, r.assign),
                    "searched": g.searched, "of": g.of, "budget_out": g.budget_out})
    return out
