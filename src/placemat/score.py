"""The run score: how good a layout is, as one number in millimetres of
wire, lower better. Each thing that can go wrong is counted and weighted by
a `[score]` setting; airwire counts a millimetre each. Runs, explore
variants and the bench are judged by it.

A run records its measures, not its score (`measures` below), so the score
is worked out whenever two runs are compared: a weight changed in
placemat.toml re-ranks the runs already recorded, the stored best included.

measures:
    v            MEASURES_VERSION: how the measures below were counted; a run recorded under another version is
                 not compared (report.comparable)
    unplaced     {priority: parts} not placed, by their declaration's priority
    drc          real DRC violations (a run; a plan has none)
    link_excess  the sum over links past their limit of (mm past it x the link's weight)
    link_mm      the sum over declared links with both pads placed of the link's weight x its pad-to-pad length
    findings     {kind: count} of the other findings (findings.KINDS)
    crossings    {"plain", "impedance", "pair_net", "plane", "pair"}: ratsnest crossings, each counted once in the
                 class that priced it (ratsnest.crossing_class): "plane" when either net is a plane's or free
                 net, "pair" between a differential pair's two halves, else the dearer kind of the two nets
    airwire_mm   the ratsnest's length over the nets that pull (not planes or free nets), a controlled-impedance
                 net's length counted score.impedance times
    area_mm2     a fitted frame's area (`board.rect(fit=...)`), 0.0 on a fixed outline
    giveway      the sum of the costs of the carried vias' actions (giveway.Action.cost: share, move,
                 leave, route, shorten, drop, and a field relay's once), as the search priced them
    pushes       the sum over placed pushes of value / limit at the final placement: the whole modelled
                 value over its limit, not only the excess, as the search prices a push (priced score.push)
    back_face    items a Face.EITHER search put on the back (priced score.back_face)
    rudy_steps   the worst RUDY cell, in score.congestion_step steps (absent when the step is 0)
"""
from __future__ import annotations

# How the measures are counted. A run recorded under another version is not comparable (report.comparable).
MEASURES_VERSION = 2

TERMS = ("unplaced", "drc", "link_over", "fixed", "copper", "label", "escape_crossed", "escape_closed",
         "escape_walled", "escape_via", "escape_lane", "setup", "crossings", "airwire", "link", "giveway", "push",
         "back_face", "congestion", "area")

# a finding kind -> the setting that weighs one; unplaced and link_over are
# measured apart (by priority, and by how far over), not counted as findings
_FINDING_WEIGHTS = {"fixed": "score_fixed", "copper": "score_copper", "label": "score_label",
                    "escape_crossed": "score_escape_crossed", "escape_closed": "score_escape_closed",
                    "escape_walled": "score_escape_walled", "escape_lane": "score_escape_lane",
                    "setup": "score_setup"}


def terms(m: dict, cfg) -> dict:
    """{term: mm} for measures `m` under the settings `cfg`."""
    prio = {"high": cfg.score_unplaced_high, "default": cfg.score_unplaced_default, "low": cfg.score_unplaced_low}
    found = m.get("findings") or {}
    cross = m.get("crossings") or {}
    out = {
        "unplaced": cfg.score_unplaced * sum(prio.get(p, cfg.score_unplaced_default) * n
                                             for p, n in (m.get("unplaced") or {}).items()),
        "drc": cfg.score_drc * (m.get("drc") or 0),
        "link_over": cfg.score_link_over * (m.get("link_excess") or 0.0),
    }
    for kind, setting in _FINDING_WEIGHTS.items():
        out[kind] = getattr(cfg, setting) * found.get(kind, 0)
    out["crossings"] = (cfg.score_crossing * (cross.get("plain", 0)
                                              + cfg.score_impedance * cross.get("impedance", 0)
                                              + cfg.score_crossing_pair_net * cross.get("pair_net", 0)
                                              + cfg.score_crossing_plane * cross.get("plane", 0))
                        + cfg.score_pair_crossing * cross.get("pair", 0))
    out["escape_via"] = 0.0     # no measure yet: the surface-lane judgement (a later task) counts the vias it needs
    out["airwire"] = float(m.get("airwire_mm") or 0.0)
    out["link"] = cfg.score_link * float(m.get("link_mm") or 0.0)
    out["area"] = cfg.score_area * float(m.get("area_mm2") or 0.0)
    out["giveway"] = float(m.get("giveway") or 0.0)         # costs already weighed by the search's score_via_* settings
    out["push"] = cfg.score_push * float(m.get("pushes") or 0.0)
    out["back_face"] = cfg.score_back_face * (m.get("back_face") or 0)
    out["congestion"] = cfg.score_congestion * (m.get("rudy_steps") or 0)
    return out


