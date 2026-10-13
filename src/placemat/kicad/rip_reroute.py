"""Rip and reroute of earlier calls' copper (docs/superpowers/specs/2026-10-12-rip-reroute-design.md). After a router
call of a phase leaves a connection open and the router names another net's copper an earlier call laid as blocking
it, that net's router copper is taken off, the blocked connection routed, and the removed connections routed again at
their own phases' widths, layers and clearance; the result is kept only when nothing judged before is worse.
Everything returned here is a value or a record; route.phase_lines renders them."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import subprocess
import time

from . import pour_join
from .phase_run import (Call, TaskRun, _end_pair, fresh_output, is_clean, joined_pairs, judge_obligations,
                        phase_input_drc, phase_neck, phase_settings, phase_widths, records_of, route_tasks, superseded)
from .route import RouteRefused, RouterFailed

TASK_CALLS = ("tasks", "bus_tasks", "pour")
NET_CALLS = ("nets", "rest", "bus")


@dataclass(frozen=True)
class Named:
    net: str
    found_by: str

    def record(self) -> dict:
        return {"net": self.net, "found_by": self.found_by}


@dataclass(frozen=True)
class Blocked:
    net: str
    named: tuple
    connections: tuple = ()


def _named(blocked_by) -> list:
    """The nets an evidence record's `blocked_by` names as other copper (KRT docs/connections.md, "Failure evidence"):
    `preexisting` entries, and `static` entries of kind `track` (a net's tracks the failed search's frontier met).
    Pads and this call's own routed copper (`frontier`) are not earlier copper."""
    out = []
    for b in blocked_by or ():
        if b.get("net") and (b.get("found_by") == "preexisting"
                             or (b.get("found_by") == "static" and b.get("kind") == "track")):
            out.append(Named(b["net"], b["found_by"]))
    return out


def _once(named) -> tuple:
    seen, out = set(), []
    for n in named:
        if n.net not in seen:
            seen.add(n.net)
            out.append(n)
    return tuple(out)


def blocked_of(kind: str, records=(), summary: dict | None = None) -> list:
    """The blocked units of one call: for a task call (`tasks`, `bus_tasks`, a `pour` call's tasks) each net with a
    `failed` record, its failed tasks as the unit's connections; for a whole-net call each net in the summary's
    `net_evidence` (a net named only in `blockers` may have joined later in the call, so it is no unit), named from
    it and from the summary's `blockers` entries of stage `preexisting` (KRT
    route.py:4615-4625: the router's pre-existing blocker names, kept there when a reconcile pass replaced the net's
    evidence). A unit nothing names is left out; a pair call has none."""
    if kind in TASK_CALLS:
        units = {}
        for r in records:
            if r.get("status") != "failed":
                continue
            conns, named = units.setdefault(r["net"], ([], []))
            conns.append({k: r[k] for k in ("net", "from", "to", "widths")})
            named.extend(_named((r.get("evidence") or {}).get("blocked_by")))
        return [Blocked(n, _once(named), tuple(conns)) for n, (conns, named) in units.items() if named]
    if kind in NET_CALLS:
        summary = summary or {}
        evidence = summary.get("net_evidence") or {}
        pre = {}
        for b in summary.get("blockers") or ():
            if b.get("stage") == "preexisting":
                pre.setdefault(b.get("net"), []).extend(Named(x["net"], "preexisting")
                                                         for x in b.get("blocked_by") or () if x.get("net"))
        out = []
        for n in evidence:                  # the nets still failed at the end of the call (KRT docs/connections.md)
            named = _once(_named((evidence.get(n) or {}).get("blocked_by")) + pre.get(n, []))
            if named:
                out.append(Blocked(n, named))
        return out
    return []


def router_nets(board, script_keys) -> dict:
    """{net: count} of the router copper on `board`: its tracks, arcs and vias that are not script copper (the route's
    input board, `script_keys` = route.copper_items of it)."""
    from .route import copper_items
    out = {}
    for k in copper_items(board) - set(script_keys):
        out[k[1]] = out.get(k[1], 0) + 1
    return out


