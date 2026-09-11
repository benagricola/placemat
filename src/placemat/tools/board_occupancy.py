#!/usr/bin/env python3
"""Two-faced board occupancy model + defect auditor (KiCad 10 / pcbnew).

WHY: cells INTERLEAVE, so packing them by bounding box over-reserves board,
and a whole defect class is invisible to DRC: a through-hole
pin is a hole through the WHOLE board, so its lead and solder fillet land on the
FAR face.  A pin under an opposite-face component body is assembly-impossible;
DRC never looks, because it is not a copper-clearance violation.

THE MODEL - real geometry, never bounding boxes.  Everything is an exact
polygon (pcbnew SHAPE_POLY_SET / Clipper); arcs and circles are flattened at
0.005mm with ERROR_OUTSIDE, so a modelled shape circumscribes the true one and
overlap is never under-reported.  Raster was not needed: boolean unions over a
whole board run in ~1s, and area/fill come out exact.

Per face (F, B) occupancy is the union of three classes:
  body    footprints ON that face -> their real F/B.Courtyard polygons.
          Footprints with no courtyard fall back to pads + *.Fab body union
          and are ALWAYS listed in the report (a silent fallback would
          under-report).
  copper  pads, tracks, vias, gr_polys and zone fills on that layer.
  through THE CROSS-FACE CLASS.  PTH/NPTH pads, vias, and pad-less mounting
          holes occupy BOTH faces: the barrel is copper end to end and the
          lead protrudes.  Modelled as the land/annulus (drill circle where
          there is no land) grown by an assembly clearance.

CLEARANCE DEFAULTS (all overridable; set to 0 to see bare geometry):
  --tht-fillet 0.25mm   radial growth of a THT land on the far face, for the
          protruding lead's solder meniscus.  Basis: IPC-A-610 wants the
          fillet wetted to the land, so the land IS the footprint and 0.25 is
          margin.  Vias get 0 here - a via has no lead.
  --copper-clearance 0.20mm  the house netclass floor (modules/
          fab-profile clearance default).  Used to split class (b) into
          SHORT (copper touching) / CLEAR (inside clearance, not touching).
  --npth-clearance 0.25mm    copper kept off an unplated drill.
  --via-in-pad-slop 0.05mm   annulus allowed to protrude past a SAME-NET pad
          before the landing counts as PARTIAL rather than designed
          via-in-pad.  0.05 is exactly what a 0.6mm land on a 0.5mm-wide 0402
          pad protrudes, which is house practice for a plane drop.

WHAT IT DOES NOT MODEL (honesty):
  * HEIGHT.  Everything here is 2D.  A tall part under a sealed lid, the
    spacer stack gap, a connector's mating volume - none of it is expressed.
    A pin under a 0.5mm-tall part and a pin under a 10mm electrolytic read
    identically.
  * Lead PROTRUSION length, and therefore whether a far-side part could
    straddle a clipped lead.  Treated as always-colliding, which is right for
    a reflowed SMD body sitting ~0.1mm off the board.
  * Assembly ORDER / process (selective solder pallets, hand-solder access).
  * Keepouts a cell needs but does not fill (routing lanes, hot loops,
    thermal or isolation regions) - a cell must DECLARE these; the model has
    no source for them, so it reports occupancy, not entitlement.

Usage:
  placemat occupancy                       # every board layout in repo
  placemat occupancy <board>/layout/<Board>/layout.kicad_pcb
  placemat occupancy <board> --cells       # bbox / occupied / fill%
  placemat occupancy <board> --json out.json
"""
import argparse
import glob
import json
import math
import os
import sys

import pcbnew

from placemat.args import board as board_arg

from placemat.report import emit, hush, json_option, unhush

sys.dont_write_bytecode = True   # no __pycache__ beside the sources
from placemat import geometry                                                    # noqa: E402
from placemat.geometry import (CU, CRTYD, FACES, inst_of, ps_add, ps_area_mm2,  # noqa: E402,F401
                      ps_bbox_mm, ps_circle, ps_gap_mm, ps_hits, ps_hull,
                      ps_inter, ps_new)

# The polygon machinery lives in modules/geometry.py so the oracle
# (modules/layout_oracle.py) collides a PROPOSED pose against the same model
# this tool audits.  Names re-exported above for callers importing from here.
MM = geometry.NM                 # nm per mm (historic name in this file)
POLY_ERR_NM = geometry.OCC_ERR_NM
FAB = geometry.FAB_LAYERS

DEF_THT_FILLET = 0.25
DEF_COPPER_CLR = 0.20
DEF_NPTH_CLR = 0.25
DEF_VIA_SLOP = 0.05


