"""Each selected net's track width per phase and layer, as the configured router resolves it.

Before any copper changes the route asks the router which width it will draw each net at: the router decides between
net class, design rule and router flags (py_router/nominal_width_policy.py on the placemat fork of KiCadRoutingTools,
which reads them with the router's own resolvers). Each phase's joins are judged against those widths
(phase_run.judge_obligations). A net the router cannot resolve gets no width: its obligation is width-unknown.

The query reads a JSON request on stdin and prints its answer on one stdout line after `PLACEMAT_WIDTH_POLICY `.
A failure is a record, {"code", "facts"}: on the answer (`failure`), and on each obligation it leaves without a width
(`width_policy_failure`).
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

SCRIPT = Path("py_router") / "nominal_width_policy.py"
_PREFIX = "PLACEMAT_WIDTH_POLICY "


def requests_of(phases, selections, cfg):
    """The actual single-ended and pair flag scopes, with named power requests."""
    if len(phases) != len(selections):
        raise ValueError('width policy phase/selection count mismatch')
    out = []
    prior_pairs = {}
    for phase, sel in zip(phases, selections):
        pairs = {n for pair in sel.pairs for n in pair}
        singles = set(sel.nets) | set(sel.pour_nets) | {n for bus in sel.buses for n in bus}
        task_nets = {t.net for t in sel.tasks}
        singles -= task_nets - set(sel.pour_nets)
        # Default rest is a fallback for still-open copper. A prior pair's
        # completed geometry remains governed by its pair width, rather than
        # acquiring an unrelated single-ended class width on the final board.
        if sel.rest and sel.width is None and not sel.tasks:
            inherited = {}
            for net in sorted(singles & set(prior_pairs)):
                owner, pair, args = prior_pairs[net]
                inherited.setdefault(owner, {'pairs': set(), 'nets': set(), 'args': args})
                inherited[owner]['pairs'].add(pair)
                inherited[owner]['nets'].add(net)
            for owner, group in inherited.items():
                out.append({'name': phase.name, 'kind': 'pairs', 'owner': owner,
                            'nets': sorted(group['nets']), 'pairs': [list(p) for p in sorted(group['pairs'])],
                            'layers': list(sel.layers), 'args': list(group['args']),
                            'rest_phase_args': list(phase.router_args),
                            'rest_single_args': list(cfg.route_router_args) + list(phase.router_args)})
            singles -= set(prior_pairs)
        if singles:
            power = {n: sel.width for n in singles} if sel.width else {}
            for net in sel.pour_nets:
                own = [width for task in sel.tasks if task.net == net for _, width in task.widths]
                if own and net not in power:
                    power[net] = max(own)
            out.append({'name': phase.name, 'kind': 'nets', 'nets': sorted(singles), 'layers': list(sel.layers),
                        'args': list(cfg.route_router_args) + list(phase.router_args), 'power': power})
        if pairs:
            out.append({'name': phase.name, 'kind': 'pairs', 'nets': sorted(pairs), 'pairs': [list(p) for p in sel.pairs],
                        'layers': list(sel.layers),
                        'args': list(cfg.route_pair_router_args) + list(phase.router_args)})
            for pair in sel.pairs:
                for net in pair:
                    prior_pairs[net] = phase.name, tuple(pair), tuple(cfg.route_pair_router_args) + tuple(phase.router_args)
    return out


class Malformed(ValueError):
    """An answer that does not fit the request: `problem` names what."""

    def __init__(self, problem: str):
        super().__init__(problem)
        self.problem = problem


def check(answer, requests) -> list:
    """The answer's per-request policies, each {name, kind, by_net: {net: {status, widths}}}, in request order.
    Malformed when the answer does not cover exactly the requested phases, nets and layers with finite positive
    widths."""
    if not isinstance(answer, dict) or type(answer.get("schema")) is not int or answer["schema"] != 1:
        raise Malformed("schema")
    records = answer.get("policies")
    if not isinstance(records, list) or len(records) != len(requests):
        raise Malformed("scope_count")
    out = []
    for record, request in zip(records, requests):
        if record.get("name") != request["name"] or record.get("kind") != request["kind"]:
            raise Malformed("scope_identity")
        if set(record.get("by_net") or ()) != set(request["nets"]):
            raise Malformed("net_membership")
        by_net = {}
        for net, entry in record["by_net"].items():
            if entry.get("status") == "unknown":
                by_net[net] = {"status": "unknown", "widths": None, "reason": str(entry.get("reason") or "")}
                continue
            widths = entry.get("widths")
            if entry.get("status") != "known" or not isinstance(widths, dict) or set(widths) != set(request["layers"]):
                raise Malformed("layer_membership")
            if any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0
                   for w in widths.values()):
                raise Malformed("width")
            by_net[net] = {"status": "known", "widths": dict(widths)}
        out.append({"name": record["name"], "kind": record["kind"], "by_net": by_net})
    return out


def resolve(rpy, router_dir, pcb, phases, selections, cfg, log: Path, env=None, *, timeout=None) -> dict:
    """The router's widths for every phase's selected nets: {"schema", "config_sha256" (of the request), "policies"
    (check's), and "failure" {code, facts} when the query gave no usable answer}. Codes: `unavailable` (the router has
    no width query, or its interpreter will not start), `timeout`, `failed` (a non-zero exit), `malformed`. On a
    failure every net is unknown. The query's output is in `log`."""
    requests = requests_of(phases, selections, cfg)
    contract = hashlib.sha256(json.dumps(requests, sort_keys=True).encode()).hexdigest()

    def failed(code, **facts):
        return {"schema": 1, "config_sha256": contract, "failure": {"code": code, "facts": facts},
                "policies": [{"name": r["name"], "kind": r["kind"],
                              "by_net": {n: {"status": "unknown", "widths": None} for n in r["nets"]}}
                             for r in requests]}

    if not requests:
        return {"schema": 1, "config_sha256": contract, "policies": []}
    script = Path(router_dir) / SCRIPT
    if not script.is_file():
        return failed("unavailable", script=str(script))
    timeout = float(cfg.timeout_route if timeout is None else timeout)
    from .phase_run import run_router
    try:
        rc = run_router([str(rpy), str(script)], log, router_dir, dict(env) if env else None, timeout,
                        stdin=json.dumps({"board": str(Path(pcb).resolve()), "requests": requests}))
    except subprocess.TimeoutExpired:
        return failed("timeout", seconds=timeout, log=str(log))
    except OSError as e:
        return failed("unavailable", script=str(script), error=type(e).__name__, errno=e.errno)
    if rc:
        return failed("failed", exit_code=rc, log=str(log))
    lines = [line for line in Path(log).read_text(errors="replace").splitlines() if line.startswith(_PREFIX)]
    try:
        if not lines:
            raise Malformed("no_answer")
        try:
            answer = json.loads(lines[-1][len(_PREFIX):])
        except ValueError:
            raise Malformed("not_json") from None
        return {"schema": 1, "config_sha256": contract, "policies": check(answer, requests)}
    except Malformed as e:
        return failed("malformed", problem=e.problem, log=str(log))


def apply(obligations, selections, phases, policy):
    """The obligations with the router's widths. A phase with its own tasks keeps the tasks' widths (S9: a pour routes
    at the widest task width, but each task's obligation keeps its own); any other obligation takes its net's width
    in its phase, or none with `width_policy_unknown` and `width_policy_failure` {code, facts} saying why."""
    if len(obligations) != len(selections) or len(selections) != len(phases):
        raise ValueError("width policy obligation/selection/phase count mismatch")
    failure = policy.get("failure")
    records = {}
    for record in policy["policies"]:
        for net, entry in record["by_net"].items():
            key = record["name"], net
            if key in records and records[key]["widths"] != entry["widths"]:
                records[key] = {"status": "unknown", "widths": None, "conflict": True}
            elif key not in records:
                records[key] = entry
    out = []
    for obs, sel, phase in zip(obligations, selections, phases):
        own = []
        for obligation in obs:
            item = dict(obligation)
            if policy.get("config_sha256"):
                # two different requests are not comparable, even when neither resolved a width
                item["width_policy_contract"] = policy["config_sha256"]
            if not sel.tasks:
                entry = records.get((phase.name, item["net"]))
                if entry is not None and entry["status"] == "known":
                    item["widths"] = dict(entry["widths"])
                else:
                    item["widths"] = None
                    item["width_policy_unknown"] = True
                    item["width_policy_failure"] = (
                        failure if failure else
                        {"code": "no_policy", "facts": {}} if entry is None else
                        {"code": "conflicting_policies", "facts": {}} if entry.get("conflict") else
                        {"code": "router_unknown", "facts": {"reason": entry.get("reason", "")}})
            own.append(item)
        out.append(own)
    return out


def phase_key(policy, name) -> list:
    """What a phase's kept result depends on from the answer: its nets' statuses and widths. The board, its rules and
    the router's version are in the route's own chain (route_state)."""
    return [{"name": r["name"], "kind": r["kind"],
             "by_net": {net: {"status": e["status"], "widths": e.get("widths")} for net, e in r["by_net"].items()}}
            for r in policy["policies"] if r["name"] == name]