def laid_nets(before, after) -> set:
    """The nets a call laid copper on: copper on its output board `after` that its input board `before` has not."""
    from .route import copper_items
    return {k[1] for k in copper_items(after) - copper_items(before)}


def victims_of(unit, *, router_nets, laid_by_call, pour_nets, pair_nets, excluded) -> tuple:
    """The named nets an attempt may move, and the others with why not, in the router's order (spec "What triggers an
    attempt"): never the unit's own net, a net with no router copper (script copper only), a net the failing call laid
    copper on, a pour net, a pair net or an excluded net."""
    victims, skipped = [], []
    for n in unit.named:
        reason = ("own_net" if n.net == unit.net else
                  "no_router_copper" if not router_nets.get(n.net) else
                  "routed_by_call" if n.net in laid_by_call else
                  "pour_net" if n.net in pour_nets else
                  "pair_net" if n.net in pair_nets else
                  "excluded" if n.net in excluded else None)
        if reason:
            skipped.append({"net": n.net, "reason": reason})
        else:
            victims.append(n.net)
    return tuple(victims), tuple(skipped)


def remove_copper(src, dst, victims, script_keys) -> dict:
    """`src` written to `dst` without the victims' router copper: every track, arc and via of a net in `victims` that
    is not script copper, taken off with board.Delete (CLAUDE.md: never board.Remove), after group.RemoveItem when it
    is grouped. `src` is left as it was. Returns what was taken off."""
    import shutil
    from .quiet import import_pcbnew, quiet_stderr
    from .route import _copy_project, _load_board, copper_key
    from .route_cleanup import _delete
    pcbnew = import_pcbnew()
    shutil.copy(src, dst)
    _copy_project(src, dst)
    with quiet_stderr():
        board = _load_board(str(dst))
    out, mm = {"tracks": 0, "arcs": 0, "vias": 0}, 0.0
    for t in list(board.GetTracks()):
        if t.GetNetname() not in victims:
            continue
        key = copper_key(pcbnew, t)
        if key in script_keys:
            continue
        out[{"segment": "tracks", "arc": "arcs", "via": "vias"}[key[0]]] += 1
        if key[0] != "via":
            mm += pcbnew.ToMM(t.GetLength())
        _delete(board, t)                   # group.RemoveItem, then board.Delete (route_cleanup.py:200-204)
    with quiet_stderr():
        board.Save(str(dst))
    return dict(out, track_mm=round(mm, 3))


@dataclass(frozen=True)
class Move:
    owner: int                  # the phase index whose settings it is rerouted at
    obligation: dict            # {"net", "from", "to", "widths"}
    asked: bool                 # an obligation of `owner`; False: a join no phase asks (spec, "unasked")
    amps: float | None = None   # the owner task's current (current_paths), so the reroute's width rows say "current"


def asked_moves(victims, asked, upto, joined, selections=None) -> tuple:
    """The obligations of phases 0..upto on a victim net that are joined on the failing call's board (`joined[k]`,
    aligned with `asked[k]`), each pad pair once, owned by the earliest phase that asks it (spec "The removed
    connections"), each with the current of its owner's task (task_amps) when `selections` are given. (moves, None),
    or ([], reason) when one cannot be a task: `victim_end_not_pad`, `victim_width_unknown`. pour_served obligations
    are on pour nets, never victims."""
    from .phase_run import _pair_key
    out, seen = [], set()
    for k in range(upto + 1):
        for o, j in zip(asked[k], joined[k]):
            if o["net"] not in victims or not j or o.get("pour_served"):
                continue
            key = _pair_key(o)
            if key in seen:
                continue
            seen.add(key)
            if not (o["from"].get("ref") and o["to"].get("ref")):
                return [], "victim_end_not_pad"
            if not o.get("widths"):
                return [], "victim_width_unknown"
            amps = task_amps(selections[k], o) if selections is not None else None
            out.append(Move(k, {f: o[f] for f in ("net", "from", "to", "widths")}, True, amps))
    return out, None