# ------------------------------------------------------------------- entities
class Part:
    """A footprint's SAME-FACE body occupancy.

    `poly` is the real courtyard - taken from FOOTPRINT.GetCourtyard(), which
    is the CLOSED region KiCad's own DRC uses.  Transforming the courtyard
    GRAPHICS instead is a trap: a courtyard drawn as an unfilled Rect or four
    Lines transforms to its stroke only, so a pin sitting squarely inside the
    part reads as zero overlap (it cost this tool a full round).
    `body` is the tighter *.Fab outline - what the pin physically hits."""
    __slots__ = ("ref", "inst", "face", "poly", "body", "courtyard", "fp")

    def __init__(self, fp):
        self.fp = fp
        self.ref = fp.GetReference()
        self.inst = inst_of(fp)
        self.face = "B" if fp.IsFlipped() else "F"
        p = ps_new()
        for lay in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            c = fp.GetCourtyard(lay)
            if c.OutlineCount():
                p.BooleanAdd(c)
        self.courtyard = bool(p.OutlineCount())
        pts = []
        for s in fp.GraphicalItems():
            if s.GetLayerName() in FAB:
                t = ps_new()
                ps_add(t, s, s.GetLayer())
                for i in range(t.OutlineCount()):
                    o = t.Outline(i)
                    pts += [(o.CPoint(j).x, o.CPoint(j).y)
                            for j in range(o.PointCount())]
        self.body = ps_hull(pts)        # *.Fab is an unfilled outline; hull it
        if not self.courtyard:          # fallback: pads + fab body, reported
            for pad in fp.Pads():
                ps_add(p, pad, CU[self.face])
            p.BooleanAdd(self.body)
        p.Simplify()
        self.poly = p


class Through:
    """A feature that punches through the board: it occupies BOTH faces.

    `land` is the copper annulus/pad (what shorts to far-side copper); `body`
    is `land` grown by the assembly clearance for that kind (what makes a
    far-side component body unassemblable)."""
    __slots__ = ("kind", "ref", "pin", "net", "inst", "face", "land", "body", "drill")

    def __init__(self, kind, ref, pin, net, inst, face, land, fillet_nm, drill=None):
        self.kind, self.ref, self.pin = kind, ref, pin
        self.net, self.inst, self.face = net, inst, face
        self.land, self.drill = land, drill
        b = pcbnew.SHAPE_POLY_SET(land)
        if fillet_nm:
            b.Inflate(int(fillet_nm), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                      POLY_ERR_NM)
        self.body = b

    @property
    def label(self):
        return "%s%s" % (self.ref, ("." + self.pin) if self.pin else "")


def pads_and_throughs(part, tht_fillet_nm):
    """ONE footprint's cross-face model: its through features, and its pad
    polygons per face.

    Split out of Board._collect_pads so modules/layout_oracle.py can build the
    same model for a HYPOTHETICAL pose without a second implementation.
    Returns (throughs, pads) where pads is {"F": [(label, net, poly, part)],
    "B": [...]}."""
    through, pads = [], {f: [] for f in FACES}
    for pad in part.fp.Pads():
        attr = pad.GetAttribute()
        lbl = "%s.%s" % (part.ref, pad.GetNumber() or "?")
        if attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
            land = ps_new()
            if attr == pcbnew.PAD_ATTRIB_PTH:
                for f in FACES:
                    ps_add(land, pad, CU[f])
            if not land.OutlineCount():        # NPTH: the drill IS it
                c = pad.GetPosition()
                land = ps_circle(c.x, c.y, max(pad.GetDrillSizeX(),
                                               pad.GetDrillSizeY()) / 2)
            c = pad.GetPosition()
            drill = ps_circle(c.x, c.y, max(pad.GetDrillSizeX(),
                                            pad.GetDrillSizeY()) / 2)
            kind = "npth" if attr == pcbnew.PAD_ATTRIB_NPTH else "tht"
            through.append(
                Through(kind, part.ref, pad.GetNumber(), pad.GetNetname(),
                        part.inst, part.face, land, tht_fillet_nm, drill))
        if attr != pcbnew.PAD_ATTRIB_NPTH:
            for f in FACES:
                if pad.IsOnLayer(CU[f]):
                    p = ps_new()
                    ps_add(p, pad, CU[f])
                    pads[f].append((lbl, pad.GetNetname(), p, part))
    return through, pads


