"""Tracks what occupies each face of the board and decides whether a
candidate placement is legal, without pcbnew.

Built from the geometry read off the generated .kicad_pcb and updated as
placements are committed. Checks: body box inside the edge margin;
reservations block parts unless they carry an allowed net; what each part
claims keeps clear of what the others claim on the faces they share -
courtyards in the courtyard envelope, pads, mask openings, silk and bodies
at the board's own gaps in the physical one, both in union; through features
block both faces; pads keep net-class clearance from foreign copper."""
from __future__ import annotations

import functools
import math
from dataclasses import dataclass

from . import geometry as _geometry_module
from .geometry import (_clean, PolyRaster, Polygon, Transform, box_polygon, circle_polygon, poly_distance,
                       polys_overlap, transform_box, transform_polygon)
from .placement import Placement
from .settings import Settings
from .board_geometry import CellGeom, Footprint, BoardGeometry
from .values import Box, CopperLayer, Face, Location


@dataclass(frozen=True)
class Shape:
    """One obstacle: a polygon on a set of copper layers (or both faces for a
    courtyard/through feature), tagged with who owns it and what net it is."""
    owner: str                      # refdes (or cell name for cell copper)
    kind: str                       # courtyard | pad | through | copper | npth
    faces: frozenset[Face]          # which faces this shape occupies (courtyard sense)
    layers: frozenset[CopperLayer]  # copper layers (clearance sense); empty for courtyards
    net: str
    poly: Polygon
    box: Box
    label: str = ""                 # pad number for a pad shape


# A Shape as a plain tuple, for the optional native accelerator (kind,
# faces as a bitmask, layers as a bitmask, net, poly, owner, whether the
# owner is a footprint this Occupancy knows, whether (owner, label) is one
# of its leads, the owner's courtyard margin) - see _to_native_shape and
# docs/superpowers/specs/2026-09-24-native-core-design.md ("Phase 2"). The
# bit assignments only need to be consistent within one call; they carry no
# meaning outside this module.
_NATIVE_LAYER_ORDER = list(CopperLayer)


def _native_faces(faces: frozenset) -> int:
    return (1 if Face.FRONT in faces else 0) | (2 if Face.BACK in faces else 0)


def _native_layers(layers: frozenset) -> int:
    bits = 0
    for l in layers:
        bits |= 1 << _NATIVE_LAYER_ORDER.index(l)
    return bits


def _to_native_shape(s: Shape, footprint_refs: frozenset, leads: frozenset, margins: dict) -> tuple:
    return (s.kind, _native_faces(s.faces), _native_layers(s.layers), s.net or "", tuple(s.poly), s.owner,
            s.owner in footprint_refs, (s.owner, s.label) in leads, margins.get(s.owner, 0.0))


@dataclass(frozen=True)
class Blocker:
    """Why one candidate placement was refused, in parts rather than prose:
    what kind of conflict, whose shape it was, and which faces it holds. The
    sentence `legal` returns is for a human; this is for counting."""
    kind: str                       # courtyard | pad | through | copper | npth | edge | reservation
    owner: str                      # as who() formats it: a cell member carries its cell
    faces: frozenset


@dataclass(frozen=True)
class Reservation:
    """A region nothing may sit in. `allow` are nets whose parts may, and
    `owners` are refdes that may by name - an antenna's clearance holds its
    own matching network, and naming the nets would admit every part that
    shares one."""
    poly: tuple
    why: str
    allow: frozenset[str]
    layer: CopperLayer | None       # None: both faces, any layer
    owners: frozenset[str] = frozenset()
    source: str = ""                # what put it here, so a re-commit can replace its own

    @functools.cached_property
    def box(self) -> Box:
        return Box.of_points(self.poly)

    @functools.cached_property
    def _raster(self):
        return PolyRaster(self.poly)

    def overlaps(self, body: Box) -> bool:
        """Whether the box shares interior with the region: polys_overlap's
        answer, from the raster where the cells decide it. A small region is
        cheaper to test than to raster."""
        if not self.box.overlaps(body):
            return False
        if len(self.poly) >= 24:
            hit = self._raster.classify(body)
            if hit is not None:
                return hit
        return polys_overlap(self.poly, box_polygon(body))


class ShapeIndex(list):
    """A scan's obstacles, and a uniform grid over their boxes so a candidate
    only tests the shapes in the cells it covers. `near` answers what the
    linear filter would, in the list's own order, because `legal` reports
    the first conflict it finds. Small lists are filtered directly."""
    CELL = 2.0          # mm; a pad or a passive's courtyard spans one to four cells
    LINEAR = 48         # below this many shapes the grid costs more than it saves

    def __init__(self, shapes=()):
        super().__init__(shapes)
        self._grid = None
        self._asked = 0

    def _cells(self, box: Box):
        c = self.CELL
        return (range(math.floor(box.left / c), math.floor(box.right / c) + 1),
                range(math.floor(box.top / c), math.floor(box.bottom / c) + 1))

    def near(self, box: Box, gap: float) -> list:
        self._asked += 1
        if len(self) < self.LINEAR or (self._grid is None and self._asked == 1):    # one question: no grid worth building
            return [o for o in self if o.box.overlaps(box, gap=gap)]
        if self._grid is None:
            self._grid = {}
            for k, o in enumerate(self):
                xs, ys = self._cells(o.box)
                for x in xs:
                    for y in ys:
                        self._grid.setdefault((x, y), []).append(k)
        xs, ys = self._cells(box.inflate(gap))
        hits = set()
        for x in xs:
            for y in ys:
                hits.update(self._grid.get((x, y), ()))
        return [self[k] for k in sorted(hits) if self[k].box.overlaps(box, gap=gap)]


def parts_claim(layers, flip: bool = False):
    """(whether, layer) for a region that keeps parts out, from the copper
    layers it covers: a part sits on a face, so the region claims the faces
    among its layers - both is no layer, one is that face's copper, and
    inner layers alone claim nothing, a footprint never being on them.
    `layers` None is every layer. `flip` swaps the faces, for a region that
    came with a cell placed on the other face."""
    if layers is None:
        return True, None
    faces = {l.face for l in layers if l.face is not None}
    if not faces:
        return False, None
    if len(faces) == 2:
        return True, None
    face = next(iter(faces))
    if flip:
        face = Face.BACK if face is Face.FRONT else Face.FRONT
    return True, face.copper