def unasked_pairs(victims, input_open, moves, joined_on_board) -> list:
    """The route's input-board open connections (`input_open`) on a victim net that are joined on the failing call's
    board (`joined_on_board`, aligned) and whose pad pair no move has: joins a call made that no phase asks."""
    from .phase_run import _pair_key
    have = {_pair_key(m.obligation) for m in moves}
    return [o for o, j in zip(input_open, joined_on_board)
            if o["net"] in victims and j and o["from"].get("ref") and o["to"].get("ref") and _pair_key(o) not in have]


def first_joined(pairs, boards) -> list:
    """For each pad pair ((ref, pad[, fp]), (ref, pad[, fp])), the index of the first board in `boards` whose copper
    joins it (phase_run.joined_pairs), or None."""
    out = [None] * len(pairs)
    for i, b in enumerate(boards):
        todo = [n for n, v in enumerate(out) if v is None]
        if not todo:
            break
        for n, j in zip(todo, joined_pairs(b, [pairs[n] for n in todo])):
            if j:
                out[n] = i
    return out


def receipt_widths(receipt, phase_name, net) -> dict | None:
    """The router's width per layer for `net` in phase `phase_name` (kicad/width_policy.py's receipt), read as
    width_policy.apply reads it (width_policy.entries); None when it has none, it is unknown, or two records
    disagree."""
    from .width_policy import entries
    entry = entries(receipt).get((phase_name, net))
    return dict(entry["widths"]) if entry and entry.get("status") == "known" else None


def task_amps(sel, o) -> float | None:
    """The current of the owner Selection's task with the obligation's pad pair (current_paths), else None."""
    from .phase_run import _pair_key
    from .phase_select import end_record
    key = _pair_key(o)
    for t in sel.tasks:
        if _pair_key({"net": t.net, "from": end_record(t.start), "to": end_record(t.end)}) == key:
            return t.amps
    return None


def task_of(o, layers, amps=None):
    """An obligation as a --connections task, its widths in the layer order of the owner phase."""
    from .phase_select import Task
    return Task(o["net"], _end_pair(o["from"]), _end_pair(o["to"]), tuple((l, o["widths"][l]) for l in layers), amps)


def owner_calls(sel, moves, settings) -> list:
    """An owner phase's calls for its moved connections: plan_calls on a Selection of just those tasks at its layers,
    with its buses cut to the moved nets, so they group by (clearance, widths), widest clearance first, as its own task
    calls do (phase_run.plan_calls)."""
    from .phase_run import plan_calls
    from .phase_select import Selection
    tasks = tuple(task_of(m.obligation, settings.layers, m.amps) for m in moves)
    nets = {t.net for t in tasks}
    # a bus keeps only its moved nets; one with fewer than two is no bus, and its net goes with the plain tasks
    buses = tuple(b for b in (tuple(n for n in bus if n in nets) for bus in sel.buses) if len(b) >= 2)
    own = Selection(sel.phase, "rip", tasks=tasks, buses=buses, layers=settings.layers)
    return plan_calls(own, settings.clearance_map, settings.base_clearance, set())


LEVEL = ("open", "joined", "clean")
KEEP_CHECKS = ("blocked_not_clean", "obligation_worse", "net_open_rose", "drc_new", "off_layer")
ROUTER_REASONS = ("router_failed", "router_refused", "router_timeout")


@dataclass
class Standing:
    board: Path             # the board judged (not the DRC copy)
    copy: Path              # its DRC copy: guards off, zones filled
    drc_json: Path
    open_nets: dict         # {net: open items}
    errors: list            # drc.real_errors of the DRC
    judged: list            # per phase 0..upto: judge_obligations
    outcomes: list          # per phase 0..upto: the record status per obligation, or None
    is_real: object = None  # the DRC's is_real_kind, for judging the blocked unit on `copy`


