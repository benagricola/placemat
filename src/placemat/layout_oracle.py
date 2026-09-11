#!/usr/bin/env python3
"""The geometry oracle: questions a layout script asks BEFORE it commits copper.

The gates only speak after the board is written. `Oracle` answers the same
questions in-process, from the same exact-polygon model the gates use
(`placemat.geometry`, `placemat occupancy`), so a script can test a
coordinate before it commits to it.

    from placemat.layout_oracle import Oracle
    o = Oracle(layout.pcb)                       # layout is a ModuleLayout; or layout.oracle
    r = o.clear("V48", 10, 10, 22, 10, "F.Cu", 0.8)
    if not r["ok"]:
        print("blocked by %s (%s) at %.3f mm" % (r["blocker"], r["blocker_net"],
                                                 r["gap_mm"]))

Everything returned is plain Python - floats in mm, strings, lists, dicts.  No
SWIG object ever leaves a method, so a caller can print, json-dump or diff an
answer.  Every failure names the blocker.

STATE.  The model is built lazily on first use and then cached: the copper
index, the occupancy model, the connectivity clusters and the net classes.
After the script mutates the board (a `place()`, a `track()`, a `poly()`), call
`refresh()`.  Nothing here auto-invalidates - an oracle that silently rebuilt
on every query would cost more than the sweep it replaces.

WHAT IT DOES NOT KNOW.  Height, assembly order, mating volume (the occupancy
model is 2D - see its docstring).  Length matching and impedance.  Declared but
unfilled keepouts.  It measures what is on the board, not what a cell is
entitled to.
"""
import fnmatch
import json
import math
import os
import sys
import time

import pcbnew

_HERE = os.path.dirname(os.path.abspath(__file__))

from placemat import geometry                                                    # noqa: E402
from placemat.tools import board_occupancy as occ                    # noqa: E402
from placemat.geometry import (FACES, ps_area_mm2, ps_bbox_mm,               # noqa: E402
                      ps_hits, ps_new)

# 0.0005 mm: half the 3-decimal report resolution the clearance gate uses, and
# the same slack `module_clearance.analyse` allows before calling a pair under
# its floor.  A gap inside this of the floor is a pass, not a failure.
EPS = 5e-4

# Search radii for a clearance query, in mm.  Nearly every answer is found in
# the first ring; the last entry means "give up on the index and look at every
# item on the layer", so the answer is exact even on an empty board corner.
RINGS = (1.0, 4.0, 16.0, None)

# A courtyard pair that shares an exact edge is a defect (house rule, and DRC
# counts it), so courtyards are tested inflated by this much.
TOUCH_NM = 1000


def _mm(v):
    return v / geometry.NM


def _nm(v):
    return int(round(v * geometry.NM))


