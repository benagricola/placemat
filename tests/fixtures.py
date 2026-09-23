"""Synthetic BoardGeometry builders so the geometry, occupancy and placer tests run
without KiCad. A footprint here is a rectangle of pads on a body box."""
from pathlib import Path
import subprocess

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


def _box_poly(b):
    x0, y0, x1, y1 = b
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def footprint(ref, cx, cy, w=4.0, h=2.0, nets=("A", "B"), through=False, face=Face.FRONT,
              rotation=0.0, cell=None, inst=None, excess=0.1, fields=None, silk=(0.0, 0.0, 0.0, 0.0),
              silk_boxes=(), fab=None, mask_grow=None):
    """A two-pad part: pad 1 at the west end, pad 2 at the east end (rotation 0).
    `silk` is how far drawn graphics reach past the body: (west, north, east, south)."""
    inst = inst or ref.lower()
    pads = (pad(ref, inst, 1, nets[0], cx - w / 2 + 0.6, cy, 1.0, 1.0, through, face),
            pad(ref, inst, 2, nets[1], cx + w / 2 - 0.6, cy, 1.0, 1.0, through, face))
    body = Box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    sw, sn, se, ss = silk
    phys = Box(body.left - sw, body.top - sn, body.right + se, body.bottom + ss)
    # silk_boxes: silk graphics as (x0, y0, x1, y1) boxes, drawn; fab: the body box; mask_grow:
    # each pad's mask aperture grown by that much. Coordinates are the board's, like cx, cy.
    silk_polys = tuple((face, _box_poly(b)) for b in silk_boxes)
    fab_polys = ((face, _box_poly(fab)),) if fab else ()
    mask_polys = () if mask_grow is None else tuple(
        (face, _box_poly((p.box.left - mask_grow, p.box.top - mask_grow, p.box.right + mask_grow, p.box.bottom + mask_grow)))
        for p in pads)
    extra = [Box(*b) for b in silk_boxes] + ([Box(*fab)] if fab else [])
    if extra:
        phys = Box.union([phys] + extra)
    return Footprint(ref, inst, cell, ref, Location(cx, cy), rotation, face,
                     body, body.inflate(excess), phys, pads, fields=dict(fields or {}),
                     silk=silk_polys, mask=mask_polys, fab=fab_polys)


def board_geometry(footprints, cells=(), copper=(), width=50.0, height=50.0, clearance=0.2, extra_nets=(),
                   edge_clearance=0.4, faces=None, silk_clearance=0.0):
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
                               Box.union(own), dict((faces or {}).get(c, {})))
    pads = tuple(CopperItem("pad", p.net, p.layers, p.outlines, p.box, fp.ref)
                 for fp in footprints for p in fp.pads)
    return BoardGeometry("synthetic", tuple(footprints), cell_map, pads + tuple(copper), outline,
                    frozenset(nets), classes, clearance, (CopperLayer.F, CopperLayer.B), edge_clearance=edge_clearance,
                    silk_clearance=silk_clearance)


def track(net, x1, y1, x2, y2, w=0.3, layer=CopperLayer.F, owner=None):
    if x1 == x2:
        outline = rect((x1 + x2) / 2, (y1 + y2) / 2, w, abs(y2 - y1) + w)
    else:
        outline = rect((x1 + x2) / 2, (y1 + y2) / 2, abs(x2 - x1) + w, w)
    return CopperItem("track", net, frozenset([layer]), (outline,), Box.of_points(outline), owner, w)


def make_pdf(path, body: str):
    """A one-page PDF built with mutool from a content stream, so a test can
    state exactly what is on the page it then reads back."""
    src = Path(path).with_suffix(".txt")
    src.write_text(body)
    subprocess.run(["mutool", "create", "-o", str(path), str(src)],
                   capture_output=True, check=True)
    return Path(path)
