"""Rip and reroute of earlier calls' copper (docs/superpowers/specs/2026-10-12-rip-reroute-design.md). After a router
call of a phase leaves a connection open and the router names another net's copper an earlier call laid as blocking
it, that net's router copper is taken off, the blocked connection routed, and the removed connections routed again at
their own phases' widths, layers and clearance; the result is kept only when nothing judged before is worse.
Everything returned here is a value or a record; route.phase_lines renders them."""
from __future__ import annotations

from dataclasses import dataclass, field

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
    from .phase_run import joined_pairs
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
    from .phase_run import _end_pair
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
