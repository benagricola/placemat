"""The one-score search's scorer: the complete common objective (`place.search_wire` "mst", the default).

It evaluates every legal candidate it is asked: signed changes do not justify
the old wire-only pruning bound; the native sweep prunes on proved bounds only.
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
    """The common objective's change for a lifted item, as a scan's scorer: (pads walled, cost). The walled count is
    the pads the candidate walls in beyond the lifted board's (never below 0).

    The escapes are graded by the lanes alone (D24): a candidate's cost needs no exact path search. Walled is validity,
    decided by the exact search on the pads the lanes leave walled suspects, and is asked only where a candidate could
    be chosen. Called, the scorer is exact: cost and walled count (a decided position, an arrangement's trial). `scan`
    is what a scan asks of each candidate: the lane-graded cost, with the walled count asked exactly only of a
    candidate that beats the best one known to wall none (`best[0]`), so that best is proved; any other stands at 0
    walled until the scan asks `walls` of it before taking it. `native(rotations, face)` is `scan` in the native
    sweep, its `exact` flag making it exact for every candidate (an explore's draw). With `prune` (a scan that reads
    only its `place.refine_spots` best candidates: no `pick`, no `accept`) the native sweep prunes on proved bounds
    (R13), past the `place.refine_spots`-th best cost of a candidate proved to wall none: a pruned candidate stands at
    (placer.UNWEIGHED, its bound), below every candidate weighed in full."""
    def __init__(self, board, occ, item, *, plan, pushes=(), lanes=None, prune=False):
        from .escapes import native_judge
        self.delta = Delta(board, occ, item, plan.links, pushes=pushes, lanes=lanes, plan=plan)
        self.delta.escape_native = native_judge()
        self.prune = prune
        self.best = [math.inf]
        self._native = {}
        self._walls = {}
        self.refusals = {}

    def __call__(self, placement):
        if not self.delta.scorable(placement):
            raise ScoreDomainError(placement)
        terms, change = self.delta.relative(placement)
        total = sum(terms.values())
        walled = max(0, change)
        self._walls[self._key(placement)] = walled
        if not walled:
            self.best[0] = min(self.best[0], total)
        return walled, total

    def scan(self, placement):
        """A scan's candidate: its lane-graded cost; the exact walled count only when it beats `best[0]`."""
        if not self.delta.scorable(placement):
            raise ScoreDomainError(placement)
        terms, _ = self.delta.relative(placement, exact=False)
        total = sum(terms.values())
        if total < self.best[0]:
            return self(placement)
        return 0, total

    def walls(self, placement) -> int:
        """The exact walled count of a candidate the scan would take: what `__call__` says of it, from the native
        sweep's prepared scorer when it has the candidate's turn and face."""
        key = self._key(placement)
        if key not in self._walls:
            native = next((scoring for (rotations, face), scoring in self._native.items()
                           if scoring is not None and face == placement.face and placement.rotation in rotations), None)
            if native is not None:
                rotations = next(r for (r, f), sc in self._native.items() if sc is native)
                _, walled = native.exact(placement.location.x, placement.location.y,
                                         rotations.index(placement.rotation))
                self._walls[key] = max(0, walled)
            else:
                self(placement)
        return self._walls[key]

    @staticmethod
    def _key(placement):
        return placement.location.x, placement.location.y, placement.rotation, placement.face

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
                    (baseline.get('escape_closed', 0), baseline.get('escape_via', 0),
                     baseline.get('escape_walled', 0)), self.best[0])
                if self.prune and PRUNE and hasattr(scoring, 'configure_prune'):
                    scoring.configure_prune(*self._bounds(rotations, face))
                self._native[key] = scoring
        return self._native[key]

    def _bounds(self, rotations, face):
        """`NativeDeltaScoring.configure_prune`'s arguments: the proved lower bounds of R13 for this lifted board.

        Congestion's change is at least minus its price times the worst cell's steps now: none can go below zero.
        Escape prices: a rest pad's way is graded again with more copper about it, which only closes ways (its lanes,
        its via spots), so its price rises (SURFACE, VIA, then AWAY or a suspect, priced alike). It can fall
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
        prices = {Way.VIA: cfg.score_escape_via, Way.AWAY: cfg.score_escape_closed, Way.WALLED: cfg.score_escape_closed}
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
            if net not in nets or net in occ.quiet_nets or prices.get(way, 0.0) <= 0.0:
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
