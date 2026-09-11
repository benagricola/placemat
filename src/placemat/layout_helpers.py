#!/usr/bin/env python3
"""Shared layout mechanics for module layout scripts (pcbnew).

A module's layout script declares the DESIGN (placements, polygons, traces, vias);
this class does the geometry. Polygons are real filled `gr_poly` on copper with a
net (full shape control, no zone clearance cut-outs). Component origins snap to a
0.1mm grid. Reference designators move to F.Fab so the silk stays clean.

Run a module layout with:
    pcbc layout --no-open <module>.zen        # regenerates layout/<M>/layout.kicad_pcb (grid)
    <module>_layout.py                        # applies this layout into that fragment

Library rule: ONE implementation of each mechanic lives here (group ops, bbox
measurement, overlap tests, edge placement, silk labels, stackup colours,
width wrappers). Layout scripts never carry a private copy; extend this file
instead. Known defect awaiting a library round: from_mm()/FromMM truncate to the
nm grid (the MCU cell snaps first as a workaround).
"""
import enum
import hashlib
import json
import math
import os

import pcbnew

point = pcbnew.VECTOR2I            # a board coordinate
def from_mm(mm): return pcbnew.FromMM(mm)     # millimetres -> internal units
def to_mm(v): return pcbnew.ToMM(int(v))      # internal units -> millimetres
def snap(v, grid=0.1): return round(v / grid) * grid   # to the placement grid


# THE FAB PROFILE IS THE PROJECT'S, ASKED FOR AT THE POINT OF USE. Not read at
# import and not found by climbing the filesystem, so a call here means the
# same thing wherever it is made from.
from placemat.project import fab                                       # noqa: E402


class LinkWeight(float, enum.Enum):
    """What a millimetre on a connection is worth against every other
    connection competing for the same room (skill tactic 2a).

    A member IS its number, so the three named points and a bare number are the
    same scale and the same code path: 3 means this connection is worth three
    ordinary ones per millimetre. Named where a name fits, because a name says
    which of the three reasons applies and a number does not.
    """
    SHORT = 10.0     # the link IS the behaviour; lengthening it degrades the circuit
    PREFER = 1.0     # shorter is tidier, nothing degrades - these give way first
    FIXED = 0.0      # mechanics decided an endpoint; the net follows, so it asks for nothing


