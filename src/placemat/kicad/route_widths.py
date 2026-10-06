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

`power_widths` is written only by a run with its final reconciliation on (route.py, the `# ---- POWER WIDTHS (#1033)` block, gated
on `final_reconcile`); the quick route (route_one_round.py) runs with it off, so its stages carry none, and a net the router necked
down with no net rescue leaves no `narrowed` row either. The island nets are therefore judged on the routed board itself
(`board_widths`), and the summaries' records are kept only for the nets the board does not judge.

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


# The router's pad neck-down (KRT docs/power-nets.md "Neck-Down for Failed Power Routes"): a power route that does not fit at its
# width is routed at the layer's default width, and the copper within `--neckdown-length` of a pad stays narrow
# (single_ended_routing.py `_neck_pass`, from both ends with `neck_start`); a stepped taper `--neckdown-taper-length` long then
# carves the wide copper's end next to it (`_apply_neckdown_widths`). These are KRT's defaults, py_router/routing_defaults.py:61-62.
KRT_NECKDOWN_LENGTH_MM = 2.5
KRT_NECKDOWN_TAPER_MM = 0.5


def neck_allowance(router_args) -> float:
    """How far from a pad, along the copper, a neck-down may run before it counts as narrow copper: the router's neck length plus
    its taper, as `router_args` sets them (KRT route.py `--neckdown-length`, `--neckdown-taper-length`), 0 with
    `--no-power-tap-neckdown`."""
    from ..settings import router_flag
    args = list(router_args or ())
    if "--no-power-tap-neckdown" in args:
        return 0.0
    length, taper = router_flag(args, "--neckdown-length"), router_flag(args, "--neckdown-taper-length")
    return (KRT_NECKDOWN_LENGTH_MM if length is None else length) + (KRT_NECKDOWN_TAPER_MM if taper is None else taper)


_UNDER_MM = 1e-3
"""How much narrower than its need a track is before it counts: KRT's own tolerance (routing_common.py `power_width_report`)."""


def _key(point, layer):
    return (round(point[0] * 1000), round(point[1] * 1000), layer)


def _neck_lengths(tracks, under, pads, vias, neck_mm: float) -> set:
    """The indices of the under-width tracks in `tracks` that are a pad neck-down: every point of the track lies within `neck_mm`
    of a pad of the net along under-width copper. `under` is the indices of the under-width tracks, `pads` the net's pads
    (outlines, layers), `vias` its vias' (centre, layers)."""
    import heapq
    from ..geometry import point_in_polygon
    if neck_mm <= 0 or not under:
        return set()
    alias = {}
    for at, layers in vias:
        keys = [_key(at, l) for l in layers]
        for k in keys:
            alias[k] = keys[0]

    def node(point, layer):
        k = _key(point, layer)
        return alias.get(k, k)

    edges, start = {}, set()
    for i in under:
        t = tracks[i]
        layer = next(iter(t.layers))
        a, b = node(t.anchors[0], layer), node(t.anchors[1], layer)
        edges.setdefault(a, []).append((b, t.length_mm))
        edges.setdefault(b, []).append((a, t.length_mm))
        for end, n in zip(t.anchors, (a, b)):
            if any(layer in p_layers and any(point_in_polygon(end, o) for o in outlines) for outlines, p_layers in pads):
                start.add(n)
    dist = {n: 0.0 for n in start}
    heap = [(0.0, n) for n in start]
    while heap:
        d, n = heapq.heappop(heap)
        if d > dist.get(n, float("inf")):
            continue
        for m, length in edges.get(n, ()):
            if d + length < dist.get(m, float("inf")):
                dist[m] = d + length
                heapq.heappush(heap, (d + length, m))
    out = set()
    for i in under:
        t = tracks[i]
        layer = next(iter(t.layers))
        da, db = (dist.get(node(e, layer), float("inf")) for e in t.anchors)
        farthest = min(min(da, db) + t.length_mm, (da + db + t.length_mm) / 2)
        if farthest <= neck_mm + _UNDER_MM:
            out.add(i)
    return out