class Board:
    """Queryable occupancy for one .kicad_pcb, per face, from real geometry."""

    def __init__(self, path, tht_fillet=DEF_THT_FILLET, npth_clr=DEF_NPTH_CLR,
                 board=None):
        """`board` skips the load and models an already-open BOARD instead -
        how modules/layout_oracle.py reuses this model in-process."""
        self.path = path
        self.pcb = board if board is not None else pcbnew.LoadBoard(path)
        self.tht_fillet = int(tht_fillet * MM)
        self.npth_clr = int(npth_clr * MM)
        self.parts = [Part(fp) for fp in
                      sorted(self.pcb.GetFootprints(), key=lambda f: f.GetReference())]
        self.no_courtyard = [p.ref for p in self.parts if not p.courtyard]
        self.through = []
        self.pads = {"F": [], "B": []}     # (label, net, poly) same-face pads
        self._collect_pads()
        self._collect_vias()
        self.copper = {f: self._copper(f) for f in FACES}
        self.routed = {f: self._routed(f) for f in FACES}
        self.outline = self._outline()
        self._cache = {}

    # -- collectors ----------------------------------------------------------
    def _collect_pads(self):
        for part in self.parts:
            th, pd = pads_and_throughs(part, self.tht_fillet)
            self.through += th
            for f in FACES:
                self.pads[f] += pd[f]

    def _collect_vias(self):
        for t in self.pcb.GetTracks():
            if not isinstance(t, pcbnew.PCB_VIA):
                continue
            if t.GetViaType() != pcbnew.VIATYPE_THROUGH:
                continue                    # blind/buried: not a through feature
            c = t.GetPosition()
            land = ps_circle(c.x, c.y, t.GetWidth(pcbnew.F_Cu) / 2)   # KiCad 10: a via's width is per layer
            drill = ps_circle(c.x, c.y, t.GetDrill() / 2)
            self.through.append(
                Through("via", "via@%.2f,%.2f" % (c.x / MM, c.y / MM), "",
                        t.GetNetname(), "", None, land, 0, drill))

    def _routed(self, face):
        """Copper on one layer EXCLUDING pads: tracks, vias, gr_polys, zones."""
        lay = CU[face]
        p = ps_new()
        for t in self.pcb.GetTracks():
            if t.IsOnLayer(lay):
                ps_add(p, t, lay)
        for d in self.pcb.GetDrawings():
            if isinstance(d, pcbnew.PCB_SHAPE) and d.IsOnLayer(lay):
                ps_add(p, d, lay)
        for i in range(self.pcb.GetAreaCount()):
            z = self.pcb.GetArea(i)
            if z.IsOnLayer(lay):
                p.BooleanAdd(z.GetFilledPolysList(lay))
        p.Simplify()
        return p

    def _copper(self, face):
        """All copper on one layer: pads, tracks, vias, gr_polys, zone fills."""
        lay = CU[face]
        p = ps_new()
        for _, _, poly, _ in self.pads[face]:
            p.BooleanAdd(poly)
        for t in self.pcb.GetTracks():
            if t.IsOnLayer(lay):
                ps_add(p, t, lay)
        for d in self.pcb.GetDrawings():
            if isinstance(d, pcbnew.PCB_SHAPE) and d.IsOnLayer(lay):
                ps_add(p, d, lay)
        for i in range(self.pcb.GetAreaCount()):
            z = self.pcb.GetArea(i)
            if z.IsOnLayer(lay):
                p.BooleanAdd(z.GetFilledPolysList(lay))
        p.Simplify()
        return p

    def _outline(self):
        p = ps_new()
        ok = self.pcb.GetBoardPolygonOutlines(p, False)
        return p if ok and p.OutlineCount() else None

    # -- query API (what a placer calls) -------------------------------------
    def occupancy(self, face, classes=("body", "copper", "through")):
        """Union of everything occupying `face`. Cross-face `through` features
        are included on BOTH faces by construction."""
        key = (face, tuple(sorted(classes)))
        if key in self._cache:
            return self._cache[key]
        p = ps_new()
        if "body" in classes:
            for part in self.parts:
                if part.face == face:
                    p.BooleanAdd(part.poly)
        if "copper" in classes:
            p.BooleanAdd(self.copper[face])
        if "through" in classes:
            for t in self.through:
                p.BooleanAdd(t.body)
        p.Simplify()
        self._cache[key] = p
        return p

    def free_space(self, face, classes=("body", "copper", "through")):
        """Board outline minus occupancy. No outline -> None (a fragment)."""
        if self.outline is None:
            return None
        f = pcbnew.SHAPE_POLY_SET(self.outline)
        f.BooleanSubtract(self.occupancy(face, classes))
        return f

    def fits(self, cell, face, x_mm, y_mm, rot_deg=0.0, classes=None,
             exclude_insts=()):
        """Can `cell` (a CellGeometry) sit at (x,y,rot) on `face`?

        Returns [] if it fits, else a list of conflict dicts.  Occupancy from
        the cell's own instances (and any in `exclude_insts`) is ignored, so a
        cell can be re-placed against the board it is already part of."""
        del classes
        placed = cell.placed(x_mm, y_mm, rot_deg)
        skip = set(exclude_insts) | {cell.name}
        out = []
        for part in self.parts:
            if part.inst in skip:
                continue
            near = placed["body"][part.face]
            a = ps_hits(near, part.poly)
            if a > 0:
                out.append({"class": "body", "with": part.ref, "face": part.face,
                            "area_mm2": round(a, 4)})
        for t in self.through:
            if t.inst in skip:
                continue
            for f in FACES:
                a = ps_hits(placed["body"][f], t.body)
                if a > 0:
                    out.append({"class": "through", "with": t.label, "face": f,
                                "area_mm2": round(a, 4)})
                    break
        for f in FACES:
            a = ps_hits(placed["copper"][f], self._copper_excluding(f, skip))
            if a > 0:
                out.append({"class": "copper", "with": "face %s" % f,
                            "face": f, "area_mm2": round(a, 4)})
        if self.outline is not None:
            for f in FACES:     # copper, not body: connector bodies overhang
                t = pcbnew.SHAPE_POLY_SET(placed["copper"][f])
                t.BooleanSubtract(self.outline)
                a = ps_area_mm2(t)
                if a > 1e-6:
                    out.append({"class": "off-board", "with": "outline",
                                "face": f, "area_mm2": round(a, 4)})
        return out

    def _copper_excluding(self, face, insts):
        p = ps_new()
        for lbl, net, poly, part in self.pads[face]:
            if part.inst not in insts:
                p.BooleanAdd(poly)
        p.Simplify()
        return p