def rank(j, outcome) -> int:
    """2 clean (phase_run.is_clean), 1 joined but not clean, 0 open."""
    return 2 if is_clean(j, outcome) else 1 if j["joined"] else 0


@dataclass(frozen=True)
class Verdict:
    kept: bool
    reason: str | None
    worse: tuple = ()
    open_rose: dict = field(default_factory=dict)
    drc_new: int = 0
    off_layer: int = 0


def verdict(before, after, asked, names, blocked_clean, off_layer) -> Verdict:
    """Keep the candidate (`after`) over the failing call's board (`before`) only when every blocked connection is
    clean, no obligation of phases 0..i ranks lower, no net has more open items, the DRC has no new real error and no
    track lies off its owner's layers (spec, "The keep or restore test"). The reason is the first check that fails,
    in KEEP_CHECKS order; every finding is returned."""
    from .drc import new_errors
    worse = []
    for k, obs in enumerate(asked):
        for o, jb, ob, ja, oa in zip(obs, before.judged[k], before.outcomes[k], after.judged[k], after.outcomes[k]):
            rb, ra = rank(jb, ob), rank(ja, oa)
            if ra < rb:
                worse.append({"phase": names[k], "net": o["net"], "from": o["from"], "to": o["to"],
                              "before": LEVEL[rb], "after": LEVEL[ra]})
    rose = {n: [before.open_nets.get(n, 0), v] for n, v in sorted(after.open_nets.items())
            if v > before.open_nets.get(n, 0)}
    new = len(new_errors(after.errors, before.errors))
    failed = dict(zip(KEEP_CHECKS, (not (blocked_clean and all(blocked_clean)), bool(worse), bool(rose), new > 0,
                                    off_layer > 0)))
    reason = next((c for c in KEEP_CHECKS if failed[c]), None)
    return Verdict(reason is None, reason, tuple(worse), rose, new, off_layer)


def standing(ctx, asked, phases, upto, board, stem, connections) -> Standing:
    """A board as the keep test judges it: a DRC of a copy with guards off and zones filled (as phase_run.judge_phase),
    every obligation of phases 0..upto judged on it against its own phase's input DRC (phase_input_drc, ruling S15),
    and each obligation's outcome from `connections[k]`, that phase's records as they stand."""
    import json
    from .drc import real_errors
    from .phase_run import judging_drc
    copy, drc_json, drc = judging_drc(ctx.work, board, stem + "_drc")
    judged, outcomes = [], []
    for k in range(upto + 1):
        obs = asked[k]
        judged.append(judge_obligations(copy, obs, drc_json, phase_neck(ctx.cfg, phases[k]), drc.is_real_kind,
                                        phase_input_drc(ctx.work, k)))
        outcomes.append([r.get("status") if r else None for r in records_of(obs, connections[k])])
    return Standing(Path(board), copy, drc_json, dict(drc.open_nets),
                    real_errors(json.loads(drc_json.read_text()), drc.is_real_kind), judged, outcomes, drc.is_real_kind)


def off_layer(given, routed, layers) -> int:
    """Tracks (not vias) on `routed` that `given` lacks, on a layer outside `layers` (layer names)."""
    from ..board_geometry import added_copper
    from ..values import CopperLayer
    from .read import read_board
    allowed = {CopperLayer.of(l) for l in layers}
    new = added_copper(read_board(str(given)).copper, read_board(str(routed)).copper)
    return sum(1 for c in new if c.kind == "track" and not set(c.layers) <= allowed)


def kept_moves(record) -> list:
    """The rerouted records of a phase record's kept attempts, in order."""
    return [r for a in record["rip"]["attempts"] if a["kept"] for r in a["rerouted"]]


def moves_of(phases, k) -> list:
    """[(mover phase index j, record)]: each reroute of a connection owned by phase k that a later phase j kept."""
    return [(j, r) for j, p in enumerate(phases) if j > k for r in kept_moves(p) if r["index"] == k]


