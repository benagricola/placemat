"""BoardGeometry: everything geometric about one generated KiCad board,
read once from its .kicad_pcb: footprints with their boxes and pads, the
cells (module groups), the copper, the outline and the net classes.
Immutable; placement and copper planning query this instead of pcbnew."""
from __future__ import annotations

from dataclasses import dataclass, field
import re

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
    mask_paste: tuple = ()      # the mask and paste layers the pad opens, e.g. ("F.Mask", "F.Paste")

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
    silk: tuple = ()            # ((Face, polygon), ...): every silk graphic's stroked outline, no field text
    mask: tuple = ()            # ((Face, polygon), ...): each pad's mask aperture, the pad grown by its expansion
    fab: tuple = ()             # ((Face, polygon), ...): per face, the box of the fab graphics - the body
    courtyard_margin: float = 0.0   # how far KiCad's courtyard polygon lies inside courtyard_box, least side
    fields: dict = field(default_factory=dict, compare=False)   # the footprint's text fields (the capture's Pm.* facts)

    @property
    def box(self) -> Box:
        return self.body_box

    def pad(self, key) -> PadGeom:
        kind, value = pad_key(key)
        for p in self.pads:
            if (kind == "number" and p.number == value) or (kind == "net" and p.net == value):
                return p
        if kind == "net":                       # no net of that name on this part: a pad number like 1'
            for p in self.pads:
                if p.number == value:
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
class RuleArea:
    """A KiCad rule area already on the generated board: the module fragments
    that were stamped bring theirs with them, inside the cell's group.

    placemat did not write these and must not destroy them. `cell` is the
    group that owns it, or None for one that belongs to the board itself."""
    name: str                            # the zone name, e.g. "keepout clearance [*.Cu]_1"
    cell: str | None
    polygon: Polygon                     # in the generated board's coordinates
    layers: frozenset[CopperLayer]
    excludes: frozenset[str]             # parts | fill | tracks | vias | pads
    # Declared layers this board does not have, from the name's marker. The
    # region holds on the rest; these are reported, never silently dropped.
    missing: tuple = ()

    @property
    def base(self) -> str:
        """The name without its layer marker or the stamp that followed it."""
        return split_marker(self.name)[0]


# KiCad saves a zone on the layers its board has, so a two-layer module
# fragment cannot hold a keepout on In2, or on every layer of the board that
# will stamp it. The zone name survives both the save and pcb's stamp, so a
# declaration the layer set cannot hold travels there: ` [*.Cu]` for every
# copper layer, or the declared list. pcb appends `_1` directly after it, and
# a trailing number is only taken for a stamp when it follows the marker:
# without one, `rail_1_26` is a real name and not `rail_1` stamped.
_MARKER = re.compile(r"\s*\[([^\]]*)\](_\d+)?")


def stackup_order(layer) -> int:
    """F.Cu first, the inner layers in order, B.Cu last."""
    if layer is CopperLayer.F:
        return 0
    if layer is CopperLayer.B:
        return 31
    return int(layer.value[2:-3])


def layer_marker(declared, board_layers) -> str:
    """What a keepout's zone name must carry so its layers survive: nothing
    when the board holds them all, ` [*.Cu]` for every copper layer, or the
    declared list when the board lacks any of them."""
    if declared is None:
        return " [*.Cu]"
    if set(declared) <= set(board_layers):
        return ""
    return " [%s]" % ",".join(l.value for l in sorted(set(declared), key=stackup_order))


def split_marker(name: str) -> tuple:
    """(base name, declaration). The declaration is "*" for every copper
    layer, a tuple of layers, or None when the name carries no marker."""
    m = _MARKER.search(name)
    if not m:
        return name.strip(), None
    base = (name[:m.start()] + name[m.end():]).strip()
    body = m.group(1).strip()
    if body == "*.Cu":
        return base, "*"
    return base, tuple(CopperLayer.of(x.strip()) for x in body.split(",") if x.strip())


def resolve_marker(declared, board_layers) -> tuple:
    """(layers this board can honour, declared layers it lacks)."""
    if declared == "*":
        return frozenset(board_layers), ()
    have = frozenset(l for l in declared if l in set(board_layers))
    return have, tuple(sorted((l for l in declared if l not in have), key=stackup_order))


@dataclass(frozen=True)
class CopperItem:
    kind: str                   # pad | track | via | poly | zone
    net: str
    layers: frozenset[CopperLayer]
    outlines: tuple[Polygon, ...]
    box: Box
    owner: str | None = None    # refdes for a pad, cell name for cell copper
    width_mm: float = 0.0       # tracks
    drill_mm: float = 0.0       # vias: the hole, for the hole-to-hole rule


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
    rule_areas: tuple = ()                # what the board already forbids: a stamped cell's come with it
    board_polygon: tuple = ()             # the true edge: the outline, then its holes
    hole_to_hole: float = 0.25            # the nearest two drilled holes may come, from the board's rules
    hole_clearance: float = 0.0           # a hole's clearance to copper of another net
    silk_clearance: float = 0.0           # silk to silk and to a mask opening, from the board's rules
    _by_ref: dict = field(default_factory=dict, repr=False, compare=False)
    _by_inst: dict = field(default_factory=dict, repr=False, compare=False)

    def rule_area_names(self) -> frozenset:
        return frozenset(r.name for r in self.rule_areas)

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


# The rule-area flag that forbids each kind of copper the router lays.
_FORBIDDING = {"track": "tracks", "via": "vias"}


def _copper_key(c: CopperItem) -> tuple:
    return (c.kind, c.net, tuple(sorted(l.value for l in c.layers)),
            round(c.box.left, 3), round(c.box.top, 3), round(c.box.right, 3), round(c.box.bottom, 3))


def added_copper(before, after) -> list:
    """The tracks and vias in `after` that were not in `before`: what the
    router laid, as against what it was given and locked."""
    had = {_copper_key(c) for c in before}
    return [c for c in after if c.kind in _FORBIDDING and _copper_key(c) not in had]


def keepout_breaches(rule_areas, copper) -> list:
    """A sentence for every track or via inside a rule area that forbids it on
    a layer it covers. KiCad's DRC reports the same thing as one more
    `items_not_allowed` among the ones that are there by permission, which is
    how a region the router ignored used to go unnoticed."""
    from .geometry import polys_overlap
    out = []
    for c in copper:
        flag = _FORBIDDING.get(c.kind)
        if flag is None:
            continue
        for ra in rule_areas:
            if flag not in ra.excludes or not (c.layers & ra.layers):
                continue
            if not Box.of_points(ra.polygon).overlaps(c.box):
                continue
            if any(polys_overlap(ra.polygon, o) for o in c.outlines):
                out.append("the router laid a %s of %s inside %s, which forbids %s there"
                           % (c.kind, c.net, ra.base, flag))
                break
    return out


def members_of(item) -> tuple:
    """The footprints an item stands for: a cell's or a block's members, or
    the footprint itself."""
    return tuple(getattr(item, "members", None) or (item,))