class CellGeometry:
    """A cell's REAL occupancy - member courtyards, copper and through
    features - never its bounding box.

    Held in a local frame anchored at the occupied-union centre so a placer can
    translate/rotate it.  Reports bbox vs occupied area vs fill%, which is the
    measure that matters: a sprawling bbox with small occupied area is BETTER
    than a compact bbox that wastes its interior."""

    def __init__(self, name, parts, throughs, copper_by_face):
        self.name = name
        self.faces = sorted({p.face for p in parts})
        self.body = {f: ps_new() for f in FACES}
        self.copper = {f: pcbnew.SHAPE_POLY_SET(copper_by_face[f]) for f in FACES}
        for p in parts:
            self.body[p.face].BooleanAdd(p.poly)
        for t in throughs:                        # punches both faces
            for f in FACES:
                self.body[f].BooleanAdd(t.body)
        for f in FACES:
            self.body[f].Simplify()
            self.copper[f].Simplify()
        self.refs = sorted(p.ref for p in parts)
        self.n_through = len(throughs)
        allp = ps_new()
        for f in FACES:
            allp.BooleanAdd(self.body[f])
            allp.BooleanAdd(self.copper[f])
        allp.Simplify()
        self.union = allp
        self.bbox = ps_bbox_mm(allp)
        self.occupied_mm2 = ps_area_mm2(allp)
        self.bbox_mm2 = ((self.bbox[2] - self.bbox[0]) *
                         (self.bbox[3] - self.bbox[1])) if self.bbox else 0.0
        self.fill = (self.occupied_mm2 / self.bbox_mm2 * 100) if self.bbox_mm2 else 0.0
        self.anchor = (((self.bbox[0] + self.bbox[2]) / 2,
                        (self.bbox[1] + self.bbox[3]) / 2) if self.bbox else (0, 0))

    def placed(self, x_mm, y_mm, rot_deg=0.0, flip=False):
        """Transformed copies keyed ['body'|'copper'][face]. `flip` mirrors
        left-right about the anchor and swaps faces, as KiCad's flip does."""
        ax = pcbnew.VECTOR2I(int(self.anchor[0] * MM), int(self.anchor[1] * MM))
        dx = int((x_mm - self.anchor[0]) * MM)
        dy = int((y_mm - self.anchor[1]) * MM)
        out = {}
        for kind, src in (("body", self.body), ("copper", self.copper)):
            d = {}
            for f in FACES:
                t = pcbnew.SHAPE_POLY_SET(src[f])
                if rot_deg:
                    t.Rotate(pcbnew.EDA_ANGLE(-rot_deg, pcbnew.DEGREES_T), ax)
                if flip:
                    t.Mirror(ax, pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
                t.Move(pcbnew.VECTOR2I(dx, dy))
                d[("B" if f == "F" else "F") if flip else f] = t
            out[kind] = d
        return out


def _bbox_grow(bb, m):
    return (bb[0] - m, bb[1] - m, bb[2] + m, bb[3] + m)


def _inside(bb, poly):
    p = ps_bbox_mm(poly)
    return p and bb[0] <= p[0] and bb[1] <= p[1] and bb[2] >= p[2] and bb[3] >= p[3]


def cells(board, margin=0.5, min_parts=1, exclusive=False):
    """Group footprints into cells by stable instance path and build each
    cell's REAL geometry.

    Copper attribution: a board file records no owner for a track, via or
    pour, so a copper item is claimed by a cell when it lies wholly inside the
    cell's member-body bbox grown by `margin`.  Unclaimed copper is counted
    and reported - it is board-level routing, not cell territory.

    `exclusive` claims a copper item ONLY when exactly one cell's box contains
    it.  Cells interleave, so their boxes overlap and a shared track would
    otherwise be counted in several cells at once - harmless for a report,
    fatal for a placer, which then sees the same copper collide with itself."""
    groups = {}
    for p in board.parts:
        groups.setdefault(p.inst, []).append(p)
    names, boxes, cu, thr = [], {}, {}, {}
    for name, parts in sorted(groups.items()):
        if len(parts) < min_parts:
            continue
        bb = ps_new()
        for p in parts:
            bb.BooleanAdd(p.poly)
        box = ps_bbox_mm(bb)
        if box is None:
            continue
        names.append(name)
        boxes[name] = _bbox_grow(box, margin)
        cu[name] = {f: ps_new() for f in FACES}
        thr[name] = [t for t in board.through if t.inst == name]
        for f in FACES:
            for lbl, net, poly, part in board.pads[f]:
                if part.inst == name:
                    cu[name][f].BooleanAdd(poly)

    items = [t for t in board.pcb.GetTracks()]
    items += [d for d in board.pcb.GetDrawings() if isinstance(d, pcbnew.PCB_SHAPE)]
    for it in items:
        for f in FACES:
            if not it.IsOnLayer(CU[f]):
                continue
            q = ps_new()
            ps_add(q, it, CU[f])
            owners = [n for n in names if _inside(boxes[n], q)]
            if exclusive and len(owners) != 1:
                continue
            for n in owners:
                cu[n][f].BooleanAdd(q)
                if isinstance(it, pcbnew.PCB_VIA):
                    for th in board.through:
                        if th.kind == "via" and ps_hits(th.land, q) > 0 \
                                and not th.inst:
                            th.inst = n
                            thr[n].append(th)
    return {n: CellGeometry(n, groups[n], thr[n], cu[n]) for n in names}


# --------------------------------------------------------------------- audit
def through_on_pad(t, lbl, net, poly, dst_face, dst_inst, reach_nm, slop_nm):
    """Classify ONE (through feature, pad) pair, or None when they are apart.

    The barrel is copper end to end, so a foreign-net pad anywhere on the stack
    is a SHORT.  A same-net landing inside the pad is ordinary via-in-pad
    (tactic 12), by design - judged against the pad grown by `slop_nm`: a 0.6mm
    land on a 0.5mm-wide 0402 pad protrudes 0.05mm radially and is standard
    practice, so only a land that breaks further out than that is PARTIAL,
    where the barrel mouth sits in open mask and paste wicks down it.

    Shared with modules/layout_oracle.py so a proposed pose is graded by the
    same rule the audit applies to a committed one."""
    if not t.land.BBox(reach_nm).Intersects(poly.BBox()):
        return None
    a = ps_hits(t.land, poly)
    same = (net and net == t.net)
    if a > 0:
        gap = 0.0
        outside = 0.0
        if not same:
            sub = "FOREIGN-SHORT"
        else:
            grown = pcbnew.SHAPE_POLY_SET(poly)
            grown.Inflate(slop_nm, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                          POLY_ERR_NM)
            out = pcbnew.SHAPE_POLY_SET(t.land)
            out.BooleanSubtract(grown)
            outside = ps_area_mm2(out)
            sub = "SAME-NET-IN-PAD" if outside < 1e-3 else "SAME-NET-PARTIAL"
    else:
        g = ps_gap_mm(t.land, poly, reach_nm)
        if g is None:
            return None
        sub = "SAME-NET-CLEAR" if same else "FOREIGN-CLEAR"
        outside = 0.0
        gap = round(g, 3)
    return {"class": "b_through_on_pad", "kind": t.kind,
            "severity": "hard" if sub == "FOREIGN-SHORT" else
                        ("info" if sub == "SAME-NET-IN-PAD" else "flag"),
            "sub": sub, "src": t.label, "src_inst": t.inst,
            "src_face": t.face, "dst": lbl, "dst_inst": dst_inst,
            "dst_face": dst_face, "net": t.net, "dst_net": net,
            "overlap_mm2": round(a, 4), "gap_mm": gap,
            "outside_mm2": round(outside, 4)}


def audit(board, copper_clr=DEF_COPPER_CLR, include_same_face=False,
          via_in_pad_slop=DEF_VIA_SLOP):
    """Every violation the occupancy model can see, per instance.

    (a) through-under-body   a pin/hole under an OPPOSITE-face part.  DRC's
        `pth_inside_courtyard` covers the PTH-pad subset of this, but does not
        separate cross-face (assembly-impossible) from same-face (merely
        tight), does not cover vias, and reports no overlap area.
    (b) through-on-pad       the barrel is copper end to end, so a foreign-net
        pad anywhere on the stack is a SHORT.  Filling the via changes
        nothing.
    (c) courtyard-overlap    same-face part collision, per face.
    (d1) off-board           part or land outside the board outline.
    (d2) npth-copper         copper inside an unplated drill's clearance - the
        drill breaks out into it and there is no barrel to plate it.
    """
    V = []
    reach = int(copper_clr * MM)
    slop = int(via_in_pad_slop * MM)
    parts_by_face = {f: [p for p in board.parts if p.face == f] for f in FACES}

    for t in sorted(board.through, key=lambda t: (t.ref, t.pin)):
        # (a) body
        faces = [f for f in FACES if f != t.face] if t.face else list(FACES)
        for f in faces:
            for part in parts_by_face[f]:
                if part.ref == t.ref:
                    continue
                a = ps_hits(t.body, part.poly)
                if a <= 0:
                    continue
                hard = ps_hits(t.body, part.body) > 0
                V.append({"class": "a_through_under_body", "kind": t.kind,
                          "severity": "hard" if hard and t.kind != "via" else
                                      ("info" if t.kind == "via" else "tight"),
                          "src": t.label, "src_inst": t.inst, "src_face": t.face,
                          "dst": part.ref, "dst_inst": part.inst, "dst_face": f,
                          "net": t.net, "overlap_mm2": round(a, 4),
                          "in_body": hard})
        # (b) pads
        for f in FACES:
            if t.face == f and not include_same_face:
                continue           # same-layer copper: ordinary DRC clearance
            for lbl, net, poly, part in board.pads[f]:
                if part.ref == t.ref:
                    continue
                v = through_on_pad(t, lbl, net, poly, f, part.inst, reach, slop)
                if v:
                    V.append(v)
    return V


def audit_same_face(board):
    """(c) same-face courtyard overlaps, per face.

    NOT delegated to `placemat courtyards` on purpose: that tool reads only
    F.Courtyard and has no face concept, so on a two-sided board it drops every
    bottom part and would compare a top part against a bottom one.  It stays
    the right tool for a single-sided MODULE fragment (it also reports TIGHT
    pairs, which this does not).  --crosscheck-sweep proves they agree there."""
    V = []
    eps = 1000                  # 0.001mm: courtyards sharing an EXACT edge are
    for f in FACES:             # a defect (house rule), and DRC counts them.
        ps = [p for p in board.parts if p.face == f and p.poly.OutlineCount()]
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                a = ps_hits(ps[i].poly, ps[j].poly)
                if a <= 0:
                    t = pcbnew.SHAPE_POLY_SET(ps[i].poly)
                    t.Inflate(eps, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                              POLY_ERR_NM)
                    if ps_hits(t, ps[j].poly) <= 0:
                        continue
                # Two members of ONE stamped cell overlapping is the cell's own
                # business: its fragment DRC already reports it, and a cell may
                # place a small part inside a package's courtyard corner on
                # purpose (documented on its card). The board gate reports it
                # as information; a cross-cell overlap is a hard fail.
                same_cell = ps[i].inst == ps[j].inst
                V.append({"class": "c_courtyard_overlap/" + ("cell-internal" if same_cell else "cross-cell"),
                          "severity": "info" if same_cell else "hard",
                          "src": ps[i].ref, "src_inst": ps[i].inst,
                          "dst": ps[j].ref, "dst_inst": ps[j].inst,
                          "src_face": f, "dst_face": f,
                          "overlap_mm2": round(a, 4)})
    return V


def crosscheck_sweep(path, V):
    """Prove class (c) agrees with `placemat courtyards` where the sweep is
    valid (single-sided).  Returns (mine, sweep) overlap counts."""
    import subprocess
    tool = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "courtyard_sweep.py")
    r = subprocess.run([sys.executable, tool, path, "0.0"],
                       capture_output=True, text=True)
    n = sum(1 for ln in r.stdout.splitlines() if ln.strip().startswith("OVERLAP"))
    return sum(1 for v in V if v["class"].startswith("c_courtyard_overlap")), n