def moved_records(phases, k) -> list:
    """The records of phase k's connections that later phases rerouted and kept (moves_of), in order."""
    return [r for _, r in moves_of(phases, k)]


@dataclass
class History:
    """What a route's attempts need of the phases before them: the phases and their Selections, each phase's
    obligations after width_policy.apply and the width receipt, the input board's script copper and open
    connections; and, as the route goes, each finished phase's board and records, and the kept reroutes of each
    phase's connections by later phases (`moved`)."""
    phases: tuple            # the phases routed (run_list)
    selections: tuple        # their Selections as picked before routing (layers, buses, pairs)
    asked: tuple             # each phase's obligations after width_policy.apply
    receipt: dict            # width_policy receipt
    script_keys: frozenset   # route.copper_items of the route's input board after its guards
    input_open: tuple        # open_connections of the route's input board
    boards: list = field(default_factory=list)        # each finished phase's board, in order
    connections: list = field(default_factory=list)   # each finished phase's records ("connections")
    moved: dict = field(default_factory=dict)         # {phase index: kept reroute records owned by it, in order}

    def record_move(self, index, attempt) -> None:
        """A kept attempt of phase `index`: its reroutes of earlier phases' connections, to `moved` (finding M2:
        called after each kept attempt, so a later attempt reads the moved records)."""
        for r in attempt["rerouted"]:
            if r["index"] < index:
                self.moved.setdefault(r["index"], []).append(r)

    def finish(self, index, board, record, *, reused: bool) -> None:
        """A finished phase: its board and records; a reused one's kept moves too (its attempts did not run here)."""
        self.boards.append(board)
        self.connections.append(list(record.get("connections") or []))
        if reused:
            for a in record["rip"]["attempts"]:
                if a["kept"]:
                    self.record_move(index, a)


@dataclass
class CallRip:
    """One call's attempts so far: how many were made, the victim sets restored, and whether a router failure stopped
    them."""
    made: int = 0
    tried: set = field(default_factory=set)           # frozensets of victims restored in this call
    stopped: bool = False


def gate(victims, *, rip: CallRip, max_nets: int, attempts: int) -> str | None:
    """Why a unit with these victims gets no attempt (spec "Limits"), the first that holds in this order: no_victim,
    too_many_victims, stopped, limit, tried; None when it gets one."""
    if not victims:
        return "no_victim"
    if len(victims) > max_nets:
        return "too_many_victims"
    if rip.stopped:
        return "stopped"
    if rip.made >= attempts:
        return "limit"
    if frozenset(victims) in rip.tried:
        return "tried"
    return None


@dataclass
class AfterCall:
    board: Path              # the board the phase goes on from
    records: list            # router records that supersede phase i's connections
    calls: list              # (Call, board in, board out) of phase i's to add to out.calls
    trim: set                # the victims of the kept attempts: dropped from the asks of phase i's calls before them
    summaries: list          # summary paths of the attempts' router calls
    widths: list             # route.width rows of reroutes owned by earlier phases


def _pads(o) -> bool:
    return bool(o["from"].get("ref") and o["to"].get("ref"))


def _ends_key(o) -> tuple:
    """A connection by its net and its two pad ends, either way round: a router record and the obligation it answers
    (`answered` gives a record its task's footprint uuid) have the same key."""
    return (o["net"], frozenset((e.get("ref"), e.get("pad"), e.get("fp")) for e in (o["from"], o["to"])))


