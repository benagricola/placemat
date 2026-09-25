"""The run score: how good a layout is, as one number in millimetres of
wire, lower better. Each thing that can go wrong is counted and weighted by
a `[score]` setting; airwire counts a millimetre each. Runs, explore
variants and the bench are judged by it.

A run records its measures, not its score (`measures` below), so the score
is worked out whenever two runs are compared: a weight changed in
placemat.toml re-ranks the runs already recorded, the stored best included.

measures:
    unplaced     {priority: parts} not placed, by their declaration's priority
    drc          real DRC violations (a run; a plan has none)
    link_excess  the sum over links past their limit of (mm past it x the link's weight)
    findings     {kind: count} of the other findings (findings.KINDS)
    crossings    {"signal": n, "plane": n, "pair": n}: ratsnest crossings, those
                 with a plane's or free net's airwire counted apart, and
                 "pair" those of the signal crossings between a
                 differential pair's two halves (priced score.pair_crossing)
    airwire_mm   the ratsnest's length
    rudy_steps   explore only: the worst RUDY cell, in explore.congestion_step steps
"""
from __future__ import annotations

TERMS = ("unplaced", "drc", "link_over", "fixed", "copper", "label", "escape_crossed", "escape_closed",
         "escape_walled", "setup", "crossings", "airwire", "congestion")

# a finding kind -> the setting that weighs one; unplaced and link_over are
# measured apart (by priority, and by how far over), not counted as findings
_FINDING_WEIGHTS = {"fixed": "score_fixed", "copper": "score_copper", "label": "score_label",
                    "escape_crossed": "score_escape_crossed", "escape_closed": "score_escape_closed",
                    "escape_walled": "score_escape_walled", "setup": "score_setup"}


def terms(m: dict, cfg) -> dict:
    """{term: mm} for measures `m` under the settings `cfg`."""
    prio = {"high": cfg.score_priority_high, "default": cfg.score_priority_default, "low": cfg.score_priority_low}
    found = m.get("findings") or {}
    cross = m.get("crossings") or {}
    out = {
        "unplaced": cfg.score_unplaced * sum(prio.get(p, cfg.score_priority_default) * n
                                             for p, n in (m.get("unplaced") or {}).items()),
        "drc": cfg.score_drc * (m.get("drc") or 0),
        "link_over": cfg.score_link_over * (m.get("link_excess") or 0.0),
    }
    for kind, setting in _FINDING_WEIGHTS.items():
        out[kind] = getattr(cfg, setting) * found.get(kind, 0)
    pair = cross.get("pair", 0)             # within "signal", priced apart
    out["crossings"] = (cfg.score_crossing * (cross.get("signal", 0) - pair + cfg.score_crossing_plane * cross.get("plane", 0))
                        + cfg.score_pair_crossing * pair)
    out["airwire"] = float(m.get("airwire_mm") or 0.0)
    out["congestion"] = cfg.score_congestion * (m.get("rudy_steps") or 0)
    return out


def total(m: dict, cfg) -> float:
    return sum(terms(m, cfg).values())


def noise(a: dict, b: dict, cfg) -> float:
    """How far apart two scores may be and still tie: kicad-cli draws a
    different ratsnest for a byte-identical board run to run (report.py's
    AIRWIRE_NOISE note), so airwire and crossings each carry a band."""
    air = max(float(a.get("airwire_mm") or 0.0), float(b.get("airwire_mm") or 0.0))
    cross = max(terms(a, cfg)["crossings"], terms(b, cfg)["crossings"])
    return cfg.best_airwire_noise * air + cfg.best_crossing_noise * cross


def compare(a: dict, b: dict, cfg) -> tuple:
    """(sign, term): -1 when `a` is better than `b`, 1 when worse, 0 when
    they tie within the noise band; `term` the one that moved the score
    furthest that way (None on a tie)."""
    ta, tb = terms(a, cfg), terms(b, cfg)
    diff = sum(ta.values()) - sum(tb.values())
    if abs(diff) <= noise(a, b, cfg) + 1e-9:
        return 0, None
    sign = 1 if diff > 0 else -1
    term = max(TERMS, key=lambda t: sign * (ta[t] - tb[t]))
    return sign, term


# Measured from the plan itself, not counted from its findings: unplaced by
# priority, links by how far past their limit.
_MEASURED_APART = ("unplaced", "link_over")


# ------------------------------------------------------------ measuring a plan
def plan_measures(board, plan, congestion_step: float | None = None) -> dict:
    """The measures of a resolved plan, without DRC: its own ratsnest gives
    the crossings and the airwire. `congestion_step` adds the worst RUDY
    cell in those steps (explore)."""
    from .board_geometry import members_of
    from .findings import Finding
    from .ratsnest import Anchor, crossings, mst
    steps = {s.item: s for s in plan.steps}
    unplaced: dict = {}
    for i in board._placements():
        s = steps.get(i.key)
        if s is None or s.placement is not None:
            continue
        prio = i.priority.value if getattr(i, "priority_source", "") == "script" and i.priority is not None \
            else "default"
        unplaced[prio] = unplaced.get(prio, 0) + len(members_of(i.item))
    excess = 0.0
    for l in plan.links:
        if l.limit_mm is not None and l.achieved_mm is not None and l.achieved_mm > l.limit_mm:
            excess += (l.achieved_mm - l.limit_mm) * int(l.weight)
    found: dict = {}
    for f in plan.findings:
        kind = f.kind if isinstance(f, Finding) else "setup"
        if kind not in _MEASURED_APART:
            found[kind] = found.get(kind, 0) + 1

    quiet = set(board._plane_nets()) | set(board._free_nets)
    occ = plan.occupancy
    by_net: dict = {}
    for ref, g in occ.items.items():
        if ref in occ.pending:
            continue
        for s in g.shapes:
            if s.kind in ("pad", "through") and s.net:
                a = occ.pad_anchor(ref, s.label)
                by_net.setdefault(s.net, {})[(ref, s.label)] = Anchor(ref, s.label, a.x, a.y)
    edges = [e for net in sorted(by_net) for e in mst(net, list(by_net[net].values()))]
    every = crossings(edges)[0]
    signal = crossings(edges, weights={n: 0.0 for n in quiet})[0]
    from .pairs import pairs_of
    partners = {n: m for n, m in pairs_of(by_net).items() if n not in quiet and m not in quiet}
    # only a pair's own crossings count here: every other crossing weighs 0
    pair = crossings(edges, weights={n: 0.0 for n in by_net}, partners=partners, pair_weight=1.0)[0]
    out = {"unplaced": unplaced, "drc": 0, "link_excess": round(excess, 6), "findings": found,
           "crossings": {"signal": int(signal), "plane": int(every - signal), "pair": int(pair)},
           "airwire_mm": round(sum(((e.a.x - e.b.x) ** 2 + (e.a.y - e.b.y) ** 2) ** 0.5 for e in edges), 3)}
    if congestion_step:
        worst = getattr(getattr(plan, "rudy", None), "worst", 0.0) or 0.0
        out["rudy_steps"] = int(worst / congestion_step + 1e-9)
    return out
