"""The run score: how good a layout is, as one number in millimetres of
wire, lower better. Each soft thing that can go wrong is counted and weighted by
a `[score]` setting; airwire counts a millimetre each. What makes a board
unbuildable (unplaced parts, DRC errors beyond the baseline, failed required
widths, critical findings) is not priced: it is the validity tier of `rank`,
the one board comparison runs, explore variants and the bench are judged by.

A run records its measures, not its score (`measures` below), so the score
is worked out whenever two runs are compared: a weight changed in
placemat.toml re-ranks the runs already recorded, the stored best included.
A setting that changes how a measure is counted does not: `score.congestion_step`
and `score.congestion_box` set how `rudy_steps` is counted, and a stored run keeps
the count it was recorded with.

measures:
    v            MEASURES_VERSION: how the measures below were counted; a run recorded under another version is
                 not compared (report.comparable)
    unplaced     {priority: parts} not placed, by their declaration's priority (the validity tier's, `Validity.of`)
    drc          real DRC violations (a run; a plan has none); the validity tier reads a run's as its `drc_new`
    link_excess  the sum over links past their limit of (mm past it x the link's weight)
    link_mm      the sum over declared links with both pads placed of the link's weight x its pad-to-pad length
    findings     {kind: count} of the other findings (findings.KINDS)
    crossings    {key: n}: ratsnest crossings by what crosses, whatever they are priced at
                 (ratsnest.crossing_key): "plane" when either net is a plane's or free net, "pair" between a
                 differential pair's two halves, else the two nets' kinds, the lower first ("plain+plain",
                 "plain+impedance", "plain+pair_net", ...); `terms` prices each at the dearer kind
    airwire_mm   the ratsnest's length over the nets that pull (not planes or free nets), each net once
    airwire_impedance_mm  the part of airwire_mm that is controlled-impedance nets (`terms` counts it
                 score.impedance times in all)
    area_mm2     a fitted frame's area (`board.rect(fit=...)`), 0.0 on a fixed outline
    giveway      the sum of the costs of the carried vias' actions (giveway.Action.cost: share, move,
                 leave, route, shorten, drop, and a field relay's once), as the search priced them
    pushes       the sum over placed pushes of value / limit at the final placement: the whole modelled
                 value over its limit, not only the excess, as the search prices a push (priced score.push)
    back_face    items a Face.EITHER search put on the back (priced score.back_face)
    rudy_steps   the worst RUDY cell, in score.congestion_step steps (absent when the step is 0)
    vias, copper_mm, segments  the routed board's vias, track length and track count (a routed run only), for
                 `quality_key`
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# How the measures are counted. A run recorded under another version is not comparable (report.comparable).
# 3: rudy_steps counts each net's box at least score.congestion_box each way.
# 4: a differential pair's two airwires between the same two parts cross as ratsnest.pair_crossed judges them.
MEASURES_VERSION = 4

TERMS = ("link_over", "label", "escape_crossed", "escape_closed", "escape_via", "escape_lane", "setup", "crossings",
         "airwire", "link", "giveway", "push", "back_face", "congestion", "area")

# a finding kind -> the setting that weighs one; link_over is measured apart (by how far over), not counted as a
# finding. The critical kinds (HARD_FINDINGS) are not weighed: they are the validity tier's.
_FINDING_WEIGHTS = {"label": "score_label", "escape_crossed": "score_escape_crossed",
                    "escape_closed": "score_escape_closed", "escape_via": "score_escape_via",
                    "escape_lane": "score_escape_lane", "setup": "score_setup"}


def terms(m: dict, cfg) -> dict:
    """{term: mm} for measures `m` under the settings `cfg`."""
    found = m.get("findings") or {}
    cross = m.get("crossings") or {}
    out = {"link_over": cfg.score_link_over * (m.get("link_excess") or 0.0)}
    for kind, setting in _FINDING_WEIGHTS.items():
        out[kind] = getattr(cfg, setting) * found.get(kind, 0)
    from .ratsnest import CLASS_NAMES, prices_of
    price = dict(zip(CLASS_NAMES, prices_of(cfg)))
    out["crossings"] = cfg.score_pair_crossing * cross.get("pair", 0) + cfg.score_crossing * sum(
        n * (price["plane"] if key == "plane" else max(price[k] for k in key.split("+")))
        for key, n in cross.items() if key != "pair")
    out["airwire"] = float(m.get("airwire_mm") or 0.0) \
        + (cfg.score_impedance - 1.0) * float(m.get("airwire_impedance_mm") or 0.0)
    out["link"] = cfg.score_link * float(m.get("link_mm") or 0.0)
    out["area"] = cfg.score_area * float(m.get("area_mm2") or 0.0)
    out["giveway"] = float(m.get("giveway") or 0.0)         # costs already weighed by the search's score_via_* settings
    out["push"] = cfg.score_push * float(m.get("pushes") or 0.0)
    out["back_face"] = cfg.score_back_face * (m.get("back_face") or 0)
    out["congestion"] = cfg.score_congestion * (m.get("rudy_steps") or 0)
    return out


# The findings that say a layout is unusable, not merely worse, that a plan's measures count: the kinds critical by
# default (findings.SEVERITY: the board cannot be built or fully routed as it is) - a decided item illegal where it
# stands (fixed), planned copper that meets another net (copper), a pad with no route out (escape_walled). They are
# counted in the validity tier (`Validity.critical`), never priced. `fab` is the same for every variant.
HARD_FINDINGS = ("fixed", "copper", "escape_walled")


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


# ------------------------------------------------------------ the one board comparison
_PRIORITIES = ("high", "default", "low")


@dataclass(frozen=True)
class Validity:
    """What makes a board unbuildable, as counts (D13): it has one home, here, and none in the run score."""
    unplaced: tuple = (0, 0, 0)  # unplaced parts by priority: (high, default, low)
    drc_new: int | None = None   # "real" DRC errors beyond the board's baseline (D14); None when no DRC ran
    widths_failed: int = 0       # connections whose required width is not met on the final board
    critical: int = 0            # critical findings the measures count (HARD_FINDINGS)

    @property
    def valid(self) -> bool:
        return not any(self.key())

    def key(self) -> tuple:
        """(*unplaced, drc_new, widths_failed, critical), lower better: two invalid boards compare by it."""
        return (*self.unplaced, self.drc_new or 0, self.widths_failed, self.critical)

    @classmethod
    def of(cls, measures: dict, drc_new: int | None = None, widths_failed: int = 0) -> "Validity":
        """The counts of measures `m` (unplaced by priority, the HARD_FINDINGS), with the DRC errors beyond the
        baseline and the failed widths, which the measures do not hold."""
        unplaced = measures.get("unplaced") or {}
        found = measures.get("findings") or {}
        return cls(unplaced=tuple(int(unplaced.get(p, 0)) for p in _PRIORITIES), drc_new=drc_new,
                   widths_failed=int(widths_failed or 0), critical=sum(int(found.get(k, 0)) for k in HARD_FINDINGS))


@dataclass(frozen=True)
class Standing:
    """A board as `rank` compares it."""
    measures: dict
    validity: Validity = Validity()
    closures: tuple = ()        # each phase's final clean closure, in phase order; () when not routed
    clean: float | None = None  # the route's clean closure; None when not routed

    @classmethod
    def of_route(cls, measures: dict, report) -> "Standing":
        """A routed board from its route report (step 1's RouteReport): the phases' closures and the clean closure, the
        DRC errors beyond the baseline and the failed widths into the validity tier, and the routed vias, copper and
        segments into the measures, for the quality key."""
        m = dict(measures, vias=report.vias, copper_mm=report.track_mm, segments=report.segments)
        return cls(m, Validity.of(m, drc_new=report.drc_new, widths_failed=report.widths_failed),
                   tuple(p["final_closure_clean"] for p in report.phases), report.closure_clean)


QUALITY_TERMS = ("vias", "copper_mm", "segments")


def _quality_term(v):
    # as KRT's ledger_score._term (py_router/ledger_score.py:65): a number as it is, else +inf (unmeasured ranks last);
    # a bool is not a count
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return math.inf
    if isinstance(v, int) or math.isfinite(v):
        return v
    return math.inf


def quality_key(measures: dict) -> tuple:
    """(vias, copper_mm, segments) of a routed board, lower better, compared lexicographically and exactly: KRT's
    routed quality key (py_router/ledger_score.py:76 `quality_key`, its terms py_tools/board_score.py:1033 `quality`).
    A missing or non-numeric term is +inf."""
    return tuple(_quality_term(measures.get(k)) for k in QUALITY_TERMS)


def _routed(s: Standing) -> bool:
    return s.clean is not None


def _complete(s: Standing) -> bool:
    return s.clean is not None and s.clean >= 1.0 - 1e-9


def _sign(a, b) -> int:
    return (a > b) - (a < b)


def validity_order(a: Standing, b: Standing) -> int:
    """`rank`'s first tier alone: -1 when `a` is valid and `b` not, or both are invalid and `a` has the lower
    `Validity.key()`; 1 the other way; 0 when the tier does not decide."""
    va, vb = a.validity.valid, b.validity.valid
    if va != vb:
        return -1 if va else 1
    return 0 if va else _sign(a.validity.key(), b.validity.key())


def rank(a: Standing, b: Standing, cfg) -> int:
    """-1 when `a` ranks above `b`, 1 below, 0 a tie (D11-D17):
    1. validity: a valid board above an invalid one; two invalid boards by `Validity.key()`;
    2. the phases' closures in order (higher better, exact), when both are routed;
    3. the clean closure, when both are routed;
    4. when both are valid and at full clean closure: KRT's quality key (vias, copper_mm, segments), lexicographic,
       exact (D17);
    5. the run score, within its noise band (area is a term of it).
    A tie (0) keeps the incumbent: callers replace a held board only on -1, and never replace a valid board with an
    invalid one (D12)."""
    s = validity_order(a, b)
    if s:
        return s
    va = a.validity.valid
    if _routed(a) and _routed(b):
        for ca, cb in zip(a.closures, b.closures):
            s = _sign(cb, ca)
            if s:
                return s
        s = _sign(b.clean, a.clean)
        if s:
            return s
        if va and _complete(a) and _complete(b):
            s = _sign(quality_key(a.measures), quality_key(b.measures))
            if s:
                return s
    return compare(a.measures, b.measures, cfg)[0]


def placement_key(row, ranks=None):
    """Exact placement-ensemble order, shared by explore and its checkpoint.

    Rows are (seed, objective, measures). Settings are fixed by the checkpoint
    digest, so the recorded objective remains authoritative on resume. Validity
    precedes that objective using available placement evidence (including known
    DRC counts); plan-only rows do not certify DRC. Optional pin-remapped
    objectives replace it. Seed
    order breaks exact ties deterministically across worker completion orders,
    with the plain seed 0 retained on a tie. Missing evidence ranks last.
    """
    seed, objective, measures = row
    if measures is None:
        return (1, True, (), math.inf, seed)
    validity = Validity.of(measures, drc_new=measures.get("drc"))
    return (0, not validity.valid, validity.key(), (ranks or {}).get(seed, objective), seed)


# Measured from the plan itself, not counted from its findings: unplaced by
# priority, links by how far past their limit.
_MEASURED_APART = ("unplaced", "link_over", "pair_crossed", "arrangement")     # a crossed pair is priced by the crossings term


# ------------------------------------------------------------ measuring a plan
# The terms that grow and shrink as the board is made, priced: what the search and refine add to at a candidate
# (`whole`). The rest (unplaced, drc, findings, give-way, back face) are counted from the plan alone.
WHOLE_TERMS = ("airwire", "crossings", "link", "link_over", "push", "escape_crossed", "escape_closed", "escape_via",
               "escape_lane", "congestion", "area")


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
        anchor = None
        for s in g.shapes:
            if s.kind in ("pad", "through") and s.net and s.owner == ref:      # not a via it carries
                anchor = anchor or occ.pad_anchors(ref)
                a = anchor(s.label)
                by_net.setdefault(s.net, {})[(ref, s.label)] = Anchor(ref, s.label, a.x, a.y)
    edges = [e for net in sorted(by_net) for e in mst(net, list(by_net[net].values()))]
    kinds = net_kinds(board.geometry, quiet)
    partners = {n: m for n, m in board_pairs(board.geometry.netclasses).items()
                if n not in quiet and m not in quiet}
    return edges, quiet, kinds, partners


def _links_mm(board, occ, plan, links=None) -> tuple:
    """(sum of weight x length over the links with both pads placed, the excess past the limits). A resolved plan has
    each link's declared obligation; current geometry always comes from the occupancy."""
    mm, excess = 0.0, 0.0
    declared = (plan.links or board._links) if links is None else links
    pairs = [(l, occ.pad_location(*l.a).distance(occ.pad_location(*l.b)))
             for l in declared
             if all(r in occ.items and r not in occ.pending for r in (l.a[0], l.b[0]))]
    for l, d in pairs:
        if d is None:
            continue
        mm += int(l.weight) * d
        if l.limit_mm is not None and d > l.limit_mm:
            excess += (d - l.limit_mm) * int(l.weight)
    return mm, excess


def _frame_area(board, occ, plan) -> float:
    """Current occupied fit area, respecting each fixed axis; zero on a fixed outline."""
    if not board._fit:
        return 0.0
    frame = _fit_frame(board, occ, plan)
    return frame.width * frame.height


def _placed_content(occ, plan):
    """Current placed shape/copper bounds; pending owners contribute nothing."""
    from .copper import Track, Via, Pour, Text
    from .values import Box
    boxes = [shape.box for ref, geom in occ.items.items() if ref not in occ.pending for shape in geom.shapes]
    boxes.extend(c.box for c in occ.copper if c.owner not in occ.pending)
    boxes.extend(op.box for op in plan.copper if isinstance(op, (Track, Via, Pour, Text)))
    return Box.union(boxes) if boxes else None


def _fit_frame(board, occ, plan):
    from .values import Box
    content = _placed_content(occ, plan) or Box(0.0, 0.0, 0.0, 0.0)
    return board._fit_bound(content.inflate(board._fit_margin))


def _pushes(board, occ, plan):
    """Declared pushes and annotation pairs at their current physical points."""
    from .layout import _push_value
    value, seen = 0.0, set()
    declared = [push for intent in board._placements() for push in intent.pushes]
    for push in declared + list(plan.pushes):
        if id(push) in seen or push.kind or not push.limit:
            continue
        seen.add(id(push))
        ref = push.target_member_ref
        if ref not in occ.items or ref in occ.pending:
            continue
        if board._push_needs(push.source) & occ.pending:
            continue
        point = occ.pad_location(*push.target_pad_key) if push.target_pad_key else occ.geometry_of(ref).body.center
        source = board._push_source_point(occ, plan, push.source)
        value += _push_value(source, point, push)[0] / push.limit
    ann = board._annotations
    if ann:
        placed = set(occ.items) - occ.pending
        for sens in sorted(placed & ann.sensitives.keys()):
            point = board._sense_point(occ, sens)
            for kind, limit, _ in ann.sensitives[sens].limits:
                for src in sorted((placed & ann.sources.keys()) - {sens}):
                    distance = board._emission_point(occ, src).distance(point)
                    value += sum(e.at(distance) / limit for e in ann.sources[src].emissions if e.kind == kind)
    return value


def _incremental(board, occ, plan, escapes: bool = True) -> dict:
    """The raw measures of the terms in WHOLE_TERMS, of the board as the occupancy stands: the plan supplies the
    links, pushes and the fit. Escapes are counted as the escape findings judge them on the occupancy
    (`escapes.Escapes.found`), so the count is right at any moment of a resolve; `escapes=False` leaves them out, for
    a caller that counts the plan's findings."""
    from .ratsnest import KIND_IMPEDANCE
    cfg = board.settings
    edges, quiet, kinds, partners = _signal_edges(board, occ)
    from .ratsnest import crossings
    # a quiet net's edges are counted whatever score.crossing_plane is, so a changed weight re-ranks recorded runs
    _, _, per_class = crossings(edges, kinds=kinds, partners=partners, polarity=occ.pair_polarity())
    wire = impedance = 0.0
    for e in edges:
        if e.net in quiet:
            continue
        d = math.hypot(e.a.x - e.b.x, e.a.y - e.b.y)
        wire += d
        if kinds.get(e.net) == KIND_IMPEDANCE:
            impedance += d
    link_mm, excess = _links_mm(board, occ, plan)
    pushes = _pushes(board, occ, plan)
    found: dict = {}
    if escapes:
        from .escapes import judging
        found = {k: len(v) for k, v in judging(occ).found().items() if v}
        found['escape_lane'] = board._declared_lanes_blocked(occ, plan)
    out = {"crossings": per_class, "airwire_mm": wire,
           "airwire_impedance_mm": impedance, "link_mm": link_mm,
           "link_excess": excess, "pushes": pushes, "findings": found,
           "area_mm2": _frame_area(board, occ, plan)}
    if cfg.score_congestion_step:
        out["rudy_steps"] = occ.congestion().steps()
    return out


def whole(board, occ, plan) -> dict:
    """{term: mm} of WHOLE_TERMS for the board as the occupancy stands (R3): `plan` supplies its links, pushes and
    fit; escapes are judged on the occupancy. Congestion is the worst RUDY cell over the occupancy as `Board._rudy` takes it."""
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
    out = _incremental(board, plan.occupancy, plan, escapes=False)
    # Declaration notices were emitted during resolve; later movement can
    # change them. The recorded raw objective uses the live oracle once.
    found['escape_lane'] = board._declared_lanes_blocked(plan.occupancy, plan)
    out.update({"v": MEASURES_VERSION, "unplaced": unplaced, "drc": 0, "findings": found,
                "giveway": round(sum(a.cost for a in plan.given_way), 6),
                "back_face": sum(1 for s in plan.steps if s.back_face and s.placement is not None
                                 and s.placement.face is Face.BACK)})
    return out
