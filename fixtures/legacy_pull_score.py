"""Historical pull-estimate comparator for score_speed; not a production search adapter."""
import math
from placemat.layout import _push_at, _push_value, PRUNED
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.placer import UNWEIGHED
from placemat.board_geometry import members_of

class Scorer:
    """A searched item's standing at a candidate placement, as (pads it walls off, cost), compared in that order (D13):
    a candidate that walls a pad (escapes.py, `Escapes.closed`) loses to any that walls none, then the cost decides.
    The cost is each connection's weight times its length, `score.crossing` for each ratsnest crossing its airwires
    would add, and the escape weights for each escape it would cross or close. `best[0]` is the lowest cost weighed so
    far of a candidate that walls no pad: with `prune`, a candidate whose wire alone reaches it is not weighed further
    (its crossings and escapes can only add, and walling a pad only loses) and stands at (placer.UNWEIGHED, its wire plus
    PRUNED), below every candidate weighed in full.
    Explore draws among candidates near the best and needs every one weighed.

    Called, it is a historical Python reference. `native(rots, face)` returns
    None: this retained comparator runs in Python only."""

    def __init__(self, settings, item, occ: Occupancy, targets: list, prune: bool, pushes=(), lanes=None):
        s = settings
        self.s, self.item, self.occ, self.targets, self.prune = s, item, occ, targets, prune
        self.pushes = tuple(pushes)
        self.lanes = lanes          # placement -> how many of the item's declared escape lanes it would block
        self.crossing = s.score_crossing
        self.rn = occ.ratsnest() if self.crossing > 0 else None
        self.esc = occ.escapes()        # walled pads are counted whatever the escape weights are
        self.own = frozenset(fp.ref for fp in members_of(item))
        self.depth = s.score_escape_depth
        self.best = [math.inf]
        self._native = {}

    def __call__(self, placement: Placement) -> tuple:
        occ, s = self.occ, self.s
        pads = occ.candidate_pad_locations(self.item, placement)
        cost = sum(w * pads[key].distance(target) for key, target, w in self.targets if key in pads)
        if self.pushes:
            points = {}
            for source_point, push in self.pushes:
                point = _push_at(occ, self.item, placement, push, pads, points)
                if point is None:
                    continue
                value, _ = _push_value(source_point, point, push)
                cost += s.score_push * value / push.limit
        if self.prune and cost >= self.best[0]:
            return UNWEIGHED, cost + PRUNED     # its crossings and escapes can only add: it cannot be the best
        crossed = None
        if self.rn is not None:
            added, crossed = self.rn.leaf_costs(occ.candidate_anchors(self.item, placement), self.own, self.depth)
            cost += self.crossing * added
        crossed, closed, walled = self.esc.closed(self.item, placement, crossed)
        cost += s.score_escape_crossed * crossed + s.score_escape_closed * closed
        if self.lanes is not None:
            cost += s.score_escape_lane * self.lanes(placement)
        if not walled:
            self.best[0] = min(self.best[0], cost)
        return walled, cost

    def native(self, rots, face):
        """The retired pull estimate is a Python-only historical comparator."""
        return None