@dataclass
class ItemGeometry:
    """A footprint's or cell's shapes in world coordinates at its CURRENT
    placement, plus the reference placement those coordinates assume."""
    owners: frozenset[str]
    reference: Placement
    shapes: tuple[Shape, ...]
    body: Box
    nets: frozenset[str]
    reach: Box | None = None            # everything the item physically is: pads and drawn graphics (silk), not the courtyard


_BOTH = frozenset([Face.FRONT, Face.BACK])
# The defaults; a board's own come from `[place] conflict_gap` and
# `[place] courtyard_touch` and are carried on the Occupancy.
_GAP = 1.0      # how far outside a box a conflict can still reach: the largest clearance a rule asks for
TOUCH = 0.02    # two courtyards this close are touching, not overlapping: a footprint's courtyard stroke rounds by this much


def _fp_shapes(fp: Footprint, envelope: str = "courtyard") -> list[Shape]:
    """What a part claims. `courtyard`: its courtyard and its pads. `physical`:
    its pads, mask openings, silk and body - or, for a footprint that draws
    neither silk nor fab, its courtyard (which falls back to its pads).
    `union`: both."""
    shapes = []
    # The courtyard and the body stay on the part's own face: only its holes
    # reach the other (the through pads and unplated holes below).
    faces = frozenset([fp.face])
    drawn = bool(fp.silk or fp.fab)
    if envelope != "physical" or not drawn:
        ct = box_polygon(fp.courtyard_box)
        shapes.append(Shape(fp.ref, "courtyard", faces, frozenset(), "", ct, fp.courtyard_box))
    if envelope != "courtyard":
        for face, poly in fp.mask:
            shapes.append(Shape(fp.ref, "mask", frozenset([face]), frozenset(), "", poly, Box.of_points(poly)))
        for face, poly in fp.silk:
            shapes.append(Shape(fp.ref, "silk", frozenset([face]), frozenset(), "", poly, Box.of_points(poly)))
        for face, poly in fp.fab:
            shapes.append(Shape(fp.ref, "body", frozenset([face]), frozenset(), "", poly, Box.of_points(poly)))
    for p in fp.pads:
        for poly in p.outlines:
            shapes.append(Shape(fp.ref, "through" if p.through else "pad",
                                _BOTH if p.through else frozenset([fp.face]),
                                p.layers, p.net, poly, Box.of_points(poly), p.number))
    for center, drill in fp.npth:
        poly = circle_polygon(center, drill / 2.0)
        shapes.append(Shape(fp.ref, "npth", _BOTH, frozenset(CopperLayer), "", poly, Box.of_points(poly)))
    return shapes


def _is_lead(fp, pad) -> bool:
    """A plated through pad that stands proud of the far face: not a via in
    one of the part's own surface pads (an exposed pad's thermal vias are
    flat on the far face and claim only their copper there)."""
    if not pad.through:
        return False
    c = pad.box.center
    return not any(not q.through and q.box.left <= c.x <= q.box.right and q.box.top <= c.y <= q.box.bottom
                   for q in fp.pads)


