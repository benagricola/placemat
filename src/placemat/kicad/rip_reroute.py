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
