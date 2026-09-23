"""What placemat knows about a part, said out loud.

Everything here is already in the BoardGeometry; none of it was ever printed,
which is why nine entries in PLACEMAT_GAPS.md were answered by grepping a
.kicad_mod or loading pcbnew in a scratch script. Pure: the formatting is
pinned by tests that run without KiCad, and `cli.py` stays a dispatcher.
"""
from __future__ import annotations

from collections import Counter

from .geometry import distance_to_boundary, polys_overlap
from .ranking import pin_count
from .values import Box, CopperLayer


def _xy(p) -> list:
    return [round(p.x, 3), round(p.y, 3)]


def _wh(b: Box) -> list:
    return [round(b.width, 3), round(b.height, 3)]


def _ltrb(b: Box) -> list:
    return [round(b.left, 3), round(b.top, 3), round(b.right, 3), round(b.bottom, 3)]


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
            "layers": sorted(l.value for l in pad.layers),
            "outline": [[[round(x, 4), round(y, 4)] for x, y in poly] for poly in pad.outlines],
            "mask_paste": list(pad.mask_paste)}


def part_facts(fp, geometry=None) -> dict:
    out = {"instance": fp.inst, "ref": fp.ref, "value": fp.value, "cell": fp.cell,
           "face": fp.face.value, "rotation": fp.rotation, "origin": _xy(fp.location),
           "body": _wh(fp.body_box), "courtyard": _wh(fp.courtyard_box),
           "physical": _wh(fp.phys_box), "pins": pin_count(fp),
           "mm2": round(fp.courtyard_box.area, 3)}
    from .envelope import courtyard_findings, drawn_envelope
    env, sides = drawn_envelope(fp)
    out["boxes"] = {"body": _ltrb(fp.body_box), "courtyard": _ltrb(fp.courtyard_box),
                    "physical": _ltrb(fp.phys_box), "envelope": _ltrb(env if env is not None else fp.phys_box)}
    if env is not None:
        out["envelope"] = _wh(env)
        out["envelope_set_by"] = sides
    out["footprint_findings"] = courtyard_findings(fp)
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
    from .envelope import drawn_envelope
    env, sides = drawn_envelope(fp)
    if env is not None:
        lines.append("  envelope %.2f x %.2f   set by %s" % (
            env.width, env.height, ", ".join("%s %s" % (k, sides[k]) for k in ("left", "top", "right", "bottom"))))
    for finding in f["footprint_findings"]:
        lines.append("  footprint: %s" % finding)
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
        facts = [pad_facts(fp, p, geometry) for p in fp.pads]
        wheres = ["/".join(d["layers"]) if d["layers"] else d["attribute"] for d in facts]
        drills = ["drill %.2f" % d["drill"] if d["drill"] else "" for d in facts]
        # Laid out to this part's own widest entry, not to a constant: a
        # four-layer board names four layers on every through pad and a
        # two-layer board names two, so a fixed column moves the coordinates.
        wide = max([len(w) for w in wheres], default=0)
        deep = max([len(s) for s in drills], default=0)
        for d, where, drill in zip(facts, wheres, drills):
            column = "%-*s" % (wide, where) + ("  %-*s" % (deep, drill) if deep else "")
            lines.append("  pad %-5s %-14s %s  at (%.3f, %.3f)  %.3f x %.3f%s" % (
                d["number"], d["net"] or "-", column,
                d["at"][0], d["at"][1], d["size"][0], d["size"][1],
                ("  " + "/".join(d["mask_paste"])) if d["mask_paste"] else ""))
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


def pitch_of(pads):
    """The nearest gap between two pad centres: a part's pin pitch. None when
    there are not two pads to measure between."""
    centres = [p.box.center for p in pads]
    if len(centres) < 2:
        return None
    return round(min(min(a.distance(b) for b in centres if b is not a) for a in centres), 6)


def pad_size_of(pads):
    """The commonest pad size: the one most pads share, which is what a land
    pattern is checked on. A pad or two of another size - a tab, a thermal
    pad - does not move it."""
    if not pads:
        return None
    sizes = Counter((round(p.box.width, 3), round(p.box.height, 3)) for p in pads)
    return sizes.most_common(1)[0][0]


def span_of(pads):
    """How far the copper reaches across every pad."""
    box = Box.union([p.box for p in pads]) if pads else None
    return round(box.width, 6) if box is not None else None