def blocked_connections(unit, call, before, hist, index, phase) -> tuple:
    """The blocked unit's connections, each {"net", "from", "to", "widths"}, on the board `before` judged: a task
    unit's as the router answered them; a whole-net unit's the open connections of its net in `before`'s DRC, each at
    the widths phase `index` asks for that pad pair, or its width answer for the net (spec "What triggers an
    attempt"). ([conns], None), or ([], reason): `blocked_end_not_pad`, `blocked_width_unknown`, or `joined_since`
    when an earlier kept attempt of the call has joined them all."""
    from .phase_run import _pair_key, open_connections
    if unit.connections:
        conns = [dict(c) for c in unit.connections]
        if not all(_pads(c) for c in conns):
            return [], "blocked_end_not_pad"
        if not all(c.get("widths") for c in conns):
            return [], "blocked_width_unknown"
        joined = joined_pairs(before.board, [(_end_pair(c["from"]), _end_pair(c["to"])) for c in conns])
        return ([], "joined_since") if all(joined) else (conns, None)
    open_ = [c for c in open_connections(before.copy, before.drc_json) if c["net"] == unit.net]
    if not open_:
        return [], "joined_since"
    asks = {_pair_key(o): o.get("widths") for o in hist.asked[index]}
    conns = []
    for c in open_:
        if not _pads(c):
            return [], "blocked_end_not_pad"
        widths = asks.get(_pair_key(c)) or receipt_widths(hist.receipt, phase.name, unit.net)
        if not widths:
            return [], "blocked_width_unknown"
        conns.append(dict(c, widths=dict(widths)))
    return conns, None


def plan_moves(victims, hist, index, before) -> tuple:
    """The victims' connections to route again, each a Move (spec "The removed connections and their settings"): the
    obligations of phases 0..index joined on `before` (asked_moves), then the input board's open connections joined on
    `before` that no phase asks (unasked_pairs), each owned by the first phase whose board joins it (the failing
    call's board for phase `index`) at that phase's width answer for the net. ([Move], None), or ([], reason):
    `victim_end_not_pad`, `victim_width_unknown`."""
    joined = [[j["joined"] for j in before.judged[o]] for o in range(index + 1)]
    moves, reason = asked_moves(victims, hist.asked, index, joined, selections=hist.selections)
    if reason:
        return [], reason
    cand = [o for o in hist.input_open if o["net"] in victims and _pads(o)]
    pairs = [(_end_pair(o["from"]), _end_pair(o["to"])) for o in cand]
    loose = unasked_pairs(victims, cand, moves, joined_pairs(before.board, pairs))
    owners = first_joined([(_end_pair(o["from"]), _end_pair(o["to"])) for o in loose],
                          list(hist.boards[:index]) + [before.board])
    out = []
    for o, owner in zip(loose, owners):
        owner = index if owner is None else owner
        widths = receipt_widths(hist.receipt, hist.phases[owner].name, o["net"])
        if not widths:
            return [], "victim_width_unknown"
        out.append(Move(owner, {"net": o["net"], "from": o["from"], "to": o["to"], "widths": widths}, False))
    return list(moves) + out, None


def reroute_blocked(ctx_i, call, unit, conns, ripped, settings, stem, phase_name) -> TaskRun:
    """Step 2 of an attempt: the blocked unit routed on the ripped board at phase i's layers and router keywords
    (`settings`, its PhaseSettings; `ctx_i` carries its clearances). After a pour call, join_pour again for the unit's
    net (its TaskRun with `board` the join's output); after any other, its connections as --connections tasks."""
    if call.kind == "pour":
        out = ctx_i.work / (stem + "_b.kicad_pcb")
        _, run = pour_join.join_pour(ctx_i, ripped, out, unit.net, call.width, settings.layers, stem + "_b",
                                     phase_name, settings.common)
        run.board = out
        return run
    layers = list(settings.layers)
    return route_tasks(ctx_i, [task_of(c, layers) for c in conns], ripped, stem + "_b", layers, settings.common,
                       phase_name)


def _in_settings(ctx, st):
    """`ctx` with a phase's clearances (its PhaseSettings), as route_calls routes the phase."""
    return replace(ctx, clearance_map=st.clearance_map, clearances_file=st.clearances_file,
                   base_clearance=st.base_clearance)