def _group_name(it):
    """The cell an orphaned item came from, so a finding names what to fix."""
    g = it.GetParentGroup()
    return g.GetName() if g is not None else ""


def audit_extras(board, npth_clr=DEF_NPTH_CLR):
    """(d1) a PAD off the board (hard) / a courtyard overhanging it (info);
    (d2) foreign copper inside an unplated drill's clearance;
    (d3) a track, via or drawing sitting outside the outline (hard).

    Only pads are hard here: an edge-entry connector's courtyard and plastic
    body overhang the edge BY DESIGN (skill tactic 7), so flagging the
    courtyard would fire on every correctly-placed field connector.  A pad
    outside the outline is unmanufacturable in any reading."""
    V = []
    if board.outline is not None:
        for part in board.parts:
            pa = ps_new()
            for pad in part.fp.Pads():
                for f in FACES:
                    if pad.IsOnLayer(CU[f]):
                        ps_add(pa, pad, CU[f])
            for shape, cls, sev in ((pa, "d1_pad_off_board", "hard"),
                                    (part.poly, "d1_courtyard_overhang", "info")):
                t = pcbnew.SHAPE_POLY_SET(shape)
                t.BooleanSubtract(board.outline)
                a = ps_area_mm2(t)
                if a > 1e-4:
                    V.append({"class": cls, "severity": sev, "src": part.ref,
                              "src_inst": part.inst, "src_face": part.face,
                              "dst": "outline", "overlap_mm2": round(a, 4)})
    # (d3) copper or silk sitting outside the outline. Only stamp() moves a
    # cell's group, so a cell whose members are placed one by one leaves its
    # fragment's tracks, vias and knockout labels AT THE FRAGMENT ORIGIN, tens
    # of millimetres away. Nothing else notices: the parts are on the board, so
    # the pad checks pass, and DRC calls the orphaned copper dangling rather
    # than misplaced. Measured against the outline's own bounding box plus a
    # millimetre, so a label that overhangs an edge is not a finding.
    if board.outline is not None:
        bb = board.outline.BBox()
        lo_x, lo_y = bb.GetLeft() / MM - 1.0, bb.GetTop() / MM - 1.0
        hi_x, hi_y = bb.GetRight() / MM + 1.0, bb.GetBottom() / MM + 1.0
        for it in list(board.pcb.GetTracks()) + list(board.pcb.GetDrawings()):
            ib = it.GetBoundingBox()
            if (ib.GetLeft() / MM >= lo_x and ib.GetTop() / MM >= lo_y
                    and ib.GetRight() / MM <= hi_x and ib.GetBottom() / MM <= hi_y):
                continue
            V.append({"class": "d3_item_off_board", "severity": "hard",
                      "src": it.GetClass(), "src_inst": _group_name(it),
                      "src_face": "", "dst": "outline",
                      "at": [round(ib.GetLeft() / MM, 1), round(ib.GetTop() / MM, 1)]})
    for t in board.through:
        if t.kind != "npth":
            continue
        k = pcbnew.SHAPE_POLY_SET(t.drill)
        k.Inflate(int(npth_clr * MM), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                  POLY_ERR_NM)
        for f in FACES:
            for lbl, net, poly, part in board.pads[f]:
                if part.ref == t.ref:
                    continue        # the connector's own shell pads: part-forced
                a = ps_hits(k, poly)
                if a > 0:
                    V.append({"class": "d2_npth_copper", "severity": "hard",
                              "src": t.label, "src_inst": t.inst, "src_face": f,
                              "dst": lbl, "dst_face": f,
                              "overlap_mm2": round(a, 4)})
            a = ps_hits(k, board.routed[f])
            if a > 0:
                V.append({"class": "d2_npth_copper", "severity": "hard",
                          "src": t.label, "src_inst": t.inst, "src_face": f,
                          "dst": "routed copper %s" % f,
                          "overlap_mm2": round(a, 4)})
    return V


