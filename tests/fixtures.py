"""Synthetic BoardGeometry builders so the geometry, occupancy and placer tests run
without KiCad. A footprint here is a rectangle of pads on a body box."""
from placemat.board_geometry import CellGeom, CopperItem, Footprint, NetClass, PadGeom, BoardGeometry
from placemat.values import Box, CopperLayer, Face, Location


def rect(cx, cy, w, h):
    return ((cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
            (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2))


def pad(owner, inst, number, net, cx, cy, w=1.0, h=1.0, through=False, face=Face.FRONT):
    outline = rect(cx, cy, w, h)
    layers = frozenset([CopperLayer.F, CopperLayer.B]) if through else frozenset([face.copper])
    return PadGeom(owner, inst, str(number), net, layers, (outline,), Box.of_points(outline),
                   through, 0.5 if through else 0.0)


def footprint(ref, cx, cy, w=4.0, h=2.0, nets=("A", "B"), through=False, face=Face.FRONT,
              rotation=0.0, cell=None, inst=None, excess=0.1):
    """A two-pad part: pad 1 at the west end, pad 2 at the east end (rotation 0)."""
    inst = inst or ref.lower()
    pads = (pad(ref, inst, 1, nets[0], cx - w / 2 + 0.6, cy, 1.0, 1.0, through, face),
            pad(ref, inst, 2, nets[1], cx + w / 2 - 0.6, cy, 1.0, 1.0, through, face))
    body = Box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return Footprint(ref, inst, cell, ref, Location(cx, cy), rotation, face,
                     body, body.inflate(excess), body, pads)


def board_geometry(footprints, cells=(), copper=(), width=50.0, height=50.0, clearance=0.2, extra_nets=()):
    nets = {p.net for fp in footprints for p in fp.pads} | {c.net for c in copper} | set(extra_nets)
    classes = {n: NetClass("Default", 0.2, clearance, 0.6, 0.3) for n in nets}
    outline = (((0.0, 0.0), (width, 0.0), (width, height), (0.0, height)),)
    cell_map = {}
    for c in cells:
        members = tuple(fp for fp in footprints if fp.cell == c)
        own = [cp.box for cp in copper if cp.owner == c]
        box = Box.union([fp.body_box for fp in members] + own)
        cell_map[c] = CellGeom(c, members, box,
                               Box.union([fp.phys_box for fp in members] + own),
                               Box.union([fp.courtyard_box for fp in members] + own),
                               Box.union(own))
    pads = tuple(CopperItem("pad", p.net, p.layers, p.outlines, p.box, fp.ref)
                 for fp in footprints for p in fp.pads)
    return BoardGeometry("synthetic", tuple(footprints), cell_map, pads + tuple(copper), outline,
                    frozenset(nets), classes, clearance, (CopperLayer.F, CopperLayer.B))


def track(net, x1, y1, x2, y2, w=0.3, layer=CopperLayer.F, owner=None):
    if x1 == x2:
        outline = rect((x1 + x2) / 2, (y1 + y2) / 2, w, abs(y2 - y1) + w)
    else:
        outline = rect((x1 + x2) / 2, (y1 + y2) / 2, abs(x2 - x1) + w, w)
    return CopperItem("track", net, frozenset([layer]), (outline,), Box.of_points(outline), owner, w)
