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

import dataclasses
import functools
import math
from dataclasses import dataclass

from . import geometry as _geometry_module
from .geometry import (_clean, PolyRaster, Polygon, Transform, box_polygon, circle_polygon, poly_distance,
                       point_in_polygon, point_segment_distance, polys_overlap, transform_box,
                       transform_polygon)
from .placement import Placement
from .settings import Settings
from .board_geometry import CellGeom, Footprint, BoardGeometry, stackup_order
from .rules import ClearanceRules
from .values import Box, CopperLayer, Face, Location


@dataclass(frozen=True)
class Shape:
    """One obstacle: a polygon on a set of copper layers (or both faces for a
    courtyard/through feature), tagged with who owns it and what net it is."""
    owner: str                      # refdes (or cell name for cell copper)
    kind: str                       # courtyard | pad | through | copper | npth | hole (a plated hole's drill)
    faces: frozenset[Face]          # which faces this shape occupies (courtyard sense)
    layers: frozenset[CopperLayer]  # copper layers (clearance sense); empty for courtyards
    net: str
    poly: Polygon
    box: Box
    label: str = ""                 # pad number for a pad shape
    ends: tuple = ()                # a track's own two endpoints, for a finding that names the segment
    circle: tuple = ()              # a via's (x, y, radius): its copper as the circle it is, for a finding
    # A carried via (giveway.py): its ring, its hole and its tail carry its id, and `points`
    # its centre (and a tail's far end after it), moved as the shape moves. `given` names the
    # via whose giving way drew this shape.
    carried: str = ""
    points: tuple = ()
    given: str = ""
    # a courtyard claimed as the part itself: under the physical envelope, a footprint that
    # draws neither silk nor fab claims its courtyard, which keeps other parts' drawn shapes out
    claims: bool = False
    # an escape's reserved riser, lane or via (board.escape): the name a finding gives it
    lane: str = ""


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
    kind = "keepclear" if (s.kind == "courtyard" and s.claims) else s.kind
    return (kind, _native_faces(s.faces), _native_layers(s.layers), s.net or "", tuple(s.poly), s.owner,
            s.owner in footprint_refs, (s.owner, s.label) in leads, margins.get(s.owner, 0.0))


@dataclass(frozen=True)
class Blocker:
    """Why one candidate placement was refused, in parts rather than prose:
    what kind of conflict, whose shape it was, and which faces it holds. The
    sentence `legal` returns is for a human; this is for counting."""
    kind: str                       # courtyard | pad | through | copper | npth | hole | edge | reservation
    owner: str                      # as who() formats it: a cell member carries its cell
    faces: frozenset


@dataclass(frozen=True)
class Reservation:
    """A region nothing may sit in. `owners` are refdes that may sit in it by
    name; `allow` are nets whose copper may run through it (a cell's own
    tracks), not the parts that carry them - an antenna's clearance holds its
    own matching network, and admitting a net's parts would admit every part
    that shares one."""
    poly: tuple
    why: str
    allow: frozenset[str]
    layer: CopperLayer | None       # None: both faces, any layer
    owners: frozenset[str] = frozenset()
    source: str = ""                # what put it here, so a re-commit can replace its own
    admitted: frozenset | None = None   # a height-limited region: the parts short enough to sit in it
    copper: bool = True             # whether it keeps copper out too: a parts-only keepout leaves a cell's own be
    barred: frozenset = frozenset() # the parts a `bars=` keepout names: refused whatever their height, and said so

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
    parts: tuple = ()                   # a cell's members' bodies (and its own copper): what the edge and keepouts judge
    part_refs: tuple = ()               # the members whose bodies lead `parts`, in its order; its own copper follows


@dataclass(frozen=True, eq=False)
class WithoutCarried:
    """An item less its carried vias (giveway.py): judged as the item is,
    before its vias give way."""
    item: object


_BOTH = frozenset([Face.FRONT, Face.BACK])
# The defaults; a board's own come from `[place] conflict_gap` and
# `[place] courtyard_touch` and are carried on the Occupancy.
_GAP = 1.0      # how far outside a box a conflict can still reach: the largest clearance a rule asks for
TOUCH = 0.02    # two courtyards this close are touching, not overlapping: a footprint's courtyard stroke rounds by this much


def _polygon_area(poly) -> float:
    n = len(poly)
    return abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))) / 2.0


def courtyard_drawn(fp: Footprint, share: float) -> bool:
    """Whether the part's courtyard is claimed as KiCad draws it rather than
    as the box round it: its polygon covers less than `share` of its box (a
    slice of a disc, an L), so the box would claim room the part does not."""
    poly = getattr(fp, "courtyard_poly", ())
    if len(poly) < 3:
        return False
    box = Box.of_points(poly)
    return box.area > 0 and _polygon_area(poly) < share * box.area


def _fp_shapes(fp: Footprint, envelope: str = "courtyard", polygon_share: float = 0.0) -> list[Shape]:
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
        claims = envelope == "physical"         # the part claims its courtyard in place of what it would draw
        if courtyard_drawn(fp, polygon_share):
            ct = tuple(fp.courtyard_poly)
            shapes.append(Shape(fp.ref, "courtyard", faces, frozenset(), "", ct, Box.of_points(ct), claims=claims))
        else:
            ct = box_polygon(fp.courtyard_box)
            shapes.append(Shape(fp.ref, "courtyard", faces, frozenset(), "", ct, fp.courtyard_box, claims=claims))
    if envelope != "courtyard":
        for face, poly in fp.mask:
            shapes.append(Shape(fp.ref, "mask", frozenset([face]), frozenset(), "", poly, Box.of_points(poly)))
        for face, poly in fp.silk:
            shapes.append(Shape(fp.ref, "silk", frozenset([face]), frozenset(), "", poly, Box.of_points(poly)))
        for face, poly in fp.fab:
            shapes.append(Shape(fp.ref, "body", frozenset([face]), frozenset(), "", poly, Box.of_points(poly)))
    for layer, poly in fp.copper:         # its own copper graphics: copper of no net, kept clear of every other
        shapes.append(Shape(fp.ref, "copper", frozenset([layer.face]) if layer.face else frozenset(), frozenset([layer]),
                            "", poly, Box.of_points(poly)))
    for p in fp.pads:
        for poly in p.outlines:
            shapes.append(Shape(fp.ref, "through" if p.through else "pad",
                                _BOTH if p.through else frozenset([fp.face]),
                                p.layers, p.net, poly, Box.of_points(poly), p.number))
        if p.through and p.drill_mm:
            shapes.append(hole_shape(fp.ref, p.box.center, p.drill_mm, p.net, p.number))
    for center, drill in fp.npth:
        poly = circle_polygon(center, drill / 2.0)
        shapes.append(Shape(fp.ref, "npth", _BOTH, frozenset(CopperLayer), "", poly, Box.of_points(poly)))
    return shapes


def hole_shape(owner: str, centre: Location, drill: float, net: str = "", label: str = "",
               layers: frozenset = frozenset()) -> Shape:
    """A plated hole's drill: net-blind, it keeps the board's hole-to-hole
    rule from another owner's holes; its pad or via ring is its copper.
    `layers` are the layers a micro, blind or buried via's hole spans; none,
    a hole through the board."""
    poly = circle_polygon(centre, drill / 2.0)
    faces = frozenset(l.face for l in layers if l.face is not None) if layers else _BOTH
    return Shape(owner, "hole", faces, frozenset(layers), net, poly, Box.of_points(poly), label)


_TOUCH_MM = 1e-4     # a track's end on a via's centre: KiCad writes both to the nanometre