# ----------------------------------------------------------------------- CLI
def _boards(targets, root):
    out = []
    for t in targets or [root]:
        if t.endswith(".kicad_pcb"):
            out.append(os.path.abspath(t))
        elif os.path.isdir(t):
            for f in sorted(glob.glob(os.path.join(t, "*", "layout", "*",
                                                   "layout.kicad_pcb"))):
                if os.sep + "_" not in f:      # skip probe/scratch mills
                    out.append(f)
    return out


def _summary(V):
    s = {}
    for v in V:
        k = "%s/%s" % (v["class"], v.get("sub") or v.get("kind") or "")
        s.setdefault(k, {"hard": 0, "tight": 0, "flag": 0, "info": 0})
        s[k][v["severity"]] += 1
    return s


def run(path, args):
    b = Board(path, tht_fillet=args.tht_fillet, npth_clr=args.npth_clearance)
    V = audit(b, copper_clr=args.copper_clearance,
              include_same_face=args.include_same_face,
              via_in_pad_slop=args.via_in_pad_slop)
    if not args.no_courtyard_check:
        V += audit_same_face(b)
    V += audit_extras(b, npth_clr=args.npth_clearance)
    xcheck = crosscheck_sweep(path, V) if args.crosscheck_sweep else None
    occ = {f: ps_area_mm2(b.occupancy(f)) for f in FACES}
    free = {f: (ps_area_mm2(b.free_space(f)) if b.outline is not None else None)
            for f in FACES}
    rec = {"path": path, "parts": len(b.parts), "through": len(b.through),
           "no_courtyard": b.no_courtyard,
           "board_mm2": round(ps_area_mm2(b.outline), 1) if b.outline is not None
                        else None,
           "occupied_mm2": {f: round(occ[f], 1) for f in FACES},
           "free_mm2": {f: (round(free[f], 1) if free[f] is not None else None)
                        for f in FACES},
           "summary": _summary(V), "crosscheck_sweep": xcheck,
           "violations": V}
    if args.cells:
        cs = cells(b, margin=args.cell_margin, min_parts=args.min_parts)
        rec["cells"] = [{"name": c.name, "parts": len(c.refs),
                         "faces": c.faces, "through": c.n_through,
                         "bbox": [round(v, 2) for v in c.bbox] if c.bbox else None,
                         "bbox_mm2": round(c.bbox_mm2, 1),
                         "occupied_mm2": round(c.occupied_mm2, 1),
                         "fill_pct": round(c.fill, 1)}
                        for c in sorted(cs.values(),
                                        key=lambda c: -c.bbox_mm2)]
    return b, rec


