"""What a code change does to placement, across the module fixtures.

Every part of each module under fixtures/*/modules/ is released to a bare
place() and resolved under each configuration in CONFIGS. A result is scored
by parts placed, then placemat's findings, then half-perimeter wirelength
(HPWL) over the nets that are not planes, and compared with the committed
baseline in bench.json: more placed is better, then fewer findings, then HPWL
more than NOISE shorter.

    .venv/bin/python fixtures/bench.py [name ...] [--config NAME] [--jobs N] [--update]

A change that can move a placement runs this before it is committed, puts the
tally lines in the commit message, and commits bench.json with it when a
number changed.
"""
from __future__ import annotations

import json

CONFIGS = {"default": {}, "solve": {"solve_enabled": True}}
NOISE = 0.01          # report.AIRWIRE_NOISE's value; HPWL is deterministic, the margin is for trivia
KINDS = ("better", "worse", "same", "new", "gone")


def hpwl(pads, skip=frozenset()) -> float:
    """Per net, the width plus height of the box round its pads, summed."""
    by_net = {}
    for net, x, y in pads:
        if net and net not in skip:
            by_net.setdefault(net, []).append((x, y))
    total = 0.0
    for pts in by_net.values():
        if len(pts) >= 2:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            total += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return round(total, 1)


def verdict(new: dict, old: dict) -> int:
    if new["placed"] != old["placed"]:
        return 1 if new["placed"] > old["placed"] else -1
    if new["findings"] != old["findings"]:
        return 1 if new["findings"] < old["findings"] else -1
    if new["hpwl"] < old["hpwl"] * (1 - NOISE):
        return 1
    if new["hpwl"] > old["hpwl"] * (1 + NOISE):
        return -1
    return 0


def diff(run: dict, base: dict) -> list:
    out = []
    names = sorted(set(run["modules"]) | set(base["modules"]))
    configs = sorted(set(run["configs"]) | set(base["configs"]))
    for m in names:
        new_m, old_m = run["modules"].get(m, {}), base["modules"].get(m, {})
        for c in configs:
            new, old = new_m.get(c), old_m.get(c)
            if new is None and old is None:
                continue
            if old is None:
                kind = "new"
            elif new is None:
                kind = "gone"
            else:
                kind = {1: "better", -1: "worse", 0: "same"}[verdict(new, old)]
            out.append((c, m, kind))
    return out


def tally(changes) -> dict:
    out = {}
    for c, _, kind in changes:
        out.setdefault(c, dict.fromkeys(KINDS, 0))[kind] += 1
    return out


def dump(results: dict) -> str:
    """Sorted, one module per line, so a diff shows which modules moved."""
    configs = json.dumps(results["configs"], sort_keys=True)
    rows = ['    %s: %s' % (json.dumps(m), json.dumps(results["modules"][m], sort_keys=True))
            for m in sorted(results["modules"])]
    return '{\n  "configs": %s,\n  "modules": {\n%s\n  }\n}\n' % (configs, ",\n".join(rows))


def load(text: str) -> dict:
    return json.loads(text)
