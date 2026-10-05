"""The widths a route delivered against the widths it asked for, from the router's per-stage summaries.

The router measures the copper it ships, not what a pass requested (KRT py_router/routing_common.py `power_width_report`, written as
JSON_SUMMARY `power_widths` by py_router/route.py when the run has `--power-nets-widths`, which placemat gives an island net that has a
width). A wide route that is blocked is retried at the default track width, the "neck-down" (single_ended_routing.py, a log line only),
and nothing in the route's outcome says so but these summary fields:

- `power_widths[net]`: `requested_mm`, `length_mm`, `under_mm`, `under_share`, `min_mm`, `by_width_mm`, `in_run_scope` (route.py);
- `design_rules.narrowed[]`: one row per net that ships under its width, `net_name`, `kind` "track_width", `requested`, `delivered`,
  `length_mm` (the length under), `site` (fab_tiers.py `replace_power_track_rows`);
- `power_trace_ampacity[]`: `net`, `bottleneck_width_mm`, `bottleneck_layer`, `max_current_a` (IPC-2152) (route.py).

`power_widths` and `power_trace_ampacity` exist only in a stage that was given power nets; `design_rules.narrowed` is in every stage's
summary, and holds a net-class or pair narrowing only where the router's own escalation recorded one. The pair router writes no summary.

A record is a dict (the report's `as_dict` carries them as `widths`); the sentence is rendered from the finding's facts."""
from __future__ import annotations

import json
from pathlib import Path


def _read(path) -> dict:
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _ampacity(summary: dict) -> dict:
    return {a["net"]: {"max_a": a.get("max_current_a"), "bottleneck_mm": a.get("bottleneck_width_mm")}
            for a in summary.get("power_trace_ampacity") or () if isinstance(a, dict) and "net" in a}


def stage_widths(stage: str, summary: dict, declared=()) -> list:
    """The records of one stage's summary: a net whose delivered copper was narrower than it was asked, each
    {net, stage, requested_mm, delivered_min_mm, length_under_mm, length_mm, share, declared, max_a, bottleneck_mm}.
    `declared` is the nets the script gave a width. `length_mm` and `share` are None where the router gave the narrowing alone."""
    amps = _ampacity(summary)
    out, seen = [], set()

    def add(net, requested, minimum, under, length, share):
        a = amps.get(net) or {}
        out.append({"net": net, "stage": stage, "requested_mm": requested, "delivered_min_mm": minimum, "length_under_mm": under,
                    "length_mm": length, "share": share, "declared": net in declared, "max_a": a.get("max_a"),
                    "bottleneck_mm": a.get("bottleneck_mm")})
        seen.add(net)

    for net, p in sorted((summary.get("power_widths") or {}).items()):
        if p.get("in_run_scope", True) and (p.get("under_mm") or 0) > 0:
            add(net, p["requested_mm"], p.get("min_mm"), p["under_mm"], p.get("length_mm"), p.get("under_share"))
    for row in (summary.get("design_rules") or {}).get("narrowed") or ():
        net = row.get("net_name")
        if row.get("kind") == "track_width" and net not in seen and row.get("delivered") is not None:
            add(net, row["requested"], row["delivered"], row.get("length_mm") or 0.0, None, None)
    return out


def read_widths(work, islands: dict, classes: int = 0) -> list:
    """Every stage's records for the route in `work`: each island net's own pass (islandsN_summary.json, N the net's place in the
    sorted names), each of the `classes` class stages (classesN_summary.json), then the main pass (router_summary.json)."""
    work = Path(work)
    declared = {n for n, w in islands.items() if w}
    out = []
    for i, _ in enumerate(sorted(islands)):
        out += stage_widths("islands", _read(work / ("islands%d_summary.json" % i)), declared)
    for i in range(classes):
        out += stage_widths("classes", _read(work / ("classes%d_summary.json" % i)), declared)
    return out + stage_widths("main", _read(work / "router_summary.json"), declared)


def findings_of(records: list, stated: dict | None = None) -> list:
    """A finding for each record. Critical when the net is a declared one (the script gave it a width because it carries current) or
    when the router's ampacity for its narrowest copper is under the current the design states for it (`stated`: {net: amps}, from
    the parts' `Pm.I`); warning otherwise (a narrowing the router recorded on a net the script gave no width)."""
    from ..findings import Finding, FindingCause as C
    stated = stated or {}
    out = []
    for r in records:
        amps = stated.get(r["net"])
        short = amps is not None and r["max_a"] is not None and r["max_a"] < amps
        facts = {k: r[k] for k in ("net", "stage", "requested_mm", "delivered_min_mm", "length_under_mm", "length_mm", "share",
                                   "declared", "max_a", "bottleneck_mm")}
        facts["stated_a"] = amps
        out.append(Finding(C.ROUTE_WIDTH, facts, "critical" if r["declared"] or short else "warning"))
    return out


def stated_currents(geometry) -> dict:
    """The current the design states for each net: the most any part carrying it says (`Pm.I`, checks.carriers_of)."""
    from ..checks import carriers_of
    return {net: max(on.values()) for net, on in carriers_of(geometry).items() if on}


def brief(r: dict) -> str:
    """One record as the route's summary line has it."""
    length = "" if r["length_mm"] is None else " of %.1f" % r["length_mm"]
    return "%s %.1f%s mm under %g (min %g)" % (r["net"], r["length_under_mm"], length, r["requested_mm"], r["delivered_min_mm"])