class ModuleLayout:
    def __init__(self, path):
        self.path = path
        # Every item this script creates - track, via, zone, label - is minted a
        # random KIID by pcbnew, and the board file is written in item order, so
        # two runs of the SAME script produce a diff of hundreds of lines that
        # carries no information and hides the lines that do. Seeding the
        # generator per board makes a regeneration byte-comparable, which is what
        # lets a refactor be verified by diffing its output. The seed is the
        # board's own path, so two boards never layout the same sequence.
        pcbnew.KIID.SeedGenerator(int(hashlib.sha256(os.path.abspath(path).encode()).hexdigest()[:8], 16))
        self.pcb = pcbnew.LoadBoard(path)
        self.footprints = {f.GetReference(): f for f in self.pcb.GetFootprints()}
        self.links = []                      # declared proximity classes, see link()
        self.both_faces = False              # render the bottom too (parts on both faces)
        self.on_save = []                    # f(board_path) for each sibling file a save must write
        self.before_save = []                # f() that FINISHES THE BOARD, run before it is written
                                             # (on_save is too late: the file is already on disk).
                                             # A step whose inputs are "everything the script drew"
                                             # belongs here, not at whatever line the script calls it.
        self.netcode = {}
        for fp in self.pcb.GetFootprints():
            for p in fp.Pads():
                self.netcode[p.GetNetname()] = p.GetNetCode()

    def _nc(self, net):
        """Live netcode lookup - NEVER trust `self.netcode[net]` directly for
        SetNetCode(): pcbnew's
        NETINFO_LIST renumbers as PCB_TRACK/PCB_VIA objects are added (a net
        with pads but no copper yet appears to get a provisional code at
        LoadBoard() that shifts once real copper exists), so a code cached at
        __init__ silently goes stale mid-script - a track can end up saved
        under a completely different net name than the string you passed to
        track()/via(), with no error and no DRC short (the copper still lands
        on the pad it was aimed at, so DRC's geometry check is satisfied; only
        the net LABEL is wrong). `BOARD.FindNet(name)` re-resolves live every
        call, which is correct regardless of how many renumbers have
        happened. `self.netcode` is kept only for callers that want a
        best-effort snapshot; every SetNetCode() in this class goes through
        this method instead."""
        n = self.pcb.FindNet(net)
        if n is None:
            raise KeyError("no net named %r on this board" % net)
        return n.GetNetCode()

    @property
    def oracle(self):
        """The geometry oracle for this board (modules/layout_oracle.py), built
        on first use and kept.

        Ask it what a placement or a run clears BEFORE committing it:

            if layout.oracle.clear("V48", 10, 10, 22, 10, "F.Cu", 0.8)["ok"]:
                layout.trk("V48", 10, 10, 22, 10)

        The oracle caches the board's geometry, so call `L.oracle.refresh()`
        after adding copper or moving a part if the next query must see it."""
        if getattr(self, "_oracle", None) is None:
            from placemat import layout_oracle
            self._oracle = layout_oracle.Oracle(self.pcb, self.path)
        return self._oracle

    def check(self, allow_open=()):
        """Fail the script if any net is left open.

        `allow_open` names the nets a fragment is entitled to leave to the
        board - plane drops, edge stubs, the rails a module only lands on.
        Everything else must be joined by copper, or this raises with the full
        listing (net, and the item pair for each missing connection).

            layout.check(allow_open=("gnd", "vin"))     # before layout.save()
        """
        opens = self.oracle.refresh().unrouted()
        bad = {n: v for n, v in opens.items() if n not in set(allow_open)}
        if bad:
            lines = []
            for net in sorted(bad):
                for a, b in bad[net]:
                    lines.append("  %-24s %s <-> %s" % (net, a, b))
            raise AssertionError(
                "%d net(s) left open (%d missing connections) in %s:\n%s"
                % (len(bad), sum(len(v) for v in bad.values()), self.path,
                   "\n".join(lines)))
        return self

    def place(self, ref, x, y, rot, grid=0.1, bottom=None):
        """Place a component, origin snapped to `grid` (default 0.1mm). Use
        grid=0.05 when pad-axis alignment demands it (e.g. a cap's served pad
        exactly on the served IC pin's axis) - alignment beats grid coarseness.
        `bottom` puts the part on a face, flipped about its own position before
        the angle is applied, so the pose asked for is the pose it lands in."""
        fp = self.footprints[ref]
        # The flip goes FIRST: flipping mirrors the orientation, so a part
        # flipped after being turned lands at the mirror of the angle asked for.
        if bottom is not None and bool(fp.IsFlipped()) != bool(bottom):
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot); fp.SetPosition(point(from_mm(snap(x, grid)), from_mm(snap(y, grid))))
        return self

    def poly(self, net, pts, layer="F.Cu", pad_margin_mm=0.12, stroke_mm=0.2):
        """Filled copper polygon (gr_poly) on `net`, stroke 0.2mm standard (the
        stroke rounds the outline and is part of the copper; drop to 0.05 via
        stroke_mm= ONLY where a tight pool needs the thinner edge). The outline is
        `pts`, but any same-net pad the outline touches is swallowed WHOLE
        (grown by pad_margin) so no pad edge ever pokes out - a joining pour
        must fully contain its pads. Adjacent aligned pad boxes are merged so
        the pour covers them with a single edge (no small notches between).
        Pass pad_margin_mm=None for a RAW outline (no pad swallowing): use this
        when the vertex list is already the final hand-authored shape."""
        code = self._nc(net)
        ps = pcbnew.SHAPE_POLY_SET(); ps.NewOutline()
        for x, y in pts:
            ps.Append(from_mm(x), from_mm(y))
        if pad_margin_mm is None:
            sh = pcbnew.PCB_SHAPE(self.pcb, pcbnew.SHAPE_T_POLY)
            sh.SetLayer(self.pcb.GetLayerID(layer)); sh.SetFilled(True); sh.SetWidth(from_mm(stroke_mm))
            sh.SetPolyShape(ps)
            sh.SetNetCode(code)
            self.pcb.Add(sh)
            return self
        m = from_mm(pad_margin_mm)
        boxes = []
        for fp in self.footprints.values():
            for p in fp.Pads():
                if p.GetNetCode() != code:
                    continue
                bb = p.GetBoundingBox()
                corners = [pcbnew.VECTOR2I(bb.GetLeft(), bb.GetTop()),
                           pcbnew.VECTOR2I(bb.GetRight(), bb.GetTop()),
                           pcbnew.VECTOR2I(bb.GetRight(), bb.GetBottom()),
                           pcbnew.VECTOR2I(bb.GetLeft(), bb.GetBottom()), p.GetPosition()]
                if any(ps.Contains(c) for c in corners):        # outline touches this pad -> cover it whole
                    boxes.append([bb.GetLeft() - m, bb.GetTop() - m, bb.GetRight() + m, bb.GetBottom() + m])
        # merge adjacent aligned boxes so a pour covers them with ONE edge -
        # closely wrapping neighbouring pads leaves small notches (banned).
        GAP = from_mm(0.6); ALIGN = from_mm(0.1)
        merged = True
        while merged:
            merged = False
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    a, b = boxes[i], boxes[j]
                    same_row = abs(a[1] - b[1]) <= ALIGN and abs(a[3] - b[3]) <= ALIGN \
                        and (b[0] - a[2] <= GAP if a[0] <= b[0] else a[0] - b[2] <= GAP)
                    same_col = abs(a[0] - b[0]) <= ALIGN and abs(a[2] - b[2]) <= ALIGN \
                        and (b[1] - a[3] <= GAP if a[1] <= b[1] else a[1] - b[3] <= GAP)
                    if same_row or same_col:
                        boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                        boxes.pop(j); merged = True; break
                if merged:
                    break
        for x1, y1, x2, y2 in boxes:
            r = pcbnew.SHAPE_POLY_SET(); r.NewOutline()
            r.Append(x1, y1); r.Append(x2, y1); r.Append(x2, y2); r.Append(x1, y2)
            ps.BooleanAdd(r)
        ps.Simplify()
        sh = pcbnew.PCB_SHAPE(self.pcb, pcbnew.SHAPE_T_POLY)
        sh.SetLayer(self.pcb.GetLayerID(layer)); sh.SetFilled(True); sh.SetWidth(from_mm(stroke_mm))
        sh.SetPolyShape(ps)
        sh.SetNetCode(code)
        self.pcb.Add(sh)
        return self

    def track(self, net, width, x1, y1, x2, y2, layer="F.Cu"):
        t = pcbnew.PCB_TRACK(self.pcb); t.SetLayer(self.pcb.GetLayerID(layer))
        t.SetNetCode(self._nc(net)); t.SetWidth(from_mm(width))
        t.SetStart(point(from_mm(x1), from_mm(y1))); t.SetEnd(point(from_mm(x2), from_mm(y2))); self.pcb.Add(t)
        return self

    def widths(self, table=None, default=0.2):
        """Set the width-by-net-role table used by trk()/segs(). Consolidates the
        per-script `W = {...}` + `def trk(...)` pair every module grew: the net
        name keys a role width (power pours/rails wider), everything else falls
        back to `default` (the 0.2mm netclass FLOOR - go wider where room allows).
        `table` may be a dict or a bare float (one width for the whole script)."""
        if isinstance(table, (int, float)):
            self._w, self._wdef = {}, float(table)
        else:
            self._w, self._wdef = dict(table or {}), default
        return self

    def _wof(self, net, w=None):
        if w is not None:
            return w
        return getattr(self, "_w", {}).get(net, getattr(self, "_wdef", 0.2))

    def trk(self, net, x1, y1, x2, y2, layer="F.Cu", w=None):
        """One segment at the net's role width (see widths()); w= overrides."""
        return self.track(net, self._wof(net, w), x1, y1, x2, y2, layer=layer)

    def segs(self, net, segs, w=None, layer="F.Cu", origin=(0, 0)):
        """Several (x1,y1,x2,y2) segments on one net, optionally all offset by
        `origin` - the anchor-relative style (coords written relative to an IC,
        lifted to board mm at layout time)."""
        ox, oy = origin
        for x1, y1, x2, y2 in segs:
            self.track(net, self._wof(net, w), ox + x1, oy + y1, ox + x2, oy + y2, layer=layer)
        return self

    def l45(self, net, x0, y0, x1, y1, w=None, layer="F.Cu"):
        """Two segments between two points, the 45 FIRST and the straight leg
        last so the final segment rides the destination pad's own axis (skill
        tactic 9). The diagonal covers the smaller axis delta; a purely
        straight run draws one segment; a zero-length leg is not drawn."""
        dx, dy = x1 - x0, y1 - y0
        d = min(abs(dx), abs(dy))
        if d < 1e-6:
            self.track(net, self._wof(net, w), x0, y0, x1, y1, layer=layer)
            return self
        xm = x0 + (d if dx > 0 else -d)
        ym = y0 + (d if dy > 0 else -d)
        if abs(dx) > abs(dy):
            ym = y1
        else:
            xm = x1
        self.track(net, self._wof(net, w), x0, y0, xm, ym, layer=layer)
        if (xm - x1) ** 2 + (ym - y1) ** 2 > 1e-8:
            self.track(net, self._wof(net, w), xm, ym, x1, y1, layer=layer)
        return self

    def route45(self, net, pts, w=None, layer="F.Cu"):
        """A polyline whose every leg is an l45 (45 then straight)."""
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            self.l45(net, x0, y0, x1, y1, w=w, layer=layer)
        return self

    def io_nets(self):
        """The module's handoff nets (its .zen io() list); [] on a board or when
        no .zen sits beside the fragment."""
        zen = module_zen(self.path)
        return zen_io_nets(zen) if zen else []

    def airwires(self):
        """The fragment's ratsnest as the oracle measures it, split into the
        nets the module must close itself and the io nets it hands to the
        board. See Oracle.airwires()."""
        aw = self.oracle.refresh().airwires()
        io = set(self.io_nets())
        aw["internal_open"] = {n: v for n, v in aw["per_net"].items() if n not in io}
        aw["io_open"] = {n: v for n, v in aw["per_net"].items() if n in io}
        return aw

    def pack(self, ref, dx, dy, gap=0.01, clr=None, limit=5.0, step=0.01):
        """Slide a placed part along (dx, dy) until real geometry stops it:
        its courtyard would come within `gap` of another courtyard, or one of
        its pads within `clr` (default: the fragment's clearance) of copper on
        another net. Returns the distance moved. This is the measured stop the
        skill asks for: a part sits where its neighbour stops it, never a
        round "air" constant short of it."""
        fp = self.footprints[ref]
        n = (dx * dx + dy * dy) ** 0.5
        ux, uy = dx / n, dy / n
        if clr is None:                       # the fragment's own default class, else the 0.2 house floor
            clr = default_clearance_mm(self.pcb)
        clr_nm = from_mm(clr)
        layer = pcbnew.B_Cu if fp.IsFlipped() else pcbnew.F_Cu
        others = [g for g in self.pcb.GetFootprints() if g.GetReference() != ref and g.IsFlipped() == fp.IsFlipped()]
        other_crt = [fp_courtyard_box_mm(g) for g in others]
        foreign = []
        my_nets = {p.GetNetCode() for p in fp.Pads()}
        for g in self.pcb.GetFootprints():
            if g.GetReference() == ref:
                continue
            for p in g.Pads():
                if p.IsOnLayer(layer):
                    foreign.append(p)
        for t in self.pcb.GetTracks():
            if t.IsOnLayer(layer):
                foreign.append(t)
        for d in self.pcb.GetDrawings():
            if isinstance(d, pcbnew.PCB_SHAPE) and d.IsOnLayer(layer) and d.GetNetCode() > 0:
                foreign.append(d)
        start = fp.GetPosition()

        def clear_at(t):
            fp.SetPosition(point(start.x + from_mm(ux * t), start.y + from_mm(uy * t)))
            cy = fp_courtyard_box_mm(fp)
            for oc in other_crt:
                if cy[0] < oc[2] + gap and oc[0] < cy[2] + gap and cy[1] < oc[3] + gap and oc[1] < cy[3] + gap:
                    return False
            for p in fp.Pads():
                ps = p.GetEffectiveShape(layer)
                pbb = p.GetBoundingBox(); pbb.Inflate(clr_nm + from_mm(0.1))
                for it in foreign:
                    if it.GetNetCode() == p.GetNetCode() or not pbb.Intersects(it.GetBoundingBox()):
                        continue
                    if ps.Collide(it.GetEffectiveShape(layer), clr_nm):
                        return False
            return True

        moved = 0.0
        k = 1
        while k * step <= limit + 1e-9 and clear_at(k * step):
            moved = k * step
            k += 1
        fp.SetPosition(point(start.x + from_mm(ux * moved), start.y + from_mm(uy * moved)))
        print("pack %s: moved %.2f mm along (%+.0f, %+.0f)" % (ref, moved, dx, dy))
        return round(moved, 3)

    def place_two_pin(self, ref, x, y_of_pad, pad_on_axis, other_south=True, grid=0.01):
        """A vertical two-pin part placed so pad `pad_on_axis` lands at world y
        = y_of_pad with the other pad SOUTH of it (or north). Rotation and
        centre are derived from the real pad geometry, never assumed."""
        self.place(ref, x, y_of_pad, 90, grid=grid)
        ax = self.pad_xy(ref, pad_on_axis)[1]
        ox = [self.pad_xy(ref, k)[1] for k in ("1", "2") if k != pad_on_axis][0]
        rot = 90 if ((ox > ax) == other_south) else 270
        self.place(ref, x, y_of_pad, rot, grid=grid)
        dy = y_of_pad - self.pad_xy(ref, pad_on_axis)[1]
        ndigits = max(0, -int(math.floor(math.log10(grid))))   # 0.01 -> 2, 0.005 -> 3, 1e-9 -> 9
        self.place(ref, x, round(y_of_pad + dy, ndigits), rot, grid=grid)
        return self.footprints[ref]

    def pad_of(self, ref, net):
        """The pad of `ref` on `net` (pcbnew PAD)."""
        return pad_on_net(self.footprints[ref], net)

    def pad_net_xy(self, ref, net):
        """(x, y) mm of the pad of `ref` on `net`."""
        p = pad_on_net(self.footprints[ref], net).GetPosition()
        return to_mm(p.x), to_mm(p.y)

    def route(self, net, pts, w=None, layer="F.Cu", origin=(0, 0)):
        """A POLYLINE on one net: consecutive (x, y) points joined end to end.
        The natural form for a serve or an escape - one call per net, so the
        corner list reads as the route it is (segs() stays for scattered runs).
        NOT named path(): ModuleLayout.path is the board file's own path."""
        ox, oy = origin
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            self.track(net, self._wof(net, w), ox + x1, oy + y1, ox + x2, oy + y2, layer=layer)
        return self

    def via(self, net, x, y, drill=None, size=None):
        drill = fab()["via"]["default_drill_mm"] if drill is None else drill
        size = fab()["via"]["default_size_mm"] if size is None else size
        v = pcbnew.PCB_VIA(self.pcb); v.SetPosition(point(from_mm(x), from_mm(y)))
        v.SetDrill(from_mm(drill)); v.SetWidth(from_mm(size)); v.SetNetCode(self._nc(net)); self.pcb.Add(v)
        return self

    def _pad(self, ref, key):
        for p in self.footprints[ref].Pads():
            if p.GetNumber() == str(key) or p.GetNetname() == key:
                return p
        raise KeyError("%s has no pad '%s'" % (ref, key))

    def pad_xy(self, ref, padkey):
        """World (x, y) in mm of a PLACED pad - ground truth for trace endpoints,
        so a script never re-derives a pad position with its own rotation maths.
        `padkey` is a pad number or a net name (see _pad)."""
        p = self._pad(ref, padkey).GetPosition()
        return to_mm(p.x), to_mm(p.y)

    def pad_boxes(self, ref, net):
        """(x1, y1, x2, y2) mm for EVERY pad of `ref` on `net`, as placed.

        A multi-pad terminal (a FET's drain, an EP fed by a pad array) has no
        single box, and the copper that has to cover or dodge it is drawn
        against all of them."""
        out = []
        for p in self.footprints[ref].Pads():
            if p.GetNetname() == net:
                bb = p.GetBoundingBox()
                out.append((to_mm(bb.GetLeft()), to_mm(bb.GetTop()), to_mm(bb.GetRight()), to_mm(bb.GetBottom())))
        return sorted(out)

    def pad_box(self, ref, padkey, origin=(0, 0)):
        """World (x1, y1, x2, y2) in mm of a PLACED pad's bounding box - the pad's
        real copper EDGES, rotation included - minus `origin` when a script
        works in a cell frame. Use this (never centre +/- a literal half-size)
        whenever a frontier line, keepout or standoff is derived from the
        outermost pad of a face."""
        b = self._pad(ref, padkey).GetBoundingBox()
        ox, oy = origin
        return to_mm(b.GetLeft()) - ox, to_mm(b.GetTop()) - oy, to_mm(b.GetRight()) - ox, to_mm(b.GetBottom()) - oy

    def drop_via(self, ref, padkey, net=None, stub_dir=(1, 0)):
        """Plane-drop via at a pad. Via-in-pad when the pad is big enough (>=0402
        per the fab profile); for a 0201-class pad, stub a short trace away and drop
        the via in open copper (avoids a below-minimum drill / upcharge)."""
        p = self._pad(ref, padkey); net = net or p.GetNetname()
        px, py = to_mm(p.GetPosition().x), to_mm(p.GetPosition().y)
        pmin = to_mm(min(p.GetSize().x, p.GetSize().y))
        vs = fab()["via"]["default_size_mm"]
        if pmin >= fab()["via_in_pad"]["min_pad_dim_mm"]:
            self.via(net, px, py)                                     # via-in-pad
        else:
            n = (stub_dir[0] ** 2 + stub_dir[1] ** 2) ** 0.5 or 1
            off = pmin / 2 + vs / 2 + 0.15
            vx, vy = px + stub_dir[0] / n * off, py + stub_dir[1] / n * off
            self.track(net, 0.2, px, py, vx, vy); self.via(net, vx, vy)   # 0201: stub + via
        return self

    def stitch(self, net, refs=None):
        """Drop a plane via on every pad of `net` (optionally limited to `refs`).
        For ground + distributed power, which come from a plane - the module never
        routes these between parts, it just gives the plane landing points."""
        for ref, fp in self.footprints.items():
            if refs and ref not in refs:
                continue
            for p in fp.Pads():
                if p.GetNetname() == net:
                    self.drop_via(ref, p.GetNumber(), net)
        return self

    def refs_to_fab(self, text_mm=0.8, thick_mm=0.15):
        """Move every reference designator to F.Fab, nudged clear of pads/other refs."""
        clr = from_mm(0.12)
        pad_boxes = []
        for fp in self.footprints.values():
            for p in fp.Pads():
                bb = p.GetBoundingBox(); bb.Inflate(clr); pad_boxes.append(bb)
        placed, dirs = [], [(0, -1), (0, 1), (1, 0), (-1, 0), (1, -1), (-1, -1), (1, 1), (-1, 1)]
        # smallest part first, PHYSICAL area (a courtyard is not part size), and
        # ties broken by ref - `self.footprints` is in generation order, which changes run to
        # run, and identical chips tie on area constantly.
        for ref in sorted(self.footprints, key=lambda r: (fp_phys_bbox(self.footprints[r]).GetArea(), r)):
            t = self.footprints[ref].Reference()
            t.SetLayer(pcbnew.F_Fab); t.SetTextSize(point(from_mm(text_mm), from_mm(text_mm))); t.SetTextThickness(from_mm(thick_mm))
            fx, fy = self.footprints[ref].GetPosition().x, self.footprints[ref].GetPosition().y
            best, best_hits = None, 1e9
            for r in [0.9, 1.4, 1.9, 2.5, 3.1, 3.8]:
                for dx, dy in dirs:
                    n = (dx * dx + dy * dy) ** 0.5
                    t.SetPosition(point(fx + int(from_mm(r) * dx / n), fy + int(from_mm(r) * dy / n)))
                    box = t.GetBoundingBox(); box.Inflate(clr)
                    hits = sum(1 for pb in pad_boxes if box.Intersects(pb)) + sum(1 for rb in placed if box.Intersects(rb))
                    if hits == 0:
                        best, best_hits = t.GetPosition(), 0; break
                    if hits < best_hits:
                        best, best_hits = t.GetPosition(), hits
                if best_hits == 0:
                    break
            t.SetPosition(best); placed.append(t.GetBoundingBox())
        return self

    # A proximity constraint belongs to a CONNECTION, not to a part (skill
    # tactic 2a): a filter's filtered side must reach its load while its
    # unfiltered side may cross the board, so no per-part class can say it.
    # Declaring the LINK says it, and the placement objective can then spend
    # scarce adjacency on the connections that need it.
    LinkWeight = LinkWeight          # so a script holding only L can name them
    LINK_DEFAULT = LinkWeight.PREFER  # undeclared links keep the uniform weighting

    @staticmethod
    def link_weight(spec):
        """The number a weight field means. A LinkWeight IS its number, so this
        only has to reject what is not one."""
        if isinstance(spec, bool) or not isinstance(spec, (int, float)):
            raise ValueError("link weight %r is not a LinkWeight (%s) or a number"
                             % (spec, ", ".join("LinkWeight." + m.name for m in LinkWeight)))
        w = float(spec)
        if not (w >= 0.0) or w == float("inf"):     # the NaN case fails the >= too
            raise ValueError("link weight %r must be a finite number >= 0" % (spec,))
        return w

    def link(self, a_ref, a_pad, b_ref, b_pad, weight=LinkWeight.SHORT, why="", limit_mm=None):
        """Declare how much a connection's LENGTH is worth, between two pads.

            layout.link(C_VCP, "1", U, "34", LinkWeight.SHORT, why="reservoir on its own pin")
            layout.link(R_SENSE, "2", U, "12", 3, why="sense tap, above ordinary pull")

        This annotates connectivity the netlist already has - it creates no net,
        changes no pad and draws no copper. All it says is what a millimetre on
        this connection costs the placement search.

        `weight` is a LinkWeight (SHORT 10, PREFER 1, FIXED 0) or any number
        >= 0 for the cases between them. `limit_mm` makes it checkable: state
        the length the circuit actually needs and the gate fails when placement
        misses it. Without one the link is reported and not enforced, because
        how short "short" has to be is a property of the circuit, not a number
        this library can pick.

        Endpoints are recorded by the footprint's instance PATH, not its refdes,
        so the declaration survives the renumbering a schematic edit causes. An
        undeclared link weighs PREFER, exactly as every link did before weights
        existed - declaring nothing changes nothing.
        """
        rec = {"weight": self.link_weight(weight),
               "name": weight.name.lower() if isinstance(weight, LinkWeight) else None,
               "why": why, "limit_mm": limit_mm,
               "a": {"ref": a_ref, "pad": str(a_pad), "path": self._path_of(a_ref)},
               "b": {"ref": b_ref, "pad": str(b_pad), "path": self._path_of(b_ref)}}
        for end in ("a", "b"):
            # raises if the pad is not there; the net goes in the record because
            # a mistyped pad number usually lands on a different net, and a link
            # that legitimately spans one (a Kelvin tap across a sense resistor)
            # is then still readable as deliberate
            rec[end]["net"] = self._pad(rec[end]["ref"], rec[end]["pad"]).GetNetname()
        self.links.append(rec)
        return rec

    def _path_of(self, ref):
        fp = self.footprints.get(ref)
        return (fp.GetFieldsText().get("Path", "") if fp else "") or ""

    def link_report(self):
        """Every declared link with the length placement actually achieved,
        heaviest first and worst first within a weight.

        Without this the classes are decoration: a link worth 10 that ended up
        14 mm long reads exactly like one that ended up at 0.8 mm."""
        rows = []
        for rec in self.links:
            try:
                ax, ay = self.pad_xy(rec["a"]["ref"], rec["a"]["pad"])
                bx, by = self.pad_xy(rec["b"]["ref"], rec["b"]["pad"])
            except (KeyError, AttributeError):
                continue
            mm = round(math.hypot(ax - bx, ay - by), 3)
            rows.append({"weight": rec["weight"], "name": rec.get("name"),
                         "cell": rec.get("cell"),
                         "why": rec.get("why", ""), "limit_mm": rec.get("limit_mm"),
                         "a": "%s.%s" % (rec["a"]["ref"], rec["a"]["pad"]),
                         "b": "%s.%s" % (rec["b"]["ref"], rec["b"]["pad"]),
                         "nets": [rec["a"].get("net"), rec["b"].get("net")],
                         "mm": mm,
                         "over_limit": bool(rec.get("limit_mm") and mm > rec["limit_mm"])})
        rows.sort(key=lambda r: (-r["weight"], -r["mm"]))
        return rows

    def write_links(self, out):
        """The declared links beside the board file, keyed by instance path.

        A stamped cell's links have to reach the board that stamps it, and the
        board knows a cell's footprints by `<instance>.<path in the fragment>`
 - the same mapping the clearance floors use."""
        d = os.path.dirname(os.path.abspath(out))
        dst = os.path.join(d, "links.json")
        if not self.links:
            # a script that stops declaring links must not leave the last run's
            # file behind for the gate to read as current
            for stale in (dst, os.path.join(d, "links-achieved.json")):
                if os.path.exists(stale):
                    os.remove(stale)
            return None
        json.dump(self.links, open(dst, "w"), indent=1)
        json.dump(self.link_report(), open(os.path.join(d, "links-achieved.json"), "w"), indent=1)
        return dst

    def save(self, path=None, stackup_colors=False, render=None, stackup_thickness=None):
        """Save + patch the project presets + render. `stackup_colors=True` also
        applies the house render convention (green mask / white silk) to the
        saved file - opt-in, because scripts that already patch the generated
        fragment before LoadBoard() get the same result and must not double up.
        `render` defaults to the LAYOUT_RENDER environment variable (unset or
        "1" renders; "0" skips the two PNGs, which are most of a script's run
        time and are only wanted on a pass that will be looked at or kept)."""
        out = path or self.path
        # ATOMIC: write beside the target and MOVE it into place. A board file
        # is tens of thousands of lines and takes a moment to write, and the
        # path being written is the one a person has open in KiCad - so a
        # direct write leaves a window where the file on disk is a board with
        # no outline and every part at its netlist position. That is
        # indistinguishable from a broken layout to anyone who opens it, and it
        # is the state a long script spends most of its time in.
        for hook in self.before_save:        # last chance to change the BOARD, in dependency order
            hook()
        _tmp = out + ".writing"
        self.pcb.Save(_tmp)
        os.replace(_tmp, out)
        self.write_links(out)
        for hook in self.on_save:            # sibling files (design rules, ...) belong to the save
            hook(out)
        if stackup_colors or stackup_thickness:
            # After the write, not before: the patch is a targeted sexpr edit and
            # a freshly generated file may not carry the block it edits, while a
            # pcbnew-written one always does. Before the render, so the render
            # sees the colours.
            patch_stackup_colors(out, thickness=stackup_thickness)
        self._patch_project(out)
        if render is None:
            render = os.environ.get("LAYOUT_RENDER", "1") != "0"
        if render:
            self._render(out)
        else:
            print("renders skipped (LAYOUT_RENDER=0)")
        print("saved ->", out)
        return self

    def render(self, name, side="top", extra=(), pcb_path=None):
        """One render beside the board file. `side` is "top" or "bottom",
        `extra` adds kicad-cli flags (the iso view's rotation, say).

        Always with --use-board-stackup-colors: without it kicad-cli renders its
        own appearance preset and the board comes out purple whatever the
        (stackup) block says, which is how a bottom view drifts from a top one."""
        import subprocess
        pcb_path = pcb_path or self.path
        try:
            subprocess.run(["kicad-cli", "pcb", "render", "--side", side,
                            "--background", "opaque", "--quality", "high",
                            "--use-board-stackup-colors",
                            "-o", os.path.join(os.path.dirname(pcb_path), name),
                            pcb_path] + list(extra),
                           capture_output=True, timeout=120)
        except Exception as e:
            print("WARN: render %s failed: %s" % (name, e))
        return self

    def _render(self, pcb_path):
        """Drop layout.png (top-down) + layout-iso.png (isometric) next to the
        board - the current design's visual state, overwritten every save (no
        history). The iso view exposes wrong component Z heights/models.
        `both_faces` adds layout-bottom.png: on a board that carries parts on
        both faces a top view is half the placement."""
        views = [("layout.png", "top", []),
                 ("layout-iso.png", "top", ["--rotate", "-45,0,45", "--perspective"])]
        if self.both_faces:
            views.append(("layout-bottom.png", "bottom", []))
        for name, side, extra in views:
            self.render(name, side=side, extra=extra, pcb_path=pcb_path)

    def _patch_project(self, pcb_path):
        """Give the sibling .kicad_pro user width/via presets (from the fab
        profile) so hand edits can pick real track widths, not just the
        netclass width. Re-applied every save - the generator rewrites the
        project file on each mill."""
        pro = os.path.splitext(pcb_path)[0] + ".kicad_pro"
        if not os.path.exists(pro):
            return
        tw = fab().get("track_width_presets_mm", {"min": 0.15, "max": 1.0, "step": 0.05})
        n = int(round((tw["max"] - tw["min"]) / tw["step"])) + 1
        widths = [round(tw["min"] + i * tw["step"], 2) for i in range(n)]
        try:
            d = json.load(open(pro))
            ds = d.setdefault("board", {}).setdefault("design_settings", {})
            ds["trace_widths"] = widths
            ds["via_dimensions"] = [{"diameter": fab()["via"]["default_size_mm"],
                                     "drill": fab()["via"]["default_drill_mm"]}]
            json.dump(d, open(pro, "w"), indent=2)
        except Exception as e:
            print("WARN: could not patch %s: %s" % (pro, e))


