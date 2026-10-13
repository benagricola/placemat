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
from .ratsnest import Anchor, KIND_IMPEDANCE, count_crossings, crossing_price, mst_change, nm_segment, prices_of
from .values import Box


@dataclass(frozen=True)
class Change:
    terms: dict
    total: float
    walled_change: int
    walled: int


class Delta:
    """Exact twin for one lifted rest-board snapshot.

    Discard on any fixed geometry, pending-set or frame change. Search must
    rebuild after adoption. Even a moving-owner commit/lift can rebase a cell's
    arrangement and reference, so every occupancy mutation ends this lifetime.
    """
    def __init__(self, board, occ, item, links, pushes=(), lanes=None, *, plan):
        self.board, self.occ, self.item, self.plan = board, occ, item, plan
        self._metadata = board.settings, occ.settings, occ.geometry, occ.rules, occ.quiet_nets
        self._revision = occ.__dict__.get('_score_revision', 0)
        self._pending, self._frame = frozenset(occ.pending), occ.board_box
        self._congestion_frame = occ.congestion_frame()
        self.links, self.pushes, self.lanes = tuple(links), tuple(pushes), lanes
        self.has_push = bool(self.pushes) or any(i.pushes for i in board._placements()) or bool(board._annotations)
        self.own = frozenset(fp.ref for fp in members_of(item))
        if not self.own <= occ.pending:
            raise ValueError('Delta requires the moving item to be lifted')
        self.rn = occ.ratsnest()
        self.before_edges, self.quiet, self.kinds, self.partners = score._signal_edges(board, occ)
        self.rest = {net: list(anchors) for net, anchors in self.rn._anchors.items()}
        self.old = {net: [] for net in self.rest}
        for edge in self.before_edges:
            self.old[edge.net].append(edge)
        cfg = board.settings
        self.cross_prices = tuple(p * cfg.score_crossing for p in prices_of(cfg)[:4]) + (cfg.score_pair_crossing,)
        self.base_link = score._links_mm(board, occ, plan, self.links)
        self.base_push = score._pushes(board, occ, plan)
        self.base_lane = board._declared_lanes_blocked(occ, plan)
        self.others_box = score._placed_content(occ, plan)
        self.base_area = score._frame_area(board, occ, plan)
        if board.settings.score_congestion_step and self._congestion_frame is None:
            raise ValueError("Delta requires a fixed search frame for congestion")
        self.grid = occ.congestion() if board.settings.score_congestion_step else None
        self._native = {}
        self._native_shapes = {}
        self._escape_snapshot = None
        # Judge escapes with the native classification twin (rest board and candidates alike) instead of the Python
        # oracle; set before the first candidate.
        self.escape_native = False

    @property
    def _escape_delta(self):
        # Prepared native composition has its own exact rest-board snapshot.
        # Build the independent Python oracle only when a caller needs it,
        # after proving this is still the original lifted occupancy.
        self._check_snapshot()
        if self._escape_snapshot is None:
            from .escapes import EscapeDelta
            self._escape_snapshot = EscapeDelta(self.occ, self.own, native=self.escape_native)
        return self._escape_snapshot

    @property
    def _escape_base(self):
        return self._escape_delta.counts

    def _escape_change(self, view, geometries, copper, *, native=None):
        """Signed escape terms and the signed change of unpriced validity from the lifted snapshot."""
        native = self.escape_native if native is None else native
        difference, _ = self._escape_delta.difference(view, geometries, copper, native=native)
        cfg = self.board.settings
        terms = {kind: getattr(cfg, 'score_' + kind) * difference[kind]
                 for kind in ('escape_crossed', 'escape_closed', 'escape_via')}
        return terms, difference['escape_walled']

    def _crossing_change(self, changed):
        old_nm = self.__dict__.get('_old_nm')
        if old_nm is None:          # the lifted board's airwires on whole nanometres, made once per snapshot
            old_nm = self._old_nm = {net: [nm_segment(e) for e in edges] for net, edges in self.old.items()}
        changed_nm = {net: tuple([nm_segment(e) for e in edges] for edges in lists) for net, lists in changed.items()}
        result = 0.0
        nets = sorted(changed)
        for index, net in enumerate(nets):
            _, added, dropped = changed_nm[net]
            for other in sorted(self.old.keys() - changed.keys()):
                price = crossing_price(self.kinds, self.partners, self.cross_prices, net, other)
                if price:
                    result += price * (count_crossings(added, old_nm[other]) - count_crossings(dropped, old_nm[other]))
            for other in nets[index + 1:]:
                price = crossing_price(self.kinds, self.partners, self.cross_prices, net, other)
                if price:
                    new, a, d = changed_nm[other]
                    before = old_nm.get(net, [])
                    # Signed bilinear expansion counts simultaneous changes once.
                    result += price * (count_crossings(added, new) - count_crossings(dropped, new)
                                       + count_crossings(before, a) - count_crossings(before, d))
        return result

    def _view(self, placement):
        """A candidate geometry view, without a commit or shared-cache mutation."""
        view = copy.copy(self.occ)
        geometries, copper = self.occ.placed_geometries(self.item, placement)
        view.items = dict(self.occ.items, **geometries)
        owners = self.occ._geometry(self.item).owners
        view.pending = self.occ.pending - owners
        view.copper = [shape for shape in self.occ.copper if shape.owner not in owners] + copper
        from .board_geometry import CellGeom
        if isinstance(self.item, CellGeom):
            arranged = self.occ._arranged(self.item, placement)
            rules, fills = self.occ._placed_cell_areas(arranged, placement, self.occ._geometry(arranged))
            view._cell_rule_areas = {**self.occ._cell_rule_areas, self.item.name: rules}
            view._cell_fill_areas = {**self.occ._cell_fill_areas, self.item.name: fills}
            view.fill_areas = {**self.occ.fill_areas, self.item.name: [
                (area.source, area.polygon, area.layers) for area in fills]}
        view._pristine = {ref: geom for ref, geom in self.occ._pristine.items() if ref not in owners}
        view._pad_location_cache = {}
        view._cells = {}
        view._native_obstacle_cache = {}
        for key in ('_placed_groups', '_placed_groups_owners', '_escapes', '_ratsnest', '_rn_anchors',
                    '_congestion', '_congestion_pads'):
            view.__dict__.pop(key, None)
        return view, geometries, copper

    def _candidate_ratsnest(self, added, changed):
        """Reuse the proved sparse trees rather than rebuilding every MST.

        A fresh Python-only index keeps candidate judgement independent of the
        lifted board's mirror and caches. Anchor order matches occupancy's
        ref/pad sort, including raw nearest-target tie semantics.
        """
        from .ratsnest import Ratsnest, _cells, _ends, _nm
        rn = Ratsnest(self.rn.kinds, partners=self.rn.partners, prices=self.rn.prices)
        for net in self.rest.keys() | added.keys():
            rn._anchors[net] = sorted(self.rest.get(net, []) + added.get(net, []),
                                       key=lambda a: (a.ref, a.number))
            rn._edges[net] = changed[net][0] if net in changed else self.old.get(net, [])
            if not rn._kept(net):
                rn._edges[net] = []
            for edge in rn._edges[net]:
                rn._nmends[id(edge)] = (_nm(edge.a.x), _nm(edge.a.y), _nm(edge.b.x), _nm(edge.b.y))
                for cell in _cells(*_ends(edge)):
                    rn._grid.setdefault(cell, []).append(edge)
        return rn

    def _check_snapshot(self):
        current = self.board.settings, self.occ.settings, self.occ.geometry, self.occ.rules, self.occ.quiet_nets
        if any(now is not old for now, old in zip(current, self._metadata)):
            raise ValueError('Delta settings, geometry or rules changed; rebuild the lifted snapshot')
        if not self.own <= self.occ.pending:
            raise ValueError('Delta snapshot requires the moving item to remain lifted')
        if self.occ.__dict__.get('_score_revision', 0) != self._revision:
            raise ValueError('Delta occupancy changed; rebuild the lifted snapshot')
        if frozenset(self.occ.pending) != self._pending:
            raise ValueError('Delta pending geometry changed; rebuild the lifted snapshot')
        if self.occ.board_box != self._frame or self.occ.congestion_frame() != self._congestion_frame:
            raise ValueError('Delta frame changed; rebuild the lifted snapshot')

    def __call__(self, placement, prune_above=math.inf):
        terms, walled_change = self.relative(placement)
        # Pruning is intentionally absent until every remaining signed term
        # has a proved lower bound. Walled evidence never enters the scalar.
        return Change(terms, sum(terms.values()), walled_change,
                      self._escape_base.get('escape_walled', 0) + walled_change)

    def relative(self, placement, *, escapes=True):
        """(the signed terms, the signed change of walled pads) of a candidate: `__call__`'s, without the rest board's
        absolute walled count, which only judging every rest pad gives. Two candidates compare on these alone.
        `escapes` off leaves out the escape grades (`escape_closed`, `escape_via`) and the walled check: the terms
        stop at `escape_crossed`, a crossing count, and the walled change is 0 (not asked)."""
        self._check_snapshot()
        cfg = self.board.settings
        if self.grid is not None and self.grid.board != (self.occ.congestion_frame() or Box(0, 0, 0, 0)):
            raise ValueError("Delta frame changed; rebuild the lifted snapshot")
        view, geometries, copper = self._view(placement)
        named = self.occ.candidate_named_anchors(self.item, placement, geometries=geometries)
        added = {}
        for net, ref, pad, x, y in named:
            added.setdefault(net, []).append(Anchor(ref, pad, x, y))
        changed = {}
        wire = 0.0
        for net, nodes in added.items():
            old = self.old.get(net, [])
            new, dropped, difference = mst_change(self.rest.get(net, []), old, nodes, net=net)
            identities = {frozenset((e.a, e.b)) for e in dropped}
            changed[net] = ([e for e in old if frozenset((e.a, e.b)) not in identities] + new, new, dropped)
            if net not in self.quiet:
                wire += difference * (cfg.score_impedance if self.kinds.get(net) == KIND_IMPEDANCE else 1.0)
        view._ratsnest = self._candidate_ratsnest(added, changed)
        view._rn_anchors = {net: {(a.ref, a.number): a for a in nodes}
                            for net, nodes in view._ratsnest._anchors.items()}
        link, excess = score._links_mm(self.board, view, self.plan, self.links)
        terms = {'airwire': wire, 'crossings': self._crossing_change(changed),
                 'link': cfg.score_link * (link - self.base_link[0]),
                 'link_over': cfg.score_link_over * (excess - self.base_link[1]),
                 'push': cfg.score_push * (score._pushes(self.board, view, self.plan) - self.base_push),
                 'escape_lane': cfg.score_escape_lane * (self.board._declared_lanes_blocked(view, self.plan)
                                                        - self.base_lane),
                 'area': 0.0, 'congestion': 0.0}
        if self.board._fit:
            boxes = ([self.others_box] if self.others_box is not None else [])
            boxes.extend(shape.box for geom in geometries.values() for shape in geom.shapes)
            boxes.extend(shape.box for shape in copper)
            content = Box.union(boxes) if boxes else Box(0.0, 0.0, 0.0, 0.0)
            frame = self.board._fit_bound(content.inflate(self.board._fit_margin))
            terms['area'] = cfg.score_area * (frame.width * frame.height - self.base_area)
        if self.grid is not None:
            new = self._congestion_points(geometries)
            if not self._in_grid(new):
                raise ValueError("Delta candidate pads exceed the fixed search frame")
            pads = self.occ.__dict__['_congestion_pads']
            replacements = {net: list(pads.get(net, {}).values()) + points for net, points in new.items()}
            terms['congestion'] = cfg.score_congestion * self.grid.change(replacements)
        if not escapes:
            depth = self._escape_delta.base.depth
            terms['escape_crossed'] = cfg.score_escape_crossed * (
                view.ratsnest().crossed_pairs(depth) - self._escape_delta._base_crossed())
            return terms, 0
        escaped, walled_change = self._escape_change(view, geometries, copper)
        terms.update(escaped)
        return terms, walled_change

    def _congestion_points(self, geometries):
        new = {}
        for ref, geom in geometries.items():
            for shape in geom.shapes:
                if shape.kind in ('pad', 'through') and shape.owner == ref and shape.net and shape.net not in self.quiet:
                    new.setdefault(shape.net, []).append(shape.box.center)
        return new

    def _in_grid(self, pads):
        frame = self.grid.board
        return not any(p.x < frame.left - 1e-9 or p.x > frame.right + 1e-9
                       or p.y < frame.top - 1e-9 or p.y > frame.bottom + 1e-9
                       for points in pads.values() for p in points)

    def scorable(self, placement):
        """Whether this candidate lies in the fixed congestion domain.

        An invalid kept-going placement can still be diagnosed independently,
        but a turn comparison must not clip its pads to invent a lower cost.
        Other snapshot/geometry errors propagate rather than becoming a skip.
        """
        self._check_snapshot()
        if self.grid is None:
            return True
        _, geometries, _ = self._view(placement)
        return self._in_grid(self._congestion_points(geometries))

    def native_shapes(self, rots, face):
        """Exact prepared candidate polygons, explicitly for parity until integrated."""
        self._check_snapshot()
        from .geometry import _native
        from .escapes import _layer_bits
        from .placement import Placement
        from .values import Location
        if _native is None or not hasattr(_native, 'PreparedCandidate'):
            return None
        key = tuple(rots), face
        if key not in self._native_shapes:
            geom = self.occ._geometry(self.item)
            records = []
            for rotation in rots:
                transform = self.occ._transform(geom, Placement(Location(0, 0), rotation, face))
                flip = face != geom.reference.face
                shapes = []
                for shape in geom.shapes:
                    layers = self.occ._flipped_layers(shape) if flip else shape.layers
                    # _moved preserves ends only for ordinary shapes. Carried
                    # via/track anchors use their separate `points` instead.
                    ends = () if shape.carried or shape.given else shape.ends
                    shapes.append((shape.owner, shape.kind, shape.net, shape.label, _layer_bits(layers),
                                   list(shape.poly), list(ends), False, shape.wire))
                records.append(((transform.a, transform.b, transform.c, transform.d, transform.tx, transform.ty), shapes))
            self._native_shapes[key] = _native.PreparedCandidate(records)
        return self._native_shapes[key]

    def native(self, rots, face):
        """Six non-escape terms for prepared turns; no sweep adoption yet."""
        self._check_snapshot()
        if self.grid is not None and self.grid.board != (self.occ.congestion_frame() or Box(0, 0, 0, 0)):
            raise ValueError("Delta frame changed; rebuild the lifted snapshot")
        if self.has_push or self.lanes is not None or self.rn.mirror is None:
            return None
        if self.grid is not None:
            frame = self.grid.board
            if any(not frame.contains_point(point) for pads in self.occ.__dict__['_congestion_pads'].values()
                   for point in pads.values()):
                return None  # invalid fixed geometry is reportable by the Python oracle, never clipped natively
        from .geometry import _native
        if _native is None or not hasattr(_native, 'NativeDelta'):
            return None
        from .occupancy import Placement
        from .values import Location
        key = tuple(rots), face
        if key not in self._native:
            cfg = self.board.settings
            anchors = [self.occ.candidate_named_anchors(self.item, Placement(Location(0, 0), r, face)) for r in rots]
            kernel = _native.NativeDelta(self.rn.mirror, sorted(self.own), anchors,
                sorted(net for net in self.rest.keys() | {a[0] for turn in anchors for a in turn} if net not in self.quiet),
                (cfg.score_crossing, cfg.score_impedance, cfg.score_crossing_pair_net,
                 cfg.score_crossing_plane, cfg.score_pair_crossing))
            origins = [Placement(Location(0, 0), r, face) for r in rots]
            if not hasattr(kernel, 'configure_affines'):
                return None  # old native origin+translation cannot preserve categorical ties
            kernel.configure_affines([self.occ.candidate_anchor_affines(self.item, p) for p in origins])
            boxes, links, pad_boxes = [], [], []
            def bounds(box):
                return box.left, box.top, box.right, box.bottom
            for origin in origins:
                geometries, copper = self.occ.placed_geometries(self.item, origin)
                shapes = [shape for geom in geometries.values() for shape in geom.shapes] + copper
                boxes.append(bounds(Box.union(shape.box for shape in shapes) or Box(0, 0, 0, 0)))
                pad_boxes.append([(shape.net, bounds(shape.box)) for ref, geom in geometries.items()
                                  for shape in geom.shapes if shape.kind in ('pad', 'through')
                                  and shape.owner == ref and shape.net and shape.net not in self.quiet])
                pads = self.occ.candidate_pad_locations(self.item, origin)
                prepared = []
                for link in self.links:
                    def endpoint(endpoint):
                        if endpoint[0] in self.own:
                            point = pads.get(endpoint)
                            return (point.x, point.y, True) if point is not None else None
                        if endpoint[0] in self.occ.items and endpoint[0] not in self.occ.pending:
                            point = self.occ.pad_location(*endpoint)
                            return point.x, point.y, False
                        return None
                    a, b = endpoint(link.a), endpoint(link.b)
                    if a is not None and b is not None and (a[2] or b[2]):
                        prepared.append((*a, *b, float(link.weight), link.limit_mm))
                links.append(prepared)
            fit = None
            if self.board._fit:
                from .values import Axis
                fit = (bounds(self.others_box) if self.others_box is not None else None, self.board._fit_margin,
                       self.board._frame_width if self.board._fit_axis is Axis.Y else None,
                       self.board._frame_height if self.board._fit_axis is Axis.X else None, self.base_area)
            grid = None
            if self.grid is not None:
                classes = self.board.geometry.netclasses.values()
                pitch = min((c.track_width for c in classes), default=0.2) + (self.board.geometry.default_clearance or 0.2)
                rest = [(net, point.x, point.y) for net, points in self.occ.__dict__['_congestion_pads'].items()
                        for point in points.values()]
                grid = (bounds(self.grid.board), max(1, len(self.board.geometry.layers)), pitch,
                        self.grid.step, self.grid.cell, self.grid.box, rest, pad_boxes)
            kernel.configure_layout(links, boxes, fit, grid,
                (cfg.score_link, cfg.score_link_over, cfg.score_area, cfg.score_congestion))
            self._native[key] = kernel
        return self._native[key]