def _cell_vias(geometry) -> dict:
    """{id(copper item): (carried id, points)} for each via a stamped cell
    carries that may give way (giveway.py), and its tail: the one track of
    the cell's, on the via's net, that ends at the via's centre. A via that
    two of the cell's tracks meet, or whose one track runs on to another of
    the cell's vias, is part of a route and stays as drawn."""
    tracks: dict = {}
    for c in geometry.copper:
        if c.kind == "track" and c.owner in geometry.cells and len(c.anchors) == 2 and c.net:
            tracks.setdefault((c.owner, c.net), []).append(c)
    at_via: dict = {}
    for c in geometry.copper:
        if c.kind == "via" and c.owner in geometry.cells and c.anchors and c.net:
            at_via.setdefault((c.owner, c.net), []).append(c.anchors[0])

    def on(p, q):
        return abs(p[0] - q[0]) <= _TOUCH_MM and abs(p[1] - q[1]) <= _TOUCH_MM

    out: dict = {}
    count: dict = {}
    for c in geometry.copper:
        if not (c.kind == "via" and c.owner in geometry.cells and c.anchors and c.net):
            continue
        n = count.get(c.owner, 0)
        count[c.owner] = n + 1
        at = c.anchors[0]
        touching = [t for t in tracks.get((c.owner, c.net), ()) if on(t.anchors[0], at) or on(t.anchors[1], at)]
        if len(touching) > 1:
            continue
        tag = "%s via %d" % (c.owner, n)
        if touching:
            t = touching[0]
            far = t.anchors[1] if on(t.anchors[0], at) else t.anchors[0]
            if any(on(far, v) for v in at_via[(c.owner, c.net)]):
                continue
            out[id(t)] = (tag, (tuple(at), tuple(far)))
        out[id(c)] = (tag, (tuple(at),))
    return out


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
                 settings: Settings | None = None, component_spacing: float = 0.2, rules=()):
        self.settings = settings if settings is not None else Settings()
        self._gap = self.settings.place_conflict_gap
        self._touch = self.settings.place_courtyard_touch
        self.geometry = geometry
        self.envelope = self.settings.place_envelope
        self.component_spacing = component_spacing          # body to body, body to another part's pad
        self.silk_clearance = geometry.silk_clearance       # silk to silk, silk to a mask opening
        self._footprint_refs = frozenset(fp.ref for fp in geometry.footprints)
        # KiCad's courtyard lies inside the box by the stroke: two boxes may overlap by that much. A
        # courtyard claimed as drawn is KiCad's own polygon, with nothing to allow for.
        share = self.settings.place_courtyard_polygon_share
        self._margins = {fp.ref: fp.courtyard_margin for fp in geometry.footprints
                         if fp.courtyard_margin and not courtyard_drawn(fp, share)}
        self._leads = frozenset((fp.ref, p.number) for fp in geometry.footprints for p in fp.pads if _is_lead(fp, p))
        # Under the physical envelope a drawn part does not claim its courtyard (_fp_shapes), but
        # KiCad's DRC still refuses a courtyard over another part's plated lead: those courtyards
        # are kept as yards, which meet nothing else. A board with no plated leads keeps none.
        self._yard_refs = frozenset(fp.ref for fp in geometry.footprints if fp.silk or fp.fab) \
            if self.envelope == "physical" and self._leads else frozenset()
        # the script's clearance rules: a pair they match is judged by the last of them, not the netclass figure
        self.rules = ClearanceRules.of(geometry, rules)
        self._drawn_gap = max(component_spacing, self.silk_clearance)   # the furthest a silk, mask or body check reaches
        if self.envelope != "courtyard" and self._gap < max(component_spacing, self.silk_clearance):
            raise ValueError("[place] conflict_gap %.2f is less than the %.2f mm the %s envelope needs a check to reach"
                             % (self._gap, max(component_spacing, self.silk_clearance), self.envelope))
        if self._gap < max(geometry.hole_to_hole, geometry.hole_clearance):
            raise ValueError("[place] conflict_gap %.2f is less than the board's hole rules (%.2f hole to hole, %.2f "
                             "hole clearance) need a check to reach" % (self._gap, geometry.hole_to_hole,
                                                                         geometry.hole_clearance))
        if self._gap < self.rules.largest():
            raise ValueError("[place] conflict_gap %.2f is less than the %.2f mm a clearance rule asks of copper, "
                             "which a check must reach" % (self._gap, self.rules.largest()))
        self._copper_reach = max(self._gap, 1.0)        # how far from a box another's copper is looked for
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
        self._pad_location_cache: dict[tuple, Location] = {}   # (ref, number[, land]) -> Location, until a commit
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
        # Carried vias that gave way (giveway.py): what each did, by its id, and which items it
        # gave way to; each item a via was taken from, as it stood before, to put back when it is
        # placed again (a part's ItemGeometry, a cell's own copper).
        self.given_way: dict = {}
        self.needs: dict = {}               # frozenset of an item's owners -> the if-needed fab option that would have cleared its last refused spot
        self._given_by: dict = {}
        self._pristine: dict = {}
        self._pristine_copper: dict = {}
        for fp in geometry.footprints:
            self._register(fp)
        carried = _cell_vias(geometry)
        for c in geometry.copper:
            if c.kind == "pad":
                continue          # pads travel with their footprint
            if c.kind == "zone":
                continue          # a fill pulls back round whatever is placed; it never blocks anything
            faces = frozenset(l.face for l in c.layers if l.face is not None)
            # a via of fewer layers than the board's (a fragment built with spans) is copper and a hole there alone
            span = c.layers if c.kind == "via" and c.layers < frozenset(geometry.layers) else frozenset()
            if c.kind == "via" and not span:
                faces = _BOTH
            circle = ()
            if c.kind == "via" and c.width_mm:
                at = Location(*c.anchors[0]) if c.anchors else c.box.center
                circle = (at.x, at.y, c.width_mm / 2.0)
            tag, points = carried.get(id(c), ("", ()))
            for poly in c.outlines:
                self.copper.append(Shape(c.owner or "", "through" if c.kind == "via" else "copper",
                                         faces, c.layers, c.net, poly, Box.of_points(poly), circle=circle,
                                         carried=tag, points=points))
            if c.kind == "via" and c.drill_mm:
                at = Location(*c.anchors[0]) if c.anchors else c.box.center
                hole = hole_shape(c.owner or "", at, c.drill_mm, c.net, layers=span)
                self.copper.append(dataclasses.replace(hole, carried=tag, points=points) if tag else hole)
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
                         tuple(_fp_shapes(fp, self.envelope, self.settings.place_courtyard_polygon_share)),
                         fp.body_box, frozenset(p.net for p in fp.pads),
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
        self.__dict__.pop("_placed_groups", None)
        self.__dict__.pop("_placed_groups_owners", None)

    def _changed(self) -> None:
        """Items or copper changed outside a commit (a via gave way): drop
        what was worked out from them."""
        self._cells.clear()
        self._pad_location_cache.clear()
        self._invalidate_native()

    def geometry_of(self, ref: str) -> ItemGeometry:
        """A placed part's geometry as it was drawn: before any via it
        carries gave way."""
        return self._pristine.get(ref) or self.items[ref]

    def _geometry(self, item) -> ItemGeometry:
        if isinstance(item, Footprint):
            return self._pristine.get(item.ref) or self.items.get(item.ref) or self._register(item)
        if isinstance(item, CellGeom):
            if item.name in self._cells:
                return self._cells[item.name]
            own = self._pristine_copper.get(item.name)
            if own is None:
                own = [c for c in self.copper if c.owner == item.name]
            self._cells[item.name] = self.cell_geometry(item, {fp.ref: self.geometry_of(fp.ref) for fp in item.members},
                                                        own)
            return self._cells[item.name]
        if isinstance(item, WithoutCarried):
            return self._without_carried(item.item)
        raise TypeError("cannot place a %s" % type(item).__name__)

    def _without_carried(self, item) -> ItemGeometry:
        """The item's geometry less its carried vias: what the search judges
        natively before the vias give way (giveway.py)."""
        geom = self._geometry(item)
        cache = self.__dict__.setdefault("_without_cache", {})
        hit = cache.get(id(item))
        if hit is not None and hit[0] is geom:
            return hit[1]
        shapes = tuple(s for s in geom.shapes if not s.carried)
        parts = geom.parts
        if geom.part_refs:
            n = len(geom.part_refs)
            name = next(o for o in geom.owners if o not in geom.part_refs and o not in self._footprint_refs)
            parts = tuple(geom.parts[:n]) + tuple(s.box for s in shapes if s.owner == name)
        less = dataclasses.replace(geom, shapes=shapes, parts=parts)
        cache[id(item)] = (geom, less)
        return less

    def carries(self, item) -> bool:
        """Whether the item has a carried via that may give way."""
        return any(s.carried for s in self._geometry(item).shapes)

    def placed_groups(self) -> dict:
        """{id: giveway.Group} of every carried via on the board, where it
        stands: the parts' and the placed cells' (a pending item's are
        nowhere)."""
        hit = self.__dict__.get("_placed_groups")
        if hit is None:
            from .giveway import groups
            shapes = [s for owner, g in self.items.items() if owner not in self.pending for s in g.shapes if s.carried]
            shapes += [c for c in self.copper if c.carried and c.owner not in self.pending]
            hit = groups(self, shapes)
            self.__dict__["_placed_groups"] = hit
        return hit

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
        """The layers a cell's own copper stands on once the cell is flipped:
        F and B swap, and inner copper keeps its layer, so a module keeps the
        layer roles it was laid out for. This diverges from KiCad's own flip,
        which mirrors inner layers through the stack; the writer puts them
        back."""
        return frozenset(l.other_face if l in (CopperLayer.F, CopperLayer.B) else l for l in layers)

    @property
    def _all_layers(self) -> frozenset[CopperLayer]:
        return frozenset(self.geometry.layers)

    def _mirror_layers(self, layers: frozenset[CopperLayer]) -> frozenset[CopperLayer]:
        """KiCad's own flip: F and B swap, and the board's inner layers mirror
        through the stack (In1 and the last inner layer swap). A footprint's
        copper flips so, being one part drawn for a face. A layer the board
        lacks stays as it is."""
        mirror = self.__dict__.get("_inner_mirror")
        if mirror is None:
            inner = sorted((l for l in self.geometry.layers if l.face is None), key=stackup_order)
            mirror = self._inner_mirror = dict(zip(inner, reversed(inner)))
        return frozenset(l.other_face if l in (CopperLayer.F, CopperLayer.B) else mirror.get(l, l) for l in layers)

    def _flip_span(self, layers: frozenset[CopperLayer]) -> frozenset[CopperLayer]:
        """The layers a via spans once its item is flipped. A via that reaches
        a face mirrors through the stack, as KiCad flips it, so its face end
        moves with the face (F-In1 becomes B-In4). A buried via keeps its
        layers, as a cell's inner copper does."""
        if not any(l in (CopperLayer.F, CopperLayer.B) for l in layers):
            return layers
        return self._mirror_layers(layers)

    def _flip_faces(self, faces: frozenset[Face]) -> frozenset[Face]:
        return frozenset(Face.BACK if f is Face.FRONT else Face.FRONT for f in faces)

    def candidate_shapes(self, item, placement: Placement) -> tuple[ItemGeometry, list[Shape]]:
        geom = self._geometry(item)
        return geom, self._moved(geom, geom.shapes, placement)

    def _moved(self, geom: ItemGeometry, shapes, placement: Placement) -> list[Shape]:
        """`shapes`, where the item stands now, moved as the item moves to `placement`."""
        t = self._transform(geom, placement)
        flip = placement.face != geom.reference.face
        out = []
        for s in shapes:
            poly = transform_polygon(s.poly, t)
            faces = self._flip_faces(s.faces) if (flip and len(s.faces) == 1) else s.faces
            layers = self._flipped_layers(s) if flip else s.layers
            if s.carried or s.given:
                out.append(Shape(s.owner, s.kind, faces, layers, s.net, poly, Box.of_points(poly), s.label,
                                 carried=s.carried, points=tuple(t.apply(p) for p in s.points), given=s.given,
                                 claims=s.claims))
            else:
                out.append(Shape(s.owner, s.kind, faces, layers, s.net, poly, Box.of_points(poly), s.label,
                                 claims=s.claims))
        return out

    def _flipped_layers(self, s: Shape) -> frozenset[CopperLayer]:
        """A shape's layers once its item is flipped: a footprint's mirror as
        KiCad flips them, a via that spans some layers by `_flip_span`, a
        cell's own copper by `_flip_layers`."""
        if self.geometry.has_footprint(s.owner):
            return self._mirror_layers(s.layers)
        if s.kind in ("through", "hole") and s.layers and not self._all_layers <= s.layers:
            return self._flip_span(s.layers)
        return self._flip_layers(s.layers)

    def _yard(self, ref: str) -> Shape:
        """A part's courtyard where it stands now, as the courtyard envelope
        would claim it (KiCad's polygon, or the box), as a `yard`: judged only
        against another part's plated lead."""
        g = self.items[ref]
        cache = self.__dict__.setdefault("_yard_cache", {})
        hit = cache.get(ref)
        if hit is not None and hit[0] == g.reference:
            return hit[1]
        fp = self.geometry.footprint(ref)
        ct = tuple(fp.courtyard_poly) if courtyard_drawn(fp, self.settings.place_courtyard_polygon_share) \
            else box_polygon(fp.courtyard_box)
        read = ItemGeometry(frozenset([ref]), Placement(fp.location, fp.rotation, fp.face), (), fp.body_box,
                            frozenset())
        yard = self._moved(read, (Shape(ref, "yard", frozenset([fp.face]), frozenset(), "", ct, Box.of_points(ct)),),
                           g.reference)[0]
        cache[ref] = (g.reference, yard)
        return yard

    def _yards_of(self, owners) -> list[Shape]:
        return [self._yard(o) for o in owners if o in self._yard_refs and o in self.items]

    @staticmethod
    def native_module():
        return _geometry_module._native

    def reference_pad_centres(self, item) -> dict:
        """{(refdes, pad number): centre} of the item's pads where its
        geometry stands: what `candidate_pad_locations` moves."""
        geom = self._geometry(item)
        boxes: dict = {}
        for s in geom.shapes:
            if s.kind in ("pad", "through"):
                boxes.setdefault((s.owner, s.label), []).append(s.box)
        return {k: Box.union(v).center for k, v in boxes.items()}

    def turn_transform(self, geom, rotation: float, face) -> tuple:
        """`_transform(geom, placement)` before its last step, the move to the
        placement's location: (a, b, c, d, tx, ty). The native scorer adds
        that step itself, as `Transform.then` does."""
        ref = geom.reference
        t = Transform.translate(-ref.location.x, -ref.location.y)
        flip = face != ref.face
        if flip:
            t = t.then(Transform.mirror_x(Location(0, 0)))
        turn = rotation + ref.rotation if flip else rotation - ref.rotation
        t = t.then(Transform.rotate(turn))
        return (t.a, t.b, t.c, t.d, t.tx, t.ty)

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

    def pad_location(self, ref: str, number: str, land: int | None = None) -> Location:
        """Where a pad is NOW (after every commit so far): its outline's box
        centre, or with `land` (0-based, in the footprint's order for that
        number) that one land's. Cached per (ref, number, land) until the
        next commit() - a cleanup pass asks this for every pin of a net to
        weigh one key's move, and only the moving key's own pins actually
        change between two such asks."""
        key = (ref, number) if land is None else (ref, number, land)
        hit = self._pad_location_cache.get(key)
        if hit is not None:
            return hit
        loc = Box.union([s.box for s in self.pad_shapes(ref, number, land)]).center
        self._pad_location_cache[key] = loc
        return loc

    def pad_shapes(self, ref: str, number: str, land: int | None = None) -> list:
        """The pad's shapes where it is NOW: every land's, or with `land`
        (0-based, in the footprint's order for that number) that one land's.
        A part's shapes keep the order _fp_shapes gave them, each land's
        outlines together, so a land is its run of them."""
        shapes = [s for s in self.items[ref].shapes if s.kind in ("pad", "through") and s.label == number]
        if not shapes:
            raise KeyError("%s has no pad %s" % (ref, number))
        if land is None:
            return shapes
        counts = [len(p.outlines) for p in self.geometry.footprint(ref).pads if p.number == number]
        if not 0 <= land < len(counts) or sum(counts) != len(shapes):
            raise KeyError("%s pad %s has no land %d" % (ref, number, land + 1))
        start = sum(counts[:land])
        return shapes[start:start + counts[land]]

    def pad_anchor(self, ref: str, number: str) -> Location:
        """Where the airwires to a pad end NOW: its anchor as read
        (`PadGeom.airwire_end`, KiCad's PAD::ShapePos) moved as the part has
        moved since. The outline's box centre carries the polygon's rounding,
        enough to make the airwires along a row of pads cross."""
        fp = self.geometry.footprint(ref)
        pad = next((p for p in fp.pads if p.number == number), None)
        if pad is None:
            return self.pad_location(ref, number)
        read = ItemGeometry(frozenset([ref]), Placement(fp.location, fp.rotation, fp.face), (), fp.body_box,
                            frozenset())
        return self._transform(read, self.items[ref].reference).apply_location(pad.airwire_end)

    def carry(self, ref: str, shapes) -> None:
        """Copper a part takes with it wherever it is placed: `shapes` in
        its current frame, moved and turned as its own are."""
        import dataclasses
        g = self.items[ref]
        self.items[ref] = dataclasses.replace(g, shapes=g.shapes + tuple(shapes))
        carried = self.__dict__.setdefault("_carried", {})
        for s in shapes:
            carried[s.owner] = ref                # a cell's commit hands them back to the part
        self._cells.clear()
        self._pad_location_cache.clear()
        self._invalidate_native()

    def add_copper(self, shapes) -> None:
        """Planned copper becomes an obstacle for everything placed after it."""
        self.copper.extend(shapes)
        self._invalidate_native()
        if self.__dict__.get("_escapes") is not None:
            self._escapes.add_copper(shapes)

    def remove_copper(self, shapes) -> None:
        """Planned copper that stood as an obstacle is taken back (a reservation the copper
        drawn in its place replaces)."""
        gone = {id(s) for s in shapes}
        self.copper = [c for c in self.copper if id(c) not in gone]
        self._invalidate_native()
        if self.__dict__.get("_escapes") is not None:
            self._escapes.remove_copper(shapes)

    def copper_conflicts(self, shape: Shape) -> list[str]:
        """Every pad or copper of another net within clearance of `shape`."""
        out = []
        for owner, g in self.items.items():
            if owner in self.pending:
                continue                        # not placed yet: its pads are nowhere
            for o in g.shapes:                  # its pads, and its own copper graphics (a net-tie's winding)
                if o.kind not in ("pad", "through", "copper") or not shape.box.overlaps(o.box, gap=self._copper_reach):
                    continue
                why = self._conflict(shape, o, None, exact=True)
                if why:
                    out.append(why)
        for o in self.copper:
            if o is shape or not shape.box.overlaps(o.box, gap=self._copper_reach):
                continue
            why = self._conflict(shape, o, None, exact=True)
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

    def blame_owner(self, o) -> str:
        """What a refusal's tally names a blocking shape by: its owner, and for
        copper its net too - "cell logic's U3 GND", or "via GND" for a via no
        part owns - so a count of copper refusals says whose copper it was. An
        escape's lane is "the escape lane of U1 pin 53", and a pour "pour NET"."""
        if o.lane:
            return o.lane
        if o.kind not in ("pad", "through", "copper"):
            return self.who(o.owner)
        base = self.who(o.owner) if o.owner else (
            "via" if o.kind == "through" else "track" if o.ends else "pour")
        return "%s %s" % (base, o.net) if o.net else base

    def who(self, owner: str) -> str:
        """A refdes as a finding names it: with its cell when it has one."""
        if self.geometry.has_footprint(owner):
            cell = self.geometry.footprint(owner).cell
            if cell:
                return "cell %s's %s" % (cell, owner)
        return owner

    # ------------------------------------------------------------ mutation
    def reserve(self, region, why: str, allow=(), layer: CopperLayer | None = None, owners=(),
                source: str = "", admitted=None, copper: bool = True, barred=()):
        """Keep a region clear. `region` is a Box or a polygon. `source` names
        what put it there, so committing that thing again replaces its own
        regions instead of leaving the old ones behind."""
        poly = box_polygon(region) if isinstance(region, Box) else tuple(tuple(p) for p in region)
        self.reservations.append(Reservation(poly, why, frozenset(str(n) for n in allow),
                                             layer, frozenset(str(o) for o in owners), source,
                                             None if admitted is None else frozenset(admitted), copper,
                                             frozenset(barred)))

    def _parts_of(self, geom) -> set:
        """The parts an item is: its own refdes, or a cell's members'."""
        return {o for o in geom.owners if o in self._footprint_refs}

    def let_in(self, r: Reservation, geom) -> bool:
        """Whether a reservation lets the whole item in: a part named, or -
        in a height-limited region - short enough; a cell, when every member
        is (see `judged`). An allowed net lets copper through, not the parts
        that carry it."""
        if geom.part_refs:
            return all(self._member_let_in(r, ref) for ref in geom.part_refs)
        if geom.owners & r.owners:
            return True
        return r.admitted is not None and bool(self._parts_of(geom)) and self._parts_of(geom) <= r.admitted

    def _member_let_in(self, r: Reservation, ref: str) -> bool:
        """A cell's member, as a part of its own: named, or short enough."""
        return ref in r.owners or (r.admitted is not None and ref in r.admitted)

    def judged(self, r: Reservation, geom) -> list:
        """Which of a cell's `parts` a reservation judges: each member not let
        in by its own name or height, and the cell's own copper, which
        has no height (a height-limited region leaves it be), is let
        through by its own net, and is not judged by a region that keeps
        out parts only."""
        n = len(geom.part_refs)
        own = [s for s in geom.shapes if s.owner in geom.owners and s.owner not in geom.part_refs]
        out = [k for k in range(n) if not self._member_let_in(r, geom.part_refs[k])]
        if r.admitted is None and r.copper:
            out += [n + j for j, s in enumerate(own[:len(geom.parts) - n]) if not (s.net and s.net in r.allow)]
        return out

    def reservation_hit(self, r: Reservation, geom, k: int | None) -> tuple:
        """(the sentence, the blocker's owner) for a reservation refusing an
        item: `k` the cell's part it refuses (a member, or past them its own
        copper), None for an item with no parts. Each member is its own
        blocker, so a scan counts which of them was in the way."""
        if k is None:
            return self.refusal(r, geom), r.why
        if k >= len(geom.part_refs):
            return "its own copper sits in the reservation for %s" % r.why, "its own copper in %s" % r.why
        member = geom.part_refs[k]
        return self.refusal(r, geom, member), "%s in %s" % (member, r.why)

    def refusal(self, r: Reservation, geom, member: str | None = None) -> str:
        """The sentence for an item a reservation keeps out; in a height-
        limited region it names each part that is too tall or has no height.
        `member`: the cell's member that is refused, named."""
        from .board_geometry import part_height
        if member is not None:
            why = "its member %s sits in the reservation for %s" % (member, r.why)
            if member in r.barred:
                return why + ": %s is barred" % member
            if r.admitted is None or member in r.admitted:
                return why
            h = part_height(self.geometry.footprint(member))
            return why + (": %s has no Pm.Height" % member if h is None else ": %s is %g mm" % (member, h))
        why = "sits in the reservation for %s" % r.why
        if r.admitted is None:
            return why
        said = []
        for ref in sorted(self._parts_of(geom) - r.admitted):
            if ref in r.barred:
                said.append("%s is barred" % ref)
                continue
            h = part_height(self.geometry.footprint(ref))
            said.append("%s has no Pm.Height" % ref if h is None else "%s is %g mm" % (ref, h))
        return why + (": " + ", ".join(said) if said else "")

    def commit(self, item, placement: Placement):
        """Record that `item` now sits at `placement`; later checks see it there."""
        owners = self._geometry(item).owners
        self._commit(item, placement)
        if self.__dict__.get("_ratsnest") is not None:
            self._ratsnest_refresh(owners)
        if self.__dict__.get("_escapes") is not None:
            self._escapes.refresh(owners)

    def lift(self, refs) -> None:
        """Take placed items off the board for a moment: they are no obstacle,
        and the ratsnest and the escapes forget their pads, until `unlift` or
        a commit puts them back."""
        refs = set(refs)
        self.pending |= refs
        if self.__dict__.get("_ratsnest") is not None:
            self._ratsnest_refresh(refs)
        if self.__dict__.get("_escapes") is not None:
            self._escapes.refresh(refs)

    def unlift(self, refs) -> None:
        refs = set(refs)
        self.pending -= refs
        if self.__dict__.get("_ratsnest") is not None:
            self._ratsnest_refresh(refs)
        if self.__dict__.get("_escapes") is not None:
            self._escapes.refresh(refs)

    def escapes(self):
        """The corridors out of every placed pad (escapes.py), kept as items commit."""
        esc = self.__dict__.get("_escapes")
        if esc is None:
            from .escapes import Escapes
            esc = Escapes(self)
            self.__dict__["_escapes"] = esc
        return esc

    # ------------------------------------------------------------ the ratsnest
    quiet_nets: frozenset = frozenset()     # plane and free nets: their crossings weigh score.crossing_plane
    plane_nets: frozenset = frozenset()     # nets the board declares a plane (a pour, a finger) for: their carried vias are drops

    def ratsnest(self):
        """placemat's ratsnest (ratsnest.py) of every item placed so far, kept
        as items commit: what a candidate's crossings are counted against.
        A quiet net (a plane's, a free net's) weighs `score.crossing_plane`."""
        rn = self.__dict__.get("_ratsnest")
        if rn is None:
            from .pairs import board_pairs
            from .ratsnest import Ratsnest
            weights = {n: self.settings.score_crossing_plane for n in self.quiet_nets}
            # a pair crossing itself weighs score.pair_crossing; the search
            # prices the ratsnest's weighted count at score.crossing
            partners = {n: m for n, m in board_pairs(self.geometry.netclasses).items()
                        if n not in self.quiet_nets and m not in self.quiet_nets}
            s = self.settings
            pair_weight = s.score_pair_crossing / s.score_crossing if s.score_crossing > 0 else 1.0
            native = _geometry_module._native
            mirror = native.NativeRatsnest(weights) if native is not None and hasattr(native, "NativeRatsnest") else None
            if mirror is not None and partners and hasattr(mirror, "set_partners"):
                mirror.set_partners(sorted(partners.items()), pair_weight)
            rn = Ratsnest(weights, mirror=mirror, partners=partners, pair_weight=pair_weight)
            self.__dict__["_ratsnest"] = rn
            self.__dict__["_rn_anchors"] = {}
            self._ratsnest_refresh(set(self.items))
        return rn

    def _ratsnest_refresh(self, refs) -> None:
        """Take `refs`' pads out of the ratsnest and put back those placed now."""
        from .ratsnest import Anchor
        anchors = self.__dict__["_rn_anchors"]
        touched = set()
        for net, pads in anchors.items():
            for key in [k for k in pads if k[0] in refs]:
                del pads[key]
                touched.add(net)
        for ref in refs:
            g = self.items.get(ref)
            if g is None or ref in self.pending or not self.geometry.has_footprint(ref):
                continue
            for s in g.shapes:
                if s.kind in ("pad", "through") and s.net and s.owner == ref:
                    a = self.pad_anchor(ref, s.label)
                    anchors.setdefault(s.net, {})[(ref, s.label)] = Anchor(ref, s.label, a.x, a.y)
                    touched.add(s.net)
        rn = self.__dict__["_ratsnest"]
        for net in touched:
            rn.set_net(net, sorted(anchors.get(net, {}).values(), key=lambda a: (a.ref, a.number)))

    def candidate_anchors(self, item, placement: Placement) -> list:
        """(net, x, y) of each of the item's pads at a candidate placement,
        at their airwire anchors: turned and faced once per rotation and face,
        then shifted."""
        geom = self._geometry(item)
        cache = self.__dict__.setdefault("_anchor_cache", {})
        key = (id(geom), placement.rotation, placement.face)
        hit = cache.get(key)
        if hit is None or hit[0] is not geom:
            t = self._transform(geom, Placement(Location(0.0, 0.0), placement.rotation, placement.face))
            seen, out = set(), []
            for s in geom.shapes:
                if s.kind in ("pad", "through") and s.net and (s.owner, s.label) not in seen \
                        and self.geometry.has_footprint(s.owner):
                    seen.add((s.owner, s.label))
                    a = t.apply_location(self.pad_anchor(s.owner, s.label))
                    out.append((s.net, a.x, a.y))
            hit = (geom, out)
            cache[key] = hit
        dx, dy = placement.location.x, placement.location.y
        return [(net, x + dx, y + dy) for net, x, y in hit[1]]

    def placed_geometries(self, item, placement: Placement) -> tuple[dict, list]:
        """What commit() records for `item` at `placement`, without recording
        it: {refdes: ItemGeometry} for its footprints, and a cell's own
        copper there."""
        geom, shapes = self.candidate_shapes(item, placement)
        if isinstance(item, Footprint):
            return {item.ref: ItemGeometry(geom.owners, placement, tuple(shapes), self.body_box(item, placement),
                                           geom.nets, self.reach_box(item, placement))}, []
        t = self._transform(geom, placement)
        by_owner: dict[str, list[Shape]] = {}
        carried = self.__dict__.get("_carried", {})
        for s in shapes:
            by_owner.setdefault(carried.get(s.owner, s.owner), []).append(s)
        out = {}
        for fp in item.members:
            m = self.items[fp.ref]
            # the member's placement is where its own shapes went: _transform from it must move them so.
            # A flip mirrors the member's turn with it: turned by the cell's, less its own.
            flip = placement.face != geom.reference.face
            turn = (placement.rotation + geom.reference.rotation - m.reference.rotation) % 360.0 if flip \
                else m.reference.rotation + (placement.rotation - geom.reference.rotation)
            new_ref = Placement(t.apply_location(m.reference.location), turn,
                                (Face.BACK if m.reference.face is Face.FRONT else Face.FRONT)
                                if flip else m.reference.face)
            out[fp.ref] = ItemGeometry(m.owners, new_ref, tuple(by_owner.get(fp.ref, ())),
                                       transform_box(m.body, t), m.nets, transform_box(m.reach or m.body, t))
        return out, by_owner.get(item.name, [])

    def cell_geometry(self, item, members: dict, own: list) -> ItemGeometry:
        """A cell's geometry from its members' ({refdes: ItemGeometry}) and
        its own copper, as _geometry builds it from what is committed."""
        shapes = tuple(s for fp in item.members for s in members[fp.ref].shapes) + tuple(own)
        mine = [s.box for s in shapes if s.owner == item.name]
        body = Box.union([members[fp.ref].body for fp in item.members] + mine)
        reach = Box.union([members[fp.ref].reach or members[fp.ref].body for fp in item.members] + mine)
        return ItemGeometry(frozenset(m for fp in item.members for m in members[fp.ref].owners) | {item.name},
                            Placement(body.center, 0.0, Face.FRONT), shapes, body,
                            frozenset(n for fp in item.members for n in members[fp.ref].nets), reach,
                            tuple(members[fp.ref].body for fp in item.members) + tuple(mine),
                            tuple(fp.ref for fp in item.members))

    def _commit(self, item, placement: Placement):
        from . import giveway
        name = item.name if isinstance(item, CellGeom) else item.ref
        self._put_back(item, name)
        geom = self._geometry(item)
        gave = None
        if giveway.enabled(self.settings) and (self.carries(item) or self.placed_groups()):
            gave = giveway.resolve(self, item, placement)
        placed, own = self.placed_geometries(item, placement)
        self._cells.clear()
        self._pad_location_cache.clear()
        self._invalidate_native()
        self.pending -= geom.owners
        self.items.update(placed)
        if isinstance(item, CellGeom):
            self._commit_cell(item, placement, geom, own)
        for ref in placed:
            self._pristine.pop(ref, None)
        if gave is not None and gave.why is None and gave.actions:
            giveway.apply(self, gave, name)

    def _put_back(self, item, name: str) -> None:
        """Before an item is placed again: its own carried vias as it drew
        them, and those of other items that gave way to it alone."""
        from . import giveway
        refs = [fp.ref for fp in item.members] if isinstance(item, CellGeom) else [item.ref]
        homes = set(refs) | ({item.name} if isinstance(item, CellGeom) else set())
        # the vias that share one of its own: it moves, so they go back as they were drawn
        mine = {g.id for g in self.placed_groups().values() if g.home in homes} | \
            {v for v, a in self.given_way.items() if a.home in homes}
        for via in [v for v, a in self.given_way.items() if a.kind == "share" and a.target in mine]:
            giveway.undo(self, via)
        for via in [v for v, a in self.given_way.items() if a.home in homes]:
            del self.given_way[via]
            self._given_by.pop(via, None)
        for ref in refs:
            if ref in self._pristine:
                self.items[ref] = self._pristine.pop(ref)
        if isinstance(item, CellGeom) and item.name in self._pristine_copper:
            self.copper = [c for c in self.copper if c.owner != item.name] + self._pristine_copper.pop(item.name)
        for via in [v for v, by in self._given_by.items() if set(by) == {name}]:
            giveway.undo(self, via)
        self._changed()

    def _commit_cell(self, item, placement: Placement, geom, own) -> None:
        t = self._transform(geom, placement)
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
    def obstacles(self, geom: ItemGeometry, region: Box | None = None, carried: bool = True) -> list:
        """Every shape not owned by `geom`, within `region` (plus the
        conflict gap) when one is given: gathered once for a whole scan.

        The native index attached as `idx._native` is NOT rebuilt from this
        region-filtered list: it is a per-skip-set entry cached on the
        Occupancy (`_native_obstacle_cache`, cleared on commit), covering
        every non-skipped shape on the board regardless of region - a scan,
        a cleanup hint and a freedom's several _slide() calls for the same
        item, between commits, share one native registration instead of
        rebuilding and re-marshalling it every call. See
        _native_obstacle_index and the Phase 3 spec note.

        `carried=False` leaves out the carried vias of the items already
        placed: what the search judges an item against before they give
        way to it (giveway.py)."""
        skip = geom.owners | self.pending
        out = self._obstacle_shapes(skip, carried)
        if region is not None:
            out = [o for o in out if o.box.overlaps(region, gap=self._gap)]
        idx = ShapeIndex(out)
        idx._native = self._native_obstacle_index(skip, carried)
        return idx

    def _obstacle_shapes(self, skip, carried: bool = True) -> list:
        out = [s for owner, g in self.items.items() if owner not in skip for s in g.shapes]
        out += [c for c in self.copper if c.owner not in skip]
        if not carried:
            out = [s for s in out if not s.carried]
        return out + self._yards_of(o for o in self.items if o not in skip)

    def _native_obstacle_index(self, skip: frozenset, carried: bool = True):
        """The cached (NativeObstacles, backing shape list) for this
        skip-set, building it - over every shape in self.items/self.copper
        not owned by `skip`, NOT region-filtered - on a cache miss. `None`
        when there is no native module (the pure-Python `near()` + per-shape
        loop in `legal()` is then what runs)."""
        native = _geometry_module._native
        if native is None:
            return None
        key = skip if carried else (skip, "without carried vias")
        hit = self._native_obstacle_cache.get(key)
        if hit is not None:
            return hit
        shapes = self._obstacle_shapes(skip, carried)
        index = native.NativeObstacles(
            [_to_native_shape(s, self._footprint_refs, self._leads, self._margins) for s in shapes],
            **self._native_conflict_kwargs())
        entry = (index, shapes)
        self._native_obstacle_cache[key] = entry
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
                        gap=self._gap, drawn_gap=self._drawn_gap,
                        hole_to_hole=self.geometry.hole_to_hole, hole_clearance=self.geometry.hole_clearance,
                        rules=self.rules.native())
            self.__dict__["_native_kwargs"] = cache
        return cache

    def _edge_or_reservation_conflict(self, geom: ItemGeometry, body: Box, placement: Placement,
                                      past_edge: bool, blame: list | None, by_corners: bool = False) -> str | None:
        """The two checks `legal()` runs before it ever looks at an
        obstacle: the board edge (and cutouts) and the reservations. Both
        produce a ready sentence cheaply (a box test, or a polymorphic
        `why_not` call), so unlike the near-obstacle search below there is
        nothing to gain from deferring them - `legal()` and `legal_bucket()`
        both call this and return its answer unchanged when it fires."""
        # A cell whose box fails is judged again by its members' boxes: the
        # box of an L-shaped cell has an empty corner that may sit in a
        # keepout or past a round board's rim.
        parts = None
        if self.edge_margin is not None and not past_edge:
            why = self._edge_why(body)
            if why and geom.parts:
                parts = self._shifted_parts(geom, placement)
                why = next((w for w in map(self._edge_why, parts) if w), None)
            elif why and by_corners and self.board_shape is not None and self._corners_inside(geom, placement):
                # a decided part turned off the axes: its box's corner passes a round rim, the part does not.
                # Only for a place the script decided: a scan judges by boxes, natively and in Python alike
                why = None
            if why:
                if blame is not None:
                    blame.append(Blocker("edge", "", frozenset()))
                return why
        faces = self.standing_faces(geom, placement.face)
        for r in self.reservations:
            if r.layer is not None and r.layer.face not in faces:
                continue                                   # reserved on the other face only
            if self.let_in(r, geom):
                continue                                   # named, carrying a net let through, or short enough
            # the box first because it is cheap, and the placer asks this tens of thousands of times
            if r.overlaps(body):
                hit = None
                if geom.parts:
                    parts = self._shifted_parts(geom, placement) if parts is None else parts
                    hit = next((k for k in self.judged(r, geom) if r.overlaps(parts[k])), None)
                    if hit is None:
                        continue
                why, owner = self.reservation_hit(r, geom, hit)
                if blame is not None:
                    blame.append(Blocker("reservation", owner, frozenset()))
                return why
        return None

    def standing_faces(self, geom: ItemGeometry, face) -> set:
        """The faces an item stands on, for a reservation that keeps parts
        out: its own, and the other when a plated lead or an unplated hole
        goes through to it. A via does not: a cell's own vias leave its parts
        on the face it is placed on."""
        through = any(s.kind == "npth" or (s.kind == "through" and (s.owner, s.label) in self._leads)
                      for s in geom.shapes)
        return {face} | ({Face.FRONT, Face.BACK} if through else set())

    def _edge_why(self, body: Box) -> str | None:
        """What the board's edge says of a body box, or None."""
        if self.board_shape is not None:
            why = self.board_shape.why_not(body, self.edge_margin)
            return ("body box %s is %s" % (_fmt(body), why)) if why else None
        if self.board_box is not None:
            inner = self.board_box.inflate(-self.edge_margin)
            if not inner.contains(body):
                return "body box %s crosses the board edge margin (%.2f mm)" % (_fmt(body), self.edge_margin)
            if self.board_cutouts:
                why = self.board_cutouts.why_not(body, self.edge_margin)
                if why:
                    return "body box %s is %s" % (_fmt(body), why)
        return None

    def origin_parts(self, geom: ItemGeometry, rotation: float, face) -> list:
        """A cell's member boxes (`parts`) turned and faced at the origin."""
        cache = self.__dict__.setdefault("_parts_cache", {})
        key = (id(geom), rotation, face)
        hit = cache.get(key)
        if hit is None or hit[0] is not geom:
            t = self._transform(geom, Placement(Location(0.0, 0.0), rotation, face))
            hit = (geom, [transform_box(b, t) for b in geom.parts])
            cache[key] = hit
        return hit[1]

    def _corners_inside(self, geom: ItemGeometry, placement: Placement) -> bool:
        """Every corner of every shape the part is made of - pads, body,
        courtyard, as the envelope claims them - inside the board's shape
        with the keep-in to spare. On a round board a convex shape whose
        corners are inside is inside."""
        t = self._transform(geom, placement)
        corners = [pt for s in geom.shapes if s.kind != "npth" for pt in transform_polygon(s.poly, t)]
        return bool(corners) and all(self.board_shape.why_not(Box(x, y, x, y), self.edge_margin) is None
                                     for x, y in corners)

    def _shifted_parts(self, geom: ItemGeometry, placement: Placement) -> list:
        dx, dy = placement.location.x, placement.location.y
        return [Box(_clean(b.left + dx), _clean(b.top + dy), _clean(b.right + dx), _clean(b.bottom + dy))
                for b in self.origin_parts(geom, placement.rotation, placement.face)]

    def legal(self, item, placement: Placement, clearance: float | None = None, others=None,
              past_edge: bool = False, blame: list | None = None, by_corners: bool = False,
              board: bool = True) -> str | None:
        """None when `item` may sit at `placement`, else one sentence saying
        what stops it. The first failure found is reported. `others` is a
        prefiltered obstacle list from `obstacles()`; without one every
        shape on the board is a candidate obstacle. `past_edge` allows a
        body over the edge margin: a connector face declared to overhang.
        `blame`, when a list is passed, collects a `Blocker` for the conflict
        found: the same refusal in parts rather than prose, so a scan can
        count who was in the way rather than only how often. `board=False`
        judges `others` alone: not the edge, not the reservations."""
        geom = self._geometry(item)
        body = self.shifted_body_box(item, placement)
        why = self._edge_or_reservation_conflict(geom, body, placement, past_edge, blame, by_corners) \
            if board else None
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
            origin_shapes = list(self._legal_origin_shapes(item, geom, placement))
            origin_handle = self._native_origin_shapes(item, geom, placement)
            hit = native_index.first_conflict_shifted(origin_handle, dx, dy, clearance)
            if hit is None:
                return None
            si, oi = hit
            o = native_shapes[oi]
            s = origin_shapes[si]
            moved = Shape(s.owner, s.kind, s.faces, s.layers, s.net,
                         tuple((x + dx, y + dy) for x, y in s.poly), s.box.moved(dx, dy), s.label, claims=s.claims)
            why = self._conflict(moved, o, clearance)
            if why is None:
                raise AssertionError(
                    "native found a conflict between a %s and a %s that _conflict disagrees with; "
                    "this is a native/Python mismatch, not a placement question" % (moved.kind, o.kind))
            if blame is not None:
                blame.append(Blocker(_blocker_kind(o.kind), self.blame_owner(o), frozenset(o.faces)))
            return why
        # What a conflict can reach from: the body, or in a drawn envelope every
        # shape the part claims - silk can stand well past the body.
        shapes = self._legal_origin_shapes(item, geom, placement)
        yards = [s.box.moved(dx, dy) for s in shapes if s.kind == "yard"]
        reach = Box.union([body, transform_box(self._extent(geom), self._transform(geom, placement))] + yards)
        near = others.near(reach, self._gap) if isinstance(others, ShapeIndex) else \
            [o for o in others if o.box.overlaps(reach, gap=self._gap)]
        if not near:
            return None
        # Each shape is turned and faced once per rotation and face, then
        # shifted; only a shape whose box reaches an obstacle is moved as a polygon.
        for s in shapes:
            sb = s.box.moved(dx, dy)
            close = [o for o in near if sb.overlaps(o.box, gap=self.gap_for(s))]
            if not close:
                continue
            moved = Shape(s.owner, s.kind, s.faces, s.layers, s.net,
                          tuple((x + dx, y + dy) for x, y in s.poly), sb, s.label, claims=s.claims)
            for o in close:
                why = self._conflict(moved, o, clearance)
                if why:
                    if blame is not None:
                        blame.append(Blocker(_blocker_kind(o.kind), self.blame_owner(o), frozenset(o.faces)))
                    return why
        return None

    def legal_giving_way(self, item, placement: Placement, clearance: float | None = None, others=None,
                         past_edge: bool = False, blame: list | None = None, by_corners: bool = False) -> tuple:
        """(why, resolution): `legal()`, except that where it refuses the
        item, the item less its carried vias is judged, and the vias - its
        own and those of items already placed - may give way (giveway.py).
        `resolution` is what they would do, None when nothing need; `why`
        is `legal()`'s sentence when the item less its vias is refused too,
        else why a via cannot give way."""
        from . import giveway
        why = self.legal(item, placement, clearance, others=others, past_edge=past_edge, blame=blame,
                         by_corners=by_corners)
        if why is None or not giveway.enabled(self.settings):
            return why, None
        geom = self._geometry(item)
        region = transform_box(self._extent(geom), self._transform(geom, placement)).inflate(
            giveway.reach(self.settings))
        if not giveway.near_carried(self, item, region):
            return why, None
        less = self.obstacles(geom, region, carried=False)
        if self.legal(WithoutCarried(item), placement, clearance, others=less, past_edge=past_edge,
                      by_corners=by_corners) is not None:
            return why, None
        res = giveway.resolve(self, item, placement, clearance, self.obstacles(geom, region))
        if blame is not None:
            del blame[:]
            if res.why is not None:
                blame.append(res.blocker)
        return (res.why, None) if res.why is not None else (None, res)

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
        origin_shapes = list(self._legal_origin_shapes(item, geom, placement))
        origin_handle = self._native_origin_shapes(item, geom, placement)
        hit = native_index.first_conflict_shifted(origin_handle, dx, dy, clearance)
        if hit is None:
            return None
        si, oi = hit
        o = native_shapes[oi]
        s = origin_shapes[si]
        moved = Shape(s.owner, s.kind, s.faces, s.layers, s.net,
                     tuple((x + dx, y + dy) for x, y in s.poly), s.box.moved(dx, dy), s.label, claims=s.claims)
        if blame is not None:
            blame.append(Blocker(_blocker_kind(o.kind), self.blame_owner(o), frozenset(o.faces)))

        def get_reason(moved=moved, o=o, clearance=clearance):
            why = self._conflict(moved, o, clearance)
            if why is None:
                raise AssertionError(
                    "native found a conflict between a %s and a %s that _conflict disagrees with; "
                    "this is a native/Python mismatch, not a placement question" % (moved.kind, o.kind))
            return why
        return self._native_bucket(moved, o), get_reason

    def native_sweeper(self, item, face, rots, others, clearance):
        """A whole sweep pass judged natively (placemat_native.sweep), or None
        when the pieces it needs are not there: the module, the obstacles'
        native index, the board's native mirror. The answers are the ones
        `legal_bucket` gives each candidate in turn - see NativeSweeper."""
        native = _geometry_module._native
        entry = getattr(others, "_native", None)
        if native is None or entry is None or not hasattr(native, "sweep"):
            return None
        board = native_board(self)
        if board is None:
            return None
        return NativeSweeper(self, item, face, rots, entry, board, clearance)

    def _native_bucket(self, s: Shape, o: Shape) -> str:
        """`_reason_key`'s answer for a near-obstacle conflict, from the
        pair's shape kinds alone - no sentence needed. Mirrors
        `_conflict`'s OWN dispatch order, because a pair's message depends
        on which branch fires, not just which kinds are present:
        `_conflict` checks "is either shape a drawn kind (silk/mask/body)"
        FIRST, before courtyard or npth - so a body-vs-npth pair (the one
        case that is both: `_drawn_conflict` recognises `{"body","npth"}`
        as its own pair, at gap 0) goes to `_drawn_conflict`, never to
        `_conflict`'s own npth-vs-copper branch. Next, two holes (plated or
        unplated) are the hole-to-hole rule, whose sentence says
        "hole-to-hole" and none of the words before it. A drawn-envelope message
        (silk/mask/body pairs, or a body against another part's pad) never
        contains any of `_reason_key`'s seven checked words - `_NAMES` maps
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
        refdes literally containing one of the seven checked words as a
        substring could in principle beat this - `_reason_key` itself is a
        substring match over arbitrary project names, not a property of the
        conflict kind alone - but that was already true of `_reason_key`
        before this method existed, and no fixture or real board comes
        close to it.)"""
        if s.kind == "yard" or o.kind == "yard":
            return "courtyard"
        if s.kind in _DRAWN or o.kind in _DRAWN:
            return self.who(s.owner).split(" ")[0]
        if s.kind in _HOLES and o.kind in _HOLES:
            return "hole-to-hole"
        if s.kind == "courtyard" or o.kind == "courtyard":
            return "courtyard"
        if (s.kind in _COPPERISH and o.kind in _COPPERISH) or s.kind == "npth" or o.kind == "npth":
            return "copper"
        return self.who(s.owner).split(" ")[0]

    def _lead_sentence(self, court: Shape, lead: Shape) -> str:
        return "%s courtyard sits over the through-hole lead of %s%s%s" % (
            self.who(court.owner), self.who(lead.owner), " pad %s" % lead.label if lead.label else "",
            "" if lead.net else " (a plated pad with no net: often a footprint defect)")

    def _hole_name(self, s: Shape) -> str:
        """A hole as a refusal names it: a part's, a cell's via, or a via."""
        if s.kind == "hole" and s.owner in self.geometry.cells:
            return "cell %s's via" % s.owner
        if s.owner.startswith("via at "):
            return "the via %s" % s.owner[len("via "):]
        if not s.owner:
            return "a via"
        return "%s's hole" % self.who(s.owner)

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

    def _legal_origin_shapes(self, item, geom: ItemGeometry, placement: Placement) -> list:
        """`_origin_shapes` and the item's own yards, turned and faced the
        same way: what a legality check judges."""
        own = self._yards_of(geom.owners)
        if not own:
            return self._origin_shapes(item, geom, placement)
        cache = self.__dict__.setdefault("_legal_shape_cache", {})
        key = (id(geom), placement.rotation, placement.face)
        hit = cache.get(key)
        if hit is None or hit[0] is not geom:
            at = Placement(Location(0.0, 0.0), placement.rotation, placement.face)
            hit = (geom, list(self._origin_shapes(item, geom, placement)) + self._moved(geom, own, at))
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
        origin_shapes = self._legal_origin_shapes(item, geom, placement)
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

    def origin_body_box(self, item, rotation: float, face) -> Box:
        """body_box() turned and faced at the origin, unrounded: what
        `shifted_body_box` shifts."""
        cache = self.__dict__.setdefault("_body_cache", {})
        geom = self._geometry(item)
        key = (id(geom), rotation, face)
        hit = cache.get(key)
        if hit is None or hit[0] is not geom:
            hit = (geom, self.body_box(item, Placement(Location(0.0, 0.0), rotation, face)))
            cache[key] = hit
        return hit[1]

    def shifted_body_box(self, item, placement: Placement) -> Box:
        """body_box() at `placement`, from the body turned at the origin."""
        b = self.origin_body_box(item, placement.rotation, placement.face)
        dx, dy = placement.location.x, placement.location.y
        return Box(_clean(b.left + dx), _clean(b.top + dy), _clean(b.right + dx), _clean(b.bottom + dy))

    def shifted_shapes(self, item, placement: Placement) -> list:
        """The item's shapes at `placement`, from the turned shapes at the origin."""
        dx, dy = placement.location.x, placement.location.y
        return [Shape(s.owner, s.kind, s.faces, s.layers, s.net, tuple((x + dx, y + dy) for x, y in s.poly),
                      s.box.moved(dx, dy), s.label, claims=s.claims)
                for s in self._origin_shapes(item, self._geometry(item), placement)]

    def shifted_yards(self, item, placement: Placement) -> list:
        """The item's yards at `placement` (none outside the physical envelope,
        or on a board without plated leads)."""
        dx, dy = placement.location.x, placement.location.y
        return [Shape(s.owner, s.kind, s.faces, s.layers, s.net, tuple((x + dx, y + dy) for x, y in s.poly),
                      s.box.moved(dx, dy), s.label)
                for s in self._legal_origin_shapes(item, self._geometry(item), placement) if s.kind == "yard"]

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

    def pair_clearance(self, net_a: str, net_b: str, owner_a: str = "", owner_b: str = ""):
        """(clearance, rule) between copper of two nets: the last of the script's clearance rules that
        matches the pair (`owner_*` for a rule within a cell), else the netclass pair's figure, or the
        board default where either has no net; `rule` is the rule that decided, or None."""
        rule = self.rules.match(net_a, net_b, owner_a, owner_b) if self.rules else None
        if rule is not None:
            return rule.min_mm, rule
        nets = self.geometry.nets
        if net_a in nets and net_b in nets:
            return self.geometry.clearance(net_a, net_b), None
        return self.geometry.default_clearance, None

    def _conflict(self, s: Shape, o: Shape, clearance: float | None, exact: bool = False,
                  say: bool = True) -> str | None:
        """The DRC rules, in occupancy terms. A via under a body is legal to
        DRC and is only refused when `vias_block_courtyards` is set (a house
        rule for boards that pair through-feature cells with via-free parts).
        `say=False` answers a copper or hole conflict with its kind alone,
        not the sentence: for a search that only asks whether."""
        ks, ko = s.kind, o.kind
        if ks == "yard" or ko == "yard":
            yard, other = (s, o) if ks == "yard" else (o, s)
            if other.kind == "through" and other.owner != yard.owner and (other.owner, other.label) in self._leads \
                    and polys_overlap(yard.poly, other.poly):
                return self._lead_sentence(yard, other)
            return None
        claim = s if (ks == "courtyard" and s.claims) else o if (ko == "courtyard" and o.claims) else None
        if claim is not None:
            # a courtyard claimed as the part itself keeps another part's body and pads out (not its silk: ink may lie over it)
            other = o if claim is s else s
            if other.kind in ("body", "pad", "through"):
                if other.owner != claim.owner and other.owner in self._footprint_refs \
                        and claim.faces & other.faces and polys_overlap(claim.poly, other.poly):
                    return "%s %s sits in %s courtyard, which it claims as it draws nothing else" % (
                        self.who(other.owner), _NAMES.get(other.kind, other.kind), self.who(claim.owner))
                if other.kind != "through":
                    return None                 # a through pad clear of it still meets the lead and via rules
        if ks in _DRAWN or ko in _DRAWN:
            return self._drawn_conflict(s, o)
        if ks in _HOLES and ko in _HOLES:
            # hole to hole is net-blind: two holes of one net drilled too close still break the bit.
            # Two via holes that span no common layer (a micro or blind via each side) never meet:
            # KiCad's DRC checks none between them.
            if s.layers and o.layers and not (s.layers & o.layers):
                return None
            need = self.geometry.hole_to_hole
            if _box_gap(s.box, o.box) >= need + _HOLE_SLACK * (s.box.width + o.box.width) - 1e-9:
                return None
            (cs, rs), (co, ro) = _circle(s), _circle(o)
            gap = math.dist(cs, co) - rs - ro
            if gap < need - 1e-9:
                if not say:
                    return "hole-to-hole"
                return "%s %.2f mm from %s (hole-to-hole needs %.2f)" % (
                    self._hole_name(s), max(gap, 0.0), self._hole_name(o), need)
            return None
        if ks == "hole" or ko == "hole":
            return None                     # its pad or via ring answers for everything else
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
                    return self._lead_sentence(court, other)
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
            clr, rule = (clearance, None) if clearance is not None else self.pair_clearance(s.net, o.net, s.owner, o.owner)
            need = "%.2f%s" % (clr, ", rule: %s" % rule.why if rule is not None else "")
            # Two boxes this far apart hold two polygons at least as far
            # apart, so the walk round both outlines is only worth its cost
            # when the boxes themselves are close enough to fail.
            if _box_gap(s.box, o.box) >= clr - 1e-9:
                return None
            # a finding (exact) measures a via as its circle; placement keeps the polygons the
            # native judge reads, so the two agree on what is legal
            gap = _copper_gap(s, o) if exact else poly_distance(s.poly, o.poly)
            if gap < clr - 1e-9 and self._net_tie_exclusion(s, o):
                return None
            if gap < clr - 1e-9 and not say:
                return "copper"
            if gap < clr - 1e-9:
                if s.kind == "through" and not self.geometry.has_footprint(s.owner):
                    c = s.box.center            # a via: the script's, planned, or one a part carries at its pad
                    return "via %s at (%.2f, %.2f)%s is %.2f mm from %s copper on %s (needs %s)" % (
                        s.net or "-", c.x, c.y, " (%s)" % s.owner[len("via "):] if s.owner.startswith("via at ") else "",
                        gap, o.net or self.who(o.owner), self._layers_text(common), need)
                if s.kind == "copper" and s.ends:      # a declared track: name the segment, not its owner
                    who = "track %s (%.2f, %.2f)-(%.2f, %.2f)" % (
                        s.net or "-", s.ends[0][0], s.ends[0][1], s.ends[1][0], s.ends[1][1])
                else:
                    what = "pad" if s.kind in ("pad", "through") else "copper"
                    who = "%s %s %s" % (self.who(s.owner), what, s.net or "-")
                return "%s is %.2f mm from %s copper on %s (needs %s)" % (
                    who, gap, o.net or self.who(o.owner), self._layers_text(common), need)
            return None
        if (ks == "npth" and ko in _COPPERISH) or (ko == "npth" and ks in _COPPERISH):
            hole, metal = (s, o) if ks == "npth" else (o, s)
            if polys_overlap(hole.poly, metal.poly):
                return "%s hole cuts %s copper" % (self.who(hole.owner), metal.net or self.who(metal.owner))
            need = self.geometry.hole_clearance
            if need > 0 and _box_gap(hole.box, metal.box) < need + _HOLE_SLACK * hole.box.width - 1e-9:
                gap = _circle_distance(hole, metal.poly)
                if gap < need - 1e-9:
                    return "%s copper %.2f mm from %s's unplated hole (needs %.2f)" % (
                        metal.net or self.who(metal.owner), gap, self.who(hole.owner), need)
        return None

    def _layers_text(self, layers) -> str:
        """The layers two pieces of copper share, as the board has them, in
        stackup order: a via is copper on every layer placemat knows, and a
        board has only its own."""
        own = [l for l in self.geometry.layers if l in layers]
        return "/".join(l.value for l in (own or sorted(layers, key=lambda l: l.value)))

    def _net_tie_exclusion(self, s, o) -> bool:
        """KiCad's DRC_ENGINE::IsNetTieExclusion, either way round: copper of
        a net-tie footprint colliding with another item of the net of one of
        its net-tie pads is allowed where they collide inside that pad - a
        track entering the pad a winding leaves."""
        for item, other in ((s, o), (o, s)):
            if not item.net or item.owner == other.owner or not self.geometry.has_footprint(other.owner):
                continue
            fp = self.geometry.footprint(other.owner)
            if not fp.net_tie_pads or other.owner not in self.items:
                continue
            pads = [sh.poly for sh in self.items[other.owner].shapes
                    if sh.kind in ("pad", "through") and sh.label in fp.net_tie_pads and sh.net == item.net
                    and sh.layers & item.layers & other.layers]
            if not pads:
                continue
            ends = getattr(item, "ends", None)
            # a track meets the tie where KiCad's segment collision puts it (DRC test of a track against an
            # item: the track's SHAPE_SEGMENT collides with the other's polygon); other copper where their
            # outlines meet
            at = _kicad_segment_location(ends, other.poly) if ends and len(ends) == 2 else \
                _contact_point(item.poly, other.poly)
            if any(point_in_polygon(at, pad) or _point_poly_distance(at, pad) <= _NET_TIE_EPSILON for pad in pads):
                return True
        return False