# The terms that say a layout is unusable, not merely worse: parts left unplaced, and the findings whose kind is
# critical by default (findings.SEVERITY: the board cannot be built or fully routed as it is) that a plan's measures
# count - a decided item illegal where it stands (fixed), planned copper that meets another net (copper), a pad with
# no route out (escape_walled). DRC has no part in a plan's measures, and `fab` is the same for every variant.
from .findings import SEVERITY as _SEVERITY
HARD_FINDINGS = tuple(k for k in _FINDING_WEIGHTS if _SEVERITY.get(k) == "critical")


def hard_clear(m: dict) -> bool:
    """Whether measures `m` have none of the hard terms: nothing unplaced and no critical finding."""
    found = m.get("findings") or {}
    return not (m.get("unplaced") or {}) and not any(found.get(k, 0) for k in HARD_FINDINGS)


def signal_crossings(m: dict) -> int:
    """How many of measures `m`'s crossings are not a plane's or free net's (a record before version 2 counts them
    as "signal")."""
    c = m.get("crossings") or {}
    if "signal" in c:
        return int(c["signal"])
    return int(sum(v for k, v in c.items() if k != "plane"))


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
_MEASURED_APART = ("unplaced", "link_over", "pair_crossed", "arrangement")     # a crossed pair is priced by the crossings term


# ------------------------------------------------------------ measuring a plan
# The terms that grow and shrink as the board is made, priced: what the search and refine add to at a candidate
# (`whole`). The rest (unplaced, drc, findings, give-way, back face) are counted from the plan alone.
WHOLE_TERMS = ("airwire", "crossings", "link", "link_over", "push", "escape_crossed", "escape_closed", "escape_walled",
               "escape_via", "congestion", "area")
_ESCAPE_KINDS = ("escape_crossed", "escape_closed", "escape_walled")


def _signal_edges(board, occ):
    """(edges of every net the occupancy has two or more placed pads on, the quiet nets, net -> kind, partners)."""
    from .occupancy import net_kinds
    from .pairs import board_pairs
    from .ratsnest import Anchor, mst
    quiet = set(board._plane_nets()) | set(board._free_nets)
    by_net: dict = {}
    for ref, g in occ.items.items():
        if ref in occ.pending:
            continue
        for s in g.shapes:
            if s.kind in ("pad", "through") and s.net and s.owner == ref:      # not a via it carries
                a = occ.pad_anchor(ref, s.label)
                by_net.setdefault(s.net, {})[(ref, s.label)] = Anchor(ref, s.label, a.x, a.y)
    edges = [e for net in sorted(by_net) for e in mst(net, list(by_net[net].values()))]
    kinds = net_kinds(board.geometry, quiet)
    partners = {n: m for n, m in board_pairs(board.geometry.netclasses).items()
                if n not in quiet and m not in quiet}
    return edges, quiet, kinds, partners


def _links_mm(board, occ, plan) -> tuple:
    """(sum of weight x length over the links with both pads placed, the excess past the limits). A resolved plan has
    each link's achieved length; a board part way through has not, and the links are measured on the occupancy."""
    mm, excess = 0.0, 0.0
    if plan.links:
        pairs = [(l, l.achieved_mm) for l in plan.links]
    else:
        pairs = []
        for l in board._links:
            if all(r in occ.items and r not in occ.pending for r in (l.a[0], l.b[0])):
                pairs.append((l, occ.pad_location(*l.a).distance(occ.pad_location(*l.b))))
    for l, d in pairs:
        if d is None:
            continue
        mm += int(l.weight) * d
        if l.limit_mm is not None and d > l.limit_mm:
            excess += (d - l.limit_mm) * int(l.weight)
    return mm, excess