def _print(rec, args):
    name = os.path.basename(os.path.dirname(rec["path"]))
    print("\n== %s  (%s)" % (name, rec["path"]))
    print("   %d parts, %d through-features%s" %
          (rec["parts"], rec["through"],
           ", board %.1f mm2" % rec["board_mm2"] if rec["board_mm2"] else
           ", no board outline"))
    for f in FACES:
        print("   %s.Cu occupied %8.1f mm2   free %s" %
              (f, rec["occupied_mm2"][f],
               "%8.1f mm2" % rec["free_mm2"][f] if rec["free_mm2"][f] is not None
               else "n/a"))
    if rec.get("crosscheck_sweep"):
        m, n = rec["crosscheck_sweep"]
        print("   crosscheck courtyard_sweep: mine %d, sweep %d  %s"
              % (m, n, "AGREE" if m == n else "DISAGREE"))
    if rec["no_courtyard"]:
        print("   NO COURTYARD (pad+fab fallback): %s"
              % ", ".join(rec["no_courtyard"]))
    for k in sorted(rec["summary"]):
        c = rec["summary"][k]
        print("   %-34s hard %3d  tight %3d  flag %3d  info %3d"
              % (k, c["hard"], c["tight"], c["flag"], c["info"]))
    sev = {"hard": 0, "tight": 1, "flag": 2, "info": 3}
    shown = [v for v in rec["violations"]
             if args.verbose or v["severity"] in ("hard", "tight")]
    shown.sort(key=lambda v: (sev[v["severity"]], v["class"], v["src"]))
    for v in shown[:args.top]:
        print("   %-5s %-22s %-12s %s%s -> %-12s %s%s  %.4f mm2%s"
              % (v["severity"], v["class"].split("_", 1)[1],
                 v["src"], v.get("src_face") or "*", "",
                 v.get("dst", ""), v.get("dst_face", ""),
                 "" if not v.get("sub") else " " + v["sub"],
                 v.get("overlap_mm2", 0.0),
                 "" if not v.get("gap_mm") else "  gap %.3f" % v["gap_mm"]))
    if len(shown) > args.top:
        print("   ... %d more (--top N, --json for all)" % (len(shown) - args.top))
    for c in rec.get("cells", [])[:args.top]:
        print("   cell %-16s %2d parts %-4s bbox %7.1f  occupied %7.1f  "
              "fill %5.1f%%" % (c["name"], c["parts"], "/".join(c["faces"]),
                                c["bbox_mm2"], c["occupied_mm2"], c["fill_pct"]))