# KiCad's DRC epsilon (BOARD_DESIGN_SETTINGS::GetDRCEpsilon, 0.0005 mm by default): how far a
# collision may lie outside a net-tie pad and still be inside it
_NET_TIE_EPSILON = 0.0005


def _kicad_segment_location(ends, poly) -> tuple:
    """Where KiCad's DRC places a track's collision with a closed polygon:
    SHAPE_LINE_CHAIN_BASE::Collide(SEG) (libs/kimath/src/geometry/
    shape_line_chain.cpp, KiCad 10.0), on the track's centreline `ends`. Its
    start, when the polygon holds it (PointInside's crossing rule, so a point
    on a right-hand edge is outside); else the nearest point of the first of
    the polygon's edges nearest the centreline (SEG::NearestPoint). Worked in
    whole nanometres, as KiCad does."""
    nm = lambda p: (int(round(p[0] * 1e6)), int(round(p[1] * 1e6)))
    a, b = nm(ends[0]), nm(ends[1])
    pts = [nm(p) for p in poly]
    if _k_point_inside(a, pts):
        at = a
    else:
        best, at = None, a
        for i in range(len(pts)):
            edge = (pts[i], pts[(i + 1) % len(pts)])
            d2 = _k_seg_sq_distance(edge, (a, b))
            if best is None or d2 < best:
                at, best = _k_seg_nearest_to_seg(edge, (a, b)), d2
                if d2 == 0:
                    break
    return (at[0] / 1e6, at[1] / 1e6)


