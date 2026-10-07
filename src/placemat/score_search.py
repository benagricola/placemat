"""Temporary measurement search for the complete common placement objective.

The clique search remains the default until the measured adoption gate. This
scorer evaluates every legal candidate: signed changes do not justify the
old wire-only pruning bound.
"""
import math

from .score_delta import Delta


class ScoreDomainError(ValueError):
    """A candidate exceeds the diagnostic domain, not physical feasibility.

    The temporary measurement path aborts this scan rather than comparing
    unmeasured candidates. It does not silently change objectives.
    """
    code = 'score_domain_unmeasured'

    def __init__(self, placement):
        super().__init__('MST candidate pads exceed the fixed search frame; '
                         'the complete objective is unmeasured at this placement')
        self.facts = {'placement': placement, 'policy': 'abort_scan'}


class MSTScorer:
    def __init__(self, board, occ, item, *, plan, pushes=(), lanes=None):
        self.delta = Delta(board, occ, item, plan.links, pushes=pushes, lanes=lanes, plan=plan)
        self.best = [math.inf]
        self._native = {}
        self.refusals = {}

    def __call__(self, placement):
        if not self.delta.scorable(placement):
            raise ScoreDomainError(placement)
        change = self.delta(placement)
        if not change.walled:
            self.best[0] = min(self.best[0], change.total)
        return change.walled, change.total

    def native(self, rotations, face):
        from . import geometry
        from .prepared_escape import prepare
        self.delta._check_snapshot()
        rotations = tuple(rotations)
        key = rotations, face
        if key not in self._native:
            prepared, reason = prepare(self.delta, rotations, face, rest_cache=True)
            if prepared is None or not hasattr(geometry._native, 'NativeDeltaScoring'):
                self.refusals[key] = reason or 'complete native sweep adapter unavailable'
                self._native[key] = None
            else:
                cfg = self.delta.board.settings
                baseline = self.delta._escape_base
                self._native[key] = geometry._native.NativeDeltaScoring(
                    prepared.candidate, prepared.scoring, prepared.surface,
                    (cfg.score_escape_crossed, cfg.score_escape_closed, cfg.score_escape_via),
                    (baseline.get('escape_closed', 0), baseline.get('escape_via', 0)), self.best[0])
        return self._native[key]