class Occupancy:
    def __init__(self, geometry: BoardGeometry, edge_margin: float = 0.0, board_box: Box | None = None,
                 vias_block_courtyards: bool = False, board_shape=None, board_cutouts=None,
                 settings: Settings | None = None, component_spacing: float = 0.2):
        self.settings = settings if settings is not None else Settings()
        self._gap = self.settings.place_conflict_gap
        self._touch = self.settings.place_courtyard_touch
        self.geometry = geometry
        self.envelope = self.settings.place_envelope
        self.component_spacing = component_spacing          # body to body, body to another part's pad
        self.silk_clearance = geometry.silk_clearance       # silk to silk, silk to a mask opening
        self._footprint_refs = frozenset(fp.ref for fp in geometry.footprints)
        self._margins = {fp.ref: fp.courtyard_margin for fp in geometry.footprints if fp.courtyard_margin}
        self._leads = frozenset((fp.ref, p.number) for fp in geometry.footprints for p in fp.pads if _is_lead(fp, p))
        self._drawn_gap = max(component_spacing, self.silk_clearance)   # the furthest a silk, mask or body check reaches
        if self.envelope != "courtyard" and self._gap < max(component_spacing, self.silk_clearance):
            raise ValueError("[place] conflict_gap %.2f is less than the %.2f mm the %s envelope needs a check to reach"
                             % (self._gap, max(component_spacing, self.silk_clearance), self.envelope))
        self.edge_margin = edge_margin
        self.vias_block_courtyards = vias_block_courtyards
        # The board a script declared, when it is not a rectangle (a Disc or an Outline):
        # it answers `why_not(box, margin)` for the keep-in and owns the real area,
        # cutouts and all. A rectangle has no such object, so its cutouts come
        # separately and are asked alongside the box.
        self.board_shape = board_shape
        self.board_cutouts = board_cutouts
        self.board_box = board_box or (board_shape.box if board_shape is not None else geometry.outline_box)
        self.items: dict[str, ItemGeometry] = {}
        self.reservations: list[Reservation] = []
        self.copper: list[Shape] = []
        self._cells: dict[str, ItemGeometry] = {}        # a cell's geometry, until something moves
        self._pad_location_cache: dict[tuple[str, str], Location] = {}   # (ref, number) -> Location, until a commit
        self.pending: set[str] = set()                    # owners the script will place: not obstacles where the generator left them
        # A native obstacle index (Rust), one per distinct skip-set (an
        # item's own owners, plus self.pending, at the time it was asked
        # for): scan(), cleanup's per-key hints, and a freedom's several
        # _slide() calls all re-ask obstacles() for the SAME item between
        # commits, so this is a real cache, not a one-shot memo. Cleared
        # whenever self.items or self.copper changes (commit, add_copper,
        # a lazy _register) - see _invalidate_native(). Keyed on the skip
        # frozenset only, not on obstacles()'s `region`: the native index
        # holds every non-skipped shape on the board regardless of region
        # (its own grid narrows a query to what is spatially near without
        # needing a pre-filtered list), so the same entry serves any region
        # asked against the same skip-set. See
        # docs/superpowers/specs/2026-09-24-native-core-design.md
        # ("Phase 3: a persistent native obstacle index").
        self._native_obstacle_cache: dict[frozenset, tuple] = {}
        for fp in geometry.footprints:
            self._register(fp)
        for c in geometry.copper:
            if c.kind == "pad":
                continue          # pads travel with their footprint
            if c.kind == "zone":
                continue          # a fill pulls back round whatever is placed; it never blocks anything
            faces = frozenset(l.face for l in c.layers if l.face is not None)
            if c.kind == "via":
                faces = _BOTH
            for poly in c.outlines:
                self.copper.append(Shape(c.owner or "", "through" if c.kind == "via" else "copper",
                                         faces, c.layers, c.net, poly, Box.of_points(poly)))
        # Rule areas the generated board already carries: a stamped cell brings
        # its module's with it. One that belongs to the board is reserved now;
        # one a cell owns has no position until that cell lands, so it waits
        # for commit(), exactly as the cell's own courtyard does.
        # A cell's are held at their CURRENT position and moved by each commit's
        # own transform, the way a footprint's shapes are: the transform maps
        # from where the item is now, not from where the generator left it, so
        # re-transforming the original polygon would compound.
        self._cell_rule_areas: dict = {}
        for ra in geometry.rule_areas:
            if "parts" not in ra.excludes:
                continue
            if ra.cell is None:
                claims, layer = parts_claim(ra.layers)
                if claims:
                    self.reserve(ra.polygon, "rule area %r on the generated board" % ra.name, layer=layer)
            else:
                self._cell_rule_areas.setdefault(ra.cell, []).append([ra, tuple(ra.polygon)])

    # ------------------------------------------------------------ geometry of a candidate
    def _register(self, fp: Footprint) -> ItemGeometry:
        g = ItemGeometry(frozenset([fp.ref]), Placement(fp.location, fp.rotation, fp.face),
                         tuple(_fp_shapes(fp, self.envelope)), fp.body_box, frozenset(p.net for p in fp.pads),
                         Box.union([fp.body_box, fp.phys_box]))
        self.items[fp.ref] = g
        self._invalidate_native()
        return g

    def _invalidate_native(self) -> None:
        """Drop every cached native obstacle index: self.items or
        self.copper is about to change (or just did), so any index built
        from them is stale. Called from commit(), add_copper() and the
        (rare, post-init) lazy path in _register()."""
        self._native_obstacle_cache.clear()

    def _geometry(self, item) -> ItemGeometry:
        if isinstance(item, Footprint):
            return self.items.get(item.ref) or self._register(item)
        if isinstance(item, CellGeom):
            if item.name in self._cells:
                return self._cells[item.name]
            members = [self.items[fp.ref] for fp in item.members]
            shapes = tuple(s for m in members for s in m.shapes)
            for c in self.copper:
                if c.owner == item.name:
                    shapes += (c,)
            own = [s.box for s in shapes if s.owner == item.name]
            body = Box.union([m.body for m in members] + own)
            reach = Box.union([m.reach or m.body for m in members] + own)
            self._cells[item.name] = ItemGeometry(frozenset(m for mg in members for m in mg.owners) | {item.name},
                                                  Placement(body.center, 0.0, Face.FRONT), shapes, body,
                                                  frozenset(n for m in members for n in m.nets), reach)
            return self._cells[item.name]
        raise TypeError("cannot place a %s" % type(item).__name__)

    @staticmethod
    def _transform(geom: ItemGeometry, placement: Placement) -> Transform:
        """Where an item's shapes go when it moves to `placement`.

        A flip to the back mirrors about the VERTICAL axis and then turns by
        the rotation asked for - KiCad's own F key, and what the writer does
        once it stops discarding the orientation the flip computed. Adding the
        reference rotation rather than subtracting it is what cancels the
        generator's own rotation out of the answer, so the same declaration
        means the same orientation whatever the generator happened to do.

        A cell's reference rotation is always 0, so this is identical to the
        unflipped arithmetic for a cell and nothing about cells changes."""
        ref = geom.reference
        t = Transform.translate(-ref.location.x, -ref.location.y)
        flip = placement.face != ref.face
        if flip:
            t = t.then(Transform.mirror_x(Location(0, 0)))
        turn = placement.rotation + ref.rotation if flip else placement.rotation - ref.rotation
        t = t.then(Transform.rotate(turn))
        return t.then(Transform.translate(placement.location.x, placement.location.y))

    def _flip_layers(self, layers: frozenset[CopperLayer]) -> frozenset[CopperLayer]:
        out = set()
        for l in layers:
            out.add(l.other_face if l in (CopperLayer.F, CopperLayer.B) else l)
        return frozenset(out)

    def _flip_faces(self, faces: frozenset[Face]) -> frozenset[Face]:
        return frozenset(Face.BACK if f is Face.FRONT else Face.FRONT for f in faces)

    def candidate_shapes(self, item, placement: Placement) -> tuple[ItemGeometry, list[Shape]]:
        geom = self._geometry(item)
        t = self._transform(geom, placement)
        flip = placement.face != geom.reference.face
        out = []
        for s in geom.shapes:
            poly = transform_polygon(s.poly, t)
            faces = self._flip_faces(s.faces) if (flip and len(s.faces) == 1) else s.faces
            layers = self._flip_layers(s.layers) if flip else s.layers
            out.append(Shape(s.owner, s.kind, faces, layers, s.net, poly, Box.of_points(poly), s.label))
        return geom, out

    def candidate_pad_locations(self, item, placement: Placement) -> dict:
        """{(refdes, pad number): Location} for the item at a candidate
        placement: the pad centres at the reference, moved as points."""
        geom = self._geometry(item)
        t = self._transform(geom, placement)
        boxes: dict = {}
        for s in geom.shapes:
            if s.kind in ("pad", "through"):
                boxes.setdefault((s.owner, s.label), []).append(s.box)
        return {k: t.apply_location(Box.union(v).center) for k, v in boxes.items()}

    def pad_location(self, ref: str, number: str) -> Location:
        """Where a pad is NOW (after every commit so far): its outline's box
        centre. Cached per (ref, number) until the next commit() - a
        cleanup pass asks this for every pin of a net to weigh one key's
        move, and only the moving key's own pins actually change between
        two such asks."""
        key = (ref, number)
        hit = self._pad_location_cache.get(key)
        if hit is not None:
            return hit
        boxes = [s.box for s in self.items[ref].shapes if s.kind in ("pad", "through") and s.label == number]
        if not boxes:
            raise KeyError("%s has no pad %s" % (ref, number))
        loc = Box.union(boxes).center
        self._pad_location_cache[key] = loc
        return loc

    def add_copper(self, shapes) -> None:
        """Planned copper becomes an obstacle for everything placed after it."""
        self.copper.extend(shapes)
        self._invalidate_native()

    def copper_conflicts(self, shape: Shape) -> list[str]:
        """Every pad or copper of another net within clearance of `shape`."""
        out = []
        for owner, g in self.items.items():
            if owner in self.pending:
                continue                        # not placed yet: its pads are nowhere
            for o in g.shapes:
                if o.kind not in ("pad", "through") or not shape.box.overlaps(o.box, gap=1.0):
                    continue
                why = self._conflict(shape, o, None)
                if why:
                    out.append(why)
        for o in self.copper:
            if o is shape or not shape.box.overlaps(o.box, gap=1.0):
                continue
            why = self._conflict(shape, o, None)
            if why:
                out.append(why)
        return out

    def body_box(self, item, placement: Placement) -> Box:
        geom = self._geometry(item)
        return transform_box(geom.body, self._transform(geom, placement))

    def reach_box(self, item, placement: Placement) -> Box:
        """The item's outermost extent at a placement: body, pads and drawn
        graphics, so a terminal's silk counts toward the edge; the courtyard
        (an assembly margin) does not."""
        geom = self._geometry(item)
        return transform_box(geom.reach or geom.body, self._transform(geom, placement))

    def who(self, owner: str) -> str:
        """A refdes as a finding names it: with its cell when it has one."""
        if self.geometry.has_footprint(owner):
            cell = self.geometry.footprint(owner).cell
            if cell:
                return "cell %s's %s" % (cell, owner)
        return owner

    # ------------------------------------------------------------ mutation
    def reserve(self, region, why: str, allow=(), layer: CopperLayer | None = None, owners=(),
                source: str = ""):
        """Keep a region clear. `region` is a Box or a polygon. `source` names
        what put it there, so committing that thing again replaces its own
        regions instead of leaving the old ones behind."""
        poly = box_polygon(region) if isinstance(region, Box) else tuple(tuple(p) for p in region)
        self.reservations.append(Reservation(poly, why, frozenset(str(n) for n in allow),
                                             layer, frozenset(str(o) for o in owners), source))

    def commit(self, item, placement: Placement):
        """Record that `item` now sits at `placement`; later checks see it there."""
        geom, shapes = self.candidate_shapes(item, placement)
        self._cells.clear()
        self._pad_location_cache.clear()
        self._invalidate_native()
        self.pending -= geom.owners
        if isinstance(item, Footprint):
            self.items[item.ref] = ItemGeometry(geom.owners, placement, tuple(shapes),
                                                self.body_box(item, placement), geom.nets,
                                                self.reach_box(item, placement))
            return
        t = self._transform(geom, placement)
        by_owner: dict[str, list[Shape]] = {}
        for s in shapes:
            by_owner.setdefault(s.owner, []).append(s)
        for fp in item.members:
            m = self.items[fp.ref]
            new_ref = Placement(t.apply_location(m.reference.location),
                                m.reference.rotation + (placement.rotation - geom.reference.rotation),
                                (Face.BACK if m.reference.face is Face.FRONT else Face.FRONT)
                                if placement.face != geom.reference.face else m.reference.face)
            self.items[fp.ref] = ItemGeometry(m.owners, new_ref, tuple(by_owner.get(fp.ref, ())),
                                              transform_box(m.body, t), m.nets, transform_box(m.reach or m.body, t))
        tag = "cell:%s" % item.name
        self.reservations = [r for r in self.reservations if r.source != tag]
        for pair in self._cell_rule_areas.get(item.name, ()):
            ra, poly = pair
            poly = tuple(t.apply(p) for p in poly)
            pair[1] = poly
            claims, layer = parts_claim(ra.layers, flip=placement.face != geom.reference.face)
            if claims:
                what = ("label %r" % ra.name[len("label "):]) if ra.name.startswith("label ") else "rule area %r" % ra.name
                self.reserve(poly, "%s from the %s cell" % (what, ra.cell), source=tag, layer=layer)
        own = by_owner.get(item.name, [])
        self.copper = [c for c in self.copper if c.owner != item.name] + own

    # ------------------------------------------------------------ measures
    def free_area(self, face: Face | None = None) -> float:
        """Board area not under a courtyard, on one face or summed over both.
        Courtyards are taken as their boxes; overlaps (which are findings)
        are not corrected for."""
        if self.board_box is None:
            return 0.0
        board_area = self.board_shape.area if self.board_shape is not None else self.board_box.area
        if self.board_shape is None and self.board_cutouts:
            board_area -= self.board_cutouts.area
        faces = [face] if face is not None else [Face.FRONT, Face.BACK]
        total = 0.0
        for f in faces:
            used = 0.0
            for owner, g in self.items.items():
                if owner in self.pending:
                    continue
                for s in g.shapes:
                    if s.kind == "courtyard" and f in s.faces:
                        used += s.box.area
            total += board_area - used
        return total

    # ------------------------------------------------------------ legality
    def obstacles(self, geom: ItemGeometry, region: Box | None = None) -> list:
        """Every shape not owned by `geom`, within `region` (plus the
        conflict gap) when one is given: gathered once for a whole scan.

        The native index attached as `idx._native` is NOT rebuilt from this
        region-filtered list: it is a per-skip-set entry cached on the
        Occupancy (`_native_obstacle_cache`, cleared on commit), covering
        every non-skipped shape on the board regardless of region - a scan,
        a cleanup hint and a freedom's several _slide() calls for the same
        item, between commits, share one native registration instead of
        rebuilding and re-marshalling it every call. See
        _native_obstacle_index and the Phase 3 spec note."""
        skip = geom.owners | self.pending
        out = [s for owner, g in self.items.items() if owner not in skip for s in g.shapes]
        out += [c for c in self.copper if c.owner not in skip]
        if region is not None:
            out = [o for o in out if o.box.overlaps(region, gap=self._gap)]
        idx = ShapeIndex(out)
        idx._native = self._native_obstacle_index(skip)
        return idx

    def _native_obstacle_index(self, skip: frozenset):
        """The cached (NativeObstacles, backing shape list) for this
        skip-set, building it - over every shape in self.items/self.copper
        not owned by `skip`, NOT region-filtered - on a cache miss. `None`
        when there is no native module (the pure-Python `near()` + per-shape
        loop in `legal()` is then what runs)."""
        native = _geometry_module._native
        if native is None:
            return None
        hit = self._native_obstacle_cache.get(skip)
        if hit is not None:
            return hit
        shapes = [s for owner, g in self.items.items() if owner not in skip for s in g.shapes]
        shapes += [c for c in self.copper if c.owner not in skip]
        index = native.NativeObstacles(
            [_to_native_shape(s, self._footprint_refs, self._leads, self._margins) for s in shapes],
            **self._native_conflict_kwargs())
        entry = (index, shapes)
        self._native_obstacle_cache[skip] = entry
        return entry

    def _native_conflict_kwargs(self) -> dict:
        """The scalars and the net-clearance lookup `_conflict` reads off
        `self` and `self.geometry`, gathered once so a native obstacle
        index does not read Python state again per candidate. Cached: these
        never change within one Occupancy's life (`self.geometry` and the
        board's netclasses are fixed at construction)."""
        cache = self.__dict__.get("_native_kwargs")
        if cache is None:
            net_clearance = {n: self.geometry.netclass(n).clearance for n in self.geometry.nets}
            cache = dict(touch=self._touch, vias_block_courtyards=self.vias_block_courtyards,
                        silk_clearance=self.silk_clearance, component_spacing=self.component_spacing,
                        default_clearance=self.geometry.default_clearance, net_clearance=net_clearance,
                        gap=self._gap, drawn_gap=self._drawn_gap)
            self.__dict__["_native_kwargs"] = cache
        return cache

    def _edge_or_reservation_conflict(self, geom: ItemGeometry, body: Box, placement: Placement,
                                      past_edge: bool, blame: list | None) -> str | None:
        """The two checks `legal()` runs before it ever looks at an
        obstacle: the board edge (and cutouts) and the reservations. Both
        produce a ready sentence cheaply (a box test, or a polymorphic
        `why_not` call), so unlike the near-obstacle search below there is
        nothing to gain from deferring them - `legal()` and `legal_bucket()`
        both call this and return its answer unchanged when it fires."""
        if self.edge_margin is not None and not past_edge:
            if self.board_shape is not None:
                why = self.board_shape.why_not(body, self.edge_margin)
                if why:
                    if blame is not None:
                        blame.append(Blocker("edge", "", frozenset()))
                    return "body box %s is %s" % (_fmt(body), why)
            elif self.board_box is not None:
                inner = self.board_box.inflate(-self.edge_margin)
                if not inner.contains(body):
                    if blame is not None:
                        blame.append(Blocker("edge", "", frozenset()))
                    return "body box %s crosses the board edge margin (%.2f mm)" % (_fmt(body), self.edge_margin)
                if self.board_cutouts:
                    why = self.board_cutouts.why_not(body, self.edge_margin)
                    if why:
                        if blame is not None:
                            blame.append(Blocker("edge", "", frozenset()))
                        return "body box %s is %s" % (_fmt(body), why)
        faces = {placement.face} | ({Face.FRONT, Face.BACK} if any(s.kind in ("through", "npth") for s in geom.shapes) else set())
        for r in self.reservations:
            if r.layer is not None and r.layer.face not in faces:
                continue                                   # reserved on the other face only
            if (geom.owners & r.owners) or (geom.nets & r.allow):
                continue                                   # named, or carrying a net let through
            # the box first because it is cheap, and the placer asks this tens of thousands of times
            if r.overlaps(body):
                if blame is not None:
                    blame.append(Blocker("reservation", r.why, frozenset()))
                return "sits in the reservation for %s" % r.why
        return None

    def legal(self, item, placement: Placement, clearance: float | None = None, others=None,
              past_edge: bool = False, blame: list | None = None) -> str | None:
        """None when `item` may sit at `placement`, else one sentence saying
        what stops it. The first failure found is reported. `others` is a
        prefiltered obstacle list from `obstacles()`; without one every
        shape on the board is a candidate obstacle. `past_edge` allows a
        body over the edge margin: a connector face declared to overhang.
        `blame`, when a list is passed, collects a `Blocker` for the conflict
        found: the same refusal in parts rather than prose, so a scan can
        count who was in the way rather than only how often."""
        geom = self._geometry(item)
        body = self.shifted_body_box(item, placement)
        why = self._edge_or_reservation_conflict(geom, body, placement, past_edge, blame)
        if why is not None:
            return why
        if others is None:
            others = self.obstacles(geom)
        dx, dy = placement.location.x, placement.location.y
        native_entry = getattr(others, "_native", None)
        if native_entry is not None:
            # The near-obstacle search itself - ShapeIndex.near() plus the
            # per-shape "close" filter plus _conflict/_drawn_conflict's own
            # decision - runs once, natively, over every registered obstacle;
            # see docs/superpowers/specs/2026-09-24-native-core-design.md
            # ("Phase 2", "Phase 3"). It decides ONLY which pair conflicts;
            # the untouched Python _conflict below still produces the reason
            # string, so the text a script sees is always the reference
            # implementation's. native_index is a per-skip-set cache entry
            # (Phase 3), not rebuilt from `others`, so a conflicting
            # obstacle's index is looked up in ITS OWN backing shape list
            # (native_shapes), not in `others` (which may be region-filtered
            # and use a different indexing).
            native_index, native_shapes = native_entry
            origin_shapes = list(self._origin_shapes(item, geom, placement))
            origin_handle = self._native_origin_shapes(item, geom, placement)
            hit = native_index.first_conflict_shifted(origin_handle, dx, dy, clearance)
            if hit is None:
                return None
            si, oi = hit
            o = native_shapes[oi]
            s = origin_shapes[si]
            moved = Shape(s.owner, s.kind, s.faces, s.layers, s.net,
                         tuple((x + dx, y + dy) for x, y in s.poly), s.box.moved(dx, dy), s.label)
            why = self._conflict(moved, o, clearance)
            if why is None:
                raise AssertionError(
                    "native found a conflict between a %s and a %s that _conflict disagrees with; "
                    "this is a native/Python mismatch, not a placement question" % (moved.kind, o.kind))
            if blame is not None:
                blame.append(Blocker(o.kind, self.who(o.owner), frozenset(o.faces)))
            return why
        # What a conflict can reach from: the body, or in a drawn envelope every
        # shape the part claims - silk can stand well past the body.
        reach = body if self.envelope == "courtyard" else \
            Box.union([body, transform_box(self._extent(geom), self._transform(geom, placement))])
        near = others.near(reach, self._gap) if isinstance(others, ShapeIndex) else \
            [o for o in others if o.box.overlaps(reach, gap=self._gap)]
        if not near:
            return None
        # Each shape is turned and faced once per rotation and face, then
        # shifted; only a shape whose box reaches an obstacle is moved as a polygon.
        for s in self._origin_shapes(item, geom, placement):
            sb = s.box.moved(dx, dy)
            close = [o for o in near if sb.overlaps(o.box, gap=self.gap_for(s))]
            if not close:
                continue
            moved = Shape(s.owner, s.kind, s.faces, s.layers, s.net,
                          tuple((x + dx, y + dy) for x, y in s.poly), sb, s.label)
            for o in close:
                why = self._conflict(moved, o, clearance)
                if why:
                    if blame is not None:
                        blame.append(Blocker(o.kind, self.who(o.owner), frozenset(o.faces)))
                    return why
        return None

    def legal_bucket(self, item, placement: Placement, clearance: float | None = None, others=None,
                     blame: list | None = None):
        """As `legal()`, but for a scan's sweep, which only ever keeps ONE
        example sentence per rejection bucket (`ScanResult.reasons`,
        `reasons.setdefault(key, why)`) however many candidates land in it -
        `rejected` only ever needs the bucket, counted. Returns `None` when
        legal, else `(bucket, get_reason)`: `bucket` is what `_reason_key`
        would answer for the sentence `legal()` would return, known here
        without formatting one; `get_reason()` - call it only when `bucket`
        has not been seen before this sweep - returns that sentence, from
        the same unmodified `_conflict` / `_drawn_conflict` `legal()` itself
        calls.

        The saving is real only on the native near-obstacle path: Rust
        already knows which pair conflicts (see `legal()`'s own native
        branch), so formatting a sentence for a rejection nothing keeps -
        `who()`'s cell lookups, `_cross_face_note`, the `%`-formatting
        itself - is pure waste on all but the first candidate a bucket
        sees, and a scan's candidates are rejected far more often than not.
        The edge/reservation checks and the no-native fallback already
        produce their sentence cheaply (a box test or a `_conflict` call
        that has to run anyway to know the candidate is illegal at all), so
        they run exactly as `legal()` does and bucket the result with
        `_reason_key`, unchanged."""
        geom = self._geometry(item)
        body = self.shifted_body_box(item, placement)
        why = self._edge_or_reservation_conflict(geom, body, placement, False, blame)
        if why is not None:
            return _reason_key(why), (lambda why=why: why)
        if others is None:
            others = self.obstacles(geom)
        native_entry = getattr(others, "_native", None)
        if native_entry is None:
            why = self.legal(item, placement, clearance, others=others, blame=blame)
            return None if why is None else (_reason_key(why), (lambda why=why: why))
        native_index, native_shapes = native_entry
        dx, dy = placement.location.x, placement.location.y
        origin_shapes = list(self._origin_shapes(item, geom, placement))
        origin_handle = self._native_origin_shapes(item, geom, placement)
        hit = native_index.first_conflict_shifted(origin_handle, dx, dy, clearance)
        if hit is None:
            return None
        si, oi = hit
        o = native_shapes[oi]
        s = origin_shapes[si]
        moved = Shape(s.owner, s.kind, s.faces, s.layers, s.net,
                     tuple((x + dx, y + dy) for x, y in s.poly), s.box.moved(dx, dy), s.label)
        if blame is not None:
            blame.append(Blocker(o.kind, self.who(o.owner), frozenset(o.faces)))

        def get_reason(moved=moved, o=o, clearance=clearance):
            why = self._conflict(moved, o, clearance)
            if why is None:
                raise AssertionError(
                    "native found a conflict between a %s and a %s that _conflict disagrees with; "
                    "this is a native/Python mismatch, not a placement question" % (moved.kind, o.kind))
            return why
        return self._native_bucket(moved, o), get_reason

    def _native_bucket(self, s: Shape, o: Shape) -> str:
        """`_reason_key`'s answer for a near-obstacle conflict, from the
        pair's shape kinds alone - no sentence needed. Mirrors
        `_conflict`'s OWN dispatch order, because a pair's message depends
        on which branch fires, not just which kinds are present:
        `_conflict` checks "is either shape a drawn kind (silk/mask/body)"
        FIRST, before courtyard or npth - so a body-vs-npth pair (the one
        case that is both: `_drawn_conflict` recognises `{"body","npth"}`
        as its own pair, at gap 0) goes to `_drawn_conflict`, never to
        `_conflict`'s own npth-vs-copper branch. A drawn-envelope message
        (silk/mask/body pairs, or a body against another part's pad) never
        contains any of `_reason_key`'s six checked words - `_NAMES` maps
        "through" to "pad" and "npth" to "hole" for display - so
        `_reason_key` falls through to the sentence's first word, always
        `who(s.owner)` (`legal()` always calls `_conflict(moved, o, ...)`,
        the candidate's own shape first). Once drawn kinds are ruled out, a
        courtyard message always contains the word "courtyard"
        (courtyard-vs-courtyard and courtyard-vs-lead/npth both say so); a
        pad/through/copper clearance message and the npth-cuts-copper one
        both always contain "copper" (checked before "through"/"npth" in
        `_reason_key`'s own order, so it always wins first regardless).
        Verified against the live `_conflict` / `_drawn_conflict` by
        fuzzing every branch - see tests/test_native_bucket.py. (A net or
        refdes literally containing one of the six checked words as a
        substring could in principle beat this - `_reason_key` itself is a
        substring match over arbitrary project names, not a property of the
        conflict kind alone - but that was already true of `_reason_key`
        before this method existed, and no fixture or real board comes
        close to it.)"""
        if s.kind in _DRAWN or o.kind in _DRAWN:
            return self.who(s.owner).split(" ")[0]
        if s.kind == "courtyard" or o.kind == "courtyard":
            return "courtyard"
        if (s.kind in _COPPERISH and o.kind in _COPPERISH) or s.kind == "npth" or o.kind == "npth":
            return "copper"
        return self.who(s.owner).split(" ")[0]

    def _drawn_conflict(self, s: Shape, o: Shape) -> str | None:
        """Silk, mask openings and bodies of two different parts, each gap
        the board's own: silk keeps the silk clearance from silk and from a
        mask opening, a body the component spacing from a body and from
        another part's pad, and silk may touch a body but not enter it. Any
        other pair - a mask opening beside a pad, silk over copper - is not a
        placement question."""
        if not (s.faces & o.faces):
            return None
        pair = frozenset((s.kind, o.kind))
        if pair in (frozenset(("silk",)), frozenset(("silk", "mask"))):
            gap = self.silk_clearance
        elif pair == frozenset(("silk", "body")) or pair == frozenset(("body", "npth")):
            gap = 0.0
        elif pair == frozenset(("body",)):
            gap = self.component_spacing
        elif "body" in pair and pair & {"pad", "through"}:
            other = o if s.kind == "body" else s
            if other.owner not in self._footprint_refs:
                return None                 # a track or via may run under a body
            gap = self.component_spacing
        else:
            return None
        if gap <= 0.0:
            if polys_overlap(s.poly, o.poly):
                return "%s %s overlaps %s %s" % (self.who(s.owner), _NAMES[s.kind], self.who(o.owner), _NAMES[o.kind])
            return None
        if _box_gap(s.box, o.box) >= gap - 1e-9:
            return None
        d = poly_distance(s.poly, o.poly)
        if d < gap - 1e-9:
            return "%s %s is %.2f mm from %s %s (needs %.2f)" % (
                self.who(s.owner), _NAMES[s.kind], d, self.who(o.owner), _NAMES[o.kind], gap)
        return None

    def _origin_shapes(self, item, geom: ItemGeometry, placement: Placement) -> list:
        """The item's shapes turned and faced as `placement` asks, at the
        origin: moved once per turn and face, then only shifted."""
        cache = self.__dict__.setdefault("_shape_cache", {})
        key = (id(geom), placement.rotation, placement.face)
        hit = cache.get(key)
        if hit is None or hit[0] is not geom:
            _, shapes = self.candidate_shapes(item, Placement(Location(0.0, 0.0), placement.rotation, placement.face))
            hit = (geom, shapes)
            cache[key] = hit
        return hit[1]

    def _native_origin_shapes(self, item, geom: ItemGeometry, placement: Placement):
        """The native mirror of `_origin_shapes`: a `NativeOriginShapes`
        handle for this (item, rotation, face) turn, registered once and
        reused by every candidate at that turn - the shift by (dx, dy) then
        costs two floats crossing the FFI boundary, not a rebuilt polygon
        per shape on every `legal()` call. See
        docs/superpowers/specs/2026-09-24-native-core-design.md
        ("per-candidate shapes stay native"). Cached the same way, and for
        the same reason, as `_origin_shapes` itself."""
        native = _geometry_module._native
        if native is None:
            return None
        cache = self.__dict__.setdefault("_native_shape_cache", {})
        key = (id(geom), placement.rotation, placement.face)
        hit = cache.get(key)
        if hit is not None and hit[0] is geom:
            return hit[1]
        origin_shapes = self._origin_shapes(item, geom, placement)
        handle = native.NativeOriginShapes(
            [_to_native_shape(s, self._footprint_refs, self._leads, self._margins) for s in origin_shapes])
        cache[key] = (geom, handle)
        return handle

    def shifted_courtyards(self, item, placement: Placement) -> list:
        """The item's courtyard polygons at `placement`, from the turned shapes
        at the origin, shifted and rounded as a transform rounds."""
        dx, dy = placement.location.x, placement.location.y
        return [tuple((_clean(x + dx), _clean(y + dy)) for x, y in s.poly)
                for s in self._origin_shapes(item, self._geometry(item), placement) if s.kind == "courtyard"]

    def shifted_body_box(self, item, placement: Placement) -> Box:
        """body_box() at `placement`, from the body turned at the origin."""
        cache = self.__dict__.setdefault("_body_cache", {})
        geom = self._geometry(item)
        key = (id(geom), placement.rotation, placement.face)
        hit = cache.get(key)
        if hit is None or hit[0] is not geom:
            hit = (geom, self.body_box(item, Placement(Location(0.0, 0.0), placement.rotation, placement.face)))
            cache[key] = hit
        b, dx, dy = hit[1], placement.location.x, placement.location.y
        return Box(_clean(b.left + dx), _clean(b.top + dy), _clean(b.right + dx), _clean(b.bottom + dy))

    def shifted_shapes(self, item, placement: Placement) -> list:
        """The item's shapes at `placement`, from the turned shapes at the origin."""
        dx, dy = placement.location.x, placement.location.y
        return [Shape(s.owner, s.kind, s.faces, s.layers, s.net, tuple((x + dx, y + dy) for x, y in s.poly),
                      s.box.moved(dx, dy), s.label)
                for s in self._origin_shapes(item, self._geometry(item), placement)]

    def gap_for(self, s: Shape) -> float:
        """How far from `s` another shape can still conflict with it: a pad's
        clearance can be as wide as the conflict gap; silk, a mask opening
        or a body reaches no further than the drawn gaps. A pad against a
        body is judged from the pad's side too, at the wider gap."""
        return self._drawn_gap if s.kind in _DRAWN else self._gap

    def _extent(self, geom: ItemGeometry) -> Box:
        """The box round all of an item's shapes where it stands now."""
        key = id(geom)
        cache = self.__dict__.setdefault("_extents", {})
        hit = cache.get(key)
        if hit is None or hit[0] is not geom:
            hit = (geom, Box.union([s.box for s in geom.shapes] + [geom.body]))
            cache[key] = hit
        return hit[1]

    def _conflict(self, s: Shape, o: Shape, clearance: float | None) -> str | None:
        """The DRC rules, in occupancy terms. A via under a body is legal to
        DRC and is only refused when `vias_block_courtyards` is set (a house
        rule for boards that pair through-feature cells with via-free parts)."""
        ks, ko = s.kind, o.kind
        if ks in _DRAWN or ko in _DRAWN:
            return self._drawn_conflict(s, o)
        if ks == "courtyard" and ko == "courtyard":
            # courtyards may touch: a shared edge, to a rounding, is packing, not a collision
            depth = min(min(s.box.right, o.box.right) - max(s.box.left, o.box.left),
                        min(s.box.bottom, o.box.bottom) - max(s.box.top, o.box.top))
            # KiCad's courtyards lie inside ours by each part's margin: overlap by
            # less than the two, and KiCad sees them apart (it counts touching).
            allowed = max(self._touch, self._margins.get(s.owner, 0.0) + self._margins.get(o.owner, 0.0) - 0.001)
            # to a nanometre: the depth is a difference of coordinates, and exactly the allowance must not read as more
            if depth <= allowed + 1e-9 and (s.box.width > 0 and o.box.width > 0):
                return None
            if s.faces & o.faces and polys_overlap(s.poly, o.poly):
                return "%s courtyard overlaps %s courtyard" % (self.who(s.owner), self.who(o.owner))
            return None
        if "courtyard" in (ks, ko):
            other = o if ks == "courtyard" else s
            court = s if ks == "courtyard" else o
            if other.kind == "through" and other.owner != court.owner and (other.owner, other.label) in self._leads:
                if polys_overlap(court.poly, other.poly):
                    return "%s courtyard sits over a through-hole lead of %s%s" % (
                        self.who(court.owner), self.who(other.owner),
                        "" if other.net else " (a plated pad with no net: often a footprint defect)")
                return None
            if other.kind == "npth" or (other.kind == "through" and self.vias_block_courtyards
                                        and other.owner not in self.items):
                if polys_overlap(court.poly, other.poly):
                    return "%s courtyard sits over a %s (%s)" % (self.who(court.owner), other.kind, self.who(other.owner) if other.owner else "via")
            return None
        if ks in ("pad", "through", "copper") and ko in ("pad", "through", "copper"):
            common = s.layers & o.layers
            if not common:
                return None
            if s.net and s.net == o.net:
                return None
            clr = clearance
            if clr is None:
                clr = self.geometry.clearance(s.net, o.net) if (s.net in self.geometry.nets and o.net in self.geometry.nets) \
                    else self.geometry.default_clearance
            # Two boxes this far apart hold two polygons at least as far
            # apart, so the walk round both outlines is only worth its cost
            # when the boxes themselves are close enough to fail.
            if _box_gap(s.box, o.box) >= clr - 1e-9:
                return None
            gap = poly_distance(s.poly, o.poly)
            if gap < clr - 1e-9:
                return "%s pad %s is %.2f mm from %s copper on %s (needs %.2f)" % (
                    self.who(s.owner), s.net or "-", gap, o.net or self.who(o.owner), "/".join(sorted(l.value for l in common)), clr)
            return None
        if ks == "npth" and ko in ("pad", "through", "copper"):
            if polys_overlap(s.poly, o.poly):
                return "%s hole cuts %s copper" % (self.who(s.owner), o.net or self.who(o.owner))
        return None