def _k_rescale(a: int, b: int, c: int) -> int:
    """KiCad's rescale(): a * b / c, rounded half away from zero."""
    q = a * b
    r = (abs(q) + abs(c) // 2) // abs(c)
    return r if (q >= 0) == (c > 0) else -r


def _k_point_inside(p, pts) -> bool:
    """SHAPE_LINE_CHAIN_BASE::PointInside at an accuracy of 0."""
    inside = False
    n = len(pts)
    for i in range(n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        dy = p2[1] - p1[1]
        if dy == 0:
            continue
        d = _k_rescale(p2[0] - p1[0], p[1] - p1[1], dy)
        if ((p1[1] >= p[1]) != (p2[1] >= p[1])) and (p[0] - p1[0] < d):
            inside = not inside
    return inside


def _k_nearest_to_point(seg, p):
    """SEG::NearestPoint(VECTOR2I)."""
    (ax, ay), (bx, by) = seg
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return (ax, ay)
    t = dx * (p[0] - ax) + dy * (p[1] - ay)
    if t < 0:
        return (ax, ay)
    if t > l2:
        return (bx, by)
    return (ax + _k_rescale(t, dx, l2), ay + _k_rescale(t, dy, l2))


def _k_intersect(s1, s2):
    """SEG::Intersect(aSeg): the point two segments share, or None; for
    collinear ones the middle of their overlap."""
    (ax, ay), (bx, by) = s1
    (cx, cy), (ex, ey) = s2
    if max(ax, bx) < min(cx, ex) or max(cx, ex) < min(ax, bx) or \
            max(ay, by) < min(cy, ey) or max(cy, ey) < min(ay, by):
        return None
    d1x, d1y = bx - ax, by - ay
    d2x, d2y = ex - cx, ey - cy
    ox, oy = cx - ax, cy - ay
    det = d2x * d1y - d2y * d1x
    if det == 0:
        if d1x * oy - d1y * ox != 0:
            return None
        use_x = abs(d1x) >= abs(d1y)
        s1a, s1b, s2a, s2b, o1a, o1b = (ax, bx, cx, ex, ay, by) if use_x else (ay, by, cy, ey, ax, bx)
        lo, hi = max(min(s1a, s1b), min(s2a, s2b)), min(max(s1a, s1b), max(s2a, s2b))
        if hi < lo:
            return None
        proj = int((lo + hi) / 2)                  # C++ integer division truncates toward zero
        other = o1a + _k_rescale(proj - s1a, o1b - o1a, s1b - s1a) if s1b != s1a else o1a
        return (proj, other) if use_x else (other, proj)
    p2 = d2x * oy - d2y * ox
    p1 = d1x * oy - d1y * ox
    if det > 0:
        if p1 < 0 or p1 > det or p2 < 0 or p2 > det:
            return None
    elif p1 > 0 or p1 < det or p2 > 0 or p2 < det:
        return None
    return (cx + _k_rescale(p1, d2x, det), cy + _k_rescale(p1, d2y, det))


def _k_sq(p, q) -> int:
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2


def _k_seg_sq_distance(s1, s2) -> int:
    """SEG::SquaredDistance(SEG)."""
    if s1[0] == s1[1]:
        return _k_sq(_k_nearest_to_point(s2, s1[0]), s1[0])
    if s2[0] == s2[1]:
        return _k_sq(_k_nearest_to_point(s1, s2[0]), s2[0])
    if _k_intersect(s1, s2) is not None:
        return 0
    return min(_k_sq(_k_nearest_to_point(s2, s1[0]), s1[0]), _k_sq(_k_nearest_to_point(s2, s1[1]), s1[1]),
               _k_sq(_k_nearest_to_point(s1, s2[0]), s2[0]), _k_sq(_k_nearest_to_point(s1, s2[1]), s2[1]))


def _k_seg_nearest_to_seg(s1, s2):
    """SEG::NearestPoint(SEG): the point of `s1` nearest `s2`."""
    hit = _k_intersect(s1, s2)
    if hit is not None:
        return hit
    outs = [s1[0], s1[1], _k_nearest_to_point(s1, s2[0]), _k_nearest_to_point(s1, s2[1])]
    dists = [_k_sq(_k_nearest_to_point(s2, s1[0]), s1[0]), _k_sq(_k_nearest_to_point(s2, s1[1]), s1[1]),
             _k_sq(outs[2], s2[0]), _k_sq(outs[3], s2[1])]
    i = min(range(4), key=lambda k: (dists[k], k))
    return outs[i]


def _point_poly_distance(p, poly) -> float:
    return min(point_segment_distance(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def _contact_point(a, b):
    """Where polygon `a` meets polygon `b`: a point where their outlines
    cross, else a vertex of one inside the other, else the point of `a`
    nearest `b` - the one collision position KiCad's own check reads."""
    for i in range(len(a)):
        p1, p2 = a[i], a[(i + 1) % len(a)]
        for j in range(len(b)):
            q1, q2 = b[j], b[(j + 1) % len(b)]
            d = (p2[0] - p1[0]) * (q2[1] - q1[1]) - (p2[1] - p1[1]) * (q2[0] - q1[0])
            if abs(d) < 1e-15:
                continue
            t = ((q1[0] - p1[0]) * (q2[1] - q1[1]) - (q1[1] - p1[1]) * (q2[0] - q1[0])) / d
            u = ((q1[0] - p1[0]) * (p2[1] - p1[1]) - (q1[1] - p1[1]) * (p2[0] - p1[0])) / d
            if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
                return (p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1]))
    for p in a:
        if point_in_polygon(p, b):
            return p
    for p in b:
        if point_in_polygon(p, a):
            return p
    best, at = None, a[0]
    for p in a:
        d = _point_poly_distance(p, b)
        if best is None or d < best:
            best, at = d, p
    for q in b:
        for i in range(len(a)):
            p1, p2 = a[i], a[(i + 1) % len(a)]
            d = point_segment_distance(q, p1, p2)
            if d < best:
                dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                L = dx * dx + dy * dy
                t = 0.0 if L == 0 else max(0.0, min(1.0, ((q[0] - p1[0]) * dx + (q[1] - p1[1]) * dy) / L))
                best, at = d, (p1[0] + t * dx, p1[1] + t * dy)
    return at



def _copper_gap(s, o) -> float:
    """The gap between two pieces of copper, a via measured as the circle it
    is: its polygon lies a few microns outside the circle (a 16-gon's vertices,
    or a read outline's arc error), so a gap just over a clearance read as just
    under it, where KiCad's DRC, measuring the circle, passes."""
    if s.circle and o.circle:
        (ax, ay, ar), (bx, by, br) = s.circle, o.circle
        return max(0.0, math.hypot(ax - bx, ay - by) - ar - br)
    if s.circle or o.circle:
        (cx, cy, r), other = (s.circle, o) if s.circle else (o.circle, s)
        if point_in_polygon((cx, cy), other.poly):
            return 0.0
        return max(0.0, _point_poly_distance((cx, cy), other.poly) - r)
    return poly_distance(s.poly, o.poly)


_DRAWN = frozenset(("silk", "mask", "body"))


def _blocker_kind(kind: str) -> str:
    """A shape kind as a Blocker counts it: a yard is a courtyard."""
    return "courtyard" if kind == "yard" else kind
_COPPERISH = frozenset(("pad", "through", "copper"))
_HOLES = frozenset(("hole", "npth"))
# A hole's polygon lies inside its circle, by up to 1 - cos(pi/16) of the
# radius between vertices, and a turned one's box with it: the box prefilter
# for the hole rules reaches this share of the boxes' widths further.
_HOLE_SLACK = 0.02


def _circle(s: Shape) -> tuple:
    """A hole shape's centre and radius, as the circle it was drawn from:
    its polygon's vertices lie on the circle, whichever way it was turned."""
    c = s.box.center
    return (c.x, c.y), max(math.dist((c.x, c.y), p) for p in s.poly)


def _circle_distance(hole: Shape, poly) -> float:
    """How far copper `poly` lies from the edge of `hole`'s circle; 0 or less
    when it reaches it."""
    (cx, cy), r = _circle(hole)
    if _geometry_module.point_in_polygon((cx, cy), poly):
        return -r
    n = len(poly)
    return min(_geometry_module.point_segment_distance((cx, cy), poly[i], poly[(i + 1) % n]) for i in range(n)) - r
_NAMES = {"silk": "silk", "mask": "mask opening", "body": "body", "pad": "pad", "through": "pad", "npth": "hole"}


def _box_gap(a: Box, b: Box) -> float:
    """The shortest distance between two boxes; 0 when they touch or overlap."""
    dx = a.left - b.right if a.left > b.right else (b.left - a.right if b.left > a.right else 0.0)
    dy = a.top - b.bottom if a.top > b.bottom else (b.top - a.bottom if b.top > a.bottom else 0.0)
    return dx if dy == 0.0 else (dy if dx == 0.0 else math.hypot(dx, dy))


def _fmt(b: Box) -> str:
    return "%.2f,%.2f..%.2f,%.2f" % (b.left, b.top, b.right, b.bottom)


# The edge refusals, by the code the native keep-in gives them
# (native/src/board.rs): what `_edge_or_reservation_conflict` says.
_EDGE_WHY = {1: "outside the board", 2: "inside a cutout", 3: "past the board's keep-in (%.2f mm)",
             4: "past the cutout's keep-in (%.2f mm)", 5: "past the rim's keep-in (%.2f mm)",
             6: "into the bore's keep-in (%.2f mm)"}


def edge_sentence(code: int, body: Box, margin: float) -> str:
    """The sentence `_edge_or_reservation_conflict` gives for a native edge code."""
    if code == 7:
        return "body box %s crosses the board edge margin (%.2f mm)" % (_fmt(body), margin)
    why = _EDGE_WHY[code]
    return "body box %s is %s" % (_fmt(body), why % margin if "%" in why else why)


class NativeSweeper:
    """One scan's native legality: its turns' shapes and origin body boxes,
    the reservations that apply to the item, registered once; `run` judges a
    pass. Each refusal comes back from Rust as a detail (an edge code, a
    reservation, a conflicting pair) with how many candidates it refused and
    the first; this turns a detail into what `legal_bucket` gives: the
    bucket, the sentence (for the first candidate only) and the blocker."""

    def __init__(self, occ, item, face, rots, entry, board, clearance):
        from .placement import Placement
        self.occ, self.item, self.face, self.rots = occ, item, face, tuple(rots)
        self.index, self.shapes = entry
        self.board, self.clearance = board, clearance
        geom = occ._geometry(item)
        self.geom = geom
        self.handles, self.origin, self.bodies, self.parts = [], [], [], []
        for rot in self.rots:
            at = Placement(Location(0.0, 0.0), rot, face)
            self.handles.append(occ._native_origin_shapes(item, geom, at))
            self.origin.append(list(occ._legal_origin_shapes(item, geom, at)))
            b = occ.origin_body_box(item, rot, face)
            self.bodies.append((b.left, b.top, b.right, b.bottom))
            self.parts.append([(p.left, p.top, p.right, p.bottom) for p in occ.origin_parts(geom, rot, face)])
        faces = occ.standing_faces(geom, face)
        self.reservations = [i for i, r in enumerate(occ.reservations)
                             if not (r.layer is not None and r.layer.face not in faces)
                             and not occ.let_in(r, geom)]
        # a cell's parts each reservation judges: its members not let in by their own name or height
        self.judged = [occ.judged(occ.reservations[i], geom) for i in self.reservations] if geom.parts else None
        self._decoded = {}
        self._seen = _geometry_module._native.NativeSweepSeen()

    def expand(self, points, n_rots: int) -> list:
        """(x, y, turn) triples for `points` at each of `n_rots` turns not
        already produced by an earlier call on this scan: the seen-set
        `placer.native_sweep` used to keep as a Python set, moved to Rust
        (`NativeSweepSeen`) so the whole points-x-rotations loop and its
        membership test run once per pass in Rust, not once per
        (point, rotation) pair in Python."""
        return self._seen.expand(points, n_rots)

    def run(self, triples, stop_at_first: bool, scoring=None):
        """(indexes of the legal candidates, their scores, refusals) for
        (x, y, turn) triples; each refusal (bucket, count, first index,
        reason, blocker key), in the order first met. With `scoring` (a
        NativeScoring for these turns) each legal candidate is scored as the
        scan's scorer would score it; else its score is 0."""
        from . import geometry as _g
        legal, scores, refused = _g._native.sweep(self.board, self.reservations, self.index, self.handles,
                                                  self.bodies, triples, self.clearance, stop_at_first, scoring,
                                                  self.parts if self.geom.parts else None,
                                                  self.judged if self.geom.parts else None)
        out = []
        for kind, a, b, count, first in refused:
            bucket, blocker, reason = self._decode(kind, a, b, triples[first])
            out.append((bucket, count, first, reason, blocker))
        return legal, scores, out

    def _decode(self, kind, a, b, triple):
        from .placement import Placement
        occ = self.occ
        x, y, turn = triple
        cand = Placement(Location(x, y), self.rots[turn], self.face)
        if kind == 0:
            def box():              # b: the member whose box the edge refused, 1-based; 0 the whole box
                return occ.shifted_body_box(self.item, cand) if b == 0 else occ._shifted_parts(self.geom, cand)[b - 1]
            key = ("edge", a)
            hit = self._decoded.get(key)
            if hit is None:
                why = edge_sentence(a, box(), occ.edge_margin)
                hit = (_reason_key(why), ("edge", "", ""))
                self._decoded[key] = hit
            return hit[0], hit[1], (lambda: edge_sentence(a, box(), occ.edge_margin))
        if kind == 1:
            r = occ.reservations[a]
            why, owner = occ.reservation_hit(r, self.geom, b - 1 if b else None)
            return _reason_key(why), ("reservation", owner, ""), (lambda why=why: why)
        turn_of, si = a >> 32, a & 0xffffffff
        s, o = self.origin[turn_of][si], self.shapes[b]
        # The bucket and blocker are decided from `s.kind`/`s.owner` alone
        # (see `_native_bucket`'s own doc: it never reads `.poly`/`.box`),
        # which a shift by (x, y) never changes - so the cache is looked up
        # from the UNMOVED origin shape `s`, and the moved shape (its
        # polygon actually shifted) is only ever built inside `reason()`,
        # which runs only when a sentence is actually wanted (the first
        # candidate in a bucket - see `placer.tally`'s own `if key not in
        # reasons` guard).
        key = ("conflict", a, b)
        hit = self._decoded.get(key)
        if hit is None:
            hit = (occ._native_bucket(s, o), (_blocker_kind(o.kind), occ.blame_owner(o),
                                              "/".join(sorted(f.value for f in o.faces))))
            self._decoded[key] = hit
        clearance = self.clearance

        def reason(s=s, o=o, x=x, y=y, clearance=clearance):
            moved = Shape(s.owner, s.kind, s.faces, s.layers, s.net, tuple((px + x, py + y) for px, py in s.poly),
                          s.box.moved(x, y), s.label, claims=s.claims)
            why = occ._conflict(moved, o, clearance)
            if why is None:
                raise AssertionError("native found a conflict between a %s and a %s that _conflict disagrees with; "
                                     "this is a native/Python mismatch, not a placement question" % (moved.kind, o.kind))
            return why
        return hit[0], hit[1], reason


def native_board(occ):
    """The occupancy's keep-in and reservations mirrored natively
    (placemat_native.NativeBoard), or None without the module or for a board
    shape it does not know. Rebuilt when the board's shape, cutouts, box or
    margin is a different object or value, or the reservation list was
    replaced; a reservation added to the same list is added to it."""
    native = _geometry_module._native
    if native is None or not hasattr(native, "NativeBoard"):
        return None
    key = (occ.board_shape, occ.board_cutouts, occ.board_box, occ.edge_margin, occ.reservations)
    hit = occ.__dict__.get("_native_board")
    if hit is not None and all(a is b for a, b in zip(hit[0][:3] + hit[0][4:], key[:3] + key[4:])) \
            and hit[0][3] == key[3]:
        board, added = hit[1], hit[2]
    else:
        shape = occ.board_shape
        margin = occ.edge_margin
        if shape is not None:
            from .outline import Outline
            from .values import Disc
            if isinstance(shape, Disc):
                board = native.NativeBoard("disc", margin, loops=[list(l) for l in shape.cutouts.loops],
                                           centre=(shape.centre.x, shape.centre.y), radius=shape.radius,
                                           bore=shape.bore)
            elif isinstance(shape, Outline):
                board = native.NativeBoard("outline", margin, loops=[list(l) for l in shape.loops])
            else:
                return None
        elif occ.board_box is not None:
            b = occ.board_box
            cut = occ.board_cutouts
            board = native.NativeBoard("rect", margin, box=(b.left, b.top, b.right, b.bottom),
                                       loops=[list(l) for l in cut.loops] if cut else [])
        else:
            board = native.NativeBoard("none", margin)
        added = 0
    for r in occ.reservations[added:]:
        raster = None
        if len(r.poly) >= 24:
            ras = r._raster
            raster = (ras.x0, ras.y0, ras.cell, ras.nx, ras.ny, ras.state)
        board.add_reservation([tuple(p) for p in r.poly], raster)
    occ.__dict__["_native_board"] = (key, board, len(occ.reservations))
    return board


def _reason_key(why: str) -> str:
    """Which bucket a refusal sentence counts under, for a scan's `rejected`
    Counter and `reasons` dict (moved here from placer.py, which still
    re-exports it, so legal_bucket's native path can derive the same key
    without formatting the sentence first - see legal_bucket's own doc)."""
    for word in ("courtyard", "edge", "reservation", "copper", "through", "npth", "hole-to-hole"):
        if word in why:
            return word
    return why.split(" ")[0]
