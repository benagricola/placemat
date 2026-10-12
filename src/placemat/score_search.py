"""The one-score search's scorer (`place.search_wire` "mst", the default): the run score's change for a lifted item.

Each candidate is scored on every term but the escape grades; the best `place.escape_spots` by that get them
(D25). Pruning is on proved bounds only (R13).
"""
import math

from .score_delta import Delta

# Whether a pruning scorer prunes at all: False measures the exhaustive search under the same callers (a measurement
# switch, as placer.NATIVE_SWEEP is; never a setting).
PRUNE = True


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
    """The common objective's change for a lifted item, as a scan's scorer: (pads walled, cost). Called, it is the
    Python Delta in full; `native(rotations, face)` is the same in the native sweep.

    The one-score search (D25): `scan(placement)` is what a scan asks of each candidate, every term but the escape
    grades and the walled check, standing at (placer.PARTIAL, that partial cost). The scan's walk asks `full` of the
    best by it until `place.escape_spots` wall no pad beyond the lifted board's (`walled_base`), and ranks those by
    the full cost. The native sweep scores so when its scorer's `escapes` is off. With `prune` (a scan that reads only
    its best: no `pick`, no `accept`) the native sweep prunes partial costs on proved bounds (R13): a pruned candidate
    stands at (placer.UNWEIGHED, its bound), and is weighed if the walk reaches it."""
    def __init__(self, board, occ, item, *, plan, pushes=(), lanes=None, prune=False):
        from .escapes import native_judge
        self.delta = Delta(board, occ, item, plan.links, pushes=pushes, lanes=lanes, plan=plan)
        self.delta.escape_native = native_judge()
        self.prune = prune
        self.spots = board.settings.place_escape_spots
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

    @property
    def walled_base(self) -> int:
        """The pads the lifted board walls in: a candidate scored in full at no more walls none of its own."""
        return self.delta._escape_base.get('escape_walled', 0)

    def scan(self, placement):
        """A scan's candidate, on every term but the escape grades and the walled check: (placer.PARTIAL, cost)."""
        from .placer import PARTIAL
        if not self.delta.scorable(placement):
            raise ScoreDomainError(placement)
        terms, _ = self.delta.relative(placement, escapes=False)
        return PARTIAL, sum(terms.values())

    def partial(self, placement, *, python=False):
        """A candidate's partial cost, never pruned: what the scan's walk asks of a pruned candidate it reaches."""
        scoring = None if python else self._prepared(placement)
        if scoring is not None:
            rotations, scoring = scoring
            return scoring.partial_cost(placement.location.x, placement.location.y,
                                        rotations.index(placement.rotation))
        return self.scan(placement)[1]

    def _prepared(self, placement):
        """(rotations, the native sweep's prepared scorer) that has the candidate's turn and face, or None."""
        for (rotations, face), scoring in self._native.items():
            if scoring is not None and face == placement.face and placement.rotation in rotations:
                return rotations, scoring
        return None

    def full(self, placement, *, python=False):
        """A candidate the scan's walk takes, scored in full: (walled, cost), as called, from the native sweep's
        prepared scorer when it has the candidate's turn and face (`python` off)."""
        scoring = None if python else self._prepared(placement)
        if scoring is None:
            return self(placement)
        rotations, scoring = scoring
        cost, walled = scoring.full(placement.location.x, placement.location.y, rotations.index(placement.rotation))
        if not walled:
            self.best[0] = min(self.best[0], cost)
        return walled, cost

    def native(self, rotations, face):
        from . import geometry
        from .prepared_escape import prepare
        self.delta._check_snapshot()
        rotations = tuple(rotations)
        key = rotations, face
        if key not in self._native:
            # A scan of some of the turns a prepared scorer has: that scorer, its sweep's turns mapped to its own
            # (the same scores; a surface is prepared once per lifted board and face).
            wider = next((k for k, scoring in self._native.items() if scoring is not None and k[1] == face
                          and set(rotations) <= set(k[0])), None)
            if wider is not None and hasattr(self._native[wider], 'set_turn_map'):
                self._native[wider].set_turn_map([wider[0].index(r) for r in rotations])
                return self._native[wider]
            prepared, reason = prepare(self.delta, rotations, face, rest_cache=True)
            if prepared is None or not hasattr(geometry._native, 'NativeDeltaScoring'):
                self.refusals[key] = reason or 'complete native sweep adapter unavailable'
                self._native[key] = None
            else:
                cfg = self.delta.board.settings
                baseline = self.delta._escape_base
                scoring = geometry._native.NativeDeltaScoring(
                    prepared.candidate, prepared.scoring, prepared.surface,
                    (cfg.score_escape_crossed, cfg.score_escape_closed, cfg.score_escape_via),
                    (baseline.get('escape_closed', 0), baseline.get('escape_via', 0)), self.best[0])
                if self.prune and PRUNE:
                    scoring.configure_prune(self.spots, self._congestion_bound())
                self._native[key] = scoring
        scoring = self._native[key]
        if scoring is not None and hasattr(scoring, 'set_turn_map'):
            scoring.set_turn_map(None)
        return scoring

    def _congestion_bound(self):
        """The proved lower bound of R13 on the congestion change for this lifted board: at least minus its price
        times the worst cell's steps now, as none can go below zero. The other partial terms are computed before it."""
        delta = self.delta
        return -delta.board.settings.score_congestion * delta.grid.steps() if delta.grid is not None else 0.0