def _standing_connections(hist, index, connections, blocked=(), rerouted=()) -> list:
    """Each phase's records as they stand for the keep test: phase k < index's superseded by the kept reroutes of its
    connections so far (`hist.moved`), then by `rerouted`; phase `index`'s `connections`, superseded by the blocked
    unit's records (`blocked`) and its own `rerouted`."""
    later = {index: list(blocked)}
    for r in rerouted:
        later.setdefault(r["index"], []).append(r)
    return ([superseded(superseded(hist.connections[o], hist.moved.get(o, [])), later.get(o, []))
             for o in range(index)] + [superseded(connections, later.get(index, []))])


def attempt(ctx, index, phase, sel, k, a, call, unit, conns, victims, not_ripped, moves, before, connections) -> tuple:
    """One attempt (spec "The order of calls", "The keep or restore test") on `before`, the board the call left
    as judged: the victims' router copper taken off, the blocked unit routed at phase `index`'s settings
    (reroute_blocked), the moved connections owner by owner at their own phases' settings (owner_calls), then the
    candidate judged against `before` (verdict). A router failure, refusal or timeout ends it unjudged. Returns
    (record, the candidate's Standing or None, AfterCall of what a kept attempt adds to the phase)."""
    t0 = time.time()
    hist = ctx.history
    stem = "p%d_%d_rip%d" % (index, k, a)
    ripped = fresh_output(ctx.work / (stem + "_ripped.kicad_pcb"))
    removed = remove_copper(before.board, ripped, set(victims), hist.script_keys)
    blocked_records, rerouted, calls_i, summaries, widths, off = [], [], [], [], [], 0
    board, router, after, v = ripped, None, None, None
    try:
        st_i = phase_settings(ctx, phase, sel, stem + "_b")
        run = reroute_blocked(_in_settings(ctx, st_i), call, unit, conns, ripped, st_i, stem, phase.name)
        blocked_records = list(run.records)
        summaries += run.summaries
        calls_i += [(Call("tasks", tasks=attempted), s, p) for attempted, s, p in run.calls]
        off += off_layer(ripped, run.board, st_i.layers)
        board = run.board
        for o in sorted({m.owner for m in moves}):
            mine = [m for m in moves if m.owner == o]
            asked_of = {_ends_key(m.obligation): m.asked for m in mine}
            owner = hist.phases[o]
            st = phase_settings(ctx, owner, hist.selections[o], "%s_v%d" % (stem, o))
            ctx_o, calls_o = _in_settings(ctx, st), []
            for j, c in enumerate(owner_calls(hist.selections[o], mine, st)):
                got = route_tasks(ctx_o, c.tasks, board, "%s_v%d_%d" % (stem, o, j), list(st.layers), st.common,
                                  owner.name, bus_nets=c.nets if c.kind == "bus_tasks" else None)
                off += off_layer(board, got.board, st.layers)
                rerouted += [dict(r, phase=owner.name, index=o, asked=asked_of.get(_ends_key(r), False))
                             for r in got.records]
                calls_o += [(replace(c, tasks=attempted), s, p) for attempted, s, p in got.calls]
                summaries += got.summaries
                board = got.board
            if o == index:
                calls_i += calls_o
            else:
                widths += phase_widths(owner, calls_o, ctx.cfg)
    except RouterFailed as e:
        router, reason = {"code": e.code, "exit_code": e.exit_code, "log": str(e.log)}, "router_failed"
    except RouteRefused as e:
        router, reason = {"code": e.code, **e.facts}, "router_refused"
    except subprocess.TimeoutExpired as e:
        router, reason = {"code": "timeout", "seconds": e.timeout}, "router_timeout"
    if router is None:
        after = standing(ctx, hist.asked, hist.phases, index, board, stem + "_after",
                         _standing_connections(hist, index, connections, blocked_records, rerouted))
        judged = judge_obligations(after.copy, conns, after.drc_json, phase_neck(ctx.cfg, phase), after.is_real,
                                   phase_input_drc(ctx.work, index))
        status = [r.get("status") if r else None for r in records_of(conns, blocked_records)]
        v = verdict(before, after, hist.asked[:index + 1], [p.name for p in hist.phases],
                    [is_clean(j, s) for j, s in zip(judged, status)], off)
    else:
        v = Verdict(False, reason)
    record = {"call": k, "attempt": a, "blocked": [dict(c) for c in conns],
              "named": [n.record() for n in unit.named], "victims": list(victims), "not_ripped": list(not_ripped),
              "removed": removed, "rerouted": rerouted, "blocked_records": blocked_records, "kept": v.kept,
              "reason": v.reason, "worse": list(v.worse), "open_rose": dict(v.open_rose), "drc_new": v.drc_new,
              "off_layer": v.off_layer, "router": router, "widths": widths, "seconds": round(time.time() - t0, 1)}
    parts = AfterCall(Path(board), blocked_records + [r for r in rerouted if r["index"] == index], calls_i,
                      set(victims), [Path(x) for x in summaries], widths)
    return record, after, parts