_DRAWN = frozenset(("silk", "mask", "body"))
_COPPERISH = frozenset(("pad", "through", "copper"))
_NAMES = {"silk": "silk", "mask": "mask opening", "body": "body", "pad": "pad", "through": "pad", "npth": "hole"}


def _box_gap(a: Box, b: Box) -> float:
    """The shortest distance between two boxes; 0 when they touch or overlap."""
    dx = a.left - b.right if a.left > b.right else (b.left - a.right if b.left > a.right else 0.0)
    dy = a.top - b.bottom if a.top > b.bottom else (b.top - a.bottom if b.top > a.bottom else 0.0)
    return dx if dy == 0.0 else (dy if dx == 0.0 else math.hypot(dx, dy))


def _fmt(b: Box) -> str:
    return "%.2f,%.2f..%.2f,%.2f" % (b.left, b.top, b.right, b.bottom)


def _reason_key(why: str) -> str:
    """Which bucket a refusal sentence counts under, for a scan's `rejected`
    Counter and `reasons` dict (moved here from placer.py, which still
    re-exports it, so legal_bucket's native path can derive the same key
    without formatting the sentence first - see legal_bucket's own doc)."""
    for word in ("courtyard", "edge", "reservation", "copper", "through", "npth"):
        if word in why:
            return word
    return why.split(" ")[0]