def parser():
    """The arguments this command takes."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("targets", nargs="*", type=board_arg,
                    help="board names, or paths (default: every board)")
    ap.add_argument("--tht-fillet", type=float, default=DEF_THT_FILLET)
    ap.add_argument("--copper-clearance", type=float, default=DEF_COPPER_CLR)
    ap.add_argument("--npth-clearance", type=float, default=DEF_NPTH_CLR)
    ap.add_argument("--via-in-pad-slop", type=float, default=DEF_VIA_SLOP,
                    help="radial annulus allowed outside a same-net pad before "
                         "a via-in-pad counts as PARTIAL (mm)")
    ap.add_argument("--include-same-face", action="store_true",
                    help="class (b) also on the through's own face (DRC's job)")
    ap.add_argument("--crosscheck-sweep", action="store_true",
                    help="compare class (c) with `placemat courtyards` "
                         "(only valid on single-sided fragments)")
    ap.add_argument("--no-courtyard-check", action="store_true",
                    help="skip class (c) (slow on big boards)")
    ap.add_argument("--cells", action="store_true",
                    help="report each cell as bbox / occupied-union / fill%%")
    ap.add_argument("--cell-margin", type=float, default=0.5,
                    help="copper attribution margin around a cell's bodies")
    ap.add_argument("--min-parts", type=int, default=2)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--verbose", action="store_true", help="list flag/info too")
    json_option(ap, "the full model and every violation")
    return ap


def main(args=None):
    args = args if args is not None else parser().parse_args()
    _out = hush(args.json)   # with --json the JSON is the answer

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = _boards(args.targets, root)
    if not paths:
        print("no board layouts found", file=sys.stderr)
        return 2
    recs, hard = [], 0
    for p in paths:
        _, rec = run(p, args)
        recs.append(rec)
        _print(rec, args)
        hard += sum(1 for v in rec["violations"] if v["severity"] == "hard")
    print("\n%-16s %6s %6s %6s %6s %6s %6s" %
          ("board", "parts", "thru", "a-hard", "b-short", "c-ovl", "d"))
    for r in recs:
        s = r["summary"]
        count = lambda pre, sev="hard": sum(v[sev] for k, v in s.items()
                                            if k.startswith(pre))
        print("%-16s %6d %6d %6d %6d %6d %6d" %
              (os.path.basename(os.path.dirname(r["path"])), r["parts"],
               r["through"], count("a_"), count("b_"), count("c_"), count("d")))
    print("\n%d hard violations across %d boards" % (hard, len(recs)))
    unhush(_out)
    emit(recs, args.json)
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
