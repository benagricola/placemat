"""What placemat knows about a part, said out loud.

Everything here is already in the BoardGeometry; none of it was ever printed,
which is why nine entries in PLACEMAT_GAPS.md were answered by grepping a
.kicad_mod or loading pcbnew in a scratch script. Pure: the formatting is
pinned by tests that run without KiCad, and `cli.py` stays a dispatcher.
"""
from __future__ import annotations

from .geometry import distance_to_boundary, polys_overlap
from .ranking import pin_count
from .values import Box, CopperLayer


def _xy(p) -> list:
    return [round(p.x, 3), round(p.y, 3)]


def _wh(b: Box) -> list:
    return [round(b.width, 3), round(b.height, 3)]


def _box_poly(b: Box):
    return ((b.left, b.top), (b.right, b.top), (b.right, b.bottom), (b.left, b.bottom))


def nearest_edge(poly, geometry) -> float | None:
    """How near a polygon comes to the board's edge, counting its holes: a
    cutout's edge is a board edge. None when the geometry carries no outline
    polygon, because inventing one would be worse than saying nothing."""
    rings = getattr(geometry, "board_polygon", ()) or ()
    if not rings:
        return None
    return round(min(distance_to_boundary(tuple(poly), r) for r in rings), 3)


def pad_facts(fp, pad, geometry=None) -> dict:
    """One pad. `size` is the box round its copper outlines, never the anchor
    size: for a custom pad the anchor is not the copper."""
    if pad.through:
        attribute = "through"
    elif len(pad.layers) == 1:
        attribute = "smd %s" % ("front" if next(iter(pad.layers)) is CopperLayer.F else "back")
    else:
        attribute = "smd"
    return {"number": pad.number, "net": pad.net, "at": _xy(pad.box.center),
            "size": _wh(pad.box), "through": pad.through, "attribute": attribute,
            "drill": round(pad.drill_mm, 3) if pad.through else None,
            "layers": sorted(l.value for l in pad.layers)}


def part_facts(fp, geometry=None) -> dict:
    out = {"instance": fp.inst, "ref": fp.ref, "value": fp.value, "cell": fp.cell,
           "face": fp.face.value, "rotation": fp.rotation, "origin": _xy(fp.location),
           "body": _wh(fp.body_box), "courtyard": _wh(fp.courtyard_box),
           "physical": _wh(fp.phys_box), "pins": pin_count(fp),
           "mm2": round(fp.courtyard_box.area, 3)}
    court = nearest_edge(_box_poly(fp.courtyard_box), geometry) if geometry is not None else None
    if court is not None:
        out["nearest_edge_courtyard"] = court
        copper = [q for p in fp.pads for o in p.outlines for q in o]
        if copper:
            out["nearest_edge_copper"] = nearest_edge(tuple(copper), geometry)
    return out


def copper_on(fp, geometry) -> dict:
    """The tracks and vias whose copper touches one of this part's pads, by
    kind. A count rather than a list, because the question this answers is
    "is anything wired to it" - what is AT a coordinate is the occupancy
    surface's question, not this one."""
    nets = {p.net for p in fp.pads if p.net}
    hits = {"track": 0, "via": 0}
    for c in geometry.copper:
        if c.kind not in hits or c.net not in nets:
            continue
        for p in fp.pads:
            if p.net != c.net or not c.box.overlaps(p.box):
                continue
            if any(polys_overlap(o, q) for o in c.outlines for q in p.outlines):
                hits[c.kind] += 1
                break
    return hits


def part_lines(fp, geometry=None, pads: bool = False, digest: str = "") -> list:
    f = part_facts(fp, geometry)
    lines = ["part  %-24s %-6s %s" % (f["instance"], f["ref"], f["value"])]
    lines.append("  face %-6s rotation %-6g origin (%.2f, %.2f)%s" % (
        f["face"], f["rotation"], f["origin"][0], f["origin"][1],
        "  cell %s" % f["cell"] if f["cell"] else ""))
    lines.append("  body %.2f x %.2f   courtyard %.2f x %.2f   physical %.2f x %.2f" % (
        *f["body"], *f["courtyard"], *f["physical"]))
    if "nearest_edge_courtyard" in f:
        lines.append("  nearest board edge: courtyard %.2f mm%s" % (
            f["nearest_edge_courtyard"],
            "" if f.get("nearest_edge_copper") is None else
            ", copper %.2f mm" % f["nearest_edge_copper"]))
    if digest:
        lines.append("  sha256 %s" % digest)
    if pads and geometry is not None and getattr(geometry, "copper", None):
        c = copper_on(fp, geometry)
        if c["track"] or c["via"]:
            lines.append("  copper on its pads: %d track(s), %d via(s)" % (c["track"], c["via"]))
    if pads:
        for p in fp.pads:
            d = pad_facts(fp, p, geometry)
            where = "/".join(d["layers"]) if d["layers"] else d["attribute"]
            lines.append("  pad %-5s %-14s %-12s %s at (%.3f, %.3f)  %.3f x %.3f" % (
                d["number"], d["net"] or "-", where,
                "drill %.2f " % d["drill"] if d["drill"] else "          ",
                d["at"][0], d["at"][1], d["size"][0], d["size"][1]))
    return lines


def parts_rows(geometry) -> list:
    return [{"instance": fp.inst, "ref": fp.ref, "face": fp.face.value, "cell": fp.cell,
             "mm2": round(fp.courtyard_box.area, 3), "pins": pin_count(fp),
             "value": fp.value, "nets": sorted({p.net for p in fp.pads if p.net})}
            for fp in sorted(geometry.footprints, key=lambda f: f.inst)]


def parts_lines(geometry) -> list:
    rows = parts_rows(geometry)
    if not rows:
        return ["no footprints on this board"]
    out = ["%-26s %-6s %-6s %-12s %8s %5s  %s" % (
        "instance", "ref", "face", "cell", "mm2", "pins", "value")]
    for r in rows:
        out.append("%-26s %-6s %-6s %-12s %8.2f %5d  %s" % (
            r["instance"][:26], r["ref"], r["face"], (r["cell"] or "-")[:12],
            r["mm2"], r["pins"], r["value"][:28]))
    return out
