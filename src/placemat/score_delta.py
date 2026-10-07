"""Signed changes of the run objective for a lifted placement candidate.

The explicit plan supplies declared obligations and planned copper. Geometry
comes from occupancy, including temporary candidates before step facts exist.
No partial term sum is a lower bound: later terms may reduce the objective.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from . import score
from .board_geometry import members_of
from .ratsnest import Anchor, KIND_IMPEDANCE, crossings, mst, mst_change
from .values import Box


@dataclass(frozen=True)
class Change:
    terms: dict
    total: float


class Delta:
    """Exact Python twin; native support is assembled per turn by `native`."""
    def __init__(self, board, occ, item, links, pushes=(), lanes=None, *, plan):
        self.board, self.occ, self.item, self.plan = board, occ, item, plan
        self.links, self.pushes, self.lanes = tuple(links), tuple(pushes), lanes
        self.has_push = bool(self.pushes) or any(i.pushes for i in board._placements()) or bool(board._annotations)
        self.own = frozenset(fp.ref for fp in members_of(item))
        if not self.own <= occ.pending:
            raise ValueError('Delta requires the moving item to be lifted')
        self.rn = occ.ratsnest()
        self.before_edges, self.quiet, self.kinds, self.partners = score._signal_edges(board, occ)
        self.rest = {net: list(anchors) for net, anchors in self.rn._anchors.items()}
        self.old = {net: mst(net, anchors) for net, anchors in self.rest.items()}
        self.base_cross = self._crossing(self.before_edges)
        self.base_link = score._links_mm(board, occ, plan, self.links)
        self.base_push = score._pushes(board, occ, plan)
        self.others_box = score._placed_content(occ, plan)
        self.base_area = score._frame_area(board, occ, plan)
        if board.settings.score_congestion_step and occ.board_box is None:
            raise ValueError("Delta requires a fixed search frame for congestion")
        self.grid = occ.congestion() if board.settings.score_congestion_step else None
        self._native = {}

    def _crossing(self, edges):
        _, _, classes = crossings(edges, self.kinds, self.partners)
        return score.terms({'crossings': classes}, self.board.settings)['crossings']

    def _view(self, placement):
        """A candidate geometry view, without a commit or shared-cache mutation."""
        view = copy.copy(self.occ)
        geometries, copper = self.occ.placed_geometries(self.item, placement)
        view.items = dict(self.occ.items, **geometries)
        owners = self.occ._geometry(self.item).owners
        view.pending = self.occ.pending - owners
        view.copper = [shape for shape in self.occ.copper if shape.owner not in owners] + copper
        view._pristine = {ref: geom for ref, geom in self.occ._pristine.items() if ref not in owners}
        view._pad_location_cache = {}
        view._cells = {}
        view._native_obstacle_cache = {}
        for key in ('_placed_groups', '_placed_groups_owners', '_escapes', '_ratsnest', '_rn_anchors',
                    '_congestion', '_congestion_pads'):
            view.__dict__.pop(key, None)
        return view, geometries, copper

    def __call__(self, placement, prune_above=math.inf):
        cfg = self.board.settings
        if self.grid is not None and self.grid.board != (self.occ.board_box or Box(0, 0, 0, 0)):
            raise ValueError("Delta frame changed; rebuild the lifted snapshot")
        named = self.occ.candidate_named_anchors(self.item, placement)
        added = {}
        for net, ref, pad, x, y in named:
            added.setdefault(net, []).append(Anchor(ref, pad, x, y))
        after_edges = [e for e in self.before_edges if e.net not in added]
        wire = 0.0
        for net, nodes in added.items():
            old = self.old.get(net, [])
            new, dropped, difference = mst_change(self.rest.get(net, []), old, nodes, net=net)
            identities = {frozenset((e.a, e.b)) for e in dropped}
            after_edges.extend(e for e in old if frozenset((e.a, e.b)) not in identities)
            after_edges.extend(new)
            if net not in self.quiet:
                wire += difference * (cfg.score_impedance if self.kinds.get(net) == KIND_IMPEDANCE else 1.0)
        view, geometries, copper = self._view(placement)
        link, excess = score._links_mm(self.board, view, self.plan, self.links)
        terms = {'airwire': wire, 'crossings': self._crossing(after_edges) - self.base_cross,
                 'link': cfg.score_link * (link - self.base_link[0]),
                 'link_over': cfg.score_link_over * (excess - self.base_link[1]),
                 'push': cfg.score_push * (score._pushes(self.board, view, self.plan) - self.base_push),
                 'area': 0.0, 'congestion': 0.0}
        if self.board._fit:
            boxes = ([self.others_box] if self.others_box is not None else [])
            boxes.extend(shape.box for geom in geometries.values() for shape in geom.shapes)
            boxes.extend(shape.box for shape in copper)
            content = Box.union(boxes) if boxes else Box(0.0, 0.0, 0.0, 0.0)
            frame = self.board._fit_bound(content.inflate(self.board._fit_margin))
            terms['area'] = cfg.score_area * (frame.width * frame.height - self.base_area)
        if self.grid is not None:
            new = {}
            for ref, geom in geometries.items():
                for shape in geom.shapes:
                    if shape.kind in ('pad', 'through') and shape.owner == ref and shape.net \
                            and shape.net not in self.quiet:
                        new.setdefault(shape.net, []).append(shape.box.center)
            frame = self.grid.board
            if any(p.x < frame.left - 1e-9 or p.x > frame.right + 1e-9
                   or p.y < frame.top - 1e-9 or p.y > frame.bottom + 1e-9
                   for points in new.values() for p in points):
                raise ValueError("Delta candidate pads exceed the fixed search frame")
            pads = self.occ.__dict__['_congestion_pads']
            replacements = {net: list(pads.get(net, {}).values()) + points for net, points in new.items()}
            terms['congestion'] = cfg.score_congestion * self.grid.change(replacements)
        # Escapes are added in Task 9. Pruning is intentionally absent until
        # every remaining signed term has a proved lower bound.
        return Change(terms, sum(terms.values()))

    def native(self, rots, face):
        """Wire/crossing kernel for prepared turns; no sweep adoption yet."""
        if self.has_push or self.lanes is not None or self.rn.mirror is None:
            return None
        from .geometry import _native
        if _native is None or not hasattr(_native, 'NativeDelta'):
            return None
        from .occupancy import Placement
        from .values import Location
        key = tuple(rots), face
        if key not in self._native:
            cfg = self.board.settings
            anchors = [self.occ.candidate_named_anchors(self.item, Placement(Location(0, 0), r, face)) for r in rots]
            self._native[key] = _native.NativeDelta(self.rn.mirror, sorted(self.own), anchors,
                sorted(net for net in self.rest.keys() | {a[0] for turn in anchors for a in turn} if net not in self.quiet),
                (cfg.score_crossing, cfg.score_impedance, cfg.score_crossing_pair_net,
                 cfg.score_crossing_plane, cfg.score_pair_crossing))
        return self._native[key]