class Oracle:
    """Geometry queries against one open BOARD.

        o = Oracle(board)                 # board is a pcbnew.BOARD
        o.clear(...); o.fits(...); o.unrouted()
        o.refresh()                       # after mutating the board

    `path` defaults to the board's own filename and is only used to find the
    sibling `.kicad_pro` when net classes have to be read from it.
    """

    def __init__(self, board, path=None, tht_fillet=occ.DEF_THT_FILLET,
                 npth_clr=occ.DEF_NPTH_CLR, cell_mm=4.0):
        self.pcb = board
        self.path = path or board.GetFileName()
        self.tht_fillet = tht_fillet
        self.npth_clr = npth_clr
        self.cell_mm = cell_mm
        self.timing_ms = {}
        self.netclass_source = None
        self.refresh()

    # ------------------------------------------------------------- lifecycle
    def refresh(self):
        """Drop every cache. Call after any mutation of the board.

        Returns self, so `o.refresh().clear(...)` reads as one thought.

            >>> layout.track("V48", 0.8, 10, 10, 22, 10)    # doctest: +SKIP
            >>> layout.oracle.refresh().clear("GND", 10, 12, 22, 12, "F.Cu", 0.3)
            {'gap_mm': 1.45, ...}
        """
        self._items = None
        self._index = None
        self._occ = None
        self._clusters = None
        self._cluster_objs = None
        self._nc = {}
        self._pro = None
        self._fps = None
        self._cellbox = {}
        self._frontier = {}
        self._pboxes = None
        self._tboxes = None
        self._padboxes = None
        self._netitems = {}
        return self

    # ------------------------------------------------------------ lazy model
    @property
    def items(self):
        """Every copper item on the board as a geometry.Item (cached)."""
        if self._items is None:
            t0 = time.time()
            self._items = geometry.collect(self.pcb)
            self.timing_ms["collect"] = (time.time() - t0) * 1000
        return self._items

    @property
    def index(self):
        """Bbox-binned spatial index over `items`, per copper layer (cached)."""
        if self._index is None:
            t0 = time.time()
            self._index = geometry.SpatialIndex(self.items, self.cell_mm)
            self.timing_ms["index"] = (time.time() - t0) * 1000
        return self._index

    @property
    def occ(self):
        """The two-face occupancy model (tools/board_occupancy.Board), cached."""
        if self._occ is None:
            t0 = time.time()
            self._occ = occ.Board(self.path, tht_fillet=self.tht_fillet,
                                  npth_clr=self.npth_clr, board=self.pcb)
            self.timing_ms["occupancy"] = (time.time() - t0) * 1000
        return self._occ

    @property
    def footprints(self):
        if self._fps is None:
            self._fps = {fp.GetReference(): fp for fp in self.pcb.GetFootprints()}
        return self._fps

    @property
    def part_boxes(self):
        """ref -> courtyard bbox in mm, so a pose test can skip far parts."""
        if self._pboxes is None:
            self._pboxes = {p.ref: ps_bbox_mm(p.poly) for p in self.occ.parts}
        return self._pboxes

    @property
    def through_boxes(self):
        """Parallel to occ.through: each through feature's body bbox in mm."""
        if self._tboxes is None:
            self._tboxes = [ps_bbox_mm(t.body) for t in self.occ.through]
        return self._tboxes

    @property
    def pad_boxes(self):
        """Parallel to occ.pads[face]: each pad polygon's bbox in mm."""
        if self._padboxes is None:
            self._padboxes = {f: [ps_bbox_mm(e[2]) for e in self.occ.pads[f]]
                              for f in FACES}
        return self._padboxes

    def _same_net(self, net, layer_id):
        """Copper items on one net and layer (cached) - what a stub can land on."""
        key = (net, layer_id)
        if key not in self._netitems:
            self._netitems[key] = [it for it in self.items
                                   if it.net == net and layer_id in it.layers]
        return self._netitems[key]

    def _fp(self, ref):
        fp = self.footprints.get(ref)
        if fp is None:
            raise KeyError("no footprint %r on this board (have %d)"
                           % (ref, len(self.footprints)))
        return fp

    def _layer_id(self, layer):
        """"F.Cu" or an int -> the layer id, with a loud error for a typo."""
        if isinstance(layer, int):
            return layer
        lid = self.pcb.GetLayerID(layer)
        if lid < 0:
            names = [self.pcb.GetLayerName(l)
                     for l in self.pcb.GetEnabledLayers().CuStack()]
            raise KeyError("no layer %r on this board; copper layers are %s"
                           % (layer, names))
        return lid

    # ============================================================ net classes
    def _pro_patterns(self):
        """netclass_patterns + netclass_assignments from the sibling .kicad_pro."""
        if self._pro is None:
            pro = os.path.splitext(self.path)[0] + ".kicad_pro" if self.path else ""
            self._pro = {"classes": {}, "patterns": [], "assign": {}}
            if pro and os.path.exists(pro):
                try:
                    d = json.load(open(pro))
                    ns = d.get("net_settings") or {}
                    for c in ns.get("classes") or []:
                        self._pro["classes"][c.get("name")] = c
                    for p in ns.get("netclass_patterns") or []:
                        self._pro["patterns"].append((p.get("pattern"),
                                                      p.get("netclass")))
                    self._pro["assign"] = ns.get("netclass_assignments") or {}
                except Exception as e:
                    raise RuntimeError("cannot read net classes from %s: %s"
                                       % (pro, e))
        return self._pro

    def _pro_netclass(self, net):
        """Fallback resolution: apply the .kicad_pro patterns ourselves.

        Only reached when pcbnew resolved every net to Default while the
        project file declares classes - i.e. the board was opened away from its
        project.  KiCad matches a net name against a pattern with `*` and `?`
        wildcards, case-sensitively; `fnmatch.fnmatchcase` is that, plus a
        `[seq]` form KiCad does not have.  KiCad composites every matching
        class; this takes the FIRST match in file order, which is the same
        answer whenever a net matches one pattern (every pattern in this repo).
        """
        pro = self._pro_patterns()
        name = pro["assign"].get(net)
        if name is None:
            for pattern, cls in pro["patterns"]:
                if pattern and fnmatch.fnmatchcase(net, pattern):
                    name = cls
                    break
        cls = pro["classes"].get(name or "Default") or {}
        dflt = pro["classes"].get("Default") or {}

        def v(key, fallback):
            return float(cls.get(key, dflt.get(key, fallback)))

        return {"name": name or "Default",
                "track_width": v("track_width", 0.2),
                "clearance": v("clearance", 0.2),
                "via_diameter": v("via_diameter", 0.6),
                "via_drill": v("via_drill", 0.3),
                "diff_pair_width": v("diff_pair_width", 0.2),
                "diff_pair_gap": v("diff_pair_gap", 0.25),
                "source": "kicad_pro"}

    def netclass(self, net):
        """The resolved net class for `net`, all widths and gaps in mm.

        Returns dict(name, track_width, clearance, via_diameter, via_drill,
        diff_pair_width, diff_pair_gap, source).  `name` is the effective class
        with KiCad's implicit `Default` constituent dropped, so a net assigned
        by pattern reads as that pattern's class.  `source` is "pcbnew" when
        KiCad resolved it (the normal path: `LoadBoard` reads the sibling
        `.kicad_pro`, and NETINFO_ITEM.GetNetClassSlow() then returns the
        pattern-assigned class) or "kicad_pro" when the patterns had to be
        applied here because the board was opened away from its project.

            >>> o.netclass("V48")                      # doctest: +SKIP
            {'name': 'HV_BUS', 'track_width': 1.0, 'clearance': 0.25,
             'via_diameter': 0.6, 'via_drill': 0.3, 'diff_pair_width': 0.2,
             'diff_pair_gap': 0.25, 'source': 'pcbnew'}
        """
        if net in self._nc:
            return self._nc[net]
        ni = self.pcb.FindNet(net)
        if ni is None:
            raise KeyError("no net named %r on this board" % net)
        nc = ni.GetNetClassSlow()
        parts = [p for p in str(nc.GetName()).split(",") if p]
        named = [p for p in parts if p != "Default"]
        r = {"name": ",".join(named) if named else "Default",
             "track_width": _mm(nc.GetTrackWidth()),
             "clearance": _mm(nc.GetClearance()),
             "via_diameter": _mm(nc.GetViaDiameter()),
             "via_drill": _mm(nc.GetViaDrill()),
             "diff_pair_width": _mm(nc.GetDiffPairWidth()),
             "diff_pair_gap": _mm(nc.GetDiffPairGap()),
             "source": "pcbnew"}
        if r["name"] == "Default" and self._pro_patterns()["patterns"]:
            fallback = self._pro_netclass(net)
            if fallback["name"] != "Default":
                r = fallback
        self.netclass_source = r["source"]
        self._nc[net] = r
        return r

    def clearance(self, net_a, net_b=None):
        """The clearance in mm that must hold between two nets.

        KiCad's rule: the larger of the two net classes' clearances, never
        below the board's own minimum.  `net_b=None` asks what `net_a` owes
        anything else on the board.

            >>> o.clearance("V48", "GND")              # doctest: +SKIP
            0.25
        """
        c = self.netclass(net_a)["clearance"]
        if net_b:
            c = max(c, self.netclass(net_b)["clearance"])
        return max(c, _mm(self.pcb.GetDesignSettings().m_MinClearance))

    # ============================================================== clearance
    def _near(self, item, layer_id, net, radius, include_unnetted):
        """Foreign-net copper items on `layer_id` within `radius` mm."""
        if radius is None:
            cand = [it for it in self.items if layer_id in it.layers]
        else:
            cand = self.index.near(item.bbox, layer_id, radius)
        out = []
        for it in cand:
            if it.net == net:
                continue
            if not it.net and not include_unnetted:
                continue
            out.append(it)
        return out

    def _measure(self, item, layer_id, net, cutoff=None, skip=(),
                 include_unnetted=True):
        """(gap, blocker) over foreign copper, growing the search until found.

        `cutoff` stops the search once something closer than it is found - a
        corridor test does not care how far the next-nearest item is."""
        best, who = math.inf, None
        seen = set()
        for radius in RINGS:
            reach = radius if radius is not None else 1e9
            for it in self._near(item, layer_id, net, radius, include_unnetted):
                if id(it) in seen:
                    continue
                seen.add(id(it))
                if it.fp is not None and it.fp in skip:
                    continue
                if geometry.bbox_gap(item.bbox, it.bbox) >= best:
                    continue
                limit = min(best, reach)
                d = geometry.poly_dist_within(item.outlines, it.outlines, limit,
                                              it.segments)
                if d < best:
                    best, who = d, it
            if who is not None and (radius is None or best <= radius):
                break
            if cutoff is not None and best <= cutoff:
                break
        return best, who

    def clear(self, net, x1, y1, x2, y2, layer, w, clearance_mm=None,
              include_unnetted=True):
        """Minimum gap from a PROPOSED segment to foreign copper on one layer.

        The segment is a stadium of width `w` (KiCad's own track shape), so a
        proposed run measures exactly what the same run would measure once
        committed.  Pads, tracks, vias, netted gr_poly and zone fill all count;
        same-net copper does not.  Unnetted copper is an obstacle by default
        (it is physically in the way) - pass include_unnetted=False to match
        the clearance gate, which judges net pairs only.

        Returns dict(gap_mm, blocker, blocker_net, ok, clearance_mm, layer).
        `gap_mm` is None when nothing foreign shares the layer.  `ok` compares
        the gap against `clearance_mm`, defaulting to this net's class
        clearance.

            >>> o.clear("V48", 10, 10, 22, 10, "F.Cu", 0.8)   # doctest: +SKIP
            {'gap_mm': 0.31, 'blocker': 'C12.1', 'blocker_net': 'GND',
             'ok': True, 'clearance_mm': 0.25, 'layer': 'F.Cu'}
        """
        lid = self._layer_id(layer)
        clr = self.clearance(net) if clearance_mm is None else float(clearance_mm)
        item = geometry.segment_item(self.pcb, net, x1, y1, x2, y2, lid, w)
        gap, who = self._measure(item, lid, net, include_unnetted=include_unnetted)
        return {"gap_mm": None if who is None else round(gap, 4),
                "blocker": None if who is None else who.name,
                "blocker_net": None if who is None else (who.net or "<no net>"),
                "ok": who is None or gap >= clr - EPS,
                "clearance_mm": round(clr, 4),
                "layer": self.pcb.GetLayerName(lid)}

    def corridor(self, net, p, q, layer, w, clearance_mm=None,
                 include_unnetted=True):
        """Is the run from `p` to `q` free, and if not, what is in the way?

        Same geometry as `clear`, but every item closer than the clearance is
        listed, nearest first, so the caller sees the whole obstruction rather
        than only its worst point.

        Returns dict(ok, blockers, clearance_mm, gap_mm, layer) where each
        blocker is dict(name, net, gap).

            >>> o.corridor("PERMIT_A", (10, 10), (10, 30), "F.Cu", 0.25)
            ... # doctest: +SKIP
            {'ok': False, 'gap_mm': 0.0, 'clearance_mm': 0.2,
             'blockers': [{'name': 'poly@12.40,18.60', 'net': 'V48P',
                           'gap': 0.0}], 'layer': 'F.Cu'}
        """
        lid = self._layer_id(layer)
        clr = self.clearance(net) if clearance_mm is None else float(clearance_mm)
        item = geometry.segment_item(self.pcb, net, p[0], p[1], q[0], q[1], lid, w)
        blockers = []
        seen = set()
        for it in self._near(item, lid, net, max(clr * 4, 1.0), include_unnetted):
            if id(it) in seen:
                continue
            seen.add(id(it))
            if geometry.bbox_gap(item.bbox, it.bbox) > clr:
                continue
            d = geometry.poly_dist_within(item.outlines, it.outlines, clr,
                                          it.segments)
            if d < clr - EPS:
                blockers.append({"name": it.name, "net": it.net or "<no net>",
                                 "gap": round(d, 4)})
        blockers.sort(key=lambda b: b["gap"])
        return {"ok": not blockers,
                "gap_mm": blockers[0]["gap"] if blockers else None,
                "clearance_mm": round(clr, 4), "blockers": blockers,
                "layer": self.pcb.GetLayerName(lid)}

    # ================================================================== fits
    def _pose_model(self, ref, x, y, rot, face):
        """The footprint's model at a HYPOTHETICAL pose. Move, snapshot, restore.

        The real footprint is moved for the duration of the snapshot and put
        back in a `finally`, so a caller can test a pose (including a face
        flip) for a part that is currently somewhere else.  Nothing is saved
        and no other item is touched."""
        fp = self._fp(ref)
        old_pos = pcbnew.VECTOR2I(fp.GetPosition())
        old_rot = fp.GetOrientation()
        old_flip = fp.IsFlipped()
        want_flip = (face == "B")
        try:
            if want_flip != old_flip:
                fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
            fp.SetOrientationDegrees(rot)
            fp.SetPosition(pcbnew.VECTOR2I(_nm(x), _nm(y)))
            part = occ.Part(fp)
            through, pads = occ.pads_and_throughs(part, _nm(self.tht_fillet))
            cu = geometry.pad_items(fp)
            return {"part": part, "through": through, "pads": pads, "copper": cu,
                    "box": ps_bbox_mm(part.poly)}
        finally:
            if fp.IsFlipped() != old_flip:
                fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
            fp.SetOrientation(old_rot)
            fp.SetPosition(old_pos)

    def _fits_blockers(self, model, ref, clearance_mm, skip):
        """Every conflict of a posed footprint against the committed board.

        The vocabulary is board_occupancy's, so a blocker here and a violation
        in the gate's report read the same:
          c_courtyard_overlap   same-face body against body
          copper_clearance      this part's pads against same-layer foreign copper
          a_through_under_body  a through feature under an opposite-face body
          b_through_on_pad      a through feature landing on a pad
          d1_pad_off_board      a pad outside the board outline
        """
        return (self._courtyard_conflicts(model, ref, skip)
                + self._pad_copper_conflicts(model, clearance_mm, skip)
                + self._pin_under_body(model, ref, skip)
                + self._through_on_pad(model, ref, skip)
                + self._pads_off_board(model, ref))

    def _courtyard_conflicts(self, model, ref, skip):
        """Same-face body against body. An exact shared edge is a defect too."""
        part = model["part"]
        box, out = model["box"], []
        touch = TOUCH_NM / geometry.NM
        for other in self.occ.parts:
            if other.ref in skip or other.face != part.face:
                continue
            if not other.poly.OutlineCount() or not part.poly.OutlineCount():
                continue
            ob = self.part_boxes.get(other.ref)
            if box and ob and geometry.bbox_gap(box, ob) > touch:
                continue
            a = ps_hits(part.poly, other.poly)
            if a <= 0:
                t = pcbnew.SHAPE_POLY_SET(part.poly)
                t.Inflate(TOUCH_NM, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                          geometry.OCC_ERR_NM)
                if ps_hits(t, other.poly) <= 0:
                    continue
            out.append({"class": "c_courtyard_overlap", "severity": "hard",
                        "src": ref, "dst": other.ref, "dst_inst": other.inst,
                        "face": part.face, "overlap_mm2": round(a, 4)})
        return out

    def _pad_copper_conflicts(self, model, clearance_mm, skip):
        """This part's pads against foreign copper on the same layer."""
        out = []
        for it in model["copper"]:
            net = it.net
            clr = (self.clearance(net) if clearance_mm is None and net
                   else (clearance_mm if clearance_mm is not None else 0.0))
            if not clr:
                continue
            for lid in sorted(it.layers):
                gap, who = self._measure(it, lid, net, cutoff=clr, skip=skip)
                if who is not None and gap < clr - EPS:
                    out.append({"class": "copper_clearance", "severity": "hard",
                                "src": it.name, "dst": who.name,
                                "dst_net": who.net or "<no net>",
                                "face": self.pcb.GetLayerName(lid),
                                "gap_mm": round(gap, 4),
                                "clearance_mm": round(clr, 4)})
                    break
        return out

    def _pin_under_body(self, model, ref, skip):
        """Through features under a body, both directions.

        A pin's lead and fillet land on the far face, so a pin under an
        opposite-face body is assembly-impossible whatever the nets are.  A via
        has no lead: tented under a body is normal practice, so it is reported
        at `info` and does not fail the pose."""
        part = model["part"]
        face, box, out = part.face, model["box"], []
        for t in model["through"]:               # our pin, their body
            tb = ps_bbox_mm(t.body)
            for other in self.occ.parts:
                if other.ref in skip or other.face == face:
                    continue
                ob = self.part_boxes.get(other.ref)
                if tb and ob and geometry.bbox_gap(tb, ob) > 0:
                    continue
                a = ps_hits(t.body, other.poly)
                if a <= 0:
                    continue
                hard = ps_hits(t.body, other.body) > 0
                out.append({"class": "a_through_under_body", "kind": t.kind,
                            "severity": "hard" if hard else "tight",
                            "src": t.label, "dst": other.ref,
                            "dst_inst": other.inst, "face": other.face,
                            "overlap_mm2": round(a, 4), "in_body": hard})
        for i, t in enumerate(self.occ.through):   # their pin, our body
            if t.ref in skip:
                continue
            if t.face is not None and t.face == face:
                continue                       # same-face pin: DRC's business
            tb = self.through_boxes[i]
            if box and tb and geometry.bbox_gap(box, tb) > 0:
                continue
            a = ps_hits(t.body, part.poly)
            if a <= 0:
                continue
            hard = ps_hits(t.body, part.body) > 0
            out.append({"class": "a_through_under_body", "kind": t.kind,
                        "severity": "info" if t.kind == "via" else
                                    ("hard" if hard else "tight"),
                        "src": t.label, "dst": ref, "dst_inst": t.inst,
                        "face": face, "overlap_mm2": round(a, 4),
                        "in_body": hard})
        return out

    def _pads_off_board(self, model, ref):
        """Copper outside the board outline. A courtyard may overhang; a pad
        may not - an edge-entry connector's body hangs over by design."""
        if self.occ.outline is None:
            return []
        pa = ps_new()
        for f in FACES:
            for _, _, poly, _ in model["pads"][f]:
                pa.BooleanAdd(poly)
        t = pcbnew.SHAPE_POLY_SET(pa)
        t.BooleanSubtract(self.occ.outline)
        a = ps_area_mm2(t)
        if a <= 1e-4:
            return []
        return [{"class": "d1_pad_off_board", "severity": "hard", "src": ref,
                 "dst": "outline", "face": model["part"].face,
                 "overlap_mm2": round(a, 4)}]

    def _through_on_pad(self, model, ref, skip):
        """Both directions of `b_through_on_pad` for a posed footprint.

        Each pair is graded by `board_occupancy.through_on_pad`, the same
        function the gate's audit calls, so a proposed pose and a committed one
        are read by one rule: FOREIGN-SHORT (hard), FOREIGN-CLEAR /
        SAME-NET-PARTIAL / SAME-NET-CLEAR (flag) and SAME-NET-IN-PAD (info,
        designed via-in-pad)."""
        out = []
        reach = _nm(occ.DEF_COPPER_CLR)
        slop = _nm(occ.DEF_VIA_SLOP)
        pboxes = self.pad_boxes
        for t in model["through"]:               # our pin, their pad
            tb = ps_bbox_mm(t.land)
            for f in FACES:
                if t.face == f:
                    continue
                for k, (lbl, net, poly, part) in enumerate(self.occ.pads[f]):
                    if part.ref in skip:
                        continue
                    ob = pboxes[f][k]
                    if tb and ob and geometry.bbox_gap(tb, ob) > occ.DEF_COPPER_CLR:
                        continue
                    v = occ.through_on_pad(t, lbl, net, poly, f, part.inst,
                                           reach, slop)
                    if v:
                        out.append(v)
        mine = {f: [ps_bbox_mm(e[2]) for e in model["pads"][f]] for f in FACES}
        for t in self.occ.through:               # their pin, our pad
            if t.ref in skip:
                continue
            tb = ps_bbox_mm(t.land)
            for f in FACES:
                if t.face == f:
                    continue
                for k, (lbl, net, poly, part) in enumerate(model["pads"][f]):
                    ob = mine[f][k]
                    if tb and ob and geometry.bbox_gap(tb, ob) > occ.DEF_COPPER_CLR:
                        continue
                    v = occ.through_on_pad(t, lbl, net, poly, f, part.inst,
                                           reach, slop)
                    if v:
                        out.append(v)
        return out

    def fits(self, ref, x, y, rot, face, clearance_mm=None, exclude=()):
        """Would footprint `ref` collide if it sat at (x, y, rot) on `face`?

        Tests, in the occupancy model's own vocabulary:
 - same-face courtyard against every other courtyard on that face;
 - this part's pads against same-layer foreign copper at the class
            clearance (or `clearance_mm`);
 - the CROSS-FACE rules: SMD pads and bodies on opposite faces never
            conflict; a through-hole pad, via or plated hole is copper on every
            layer and a hole through the board, so against an opposite-face pad
            it is a short on a foreign net and a merge on the same net; a
            through-hole pin under an opposite-face body is hard regardless of
            net; a tented via under a body is allowed (reported at `info`);
 - a pad outside the board outline.

        The part is moved for the test and put back, so this answers for a
        footprint that is currently elsewhere, and for a face flip.

        Returns dict(ok, blockers, pose) where `ok` means no blocker at `hard`
        or `tight` severity, and each blocker is a dict carrying class,
        severity, src, dst and the overlap or gap that made it.

            >>> o.fits("C12", 24.0, 18.4, 90, "F")     # doctest: +SKIP
            {'ok': False, 'pose': {...},
             'blockers': [{'class': 'c_courtyard_overlap', 'severity': 'hard',
                           'src': 'C12', 'dst': 'R7', 'overlap_mm2': 0.18}]}
        """
        if face not in FACES:
            raise ValueError("face must be 'F' or 'B', not %r" % (face,))
        skip = {ref} | set(exclude)
        model = self._pose_model(ref, x, y, rot, face)
        blockers = self._fits_blockers(model, ref, clearance_mm, skip)
        order = {"hard": 0, "tight": 1, "flag": 2, "info": 3}
        blockers.sort(key=lambda b: (order[b["severity"]], b["class"],
                                     str(b.get("dst"))))
        return {"ok": not any(b["severity"] in ("hard", "tight")
                              for b in blockers),
                "blockers": blockers,
                "pose": {"ref": ref, "x": x, "y": y, "rot": rot, "face": face,
                         "courtyard_bbox": model["box"]}}

    # ========================================================== connectivity
    def _cluster(self):
        """Union-find over every net's items, using KiCad's own connectivity.

        `CONNECTIVITY_DATA.GetConnectedItems` is the API that works in pcbnew
        10: `GetRatsnestForNet` returns an untyped SwigPyObject whose edges
        cannot be read from Python, and `GetUnconnectedCount` gives a total
        with no attribution.  Clustering the items a net owns and counting
        (clusters - 1) per net reproduces KiCad's ratsnest edge count exactly
        (the same count `kicad-cli pcb drc` reports).  A `RecalculateRatsnest()` is issued
        first: without it a freshly mutated board answers from a stale graph."""
        if self._clusters is not None:
            return self._clusters
        t0 = time.time()
        conn = self.pcb.GetConnectivity()
        conn.RecalculateRatsnest()
        by_net = {}
        for fp in self.pcb.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetCode() > 0:
                    by_net.setdefault(pad.GetNetCode(), []).append(
                        ("%s.%s" % (fp.GetReference(), pad.GetNumber() or "?"),
                         pad))
        for t in self.pcb.GetTracks():
            if t.GetNetCode() > 0:
                c = t.GetPosition()
                kind = "via" if isinstance(t, pcbnew.PCB_VIA) else "trk"
                by_net.setdefault(t.GetNetCode(), []).append(
                    ("%s@%.3f,%.3f" % (kind, _mm(c.x), _mm(c.y)), t))
        for d in self.pcb.GetDrawings():
            if isinstance(d, pcbnew.PCB_SHAPE) and d.GetNetCode() > 0:
                c = d.GetCenter()
                by_net.setdefault(d.GetNetCode(), []).append(
                    ("poly@%.3f,%.3f" % (_mm(c.x), _mm(c.y)), d))
        for i in range(self.pcb.GetAreaCount()):
            z = self.pcb.GetArea(i)
            if z.GetNetCode() > 0:
                by_net.setdefault(z.GetNetCode(), []).append(("zone", z))

        out = {}
        objs = {}
        for code, entries in by_net.items():
            idx = {it.m_Uuid.AsString(): i for i, (_, it) in enumerate(entries)}
            parent = list(range(len(entries)))

            def find(i):
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            for i, (_, it) in enumerate(entries):
                for other in conn.GetConnectedItems(it):
                    j = idx.get(other.m_Uuid.AsString())
                    if j is None:
                        continue
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj
            groups = {}
            for i, (label, it) in enumerate(entries):
                groups.setdefault(find(i), []).append((label, it))
            name = self.pcb.FindNet(code).GetNetname()
            ordered = sorted(groups.values(), key=lambda g: g[0][0])
            out[name] = [[lab for lab, _ in g] for g in ordered]
            objs[name] = [[it for _, it in g] for g in ordered]
        self._clusters = out
        self._cluster_objs = objs
        self.timing_ms["connectivity"] = (time.time() - t0) * 1000
        return out

    def _describe(self, it):
        """One copper item as a plain record: what it is, whose it is, where."""
        l, t, r, b = it.bbox
        return {"name": it.name, "net": it.net, "ref": it.fp,
                "layers": sorted(self.pcb.GetLayerName(x) for x in it.layers),
                "box": (round(l, 3), round(t, 3), round(r, 3), round(b, 3))}

    def in_region(self, x1, y1, x2, y2, layer=None, net=None):
        """Every copper item meeting the rectangle (mm, corners in any order).

        The question behind "what is in this corridor", "what would a part
        here collide with", "who owns copper in this band".

            >>> o.in_region(28.0, 31.0, 32.6, 38.5, layer="B.Cu")   # doctest: +SKIP
        """
        lo_x, hi_x = sorted((float(x1), float(x2)))
        lo_y, hi_y = sorted((float(y1), float(y2)))
        out = []
        for it in self.items:
            if layer is not None and layer not in (self.pcb.GetLayerName(x) for x in it.layers):
                continue
            if net is not None and it.net != net:
                continue
            l, t, r, b = it.bbox
            if r < lo_x or l > hi_x or b < lo_y or t > hi_y:
                continue
            out.append(self._describe(it))
        return out

    def outside_outline(self, margin=0.0):
        """Copper that sits outside the board edge, worst first.

        A stamped cell whose fragment origin never moved, a via the purge left
        behind: ordinary items to DRC, which has no opinion about the outline,
        and invisible in a render framed on the board.
        """
        box = self.pcb.GetBoardEdgesBoundingBox()
        lo_x, lo_y = box.GetLeft() / 1e6 - margin, box.GetTop() / 1e6 - margin
        hi_x, hi_y = box.GetRight() / 1e6 + margin, box.GetBottom() / 1e6 + margin
        out = []
        for it in self.items:
            l, t, r, b = it.bbox
            if l >= lo_x and t >= lo_y and r <= hi_x and b <= hi_y:
                continue
            d = self._describe(it)
            d["outside_by_mm"] = round(max(lo_x - r, l - hi_x, lo_y - b, t - hi_y, 0.0), 3)
            out.append(d)
        return sorted(out, key=lambda d: -d["outside_by_mm"])

    def connected(self, net):
        """Is every item on `net` joined by copper?

            >>> o.connected("V48")                     # doctest: +SKIP
            False
        """
        groups = self._cluster().get(net)
        if groups is None:
            raise KeyError("no net named %r on this board" % net)
        return len(groups) <= 1

    def unrouted(self):
        """Every net with an open connection, as net -> [(item_a, item_b), ...].

        One pair per missing connection: a net whose copper falls into k
        clusters yields k-1 pairs, chaining one representative per cluster.
        That is KiCad's own accounting - the count matches `kicad-cli pcb drc`
        `unconnected_items` exactly.  The
        PAIRS need not be DRC's pairs: DRC names the two nearest items across a
        gap, this names the first item of each cluster, so the same missing
        connection can be reported between a different pair of pads.

            >>> o.unrouted()["ENN"]                    # doctest: +SKIP
            [('U1.14', 'R22.2')]
        """
        out = {}
        for net, groups in self._cluster().items():
            if len(groups) > 1:
                reps = [g[0] for g in groups]
                out[net] = [(reps[i], reps[i + 1]) for i in range(len(reps) - 1)]
        return out

    # =============================================================== frontier
    def _cell_fps(self, cell):
        fps = [fp for fp in self.pcb.GetFootprints() if geometry.in_cell(fp, cell)]
        if not fps:
            raise KeyError("no footprints in cell %r (a PCB_GROUP name or a "
                           "Path prefix such as 'mcu' or 'mcu.c_vreg')"
                           % cell)
        return fps

    def cell_box(self, cell):
        """The cell's courtyard-union bbox as (x1, y1, x2, y2) in mm.

            >>> o.cell_box("mcu")                   # doctest: +SKIP
            (33.2, 23.2, 54.3, 46.3)
        """
        if cell in self._cellbox:
            return self._cellbox[cell]
        refs = {fp.GetReference() for fp in self._cell_fps(cell)}
        boxes = [ps_bbox_mm(p.poly) for p in self.occ.parts if p.ref in refs]
        boxes = [b for b in boxes if b]
        if not boxes:
            raise KeyError("cell %r has no courtyard geometry" % cell)
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes))
        self._cellbox[cell] = box
        return box

    def _cell_tracks(self, cell, margin=0.5):
        """The tracks the cell owns: its PCB_GROUP's, else bbox attribution."""
        for g in self.pcb.Groups():
            if g.GetName() == cell:
                return [it for it in g.GetItems()
                        if isinstance(it, pcbnew.PCB_TRACK)
                        and not isinstance(it, pcbnew.PCB_VIA)]
        x1, y1, x2, y2 = self.cell_box(cell)
        box = (x1 - margin, y1 - margin, x2 + margin, y2 + margin)
        out = []
        for t in self.pcb.GetTracks():
            if isinstance(t, pcbnew.PCB_VIA):
                continue
            s, e = t.GetStart(), t.GetEnd()
            pts = ((_mm(s.x), _mm(s.y)), (_mm(e.x), _mm(e.y)))
            if all(box[0] <= px <= box[2] and box[1] <= py <= box[3]
                   for px, py in pts):
                out.append(t)
        return out

    def _touches(self, x, y, net, layer_id, exclude_uuid, tol=0.001):
        """Is (x, y) on same-net copper other than the track it came from?

        Only the net's OWN items can complete an end, so the scan is over
        `_same_net` rather than everything in the neighbourhood - which is what
        keeps a whole cell's frontier at tens of milliseconds on a board whose
        ground pours have thousands of vertices."""
        for it in self._same_net(net, layer_id):
            bb = it.bbox
            if not (bb[0] - tol <= x <= bb[2] + tol and
                    bb[1] - tol <= y <= bb[3] + tol):
                continue
            obj = it.obj
            if obj is not None and hasattr(obj, "m_Uuid") and \
                    obj.m_Uuid.AsString() == exclude_uuid:
                continue
            for outline in it.outlines:
                if geometry.point_in_poly((x, y), outline):
                    return True
                if geometry.point_to_poly((x, y), outline) <= tol:
                    return True
        return False

    def _side(self, box, x, y):
        """N/E/S/W of a point relative to a box, by normalised offset.

        Normalising by the half-extents makes the classification independent of
        how elongated the cell is: a stub 1 mm past a 20 mm-wide cell's east
        edge reads east, not north, however tall the cell is."""
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        hx = max((box[2] - box[0]) / 2, 1e-6)
        hy = max((box[3] - box[1]) / 2, 1e-6)
        dx, dy = (x - cx) / hx, (y - cy) / hy
        if abs(dx) >= abs(dy):
            return "E" if dx >= 0 else "W"
        return "S" if dy >= 0 else "N"        # KiCad y grows downward

    def frontier(self, cell, margin=0.5):
        """The cell's handoff stubs: every track end that touches nothing.

        A dangling end - one that touches no pad, no via and no same-net track
 - is where the cell hands its net to the board.  Sides are N/E/S/W
        relative to the cell's courtyard-union bbox.

        Returns a list of dict(net, x, y, side, layer, track), sorted by side
        then position.

            >>> o.frontier("mcu")[0]                # doctest: +SKIP
            {'net': 'mcu.QSPI_SCK', 'x': 41.9, 'y': 23.2, 'side': 'N',
             'layer': 'F.Cu', 'track': 'trk 41.90,23.20-41.90,24.05'}
        """
        key = (cell, margin)
        if key in self._frontier:
            return self._frontier[key]
        box = self.cell_box(cell)
        stubs = []
        for t in self._cell_tracks(cell, margin):
            net = t.GetNetname()
            lid = t.GetLayer()
            uuid = t.m_Uuid.AsString()
            s, e = t.GetStart(), t.GetEnd()
            name = "trk %.2f,%.2f-%.2f,%.2f" % (_mm(s.x), _mm(s.y),
                                                _mm(e.x), _mm(e.y))
            for pt in (s, e):
                x, y = _mm(pt.x), _mm(pt.y)
                if self._touches(x, y, net, lid, uuid):
                    continue
                stubs.append({"net": net, "x": round(x, 3), "y": round(y, 3),
                              "side": self._side(box, x, y),
                              "layer": self.pcb.GetLayerName(lid), "track": name})
        stubs.sort(key=lambda s: (s["side"], s["x"], s["y"]))
        self._frontier[key] = stubs
        return stubs

    def facing(self, cell, x, y):
        """Fraction of the cell's handoff points that face (x, y).

        A handoff point is a pad or via of one of the cell's EXTERNAL nets
        (the nets that also have items outside the cell, i.e. what the board
        has to reach). Each sits on one side of the cell box (N/E/S/W, the
        nearest edge); that side's outward normal faces the point when its
        dot product with the direction from the cell centre is positive. 1.0
        means every handoff already points that way; 0.0 means the board has
        to go the long way round. A cell with no external nets returns 0.0.

            >>> o.facing("can", 44.0, 34.0)            # doctest: +SKIP
            0.38
        """
        ext = set(self.cell_nets(cell)["external"])
        pts = []
        for fp in self._cell_fps(cell):
            for pad in fp.Pads():
                if pad.GetNetname() in ext:
                    p = pad.GetPosition()
                    pts.append((_mm(p.x), _mm(p.y)))
        for t in self.pcb.GetTracks():
            if isinstance(t, pcbnew.PCB_VIA) and t.GetNetname() in ext and self._owner(t) == cell:
                p = t.GetPosition()
                pts.append((_mm(p.x), _mm(p.y)))
        if not pts:
            return 0.0
        box = self.cell_box(cell)
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        dx, dy = x - cx, y - cy
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        normals = {"N": (0.0, -1.0), "S": (0.0, 1.0),
                   "E": (1.0, 0.0), "W": (-1.0, 0.0)}
        hit = sum(1 for (px, py) in pts
                  if normals[self._side(box, px, py)][0] * ux
                  + normals[self._side(box, px, py)][1] * uy > 0)
        return hit / len(pts)

    # =============================================================== airwires
    @staticmethod
    def _anchors(item):
        """Ratsnest anchor points of a copper item, in mm (pad and via
        centres, both ends of a track, the centre of a shape or zone)."""
        if isinstance(item, pcbnew.PCB_VIA) or isinstance(item, pcbnew.PAD):
            p = item.GetPosition()
            return [(_mm(p.x), _mm(p.y))]
        if isinstance(item, pcbnew.PCB_TRACK):
            a, b = item.GetStart(), item.GetEnd()
            return [(_mm(a.x), _mm(a.y)), (_mm(b.x), _mm(b.y))]
        c = item.GetBoundingBox().GetCenter()
        return [(_mm(c.x), _mm(c.y))]

    @staticmethod
    def _owner(item):
        """Who an item belongs to: a pad's footprint instance (the stamped
        cell's name, or the loose part's own instance), a track's or via's
        enclosing group name, "" for loose board copper."""
        if isinstance(item, pcbnew.PAD):
            fp = item.GetParentFootprint()
            try:
                return geometry.inst_of(fp)
            except geometry.PathShapeError:
                return fp.GetReference()
        g = item.GetParentGroup()
        return g.GetName() if g else ""

    def airwires(self):
        """The ratsnest as this oracle measures it (KiCad's own edges are not
        readable from Python): per net, a minimum spanning tree over the
        net's copper clusters, each edge the shortest anchor-to-anchor gap
        between two clusters. The edge count equals KiCad's unconnected
        count; the lengths are the straight-line distances a router has to
        close at the very least.

        Returns dict(count, total_mm, crossings, edges=[dict(net, a, b, mm,
        owner_a, owner_b)], per_net={net: mm}, per_owner={owner: dict(count,
        mm, internal_mm, external_mm)}). An edge is INTERNAL to an owner when
        both of its ends belong to it (a cell that has not closed its own
        net), EXTERNAL when it leaves the owner (what the board must layout).

            >>> aw = o.airwires()                      # doctest: +SKIP
            >>> aw["count"], round(aw["total_mm"]), aw["crossings"]
            (478, 1732, 211)
        """
        self._cluster()
        t0 = time.time()
        edges = []
        for net, groups in self._cluster_objs.items():
            if len(groups) < 2:
                continue
            anchors = [[(x, y, self._owner(it)) for it in grp
                        for (x, y) in self._anchors(it)] for grp in groups]
            n = len(groups)
            pairs = []
            for i in range(n):
                ai = anchors[i]
                for j in range(i + 1, n):
                    best = None
                    for (ax, ay, ao) in ai:
                        for (bx, by, bo) in anchors[j]:
                            d = math.hypot(ax - bx, ay - by)
                            if best is None or d < best[0]:
                                best = (d, (ax, ay), (bx, by), ao, bo)
                    pairs.append((best[0], i, j, best))
            pairs.sort(key=lambda p: (p[0], p[1], p[2]))
            parent = list(range(n))

            def find(i):
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            for d, i, j, best in pairs:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
                    edges.append(dict(net=net, a=(round(best[1][0], 3), round(best[1][1], 3)),
                                      b=(round(best[2][0], 3), round(best[2][1], 3)),
                                      mm=round(d, 3), owner_a=best[3], owner_b=best[4]))
        # crossings: every pair of airwires that intersect (a routing-order proxy)
        def ccw(ax, ay, bx, by, cx, cy):
            return (cy - ay) * (bx - ax) > (by - ay) * (cx - ax)

        def cross(e, f):
            (ax, ay), (bx, by) = e["a"], e["b"]
            (cx, cy), (dx, dy) = f["a"], f["b"]
            if max(ax, bx) < min(cx, dx) or max(cx, dx) < min(ax, bx) or \
               max(ay, by) < min(cy, dy) or max(cy, dy) < min(ay, by):
                return False
            return (ccw(ax, ay, cx, cy, dx, dy) != ccw(bx, by, cx, cy, dx, dy)
                    and ccw(ax, ay, bx, by, cx, cy) != ccw(ax, ay, bx, by, dx, dy))
        crossings = 0
        for i in range(len(edges)):
            for j in range(i + 1, len(edges)):
                if edges[i]["net"] != edges[j]["net"] and cross(edges[i], edges[j]):
                    crossings += 1
        per_net, per_owner = {}, {}
        for e in edges:
            per_net[e["net"]] = round(per_net.get(e["net"], 0.0) + e["mm"], 3)
            owners = {e["owner_a"], e["owner_b"]} - {""}
            internal = e["owner_a"] == e["owner_b"] and e["owner_a"] != ""
            for o in owners:
                rec = per_owner.setdefault(o, dict(count=0, mm=0.0, internal_mm=0.0, external_mm=0.0))
                rec["count"] += 1
                rec["mm"] = round(rec["mm"] + e["mm"], 3)
                key = "internal_mm" if internal else "external_mm"
                rec[key] = round(rec[key] + e["mm"], 3)
        self.timing_ms["airwires"] = (time.time() - t0) * 1000
        return dict(count=len(edges), total_mm=round(sum(e["mm"] for e in edges), 3),
                    crossings=crossings, edges=edges, per_net=per_net, per_owner=per_owner)

    def cell_nets(self, cell):
        """A cell's nets split by where they go: `internal` (every item of
        the net belongs to the cell: the cell closes it) and `external` (the
        net also has items outside the cell: the board draws it). Pads count
        by their footprint's cell, tracks and vias by their group.

            >>> o.cell_nets("can")["external"]         # doctest: +SKIP
            ['CAN_N', 'CAN_P', 'gnd', 'v3v3', ...]
        """
        inside, outside = set(), set()
        for fp in self.pcb.GetFootprints():
            own = geometry.in_cell(fp, cell)
            for pad in fp.Pads():
                if pad.GetNetCode() > 0:
                    (inside if own else outside).add(pad.GetNetname())
        for t in self.pcb.GetTracks():
            if t.GetNetCode() > 0:
                (inside if self._owner(t) == cell else outside).add(t.GetNetname())
        return dict(internal=sorted(inside - outside), external=sorted(inside & outside))

    # ================================================================= fit_in
    def fit_in(self, ref, x1, y1, x2, y2, face, rotations=(0, 90, 180, 270),
               step_mm=0.2, corridors=(), prefer=None, clearance_mm=None,
               exclude=()):
        """Every pose of `ref` inside a pocket where nothing collides.

        A calculator, not a placer: it returns the choices and the reasons, and
        the caller decides and writes the `place()` call.

        `corridors` are runs that must stay open with the part in place, each
        (net, p, q, layer, w); a corridor already blocked by committed copper
        is reported once in `blocked_corridors` rather than against every pose.
        `prefer` is a point; candidates are sorted by distance to it, else by
        distance to the pocket centre.

        Returns dict(candidates, rejected, tried, blocked_corridors) where
        `candidates` is a list of dict(x, y, rot, face, dist_mm) and `rejected`
        is a histogram of "class:blocker" -> count over the poses that failed,
        so the caller learns what is actually in the way.

            >>> r = o.fit_in("C12", 20, 14, 26, 20, "F", step_mm=0.5)
            ... # doctest: +SKIP
            >>> r["candidates"][0]
            {'x': 22.0, 'y': 17.0, 'rot': 90, 'face': 'F', 'dist_mm': 0.5}
            >>> r["rejected"]
            {'c_courtyard_overlap:R7': 41, 'copper_clearance:zone@B.Cu': 6}
        """
        if step_mm <= 0:
            raise ValueError("step_mm must be positive")
        px = prefer[0] if prefer else (x1 + x2) / 2
        py = prefer[1] if prefer else (y1 + y2) / 2
        blocked = []
        live = []
        for c in corridors:
            net, p, q, layer, w = c
            r = self.corridor(net, p, q, layer, w)
            if not r["ok"]:
                blocked.append({"net": net, "from": list(p), "to": list(q),
                                "blockers": r["blockers"][:3]})
            else:
                lid = self._layer_id(layer)
                live.append((net, geometry.segment_item(self.pcb, net, p[0], p[1],
                                                        q[0], q[1], lid, w),
                             lid, self.clearance(net)))
        cands, rejected, tried = [], {}, 0
        nx = int(math.floor((x2 - x1) / step_mm)) + 1
        ny = int(math.floor((y2 - y1) / step_mm)) + 1
        for rot in rotations:
            for i in range(nx):
                for j in range(ny):
                    x = round(x1 + i * step_mm, 4)
                    y = round(y1 + j * step_mm, 4)
                    tried += 1
                    r = self.fits(ref, x, y, rot, face,
                                  clearance_mm=clearance_mm, exclude=exclude)
                    if not r["ok"]:
                        for b in r["blockers"]:
                            if b["severity"] in ("hard", "tight"):
                                k = "%s:%s" % (b["class"], b.get("dst"))
                                rejected[k] = rejected.get(k, 0) + 1
                        continue
                    hit = self._corridor_hit(ref, x, y, rot, face, live)
                    if hit:
                        rejected[hit] = rejected.get(hit, 0) + 1
                        continue
                    cands.append({"x": x, "y": y, "rot": rot, "face": face,
                                  "dist_mm": round(math.hypot(x - px, y - py), 4)})
        cands.sort(key=lambda c: (c["dist_mm"], c["rot"], c["x"], c["y"]))
        return {"candidates": cands, "rejected": dict(sorted(rejected.items())),
                "tried": tried, "blocked_corridors": blocked}

    def _corridor_hit(self, ref, x, y, rot, face, live):
        """Does this pose's own copper close one of the live corridors?"""
        if not live:
            return None
        model = self._pose_model(ref, x, y, rot, face)
        for net, seg, lid, clr in live:
            for it in model["copper"]:
                if it.net == net or lid not in it.layers:
                    continue
                if geometry.bbox_gap(seg.bbox, it.bbox) > clr:
                    continue
                if geometry.poly_dist_within(seg.outlines, it.outlines, clr,
                                             it.segments) < clr - EPS:
                    return "corridor:%s" % net
        return None
