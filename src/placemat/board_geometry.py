"""BoardGeometry: everything geometric about one generated KiCad board,
read once from its .kicad_pcb: footprints with their boxes and pads, the
cells (module groups), the copper, the outline and the net classes.
Immutable; placement and copper planning query this instead of pcbnew."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .values import Box, CopperLayer, Face, Location, Net, Part, Cell as CellRef, pad_key

Polygon = tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class PadGeom:
    owner: str                  # refdes of the footprint
    inst: str                   # instance path of the footprint
    number: str
    net: str
    layers: frozenset[CopperLayer]
    outlines: tuple[Polygon, ...]
    box: Box
    through: bool               # plated through hole: occupies both faces
    drill_mm: float = 0.0

    @property
    def location(self) -> Location:
        return self.box.center


@dataclass(frozen=True)
class Footprint:
    ref: str
    inst: str                   # Zener instance path; refdes when absent
    cell: str | None            # top-level group it belongs to, if any
    value: str
    location: Location
    rotation: float
    face: Face
    body_box: Box               # the house placement box (courtyard deflated, unioned with pads)
    courtyard_box: Box          # what the part claims for assembly
    phys_box: Box               # pads + drawn graphics, courtyard excluded
    pads: tuple[PadGeom, ...]
    npth: tuple[tuple[Location, float], ...] = ()   # (centre, drill) of unplated holes
    fields: dict = field(default_factory=dict, compare=False)   # the footprint's text fields (the capture's Pm.* facts)

    @property
    def box(self) -> Box:
        return self.body_box

    def pad(self, key) -> PadGeom:
        kind, value = pad_key(key)
        for p in self.pads:
            if (kind == "number" and p.number == value) or (kind == "net" and p.net == value):
                return p
        raise KeyError("%s has no pad %s %r" % (self.ref, kind, value))

    def pads_on(self, net) -> list[PadGeom]:
        name = net.name if isinstance(net, Net) else net
        return [p for p in self.pads if p.net == name]


@dataclass(frozen=True)
class CellGeom:
    name: str
    members: tuple[Footprint, ...]
    box: Box                    # union of member body boxes and the cell's own copper
    phys_box: Box               # union of member phys boxes (graphics included) and the cell's copper
    courtyard_box: Box          # what the cell claims for assembly
    copper_box: Box | None      # extent of the cell's own tracks/vias/polys, if any
    faces: dict = field(default_factory=dict)   # the module's declared sides: outward, quiet, handoff (N/S/E/W at rotation 0)

    def member(self, suffix: str) -> Footprint:
        for fp in self.members:
            if fp.inst == "%s.%s" % (self.name, suffix) or fp.inst.endswith("." + suffix):
                return fp
        raise KeyError("cell %s has no member %r" % (self.name, suffix))


@dataclass(frozen=True)
class CopperItem:
    kind: str                   # pad | track | via | poly | zone
    net: str
    layers: frozenset[CopperLayer]
    outlines: tuple[Polygon, ...]
    box: Box
    owner: str | None = None    # refdes for a pad, cell name for cell copper
    width_mm: float = 0.0       # tracks


@dataclass(frozen=True)
class NetClass:
    name: str
    track_width: float
    clearance: float
    via_diameter: float
    via_drill: float
    diff_pair_width: float | None = None     # a pair's track width, when the class says
    diff_pair_gap: float | None = None       # and its gap


@dataclass(frozen=True)
class BoardGeometry:
    path: str
    footprints: tuple[Footprint, ...]
    cells: dict[str, CellGeom]
    copper: tuple[CopperItem, ...]
    outline: tuple[Polygon, ...]          # Edge.Cuts as closed outlines (may be empty on a fresh generation)
    nets: frozenset[str]
    netclasses: dict[str, NetClass]       # net name -> resolved class
    default_clearance: float
    layers: tuple[CopperLayer, ...]
    edge_clearance: float = 0.0           # copper to the board edge, from the board's rules: the keep-in
    _by_ref: dict = field(default_factory=dict, repr=False, compare=False)
    _by_inst: dict = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self):
        for fp in self.footprints:
            self._by_ref[fp.ref] = fp
            self._by_inst[fp.inst] = fp

    # ------------------------------------------------------------ lookups
    def footprint(self, key) -> Footprint:
        name = key.inst if isinstance(key, Part) else key
        if name in self._by_inst:
            return self._by_inst[name]
        if name in self._by_ref:
            return self._by_ref[name]
        raise KeyError("no footprint with instance or reference %r" % (name,))

    def has_footprint(self, key) -> bool:
        name = key.inst if isinstance(key, Part) else key
        return name in self._by_inst or name in self._by_ref

    def cell(self, key) -> CellGeom:
        name = key.name if isinstance(key, CellRef) else key
        try:
            return self.cells[name]
        except KeyError:
            raise KeyError("no cell (group) named %r; cells: %s" % (name, sorted(self.cells)))

    def pad(self, part, key) -> PadGeom:
        return self.footprint(part).pad(key)

    def cell_pad(self, cell, *, net=None, number=None, ref_prefix=None) -> PadGeom:
        """One pad inside a cell, found by net or by number, optionally only on
        members whose refdes starts with `ref_prefix` (the jumper, not the
        connector). Exactly one match is required."""
        if (net is None) == (number is None):
            raise TypeError("cell_pad needs exactly one of net= or number=")
        key = int(number) if number is not None else (net.name if isinstance(net, Net) else net)
        hits = []
        for fp in self.cell(cell).members:
            if ref_prefix and not fp.ref.startswith(ref_prefix):
                continue
            try:
                hits.append(fp.pad(key))
            except KeyError:
                continue
        if len(hits) != 1:
            raise KeyError("cell %s: %d pads match %r (ref_prefix=%r)" % (cell, len(hits), key, ref_prefix))
        return hits[0]

    def require_net(self, net) -> str:
        name = net.name if isinstance(net, Net) else net
        if name not in self.nets:
            raise KeyError("no net named %r on this board" % name)
        return name

    def netclass(self, net) -> NetClass:
        return self.netclasses[self.require_net(net)]

    def clearance(self, net_a, net_b=None) -> float:
        """KiCad's rule: the larger of the two classes' clearances."""
        a = self.netclass(net_a).clearance
        if net_b is None:
            return a
        return max(a, self.netclass(net_b).clearance)

    # ------------------------------------------------------------ geometry
    @property
    def outline_box(self) -> Box | None:
        pts = [p for o in self.outline for p in o]
        return Box.of_points(pts) if pts else None

    def loose(self) -> list[Footprint]:
        return [fp for fp in self.footprints if fp.cell is None]

    def copper_on(self, layer: CopperLayer, net=None) -> list[CopperItem]:
        name = None if net is None else (net.name if isinstance(net, Net) else net)
        return [c for c in self.copper if layer in c.layers and (name is None or c.net == name)]

    def pads_on_net(self, net) -> list[PadGeom]:
        name = net.name if isinstance(net, Net) else net
        return [p for fp in self.footprints for p in fp.pads if p.net == name]