# =============================================================================
# GEOMETRY - boxes are (left, top, right, bottom) in mm, world frame.
# =============================================================================

def fp_bbox_mm(fp, text=False):
    """THE house placement box: the part's real ON-BOARD extent in mm
    (fp_body_box_mm). `text=True` adds the drawn silk + field text on top.

    A courtyard is an ASSEMBLY KEEPOUT, not a physical extent: nothing that
    sizes an outline, an envelope, a placement offset, an edge placement, a
    spacing or a collision box may measure through one (`fp.GetBoundingBox`
    unions the courtyard layers, so an envelope measured through it grows by
    the courtyard margin). Nor is raw silk an extent: an edge connector
    draws its OFF-BOARD half on silk (see fp_body_box_mm). Use
    fp_courtyard_box_mm only to ask what a part claims for assembly - and
    prefer DRC's courtyards_overlap for that question."""
    box = fp_body_box_mm(fp)
    return union_box([box, fp_phys_box_mm(fp, text=True)]) if text else box


_PHYS_LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.F_SilkS, pcbnew.B_SilkS,
                pcbnew.F_Fab, pcbnew.B_Fab, pcbnew.F_Mask, pcbnew.B_Mask,
                pcbnew.F_Paste, pcbnew.B_Paste, pcbnew.Edge_Cuts)