def board_widths(geometry, islands: dict, rise_c: float | None = None, copper_oz: float | None = None,
                 neck_mm: float = KRT_NECKDOWN_LENGTH_MM + KRT_NECKDOWN_TAPER_MM) -> list:
    """The island nets' routed copper judged on the board: a record for each net of `islands` ({net: width asked or None}) given
    a width and with any track narrower than it needs, each
    {net, stage, requested_mm, delivered_min_mm, length_under_mm, length_mm, share, declared, max_a, bottleneck_mm,
    bottleneck_layer, amps, necks_mm, neck_limit_mm, layers}.

    A track needs the width the island was asked, on every layer: the script chose it for what the island carries, which may
    be a tap of a net whose full current flows elsewhere. Current is `check current-path`'s to judge, from carrier to carrier
    (IPC-2221, the inner constant on an inner layer); an island net given no width, and a net that is no island, are left to
    it too. `max_a` is the current its narrowest copper carries at `rise_c`. Under-width copper within `neck_mm` of a pad along under-width copper is the router's pad neck-down
    (`neck_allowance`) and is not counted, its length given as `necks_mm`. `layers` is the shortfall per layer, each
    {layer, need_mm, by ("asked" or "current"), under_mm, min_mm}; `max_a` is what the copper with the least capacity carries
    (IPC-2221), `bottleneck_mm` its width."""
    from ..checks import COPPER_OZ, TRACK_RISE_C, _layer_k, _layer_oz, ipc2221_current_a
    rise_c = TRACK_RISE_C if rise_c is None else rise_c
    copper_oz = COPPER_OZ if copper_oz is None else copper_oz
    copper_mm = getattr(geometry, "copper_mm", None) or {}
    out = []
    for net in sorted(islands):
        asked = islands[net] or None
        if not asked:
            continue
        tracks = [c for c in geometry.copper if c.net == net and c.kind == "track" and len(c.anchors) == 2 and c.layers]
        if not tracks:
            continue
        need = {next(iter(t.layers)): asked for t in tracks}
        by = {layer: "asked" for layer in need}
        under = [i for i, t in enumerate(tracks) if t.width_mm < need[next(iter(t.layers))] - _UNDER_MM]
        pads = [(c.outlines, c.layers) for c in geometry.copper if c.net == net and c.kind == "pad"]
        vias = [(c.anchors[0], c.layers) for c in geometry.copper if c.net == net and c.kind == "via" and c.anchors]
        necks = _neck_lengths(tracks, under, pads, vias, neck_mm)
        counted = [tracks[i] for i in under if i not in necks]
        if not counted:
            continue
        per = {}
        for t in counted:
            layer = next(iter(t.layers))
            row = per.setdefault(layer, {"layer": layer.value, "need_mm": round(need[layer], 4), "by": by[layer],
                                         "under_mm": 0.0, "min_mm": t.width_mm})
            row["under_mm"] += t.length_mm
            row["min_mm"] = min(row["min_mm"], t.width_mm)

        def capacity(t):
            layer = next(iter(t.layers))
            return ipc2221_current_a(t.width_mm, rise_c, _layer_oz(layer, copper_mm, copper_oz), _layer_k(layer))
        worst = min(counted, key=capacity)
        length = sum(t.length_mm for t in tracks)
        under_mm = sum(t.length_mm for t in counted)
        out.append({"net": net, "stage": "islands", "requested_mm": asked, "delivered_min_mm": round(min(t.width_mm for t in counted), 4),
                    "length_under_mm": round(under_mm, 2), "length_mm": round(length, 2),
                    "share": round(under_mm / length, 4) if length else None, "declared": bool(asked),
                    "max_a": round(capacity(worst), 2), "bottleneck_mm": round(worst.width_mm, 4),
                    "bottleneck_layer": next(iter(worst.layers)).value, "amps": None,
                    "necks_mm": round(sum(tracks[i].length_mm for i in necks), 2), "neck_limit_mm": neck_mm,
                    "layers": [dict(r, under_mm=round(r["under_mm"], 2), min_mm=round(r["min_mm"], 4))
                               for _, r in sorted(per.items(), key=lambda kv: kv[0].value)]})
    return out


def judged_on_board(islands: dict) -> set:
    """The island nets `board_widths` judges: the ones given a width."""
    return {n for n, w in islands.items() if w}


def findings_of(records: list, stated: dict | None = None) -> list:
    """A finding for each record. Critical when the net is a declared one (the script gave it a width because it carries current) or
    when the ampacity of its narrowest copper is under the current the design states for it (`stated`: {net: amps}, from the parts'
    `Pm.I`; a board record's own `amps` where `stated` has none); warning otherwise (a narrowing the router recorded on a net the
    script gave no width). A board record's facts also carry its per-layer shortfall and its necks (`board_widths`)."""
    from ..findings import Finding, FindingCause as C
    stated = stated or {}
    out = []
    for r in records:
        amps = None if "layers" in r else stated.get(r["net"], r.get("amps"))   # a board record is judged by its asked width
        short = amps is not None and r["max_a"] is not None and r["max_a"] < amps
        facts = {k: r[k] for k in ("net", "stage", "requested_mm", "delivered_min_mm", "length_under_mm", "length_mm", "share",
                                   "declared", "max_a", "bottleneck_mm")}
        facts.update({k: r[k] for k in ("bottleneck_layer", "necks_mm", "neck_limit_mm", "layers") if k in r})
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
    if r.get("layers"):
        need = ", ".join("%s %g" % (row["layer"], round(row["need_mm"], 2)) for row in r["layers"])
    else:
        need = "%g" % r["requested_mm"]
    return "%s %.1f%s mm under %s (min %g)" % (r["net"], r["length_under_mm"], length, need, r["delivered_min_mm"])
