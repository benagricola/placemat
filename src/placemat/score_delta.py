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
from .ratsnest import Anchor, KIND_IMPEDANCE, count_crossings, count_pair_crossings, crossing_price, mst_change, nm_segment, prices_of
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
        self.push_judged = self.has_push and self._push_judged()
        self.rn = occ.ratsnest()
        occ.pair_sides()                    # read on the lifted board, so each candidate's view copies them
        self.before_edges, self.quiet, self.kinds, self.partners = score._signal_edges(board, occ)
        self.rest = {net: list(anchors) for net, anchors in self.rn._anchors.items()}
        self.old = {net: [] for net in self.rest}
        for edge in self.before_edges:
            self.old[edge.net].append(edge)
        cfg = board.settings
        self.cross_prices = tuple(p * cfg.score_crossing for p in prices_of(cfg)[:4]) + (cfg.score_pair_crossing,)
        self.base_link = score._links_mm(board, occ, plan, self.links)
        self.base_push = score._pushes(board, occ, plan)
        self.lanes_each = board._lanes_blocked_each(occ, plan) if board._escapes else {}
        self.base_lane = sum(n for n, _ in self.lanes_each.values())
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

    def _crossing_change(self, changed, polarity=None):
        """The signed change of the crossings term from the lifted board's airwires (`self.old`) to `changed` ({net:
        (its airwires now, those added, those dropped)}); a pair's two halves cross where `polarity` (the candidate
        view's Occupancy.pair_polarity) says so, as `ratsnest.crossings` counts them."""
        old_nm = self.__dict__.get('_old_nm')
        if old_nm is None:          # the lifted board's airwires on whole nanometres, made once per snapshot
            old_nm = self._old_nm = {net: [nm_segment(e) for e in edges] for net, edges in self.old.items()}
        changed_nm = {net: tuple([nm_segment(e) for e in edges] for edges in lists) for net, lists in changed.items()}

        def count(net, a, a_nm, other, b, b_nm):
            if polarity is None or self.partners.get(net) != other:
                return count_crossings(a_nm, b_nm)
            return count_pair_crossings(a, a_nm, b, b_nm, polarity)
        result = 0.0
        nets = sorted(changed)
        for index, net in enumerate(nets):
            _, added, dropped = changed[net]
            _, added_nm, dropped_nm = changed_nm[net]
            for other in sorted(self.old.keys() - changed.keys()):
                price = crossing_price(self.kinds, self.partners, self.cross_prices, net, other)
                if price:
                    old, nm = self.old[other], old_nm[other]
                    result += price * (count(net, added, added_nm, other, old, nm)
                                       - count(net, dropped, dropped_nm, other, old, nm))
            for other in nets[index + 1:]:
                price = crossing_price(self.kinds, self.partners, self.cross_prices, net, other)
                if price:
                    new, a, d = changed[other]
                    new_nm, a_nm, d_nm = changed_nm[other]
                    before, before_nm = self.old.get(net, []), old_nm.get(net, [])
                    # Signed bilinear expansion counts simultaneous changes once.
                    result += price * (count(net, added, added_nm, other, new, new_nm)
                                       - count(net, dropped, dropped_nm, other, new, new_nm)
                                       + count(net, before, before_nm, other, a, a_nm)
                                       - count(net, before, before_nm, other, d, d_nm))
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
        view._lane_over = (self.occ, geometries, copper, owners)       # what an escape's layout reads of its pool
        view._pad_location_cache = {}
        view._cells = {}
        view._native_obstacle_cache = {}
        for key in ('_placed_groups', '_placed_groups_owners', '_escapes', '_ratsnest', '_rn_anchors',
                    '_congestion', '_congestion_pads'):
            view.__dict__.pop(key, None)
        return view, geometries, copper

    def _lanes_blocked(self, view, geometries, copper) -> int:
        """The declared escapes' blocked lanes on a candidate's view: an escape the candidate comes nowhere near keeps
        its count on the lifted board."""
        if not self.board._escapes:
            return 0
        changed = self._lanes_moved(view, geometries, copper) + self._lanes_left()
        return self.board._declared_lanes_blocked(view, self.plan, base=self.lanes_each, changed=changed)

    def _lanes_moved(self, view, geometries, copper) -> list:
        """The boxes of what a candidate adds to the board, which move with it: its shapes, copper and cell rule areas."""
        moved = [sh.box for g in geometries.values() for sh in g.shapes] + [sh.box for sh in copper]
        name = getattr(self.item, "name", None)
        return moved + [Box.of_points(area.polygon) for area in view._cell_rule_areas.get(name, ())]

    def _lanes_left(self) -> list:
        """The boxes of what every candidate takes off the board: the item's copper and cell rule areas as it stood."""
        owners = self.occ._geometry(self.item).owners
        left = [sh.box for sh in self.occ.copper if sh.owner in owners]
        name = getattr(self.item, "name", None)
        return left + [Box.of_points(area.polygon) for area in self.occ._cell_rule_areas.get(name, ())]

    def _push_judged(self) -> bool:
        """Whether a push or an annotation judges where the item stands: it is a push's target, what a push's source
        needs placed, or an annotated part. Where none does, every candidate's push term is the lifted board's."""
        board = self.board
        if self.pushes:
            return True
        refs = set(self.own) | set(self.occ._geometry(self.item).owners)
        name = getattr(self.item, "name", None)
        if name:
            refs.add(name)
        pushes = [p for intent in board._placements() for p in intent.pushes] + list(getattr(self.plan, "pushes", ()))
        if any(p.target_member_ref in refs or board._push_needs(p.source) & refs for p in pushes):
            return True
        ann = board._annotations
        return bool(ann) and bool(refs & (ann.sensitives.keys() | ann.sources.keys()))

    def python_terms(self, placement, lanes: bool = True) -> tuple:
        """A candidate's (push term, escape-lane term), as `relative` prices them: the push term 0 where no push or
        annotation judges the item (`push_judged`), the escape-lane term 0 unless `lanes`."""
        view, geometries, copper = self._view(placement)
        cfg = self.board.settings
        push = cfg.score_push * (score._pushes(self.board, view, self.plan) - self.base_push) if self.push_judged else 0.0
        lane = 0.0
        if lanes and self.board._escapes:
            lane = cfg.score_escape_lane * (self._lanes_blocked(view, geometries, copper) - self.base_lane)
        return push, lane

    def lanes_near(self, rotations, face):
        """What says a candidate at one of `rotations` on `face` changes no declared escape's count, as
        `NativeDeltaScoring.configure_lanes` takes it: (per turn the box at the origin holding the boxes of what the
        candidate adds, the box of each escape's asked places, the reach). None where every candidate must be laid out:
        the item carries an escape's part, what it takes off the board comes near an escape, or what it adds does not
        move with it."""
        from .layout import _asked_near
        from .placement import Placement
        from .values import Location
        board, occ = self.board, self.occ
        owners = occ._geometry(self.item).owners
        if any(decl.ref in owners for decl in board._escapes):
            return None
        reach = occ._copper_reach + board.geometry.hole_to_hole + board.geometry.hole_clearance
        left = self._lanes_left()
        if any(_asked_near(asked, left, Box.union(left), reach) for _, asked in self.lanes_each.values()):
            return None
        hulls = []
        for _, asked in self.lanes_each.values():
            boxes = [a for a in asked if isinstance(a, Box)]
            boxes += [Box(*bounds) for a in asked if not isinstance(a, Box) for bounds in a.boxes()]
            if boxes:
                hull = Box.union(boxes)
                hulls.append((hull.left, hull.top, hull.right, hull.bottom))
        turns = []
        for rotation in rotations:
            at = []
            for x, y in ((0.0, 0.0), (self._frame.left, self._frame.top) if self._frame is not None else (1.0, 1.0)):
                view, geometries, copper = self._view(Placement(Location(x, y), rotation, face))
                moved = self._lanes_moved(view, geometries, copper)
                if not moved:
                    at.append(None)
                    continue
                hull = Box.union(moved)
                at.append((hull.left - x, hull.top - y, hull.right - x, hull.bottom - y))
            if None in at or any(abs(a - b) > 1e-6 for a, b in zip(*at)):
                return None             # what the candidate adds is not the same wherever it stands
            turns.append(at[0])
        return turns, hulls, reach

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
        terms = {'airwire': wire, 'crossings': self._crossing_change(changed, view.pair_polarity()),
                 'link': cfg.score_link * (link - self.base_link[0]),
                 'link_over': cfg.score_link_over * (excess - self.base_link[1]),
                 'push': cfg.score_push * (score._pushes(self.board, view, self.plan) - self.base_push),
                 'escape_lane': cfg.score_escape_lane * (self._lanes_blocked(view, geometries, copper)
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
        if self.lanes is not None or self.rn.mirror is None:
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
            sides = self.occ.pair_sides()
            if sides:
                if not hasattr(kernel, 'configure_pairs'):
                    return None  # an older native counts a pair's halves as chords
                geometries, _ = self.occ.placed_geometries(self.item, origins[0])
                faces = {ref: g.reference.face for ref, g in geometries.items()}
                mirrored = sorted(ref for ref in self.occ.items if ref not in self.occ.pending
                                  and self.occ.mirrored(ref)) + sorted(
                    ref for ref, face in faces.items() if self.occ.geometry.has_footprint(ref)
                    and face != self.occ.geometry.footprint(ref).face)
                kernel.configure_pairs([(*key, side) for key, side in sorted(sides.items())], mirrored)
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