def fp_phys_box_mm(fp, text=False):
    """A footprint's PHYSICAL bbox in mm - pads + drawn graphics, with the
    COURTYARD layers excluded.

    pcbnew's GetBoundingBox() unions every graphic layer, courtyard included, so
    it answers "what does this part keep clear", not "how big is this part":
    an envelope measured through it grows by the courtyard margin on every
    side, enough to move a board outline. Use THIS where the answer feeds an envelope,
    a slot fit or a board dimension, and fp_courtyard_box_mm where it feeds an
    assembly keepout / collision test."""
    xs, ys = [], []
    for p in fp.Pads():
        bb = p.GetBoundingBox()
        xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
    for d in fp.GraphicalItems():
        if d.GetLayer() not in _PHYS_LAYERS:      # courtyard + user/comment out
            continue
        if not text and isinstance(d, pcbnew.PCB_TEXT):
            continue
        bb = d.GetBoundingBox()
        xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
    if text:
        for f in (fp.Reference(), fp.Value()):
            if f.IsVisible():
                bb = f.GetBoundingBox()
                xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
    if not xs:      # padless, graphic-less oddity: fall back to KiCad's own box
        bb = fp.GetBoundingBox() if text else fp.GetBoundingBox(False, False)
        return to_mm(bb.GetLeft()), to_mm(bb.GetTop()), to_mm(bb.GetRight()), to_mm(bb.GetBottom())
    return to_mm(min(xs)), to_mm(min(ys)), to_mm(max(xs)), to_mm(max(ys))


