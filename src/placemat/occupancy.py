"""Tracks what occupies each face of the board and decides whether a
candidate placement is legal, without pcbnew.

Built from the geometry read off the generated .kicad_pcb and updated as
placements are committed. Checks: body
box inside the edge margin, courtyards on a face do not overlap, through
features block both faces, pads keep net-class clearance from foreign
copper, reservations block parts unless they carry an allowed net."""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import (Polygon, Transform, box_polygon, circle_polygon, poly_distance,
                       polys_overlap, transform_box, transform_polygon)
from .placement import Placement
from .board_geometry import CellGeom, Footprint, BoardGeometry
from .values import Box, CopperLayer, Face, Location, Net


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


@dataclass(frozen=True)
class Reservation:
    box: Box
    why: str
    allow: frozenset[str]
    layer: CopperLayer | None       # None: both faces, any layer


@dataclass
class ItemGeometry:
    """A footprint's or cell's shapes in world coordinates at its CURRENT
    placement, plus the reference placement those coordinates assume."""
    owners: frozenset[str]
    reference: Placement
    shapes: tuple[Shape, ...]
    body: Box
    nets: frozenset[str]


_BOTH = frozenset([Face.FRONT, Face.BACK])


def _fp_shapes(fp: Footprint) -> list[Shape]:
    shapes = []
    through = any(p.through for p in fp.pads) or bool(fp.npth)
    faces = _BOTH if through else frozenset([fp.face])
    ct = box_polygon(fp.courtyard_box)
    shapes.append(Shape(fp.ref, "courtyard", faces, frozenset(), "", ct, fp.courtyard_box))
    for p in fp.pads:
        for poly in p.outlines:
            shapes.append(Shape(fp.ref, "through" if p.through else "pad",
                                _BOTH if p.through else frozenset([fp.face]),
                                p.layers, p.net, poly, Box.of_points(poly), p.number))
    for center, drill in fp.npth:
        poly = circle_polygon(center, drill / 2.0)
        shapes.append(Shape(fp.ref, "npth", _BOTH, frozenset(CopperLayer), "", poly, Box.of_points(poly)))
    return shapes


