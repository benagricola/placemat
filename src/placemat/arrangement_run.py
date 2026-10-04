"""The module run's side of arrangements: the board prepared once its script has declared everything, and each arrangement
resolved from a snapshot of the declarations. The later tasks of the arrangements work add the proof, the record, the extent
and the fragment's notes here."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .arrangements import Spec


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