def _box2i(box):
    l, t, r, bo = box
    return pcbnew.BOX2I(point(from_mm(l), from_mm(t)), pcbnew.VECTOR2I(from_mm(r - l), from_mm(bo - t)))


def fp_phys_bbox(fp, text=False):
    """fp_phys_box_mm as a pcbnew BOX2I (nm) - for call sites that speak the
    BOX2I API (`bb.GetLeft()`, `bb.GetWidth()`, ...)."""
    return _box2i(fp_phys_box_mm(fp, text=text))


def fp_body_bbox(fp, text=False):
    """fp_bbox_mm (the house placement box) as a pcbnew BOX2I (nm) - the
    drop-in replacement for `fp.GetBoundingBox(False, False)`, which includes
    the courtyard."""
    return _box2i(fp_bbox_mm(fp, text=text))


def item_body_bbox(it, text=False):
    """BOX2I of any board item - footprints by their body box, other items
    their own box. For the `for it in group.GetItems()` loops."""
    if isinstance(it, pcbnew.FOOTPRINT):
        return fp_body_bbox(it, text=text)
    return it.GetBoundingBox()


def fp_body_box_mm(fp, excess=None):
    """The part's real ON-BOARD extent - the courtyard DEFLATED by the house
    courtyard excess (fab-profile `courtyard.excess_mm`), unioned with the pads.
    Falls back to fp_phys_box_mm when the footprint draws no courtyard.

    NOT F.Fab: easyeda2kicad footprints layout oversize pin circles there (a 2.54
    header's F.Fab is 5.5 x 8.1mm around a 2.8 x 5.3mm body), so a fab-inclusive
    box invents clashes.

    For the parts whose SILK cannot be trusted as a body outline: a bulkhead
    connector draws its off-board barrel on silk (the CAZN M12 silk runs 17mm
    past its pads, all of it outside the board), so fp_phys_box_mm over-measures
    it southward and an edge placement made from it shoves the part inboard on
    top of its neighbours. The courtyard is generated as union(pads, body) +
    excess, so deflating by that same excess recovers the body - and the answer
    stays INVARIANT when the excess is retuned, which is the whole point."""
    ex = fab().get("courtyard", {}).get("excess_mm", 0.10) if excess is None else excess
    has_ct = any(d.GetLayerName() in ("F.Courtyard", "B.Courtyard")
                 for d in fp.GraphicalItems())
    if not has_ct:                       # no keepout drawn: the drawn extent is
        return fp_phys_box_mm(fp)        # all we have
    ct = fp_courtyard_box_mm(fp)
    ct = (ct[0] + ex, ct[1] + ex, ct[2] - ex, ct[3] - ex)
    xs, ys = [], []
    for p in fp.Pads():                  # never smaller than the copper
        bb = p.GetBoundingBox()
        xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
    pads = (to_mm(min(xs)), to_mm(min(ys)), to_mm(max(xs)), to_mm(max(ys))) if xs else None
    return union_box([ct, pads])


def fp_courtyard_box_mm(fp):
    """Union of courtyard outlines + pads (mm). The keepout the part actually
    claims - use for packing/collision. Falls back to the physical bbox when the
    footprint has no courtyard."""
    xs, ys = [], []
    for d in fp.GraphicalItems():
        if d.GetLayerName() in ("F.Courtyard", "B.Courtyard"):
            bb = d.GetBoundingBox()
            xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
    for p in fp.Pads():
        pb = p.GetBoundingBox()
        xs += [pb.GetLeft(), pb.GetRight()]; ys += [pb.GetTop(), pb.GetBottom()]
    if not xs:
        return fp_bbox_mm(fp)
    return to_mm(min(xs)), to_mm(min(ys)), to_mm(max(xs)), to_mm(max(ys))