def after_call(ctx, index, phase, sel, k, call, board_in, board_out, records, summary, connections,
               rip_record) -> AfterCall:
    """After call `k` of phase `index` (`board_in` -> `board_out`, its router `records` and `summary` doc): each
    blocked unit (blocked_of) with its victims (victims_of) through the gate, then its connections
    (blocked_connections) and moves (plan_moves), then an attempt; a unit stopped on the way is recorded in
    `rip_record["skipped"]`, an attempt in `rip_record["attempts"]`. A kept attempt's candidate is the board the call's
    later units, and the phase, go on from. Returns that board and what the kept attempts change."""
    out = AfterCall(Path(board_out), [], [], set(), [], [])
    if ctx.cfg.route_rip_attempts <= 0:
        return out
    units = blocked_of(call.kind, records, summary)
    if not units:
        return out
    hist = ctx.history
    on_board = router_nets(board_out, hist.script_keys)
    laid = laid_nets(board_in, board_out)
    pair_nets = {n for s in hist.selections for pair in s.pairs for n in pair}
    rip, before, conns_i = CallRip(), None, list(connections)
    for unit in units:
        victims, not_ripped = victims_of(unit, router_nets=on_board, laid_by_call=laid, pour_nets=set(ctx.pour_nets),
                                         pair_nets=pair_nets, excluded=set(ctx.excluded))
        reason = gate(victims, rip=rip, max_nets=ctx.cfg.route_rip_max_nets, attempts=ctx.cfg.route_rip_attempts)
        if reason is None:
            if before is None:
                before = standing(ctx, hist.asked, hist.phases, index, out.board, "p%d_%d_rip" % (index, k),
                                  _standing_connections(hist, index, conns_i))
            conns, reason = blocked_connections(unit, call, before, hist, index, phase)
            if reason is None:
                moves, reason = plan_moves(victims, hist, index, before)
        if reason is not None:
            rip_record["skipped"].append({"call": k, "net": unit.net, "named": [n.record() for n in unit.named],
                                          "not_ripped": list(not_ripped), "reason": reason})
            continue
        rec, after, parts = attempt(ctx, index, phase, sel, k, rip.made, call, unit, conns, victims, not_ripped,
                                    moves, before, conns_i)
        rip.made += 1
        rip_record["attempts"].append(rec)
        if rec["kept"]:
            hist.record_move(index, rec)        # finding M2: the next attempt's before and after read it
            out.board, before = after.board, after
            on_board = router_nets(out.board, hist.script_keys)
            laid.add(unit.net)
            conns_i = superseded(conns_i, parts.records)
            out.records += parts.records
            out.calls += parts.calls
            out.trim |= parts.trim
            out.widths += parts.widths
            out.summaries += parts.summaries
        else:
            rip.tried.add(frozenset(victims))
            if rec["reason"] in ROUTER_REASONS:
                rip.stopped = True
    return out
