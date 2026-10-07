"""One routing phase's router calls, in order, each on the board the one before it left with its copper locked, and the
phase's own judgement (closure and widths, Task 13/14). The calls are planned here from a Selection
(kicad/phase_select.py); a phase holding nets of several clearances routes one call per clearance, widest first,
because KRT spaces a whole call at the largest clearance among its nets (py_router/routing_config.py:485-509,
set_net_clearances)."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .route import clearance_groups, group_clearance


@dataclass(frozen=True)
class Call:
    kind: str                       # "pairs" | "pour" | "bus" | "nets" | "tasks" | "rest"
    nets: tuple = ()                # the nets it routes; for "rest" the ones it may route
    excluded: tuple = ()            # for "rest": the nets its `*` leaves out
    tasks: tuple = ()               # Task: a "tasks" call's pad pairs; a "pour" call's tasks on its net
    width: float | None = None
    clearance: float | None = None


def write_connections(tasks, path, layers) -> Path:
    """The --connections file of one call (KRT docs/connections.md). Each task names a width on every layer the call
    routes and no other, as KRT requires (`layer_width_missing`, `layer_not_routed`); a task that does not is
    placemat's own mistake and raises ValueError(code, task.record()) before anything is written."""
    for t in tasks:
        named = {layer for layer, _ in t.widths}
        if named != set(layers):
            raise ValueError("layer_width_missing" if set(layers) - named else "layer_not_routed", t.record())
    path = Path(path)
    path.write_text(json.dumps([{"net": t.net, "from": {"ref": t.start[0], "pad": t.start[1]},
                                 "to": {"ref": t.end[0], "pad": t.end[1]}, "widths": dict(t.widths)} for t in tasks],
                               indent=1) + "\n")
    return path


def refused_records(records) -> list:
    """The tasks the router refused, each {net, from, to, reason}. placemat selected every task from the board, so a
    refusal means the two disagree about the board; Task 13 stops the route naming them."""
    return [{"net": r["net"], "from": r["from"], "to": r["to"], "reason": r.get("reason")}
            for r in records if r.get("status") == "refused"]


def plan_calls(sel, clearance_map: dict, base: float, excluded: set) -> list:
    """The router calls of one Selection, in order: the pairs; each pour net alone (sorted), its pour handed to the
    router as a zone (D15); each bus; the pad-pair tasks grouped by (clearance, widths), widest clearance first, then
    widest width first (D5); whole nets per clearance group widest first, then the Default-clearance rest - for a
    rest selection one `*` call leaving out `excluded` and the nets routed by name.

    A task set's pour nets (Selection.pour_nets) route in their pour call, not a task call (ruling S5): the call
    carries that net's tasks, and, when the phase sets no numeric width, the widest width any of them asks; each
    task is still judged on its own path (Task 15)."""
    calls = []
    if sel.pairs:
        calls.append(Call("pairs", tuple(n for pair in sel.pairs for n in pair)))
    pours = set(sel.pour_nets)
    for n in sorted(pours):
        own = tuple(t for t in sel.tasks if t.net == n)
        width = sel.width
        if width is None and own:
            width = max(w for t in own for _, w in t.widths)
        calls.append(Call("pour", (n,), tasks=own, width=width))
    calls += [Call("bus", tuple(b), width=sel.width) for b in sel.buses]
    tasks = [t for t in sel.tasks if t.net not in pours]
    if tasks:
        def clr(t):                                 # the same groups as whole nets' (clearance_groups)
            c = group_clearance(clearance_map, t.net, base)
            return base if c is None else c
        # the widths tuple last breaks ties between groups of the same widest width, so the order is the same every run
        keys = sorted({(clr(t), t.widths) for t in tasks}, key=lambda k: (-k[0], -max(w for _, w in k[1]), k[1]))
        calls += [Call("tasks", tasks=tuple(t for t in tasks if (clr(t), t.widths) == k), clearance=k[0]) for k in keys]
    if sel.nets:
        groups = clearance_groups(clearance_map, base, sel.nets)
        wide = {n for _, ns in groups for n in ns}
        calls += [Call("nets", tuple(ns), width=sel.width, clearance=c) for c, ns in groups]
        rest = tuple(n for n in sel.nets if n not in wide)
        if sel.rest:
            calls.append(Call("rest", rest, excluded=tuple(sorted(set(excluded) | wide)), width=sel.width,
                              clearance=base))
        elif rest:
            calls.append(Call("nets", rest, width=sel.width, clearance=base))
    return calls