def item_bbox_mm(item, text=False):
    """bbox of ANY board item in mm - footprints honour `text` (see fp_bbox_mm),
    tracks/vias/shapes/text use their own box."""
    if isinstance(item, pcbnew.FOOTPRINT):
        return fp_bbox_mm(item, text=text)
    bb = item.GetBoundingBox()
    return to_mm(bb.GetLeft()), to_mm(bb.GetTop()), to_mm(bb.GetRight()), to_mm(bb.GetBottom())


def union_box(boxes):
    """Union of (l,t,r,b) boxes; None if empty."""
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def inflate_box(box, m):
    return (box[0] - m, box[1] - m, box[2] + m, box[3] + m)


def boxes_overlap(a, c, gap=0.0):
    """True when box `a` inflated by `gap` overlaps box `c`. SEMANTICS CHOSEN:
    exactly-touching edges do NOT count as overlapping (>= comparison), which is
    the majority behaviour and the one _mtv() agrees with. A script that
    treated exactly-abutting boxes as overlapping (strict comparison) may place
    a silk label in a different slot under this rule; re-render and check."""
    a = inflate_box(a, gap)
    return not (a[2] <= c[0] or c[2] <= a[0] or a[3] <= c[1] or c[3] <= a[1])


def mtv(a, c, gap=0.0):
    """Minimum translation (dx,dy) that moves box `c` clear of box `a` inflated
    by `gap`; None when they are already clear. Pushes along the shallower axis,
    away from `a`'s centre - the packing primitive for shove-style placement."""
    ox = min(a[2] + gap, c[2]) - max(a[0] - gap, c[0])
    oy = min(a[3] + gap, c[3]) - max(a[1] - gap, c[1])
    if ox <= 0 or oy <= 0:
        return None
    if ox <= oy:
        return (ox if (c[0] + c[2]) >= (a[0] + a[2]) else -ox, 0.0)
    return (0.0, oy if (c[1] + c[3]) >= (a[1] + a[3]) else -oy)


def pad_span_mm(fps, net, margin=0.0):
    """Box spanning every pad of `net` across `fps` (footprint objects or an
    iterable of them), grown by `margin`. The pour-outline primitive: a pool must
    swallow its pads whole, so shape the polygon from the measured span."""
    boxes = []
    for fp in fps:
        for p in fp.Pads():
            if p.GetNetname() == net:
                pb = p.GetBoundingBox()
                boxes.append((to_mm(pb.GetLeft()), to_mm(pb.GetTop()), to_mm(pb.GetRight()), to_mm(pb.GetBottom())))
    u = union_box(boxes)
    return inflate_box(u, margin) if u else None


# =============================================================================
# GROUP OPS - member-level, never PCB_GROUP's own transform API.
# KiCad's PCB_GROUP.Move()/Rotate()/GetBoundingBox() are UNTRUSTED: members can
# scatter after an earlier group op in the same session, and the group bbox
# goes stale right after a Rotate(). Every op below drives each MEMBER item's
# own Move()/Rotate()/Flip() around a bbox centre computed fresh from the
# members.
# =============================================================================

def group_items(grp):
    """Members of a PCB_GROUP, or the list itself if you already have one."""
    return list(grp) if isinstance(grp, (list, tuple)) else list(grp.GetItems())


def group_bbox_mm(grp, mode="physical"):
    """Union of MEMBER boxes in mm. mode: 'physical' (default - footprints
    text-excluded, everything else its own box), 'courtyard' (footprint
    courtyard+pads; other items their own box) or 'text' (text-inclusive).
    A script whose group targets were measured text-inclusively sees its
    group centres move by the silk overhang under the default; re-measure the
    targets, or pass mode='text' to reproduce the old centres exactly."""
    boxes = []
    for it in group_items(grp):
        if isinstance(it, pcbnew.FOOTPRINT):
            boxes.append(fp_courtyard_box_mm(it) if mode == "courtyard"
                         else fp_bbox_mm(it, text=(mode == "text")))
        elif hasattr(it, "GetBoundingBox"):
            boxes.append(item_bbox_mm(it))
    return union_box(boxes)


def group_center_mm(grp, mode="physical"):
    l, t, r, bo = group_bbox_mm(grp, mode)
    return (l + r) / 2.0, (t + bo) / 2.0


def group_move_by(grp, dx, dy):
    """Translate every member by (dx,dy) mm."""
    d = point(from_mm(dx), from_mm(dy))
    for it in group_items(grp):
        it.Move(d)


def group_move_to(grp, cx, cy, mode="physical"):
    """Move the group so its computed bbox CENTRE lands on (cx,cy) mm."""
    gx, gy = group_center_mm(grp, mode)
    group_move_by(grp, cx - gx, cy - gy)


def group_rotate(grp, deg, mode="physical", pivot=None):
    """Rotate every member `deg` degrees about the group's computed bbox centre
    (or an explicit (x,y) mm `pivot`). Never PCB_GROUP.Rotate()."""
    cx, cy = pivot if pivot else group_center_mm(grp, mode)
    p, ang = point(from_mm(cx), from_mm(cy)), pcbnew.EDA_ANGLE(deg, pcbnew.DEGREES_T)
    for it in group_items(grp):
        it.Rotate(p, ang)


def group_flip(grp, mode="physical", pivot=None, direction=None):
    """Mirror every member left/right about the group's computed bbox centre -
    this moves parts to the BACK layer (a real side change, not a rotation)."""
    cx, cy = pivot if pivot else group_center_mm(grp, mode)
    d = direction if direction is not None else pcbnew.FLIP_DIRECTION_LEFT_RIGHT
    p = point(from_mm(cx), from_mm(cy))
    for it in group_items(grp):
        it.Flip(p, d)


def groups_by_name(board):
    """{group name: PCB_GROUP} - the `GROUPS` dict every board script builds."""
    return {g.GetName(): g for g in board.Groups()}


# =============================================================================
# STACKUP / RENDER COLOURS + SILK
# =============================================================================

def default_clearance_mm(board):
    """The board's default net-class clearance in mm, read through whichever
    API this KiCad exposes; the 0.20 house floor when the file carries none
    (a fresh generation has no classes until the project file is patched)."""
    bds = board.GetDesignSettings()
    for get in (lambda: bds.m_NetSettings.GetDefaultNetclass().GetClearance(),
                lambda: bds.m_NetSettings.m_DefaultNetClass.GetClearance(),
                lambda: bds.GetDefault().GetClearance(),
                lambda: bds.m_MinClearance):
        try:
            v = to_mm(get())
            if v > 0:
                return v
        except Exception:
            continue
    return 0.20


def zen_io_nets(zen_path):
    """The nets a module hands to its board: every `io("name", ...)` the .zen
    declares. Everything else on the fragment is module-internal."""
    import re
    text = open(zen_path).read()
    return sorted(set(re.findall(r'\bio\(\s*"([^"]+)"', text)))


def module_zen(fragment_path):
    """The one .zen beside a module's layout/ folder, or None."""
    import glob
    d = os.path.dirname(os.path.dirname(os.path.abspath(fragment_path)))
    zens = glob.glob(os.path.join(d, "*.zen"))
    return zens[0] if len(zens) == 1 else None


def pad_on_net(fp, net):
    """The pad of footprint `fp` on `net` (pcbnew PAD); KeyError when none."""
    for p in fp.Pads():
        if p.GetNetname() == net:
            return p
    raise KeyError("%s has no %s pad" % (fp.GetReference(), net))


def group_pad(group, net=None, pin=None, ref_prefix=None):
    """(x, y) mm of ONE pad inside a stamped cell (PCB_GROUP): by exact `net`
    and/or pad number `pin`, optionally only on the member whose ref starts
    with `ref_prefix` (a connector and a jumper can both carry a segment net).
    KeyError when nothing matches."""
    for item in group_items(group):
        if not hasattr(item, "Pads"):
            continue
        if ref_prefix and not item.GetReference().startswith(ref_prefix):
            continue
        for p in item.Pads():
            if net is not None and p.GetNetname() != net:
                continue
            if pin is not None and p.GetNumber() != str(pin):
                continue
            pos = p.GetPosition()
            return to_mm(pos.x), to_mm(pos.y)
    raise KeyError((group.GetName(), net, pin, ref_prefix))