def _frame_area(board, occ, plan) -> float:
    """A fitted frame's area: the plan's outline once the frame is fitted, else the frame the placed content makes
    now (as layout fits it); 0.0 on a fixed outline. A frame fitted on one axis has the other declared, so its
    width times its height is the fitted side times the declared one."""
    if not board._fit:
        return 0.0
    from .geometry import Box
    frame = plan.outline if any(plan.fitted_axes) and plan.outline is not None else None
    if frame is None:
        content = board._placed_box(occ, plan) or Box(0.0, 0.0, 0.0, 0.0)
        frame = board._fit_bound(content.inflate(board._fit_margin))
    return (frame.right - frame.left) * (frame.bottom - frame.top)


def _incremental(board, occ, plan) -> dict:
    """The raw measures of the terms in WHOLE_TERMS, of the board as the occupancy stands: the plan supplies the
    links, pushes, findings and the fit. Escapes are the plan's findings (so counted once a run has reported them)."""
    from .findings import Finding
    from .ratsnest import KIND_IMPEDANCE
    cfg = board.settings
    edges, quiet, kinds, partners = _signal_edges(board, occ)
    prices = (1.0, cfg.score_impedance, cfg.score_crossing_pair_net, cfg.score_crossing_plane,
              cfg.score_pair_crossing / cfg.score_crossing if cfg.score_crossing > 0 else 1.0)
    from .ratsnest import crossings
    # a quiet net's edges are counted whatever score.crossing_plane is, so a changed weight re-ranks recorded runs
    _, _, per_class = crossings(edges, kinds=kinds, partners=partners, prices=prices)
    wire = 0.0
    for e in edges:
        if e.net in quiet:
            continue
        wire += ((e.a.x - e.b.x) ** 2 + (e.a.y - e.b.y) ** 2) ** 0.5 \
            * (cfg.score_impedance if kinds.get(e.net) == KIND_IMPEDANCE else 1.0)
    link_mm, excess = _links_mm(board, occ, plan)
    # a push is placed once per item, but the same Push object may be recorded again by a re-settle
    pushes, seen = 0.0, set()
    for p in plan.pushes:
        if id(p) in seen or p.achieved_value is None or not p.limit:
            continue
        seen.add(id(p))
        pushes += p.achieved_value / p.limit
    found: dict = {}
    for f in plan.findings:
        kind = f.kind if isinstance(f, Finding) else "setup"
        if kind in _ESCAPE_KINDS:
            found[kind] = found.get(kind, 0) + 1
    out = {"crossings": per_class, "airwire_mm": round(wire, 3), "link_mm": round(link_mm, 6),
           "link_excess": round(excess, 6), "pushes": round(pushes, 6), "findings": found,
           "area_mm2": round(_frame_area(board, occ, plan), 3)}
    if cfg.score_congestion_step:
        rudy = plan.rudy if plan.rudy is not None else board._rudy(occ, plan)
        out["rudy_steps"] = int((getattr(rudy, "worst", 0.0) or 0.0) / cfg.score_congestion_step + 1e-9)
    return out


def whole(board, occ, plan) -> dict:
    """{term: mm} of WHOLE_TERMS for the board as the occupancy stands (R3): `plan` supplies its links, pushes,
    escape findings and fit. Congestion is the worst RUDY cell over the occupancy as `Board._rudy` takes it."""
    t = terms(_incremental(board, occ, plan), board.settings)
    return {k: t[k] for k in WHOLE_TERMS}


def plan_measures(board, plan) -> dict:
    """The measures of a resolved plan, without DRC: `_incremental`'s for the terms the search adds to, and the
    plan's own count of the rest."""
    from .board_geometry import members_of
    from .findings import Finding
    from .values import Face
    steps = {s.item: s for s in plan.steps}
    unplaced: dict = {}
    for i in board._placements():
        s = steps.get(i.key)
        if s is None or s.placement is not None:
            continue
        prio = i.priority.value if getattr(i, "priority_source", "") == "script" and i.priority is not None \
            else "default"
        unplaced[prio] = unplaced.get(prio, 0) + len(members_of(i.item))
    found: dict = {}
    for f in plan.findings:
        kind = f.kind if isinstance(f, Finding) else "setup"
        if kind not in _MEASURED_APART:
            found[kind] = found.get(kind, 0) + 1
    out = _incremental(board, plan.occupancy, plan)
    out.update({"v": MEASURES_VERSION, "unplaced": unplaced, "drc": 0, "findings": found,
                "giveway": round(sum(a.cost for a in plan.given_way), 6),
                "back_face": sum(1 for s in plan.steps if s.back_face and s.placement is not None
                                 and s.placement.face is Face.BACK)})
    return out