class Occupancy:
    def __init__(self, geometry: BoardGeometry, edge_margin: float = 0.0, board_box: Box | None = None,
                 vias_block_courtyards: bool = False):
        self.geometry = geometry
        self.edge_margin = edge_margin
        self.vias_block_courtyards = vias_block_courtyards
        self.board_box = board_box or geometry.outline_box
        self.items: dict[str, ItemGeometry] = {}
        self.reservations: list[Reservation] = []
        self.copper: list[Shape] = []
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

    # ------------------------------------------------------------ geometry of a candidate
    def _register(self, fp: Footprint) -> ItemGeometry:
        g = ItemGeometry(frozenset([fp.ref]), Placement(fp.location, fp.rotation, fp.face),
                         tuple(_fp_shapes(fp)), fp.body_box, frozenset(p.net for p in fp.pads))
        self.items[fp.ref] = g
        return g

    def _geometry(self, item) -> ItemGeometry:
        if isinstance(item, Footprint):
            return self.items.get(item.ref) or self._register(item)
        if isinstance(item, CellGeom):
            members = [self.items[fp.ref] for fp in item.members]
            shapes = tuple(s for m in members for s in m.shapes)
            for c in self.copper:
                if c.owner == item.name:
                    shapes += (c,)
            body = Box.union([m.body for m in members] + [s.box for s in shapes if s.owner == item.name])
            return ItemGeometry(frozenset(m for mg in members for m in mg.owners) | {item.name},
                                Placement(body.center, 0.0, Face.FRONT), shapes, body,
                                frozenset(n for m in members for n in m.nets))
        raise TypeError("cannot place a %s" % type(item).__name__)

    @staticmethod
    def _transform(geom: ItemGeometry, placement: Placement) -> Transform:
        ref = geom.reference
        t = Transform.translate(-ref.location.x, -ref.location.y)
        flip = placement.face != ref.face
        if flip:
            t = t.then(Transform.mirror_x(Location(0, 0)))
        t = t.then(Transform.rotate(placement.rotation - ref.rotation))
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
        """{(refdes, pad number): Location} for the item at a candidate placement."""
        _, shapes = self.candidate_shapes(item, placement)
        boxes: dict = {}
        for s in shapes:
            if s.kind in ("pad", "through"):
                boxes.setdefault((s.owner, s.label), []).append(s.box)
        return {k: Box.union(v).center for k, v in boxes.items()}

    def pad_location(self, ref: str, number: str) -> Location:
        """Where a pad is NOW (after every commit so far): its outline's box centre."""
        boxes = [s.box for s in self.items[ref].shapes if s.kind in ("pad", "through") and s.label == number]
        if not boxes:
            raise KeyError("%s has no pad %s" % (ref, number))
        return Box.union(boxes).center

    def add_copper(self, shapes) -> None:
        """Planned copper becomes an obstacle for everything placed after it."""
        self.copper.extend(shapes)

    def copper_conflicts(self, shape: Shape) -> list[str]:
        """Every pad or copper of another net within clearance of `shape`."""
        out = []
        for owner, g in self.items.items():
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

    # ------------------------------------------------------------ mutation
    def reserve(self, box: Box, why: str, allow=(), layer: CopperLayer | None = None):
        self.reservations.append(Reservation(box, why, frozenset(str(n) for n in allow), layer))

    def commit(self, item, placement: Placement):
        """Record that `item` now sits at `placement`; later checks see it there."""
        geom, shapes = self.candidate_shapes(item, placement)
        if isinstance(item, Footprint):
            self.items[item.ref] = ItemGeometry(geom.owners, placement, tuple(shapes),
                                                self.body_box(item, placement), geom.nets)
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
                                              transform_box(m.body, t), m.nets)
        own = by_owner.get(item.name, [])
        self.copper = [c for c in self.copper if c.owner != item.name] + own

    # ------------------------------------------------------------ measures
    def free_area(self, face: Face | None = None) -> float:
        """Board area not under a courtyard, on one face or summed over both.
        Courtyards are taken as their boxes; overlaps (which are findings)
        are not corrected for."""
        if self.board_box is None:
            return 0.0
        faces = [face] if face is not None else [Face.FRONT, Face.BACK]
        total = 0.0
        for f in faces:
            used = 0.0
            for g in self.items.values():
                for s in g.shapes:
                    if s.kind == "courtyard" and f in s.faces:
                        used += s.box.area
            total += self.board_box.area - used
        return total

    # ------------------------------------------------------------ legality
    def legal(self, item, placement: Placement, clearance: float | None = None) -> str | None:
        """None when `item` may sit at `placement`, else one sentence saying
        what stops it. The first failure found is reported."""
        geom, shapes = self.candidate_shapes(item, placement)
        body = self.body_box(item, placement)
        if self.board_box is not None and self.edge_margin is not None:
            inner = self.board_box.inflate(-self.edge_margin)
            if not inner.contains(body):
                return "body box %s crosses the board edge margin (%.2f mm)" % (_fmt(body), self.edge_margin)
        for r in self.reservations:
            if r.box.overlaps(body) and not (geom.nets & r.allow):
                return "sits in the reservation for %s" % r.why
        others = [s for owner, g in self.items.items() if owner not in geom.owners for s in g.shapes]
        others += [c for c in self.copper if c.owner not in geom.owners]
        for s in shapes:
            for o in others:
                if not s.box.overlaps(o.box, gap=1.0):
                    continue
                why = self._conflict(s, o, clearance)
                if why:
                    return why
        return None

    def _conflict(self, s: Shape, o: Shape, clearance: float | None) -> str | None:
        """The DRC rules, in occupancy terms. A via under a body is legal to
        DRC and is only refused when `vias_block_courtyards` is set (a house
        rule for boards that pair through-feature cells with via-free parts)."""
        ks, ko = s.kind, o.kind
        if ks == "courtyard" and ko == "courtyard":
            if s.faces & o.faces and polys_overlap(s.poly, o.poly):
                return "%s courtyard overlaps %s courtyard" % (s.owner, o.owner)
            return None
        if "courtyard" in (ks, ko):
            other = o if ks == "courtyard" else s
            court = s if ks == "courtyard" else o
            if other.kind == "npth" or (other.kind == "through" and self.vias_block_courtyards
                                        and other.owner not in self.items):
                if polys_overlap(court.poly, other.poly):
                    return "%s courtyard sits over a %s (%s)" % (court.owner, other.kind, other.owner or "via")
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
            gap = poly_distance(s.poly, o.poly)
            if gap < clr - 1e-9:
                return "%s pad %s is %.2f mm from %s copper on %s (needs %.2f)" % (
                    s.owner, s.net or "-", gap, o.net or o.owner, "/".join(sorted(l.value for l in common)), clr)
            return None
        if ks == "npth" and ko in ("pad", "through", "copper"):
            if polys_overlap(s.poly, o.poly):
                return "%s hole cuts %s copper" % (s.owner, o.net or o.owner)
        return None


def _fmt(b: Box) -> str:
    return "%.2f,%.2f..%.2f,%.2f" % (b.left, b.top, b.right, b.bottom)
