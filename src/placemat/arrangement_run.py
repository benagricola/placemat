"""The module run's side of arrangements: the board prepared once its script has declared everything, and each arrangement
resolved from a snapshot of the declarations. The later tasks of the arrangements work add the proof, the record, the extent
and the fragment's notes here."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .arrangements import Spec
from .findings import Finding, FindingCause as C


@dataclass
class Prepared:
    board: object
    saved: tuple                # Board._snapshot() once the declarations are finished, before any arrangement is laid
    specs: tuple                # arrangements.Spec, the default first


def begin(board) -> Prepared:
    """The board as its script left it, checked and snapshotted, with the arrangements its declarations make."""
    board.finish_declarations()
    return Prepared(board, board._snapshot(), board.arrangement_specs())


def resolve_spec(prepared: Prepared, spec: Spec, *, reuse=None, lock=(), routes=None, partial=None):
    """One arrangement's Plan: the declarations put back, `spec` laid over them, and the resolve the default gets. Not
    reported to a studio: the module run's own plan is the default's. The board is left as it was found, the arrangement
    it was laid as included, whether the resolve returns or raises."""
    board = prepared.board
    found = board._snapshot()
    try:
        board._restore(prepared.saved)
        board.lay_arrangement(spec)
        return board._resolve(None, reuse, None, lock, routes, None, None, partial)
    finally:
        board._restore(found)


def signature(plan) -> str:
    """A digest of where the plan put every item and the copper it planned: two arrangements with one signature are one."""
    h = hashlib.sha256()
    for s in plan.steps:
        h.update(repr((s.item, s.kind, s.placement)).encode())
    for op in plan.copper:
        h.update(repr(op).encode())
    return h.hexdigest()[:16]


_SIDE_EDGE = (("north", lambda b: b.top, min), ("east", lambda b: b.right, max),
              ("south", lambda b: b.bottom, max), ("west", lambda b: b.left, min))
_TOL = 1e-6


def extent_from_boxes(boxes: dict) -> list:
    """The members whose box reaches the outline round all of them on a side, with how far each stands past the next member's
    edge on that side (the most over its sides). Most protruding first, then by name."""
    out: dict = {}
    for side, edge, pick in _SIDE_EDGE:
        values = sorted(((edge(b), n) for n, b in boxes.items()), key=lambda t: (t[0] if pick is min else -t[0], t[1]))
        if not values:
            continue
        best = values[0][0]
        others = [w for w, _ in values if abs(w - best) > _TOL]
        gap = abs(best - others[0]) if others else 0.0
        for v, n in values:
            if abs(v - best) > _TOL:
                break
            sides_of, was = out.get(n, ([], 0.0))
            out[n] = (sides_of + [side], max(was, gap))
    order = [s for s, _, _ in _SIDE_EDGE]
    rows = [{"item": n, "sides": sorted(s, key=order.index), "protrudes_mm": round(g, 6)} for n, (s, g) in out.items()]
    return sorted(rows, key=lambda r: (-r["protrudes_mm"], r["item"]))


def extent_of(plan) -> list:
    """`extent_from_boxes` of a resolved plan's placed members, as the placer claims them (`report.claimed_boxes`)."""
    from .report import claimed_boxes
    return extent_from_boxes(claimed_boxes(plan))


def extent_findings(board, extent: list, threshold_mm: float) -> list:
    """`arrangement.extent_fixed` for each extent member with no alternative: on a module that declares any, every one; on one
    that declares none, those standing past the next member by more than `threshold_mm` (`place.extent_notice_mm`)."""
    declares = bool(board._options or board._arr_groups)
    moved = set(board._options) | {o.item for g in board._arr_groups for o in g.options}
    out = []
    for row in extent:
        if row["item"] in moved or (not declares and row["protrudes_mm"] <= threshold_mm):
            continue
        out.append(Finding(C.ARRANGEMENT_EXTENT_FIXED, dict(row, alternatives=declares), "notice"))
    return out


@dataclass
class Proof:
    offered: bool
    refused: list               # records (finding_text.refusal_record_text reads them)
    metrics: dict               # {"drc": int | None, "findings": {severity: n}, "measures": {...}}


def plan_refusals(plan, default_plan) -> list:
    """What the resolve itself says against an arrangement: an item with no place, a critical finding, and a cell standing
    elsewhere than in the default (a module's nested cells are placed once, by the default: an arrangement that needs one moved is
    not offered)."""
    out = []
    for s in plan.steps:
        if s.kind in ("part", "cell", "block") and s.placement is None:
            out.append({"form": "unplaced", "item": s.item})
    for f in plan.findings:
        if f.severity == "critical":
            out.append({"form": "finding", "cause": f.cause.value, "item": finding_subject(f)})
    was = {s.item: s.placement for s in default_plan.steps if s.placement is not None}
    for s in plan.steps:
        if s.kind == "cell" and s.placement is not None and was.get(s.item) not in (None, s.placement):
            out.append({"form": "nested_cell", "item": s.item})
    return out


def finding_subject(f) -> str:
    from . import finding_text
    return finding_text.subject(f.cause, f.facts) or ""


def drc_refusals(report, default_unconnected: int) -> list:
    out = [{"form": "drc", "bucket": b, "count": n} for b, n in sorted(report.real.items())]
    if report.unconnected > default_unconnected:
        out.append({"form": "unconnected", "count": report.unconnected, "default": default_unconnected})
    return out


def verdict_refusals(verdicts) -> list:
    return [{"form": "verdict", "check": v.check, "item": v.subject} for v in verdicts if v.ok is False and not v.accepted]