def net_pads(board, net, exclude=()):
    """Every pad on `net` as sorted (x, y, ref) mm: stable regardless of the
    generator's emission order."""
    out = []
    for fp in board.GetFootprints():
        if fp.GetReference() in exclude:
            continue
        for pp in fp.Pads():
            if pp.GetNetname() == net:
                q = pp.GetPosition()
                out.append((to_mm(q.x), to_mm(q.y), fp.GetReference()))
    return sorted(out)


def pads_box_mm(fps, exclude_net=None):
    """Box spanning every pad of the footprints (optionally skipping pads on
    `exclude_net`)."""
    xs, ys = [], []
    for fp in fps:
        for p in fp.Pads():
            if exclude_net and p.GetNetname() == exclude_net:
                continue
            bb = p.GetBoundingBox()
            xs += [to_mm(bb.GetLeft()), to_mm(bb.GetRight())]
            ys += [to_mm(bb.GetTop()), to_mm(bb.GetBottom())]
    return min(xs), min(ys), max(xs), max(ys)


def group_net_copper_box_mm(group, net):
    """Bbox of a stamped cell's own copper (shapes and tracks) on `net`: where
    a board pour lands on a module's internal pour, measured never assumed."""
    xs, ys = [], []
    for it in group.GetItems():
        if isinstance(it, (pcbnew.PCB_SHAPE, pcbnew.PCB_TRACK)) and hasattr(it, "GetNetname") and it.GetNetname() == net:
            bb = it.GetBoundingBox()
            xs += [to_mm(bb.GetLeft()), to_mm(bb.GetRight())]
            ys += [to_mm(bb.GetTop()), to_mm(bb.GetBottom())]
    assert xs, "group %s has no copper on %s" % (group.GetName(), net)
    return min(xs), min(ys), max(xs), max(ys)


def rect_pts(l, t, r, bo):
    return [(l, t), (r, t), (r, bo), (l, bo)]


def ref_of_path(board, path):
    """The reference of the ONE footprint whose Path field equals `path`
    exactly (the generator stamps the Zener instance path there). Raises when
    none or several match: a first-match lookup is only regenerable when the
    match is unique."""
    hits = []
    for fp in board.GetFootprints():
        try:
            if fp.GetFieldText("Path") == path:
                hits.append(fp.GetReference())
        except KeyError:
            pass
    if not hits:
        raise KeyError("no footprint with instance path %r - did the .zen rename it?" % path)
    assert len(hits) == 1, "instance path %r matches %s" % (path, sorted(hits))
    return hits[0]


def pin1_mark(board, fp, size_mm=0.6, layer="F.SilkS"):
    """A filled silk dot on pad 1 of `fp` (an orientation cue for a socket)."""
    pad1 = next(p for p in fp.Pads() if p.GetNumber() == "1")
    pos = pad1.GetPosition()
    c = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_CIRCLE)
    c.SetLayer(board.GetLayerID(layer))
    c.SetWidth(from_mm(0.15))
    c.SetFilled(True)
    c.SetCenter(pos)
    c.SetEnd(point(pos.x + from_mm(size_mm / 2), pos.y))
    board.Add(c)
    return c


def patch_stackup_colors(path, mask="Green", silk="White", thickness=None):
    """House render convention: GREEN soldermask + WHITE silk, so copper reads in
    `kicad-cli pcb render` output. pcbnew exposes no stackup colour setter, so
    this is a targeted sexpr edit of the (stackup) block - call it on the milled
    fragment BEFORE LoadBoard() (pcbnew round-trips the block on Save), or via
    ModuleLayout.save(stackup_colors=True) on the written file. Idempotent.

    SEMANTICS CHOSEN: the regex form, which INSERTS a (color ...) line when the
    layer block has none (a line-scanning variant could only overwrite an
    existing one, so a fragment generated without colours stayed default). A
    file with no (stackup) at all (most generated module fragments) gets a
    DEFAULT 2-layer stackup block
    inserted carrying the colours: kicad-cli renders a colourless board in its
    appearance preset (purple), so leaving the block alone loses the house
    convention on every module fragment. Skipped on boards with
    inner copper - inventing their stack would be wrong."""
    import re
    src = open(path).read()
    if "(stackup" not in src:
        if '"In1.Cu"' in src or "\t(setup\n" not in src:
            return False
        src = src.replace("\t(setup\n", "\t(setup\n" + _DEFAULT_STACKUP, 1)
    for layer, color in ((("F.Mask", "B.Mask"), mask), (("F.SilkS", "B.SilkS"), silk)):
        for name in layer:
            pat = re.compile(r'(\(layer "%s"\s*\n\s*\(type "[^"]*(?:Silk Screen|Solder Mask)"\))'
                             r'(\s*\n\s*\(color "[^"]*"\))?' % re.escape(name))
            src, n = pat.subn(lambda m: m.group(1) + '\n\t\t\t\t(color "%s")' % color, src, count=1)
            if n != 1:
                print("WARN: stackup colour patch found no %s block" % name)
    if thickness is not None:
        lines = src.split("\n")
        for i, line in enumerate(lines[:40]):
            if line.strip().startswith("(thickness "):
                lines[i] = line.split("(thickness")[0] + "(thickness %s)" % thickness
                break
        src = "\n".join(lines)
    open(path, "w").write(src)
    return True


_DEFAULT_STACKUP = """\t\t(stackup
\t\t\t(layer "F.SilkS"
\t\t\t\t(type "Top Silk Screen")
\t\t\t)
\t\t\t(layer "F.Paste"
\t\t\t\t(type "Top Solder Paste")
\t\t\t)
\t\t\t(layer "F.Mask"
\t\t\t\t(type "Top Solder Mask")
\t\t\t\t(thickness 0.01)
\t\t\t)
\t\t\t(layer "F.Cu"
\t\t\t\t(type "copper")
\t\t\t\t(thickness 0.035)
\t\t\t)
\t\t\t(layer "dielectric 1"
\t\t\t\t(type "core")
\t\t\t\t(thickness 1.51)
\t\t\t\t(material "FR4")
\t\t\t\t(epsilon_r 4.5)
\t\t\t\t(loss_tangent 0.02)
\t\t\t)
\t\t\t(layer "B.Cu"
\t\t\t\t(type "copper")
\t\t\t\t(thickness 0.035)
\t\t\t)
\t\t\t(layer "B.Mask"
\t\t\t\t(type "Bottom Solder Mask")
\t\t\t\t(thickness 0.01)
\t\t\t)
\t\t\t(layer "B.Paste"
\t\t\t\t(type "Bottom Solder Paste")
\t\t\t)
\t\t\t(layer "B.SilkS"
\t\t\t\t(type "Bottom Silk Screen")
\t\t\t)
\t\t\t(copper_finish "None")
\t\t\t(dielectric_constraints no)
\t\t)
"""


def knockout_label(board, text, x, y, rot=0, size_mm=1.2, thickness_mm=0.2,
                   layer="F.SilkS", justify="center"):
    """House style for a user-facing marking (BOOT/RESET, connector names): silk
    PCB_TEXT in an inverted KNOCKOUT box, so it stays legible sitting close to
    other silk or over copper. Centred on (x,y) by default; `rot` in degrees.

    SEMANTICS CHOSEN: size 1.2mm / thickness 0.2mm, the house size; pass
    size_mm / thickness_mm where a board wants smaller text."""
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetLayer(board.GetLayerID(layer))
    t.SetTextSize(point(from_mm(size_mm), from_mm(size_mm)))
    t.SetTextThickness(from_mm(thickness_mm))
    t.SetIsKnockout(True)
    # A BACK-layer marking must be mirrored or it reads backwards from the side
    # you actually look at it from - the whole point of a user-facing label
    # (two-sided boards: a motor-face SWD row, bottom-side connector names).
    if layer.startswith("B."):
        t.SetMirrored(True)
    if justify == "center":
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    t.SetTextAngleDegrees(rot)
    t.SetPosition(point(from_mm(x), from_mm(y)))
    board.Add(t)
    return t


