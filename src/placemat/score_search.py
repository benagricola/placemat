"""Temporary measurement search for the complete common placement objective.

The clique search remains the default until the measured adoption gate. This
scorer evaluates every legal candidate: signed changes do not justify the
old wire-only pruning bound.
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
    Python Delta; `native(rotations, face)` is the same in the native sweep. With `prune` (a scan that reads only its
    `place.refine_spots` best candidates: no `pick`, no `accept`) the native sweep prunes on proved bounds (R13): a
    pruned candidate stands at (placer.UNWEIGHED, its bound), below every candidate weighed in full."""
    def __init__(self, board, occ, item, *, plan, pushes=(), lanes=None, prune=False):
        from .escapes import native_judge
        self.delta = Delta(board, occ, item, plan.links, pushes=pushes, lanes=lanes, plan=plan)
        self.delta.escape_native = native_judge()
        self.prune = prune
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
                scoring = geometry._native.NativeDeltaScoring(
                    prepared.candidate, prepared.scoring, prepared.surface,
                    (cfg.score_escape_crossed, cfg.score_escape_closed, cfg.score_escape_via),
                    (baseline.get('escape_closed', 0), baseline.get('escape_via', 0)), self.best[0])
                if self.prune and PRUNE and hasattr(scoring, 'configure_prune'):
                    scoring.configure_prune(*self._bounds(rotations, face))
                self._native[key] = scoring
        return self._native[key]

    def _bounds(self, rotations, face):
        """`NativeDeltaScoring.configure_prune`'s arguments: the proved lower bounds of R13 for this lifted board.

        Congestion's change is at least minus its price times the worst cell's steps now: none can go below zero.
        Escape prices: a rest pad's way is judged again with more copper about it, which only closes ways (its lanes,
        its via spots, its path search), so its price rises (SURFACE, VIA, AWAY), or it is walled, and a walled
        candidate ranks below every one that walls none, which a finite limit has `place.refine_spots` of. It can fall
        only when its target moves (a candidate anchor of its net as near as its target now) or a candidate's
        pad or copper of its net lands on it (the candidate's box overlaps the pad), or by a via costing more than a
        closed pad. The item's own pads only add a price."""
        from .escapes import Way
        from .placement import Placement
        from .values import Box, Location
        delta, occ = self.delta, self.delta.occ
        cfg = delta.board.settings
        congestion = -cfg.score_congestion * delta.grid.steps() if delta.grid is not None else 0.0
        snapshot = delta._escape_delta
        ways = snapshot.ways
        prices = {Way.VIA: cfg.score_escape_via, Way.AWAY: cfg.score_escape_closed}
        constant = -max(0.0, cfg.score_escape_via - cfg.score_escape_closed) * sum(
            way is Way.VIA for way in ways.values())
        nets, boxes = set(), []
        for rotation in rotations:
            geometries, copper = occ.placed_geometries(delta.item, Placement(Location(0, 0), rotation, face))
            shapes = [shape for geom in geometries.values() for shape in geom.shapes] + copper
            nets.update(shape.net for shape in shapes if shape.net)
            box = Box.union(shape.box for shape in shapes) or Box(0, 0, 0, 0)
            boxes.append((box.left, box.top, box.right, box.bottom))
        anchors = occ.ratsnest()._anchors
        pads = []
        for (ref, number), way in ways.items():
            net = snapshot.nets[(ref, number)]
            if net not in nets or prices.get(way, 0.0) <= 0.0:
                continue
            box = snapshot.base._lanes_of(ref)[2][number][2]
            at = box.center
            # The squared distance `Escapes._aim` takes its target at, as it reckons it.
            d2 = min(((a.x - at.x) ** 2 + (a.y - at.y) ** 2 for a in anchors.get(net, ())
                      if (a.ref, a.number) != (ref, number)), default=math.inf)
            if d2 == math.inf:
                continue                    # no target: not judged, no price
            pads.append((net, (at.x, at.y), d2, prices[way], (box.left, box.top, box.right, box.bottom)))
        return cfg.place_refine_spots, congestion, constant, pads, boxes