# =============================================================================
# CONNECTOR PLACEMENT
# =============================================================================

EDGE_ROT = {"L": 270, "R": 90, "T": 180, "B": 0}   # body mass points OUTWARD


def place_hard_edge(layout, ref, edge, pos, w=None, h=None, overhang=0.0, rot=None,
                    seed=150.0, grid=0.1):
    """Place a connector hard against (or `overhang` mm past) board `edge`
    ('L','R','T','B'); `pos` is the coordinate ALONG that edge (Y for L/R, X for
    T/B). `w`/`h` are the board size in mm - required for the far edges R/B.
    Rotation defaults to EDGE_ROT (L=270 R=90 T=180 B=0), the orientation that
    points the mating face outward. Places once at `seed`, measures the REAL
    rotated physical bbox, solves the offset and re-places exactly - never a
    hand-derived offset. Returns the INWARD-facing bbox edge (X for L/R, Y for
    T/B) so the caller can chain a measured gap to the next part.

    Measurement uses the PHYSICAL bbox (text excluded); all three prior copies
    agreed on that and on the rotation map, so no consumer changes behaviour."""
    if rot is None:
        rot = EDGE_ROT[edge]
    if (edge == "R" and w is None) or (edge == "B" and h is None):
        raise ValueError("place_hard_edge(%s,'%s') needs the board %s"
                         % (ref, edge, "w" if edge == "R" else "h"))
    horiz = edge in ("L", "R")

    def put(along_edge_offset):
        if horiz:
            layout.place(ref, along_edge_offset, pos, rot, grid=grid)
        else:
            layout.place(ref, pos, along_edge_offset, rot, grid=grid)

    put(seed)
    l, t, r, bo = fp_bbox_mm(layout.footprints[ref])
    if edge == "L":
        d = (0 - overhang) - l
    elif edge == "R":
        d = (w + overhang) - r
    elif edge == "T":
        d = (0 - overhang) - t
    else:
        d = (h + overhang) - bo
    put(seed + d)
    l, t, r, bo = fp_bbox_mm(layout.footprints[ref])
    return {"L": r, "R": l, "T": bo, "B": t}[edge]


def silk_box_mm(fp):
    """(l, t, r, b) mm of a footprint's SILKSCREEN GRAPHICS - the outline a
    silk_overlap violation is actually about. Deliberately EXCLUDES the ref /
    value text fields: refs_to_fab() moves those off silk before save, so a
    text-inclusive GetBoundingBox() measures silk the saved board will not
    carry (and it is dominated by the field text, not the part). Falls back to
    the physical bbox for a footprint that draws no silk."""
    xs, ys = [], []
    for g in fp.GraphicalItems():
        if isinstance(g, pcbnew.PCB_SHAPE) and g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            bb = g.GetBoundingBox()
            xs += [to_mm(bb.GetLeft()), to_mm(bb.GetRight())]
            ys += [to_mm(bb.GetTop()), to_mm(bb.GetBottom())]
    if not xs:
        return fp_bbox_mm(fp)
    return min(xs), min(ys), max(xs), max(ys)


def prune_silk(fp, kinds=("Arc",)):
    """Delete a footprint's DECORATIVE silk shapes of the given kinds (as
    ShowShape() names: Arc, Circle, Rect, Line, Poly), returning how many went.

    Vendor-generated footprints often layout an orientation NOTCH that bulges
    OUTSIDE the body outline (easyeda2kicad's north-edge semicircle overhangs by
    ~0.6mm here). When that decoration - not the part - is what collides with a
    neighbour's silk, trimming it is the right fix: paying real placement
    distance for a marker that sits outside the body is backwards. Check first
    that a separate pin-1 indicator survives; never prune away the last one."""
    n = 0
    for g in list(fp.GraphicalItems()):
        if (isinstance(g, pcbnew.PCB_SHAPE) and g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS)
                and g.ShowShape() in kinds):
            fp.Remove(g); n += 1
    return n


# =============================================================================
# NET / FOOTPRINT SELECTION - refs are resolved from the FRESH netlist every
# round (they churn when the schematic changes; a hardcoded ref map is a bug).
# =============================================================================

def nets_of(fp):
    """Set of net names on a footprint's pads (unconnected pads excluded)."""
    return {p.GetNetname() for p in fp.Pads() if p.GetNetname()}


def nets_of_map(board):
    return {fp.GetReference(): nets_of(fp) for fp in board.GetFootprints()}


def group_of_map(board):
    """{ref: group name or None} - which module group each footprint belongs to."""
    out = {fp.GetReference(): None for fp in board.GetFootprints()}
    for g in board.Groups():
        for it in g.GetItems():
            if isinstance(it, pcbnew.FOOTPRINT):
                out[it.GetReference()] = g.GetName()
    return out


def chain_by_nets(board, nodes, **kw):
    """The parts of a SERIES CHAIN, resolved by the nodes between them.

        chain_by_nets(b, ["24V", "V24_LED_MID", "V24_LED_A", "GND"])
        -> [ballast R, LED, return R]

    A chain has no identity of its own - its parts are ordinary resistors and
    diodes whose refdes churn - but each element is the only part bridging one
    consecutive pair of nodes, which does not churn. Extra filters go through
    to find_by_nets (prefix=, fpid=, group=)."""
    return [find_by_nets(board, a, b, exact=True, **kw)
            for a, b in zip(nodes, nodes[1:])]


def find_by_nets(board, *nets, prefix=None, fpname=None, fpid=None, group=None,
                 exclude=(), exact=False, many=False, path=None):
    """Resolve footprint ref(s) by the NET SET on their pads - the churn-proof
    alternative to a hardcoded ref map. Filters: `path` = exact match on the
    footprint's `Path` field, the HIERARCHICAL INSTANCE NAME the mill records
    ("ina_dec.C", "a.shunt.R") - the only stable way to tell two electrically
    identical parts apart (two 100nF on the same rail serving different pins:
    tactic 15b's served-pin map is schematic intent no net set can see);
    `prefix` on the ref (e.g. "C"),
    `fpname` substring of the footprint library item NAME, `fpid` substring of
    the FULL library id ("lib:item" - the only place a workspace part's
    manufacturer/family shows, e.g. "SMBJ" in
    `workspace_parts_STMicroelectronics_SMBJ5_0A_TR:SMB_L4.6-...`, where the
    item name is only the package), `exclude` refs already
    placed, and `group`: None = board-local (ungrouped) footprints only, a name =
    that module group, "*" = don't care. Raises LookupError unless exactly one
    hit; many=True instead returns the sorted list (possibly empty).

    SEMANTICS CHOSEN: `nets` is matched as a SUBSET of the footprint's pad nets
 - a 2-pad part is fully specified by both its nets, while an IC can be
    found by two of its many. Pass exact=True where set equality is meant, or
    a multi-net part will match extra candidates."""
    want = set(nets)
    gmap = group_of_map(board)
    hits = []
    for fp in board.GetFootprints():
        r = fp.GetReference()
        if r in exclude or (prefix and not r.startswith(prefix)):
            continue
        if group != "*" and gmap.get(r) != group:
            continue
        ns = nets_of(fp)
        if not (ns == want if exact else want <= ns):
            continue
        if fpname and fpname not in fp.GetFPID().GetLibItemName().wx_str():
            continue
        if fpid and fpid not in str(fp.GetFPIDAsString()):
            continue
        if path is not None and fp.GetFieldsText().get("Path") != path:
            continue
        hits.append(r)
    hits.sort()
    if many:
        return hits
    if len(hits) != 1:
        raise LookupError("find_by_nets(%s, prefix=%s, group=%s, path=%s) -> %s (want exactly 1)"
                          % (tuple(nets), prefix, group, path, hits))
    return hits[0]


def pool_by_nets(board, *nets, **kw):
    """find_by_nets(..., many=True): every matching ref, sorted. For rows/banks
    of identical parts (a cap row, an LED bank) placed by index."""
    kw["many"] = True
    return find_by_nets(board, *nets, **kw)
