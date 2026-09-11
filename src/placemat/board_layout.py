"""Board-level placement primitives on REAL geometry, shared by every board script.

A board script stamps module cells (rigid groups with their own copper), lands
loose parts between them, and re-drops the plane vias the cells gave up. The
only things that may collide are real courtyards, real copper and holes against
foreign pads on the other face; a bounding-box overlap is not a collision. These
primitives decide on that basis, so a board never re-implements placement with
boxes and via centres (a from-scratch run once did, and the real gates then
found 46 conflicts its own model had called clear).

    from placemat.board_layout import BoardLayout
    board = BoardLayout(L, width=56.4, height=56.4,
                     plane_nets={"GND", "V48", "5V", "24V", "3V3"},
                     redrop_keepout=[(x1, y1, x2, y2), ...])
    board.stamp("tmc", 18.5, 34.0, 270)                       # rigid cell, bbox centre on (x, y)
    board.stamp("can", 18.7, 46.3, 180, bottom=True, strip_plane_vias=True)
    board.settle_shift("can", radius=2.5)                    # nearest clear translation, orientation kept
    board.place_free("rpd_brk_pwm", 26.2, 35.3, bottom=True)  # loose part threaded between the far face's holes
    board.compact("tmc", 0, -1, limit=5.0)                   # slide until real geometry stops it
    board.grid_align("tmc")                                  # fine-pitch pad rows onto the routing grid
    board.plane("GND", chamfer=2.0)                          # a filled plane, one zone per layer
    board.plane("3V3", layers=("In2.Cu",), outline=[(x, y), ...])   # or a shaped region
    board.purge()                                            # remove doomed copper, keep re-droppable plane vias

State the script may read or extend: `placed_refs`, `doomed` (copper removed by
purge(), e.g. a cell's interconnect the board re-draws), `stripped`,
`free_placed` (inst, distance moved or None), `unstamped`, `redrop_keepout`.

Everything here is measured off the live board: courtyards from
`FOOTPRINT.GetCourtyard()` via the shared helpers, copper from effective shapes
(a diagonal track's bbox would veto placements nothing touches), holes with the
land radius the far face actually sees (a via's land, a PTH pad's annulus, an
NPTH's drill). The cell-clash test hashes the foreign geometry once per cell
into a 3 mm grid so a ring search stays fast.
"""
import glob
import hashlib
import json
import math
import os

import pcbnew

from placemat import geometry

from placemat.layout_helpers import (from_mm, to_mm, point, group_items, group_bbox_mm, group_move_to, group_move_by, group_rotate, group_flip,
                            fp_courtyard_box_mm, fp_phys_box_mm, fp_body_box_mm, fp_bbox_mm, fp_body_bbox, silk_box_mm,
                            union_box, inflate_box, boxes_overlap, knockout_label, place_hard_edge, rect_pts,
                            item_bbox_mm)


def rect_union_area(rects):
    """Exact area of a union of axis-aligned boxes (l, t, r, b), in mm^2.

    Summing boxes double-counts every overlap, and cells interleave by design
    (tactic 5b), so the sum is not a usable stand-in here."""
    rs = [r for r in rects if r and r[2] > r[0] and r[3] > r[1]]
    if not rs:
        return 0.0
    xs = sorted({v for r in rs for v in (r[0], r[2])})
    total = 0.0
    for x0, x1 in zip(xs, xs[1:]):
        w = x1 - x0
        if w <= 0:
            continue
        spans = sorted((r[1], r[3]) for r in rs if r[0] <= x0 and r[2] >= x1)
        cur, h = None, 0.0
        for a, b in spans:
            if cur is None or a > cur[1]:
                if cur:
                    h += cur[1] - cur[0]
                cur = [a, b]
            elif b > cur[1]:
                cur[1] = b
        if cur:
            h += cur[1] - cur[0]
        total += w * h
    return total


# What the order is allocating, and what each term costs. Calibratable, but not
# per board: a weight that has to be tuned per board is a weight that is not
# measuring what it claims to.
ORDER_WEIGHTS = {
    "shape": 1.0,       # how much an awkward outline adds to its own fit pressure
    "fit": 2.0,         # area pressure against everything else
    "pull": 1.0,        # declared adjacency to what is already down
    "apart": 1.5,       # a standoff that has to be claimed before the room goes
    "scarce": 2.0,      # few places left to land: take one while any are left
    "dominates": 0.25,  # fit pressure above which "does it fit at all" wins outright
}


def next_to_place(cands, free_area, weights=None):
    """Which candidate goes down next, and the sentence that chose it.

    `cands` are dicts of {name, area, w, h, bbox_area, pull, apart} - geometry
    in mm, `pull` the heaviest declared link weight to something already
    placed, `apart` 1.0 when a candidate this one must stand off from is now
    down. Pure: no board, no side effects, so the rule can be tested without
    building anything.

    Three terms and two rules:

      fit      area / free area REMAINING. First-fit-decreasing: an item placed
               late has no hole left to go in. A ratio rather than an absolute
               so it self-corrects - on a roomy board size barely matters, on a
               tight one it decides everything.
      shape    aspect and sprawl, in [0, 1], MULTIPLIED INTO FIT rather than
               added beside it. An awkward outline only costs you when holes of
               that size are scarce: a 0402 is as lopsided as a long strip and
               it has never once struggled to find a pocket.
      pull     heaviest declared link to what is already placed, which walks the
               order outward along the circuit from the fixed anchors.
      room     how many of THIS candidate would fit in the free board near the
               spot it was asked to go. It is the only term that reads the
               REQUEST rather than the cell, and it is why two identical cells
               are not interchangeable: they carry different hints, and the one
               with fewer places to land has to take one while any are left.
               Minimum-remaining-values, the standard constraint-satisfaction
               heuristic, and the same instinct as "most constrained first" -
               applied to what the candidate can still DO rather than to what
               it is.

      fit dominates      a candidate needing more than `dominates` of the free
                         area goes next whatever it connects to, because "does
                         this fit anywhere at all" outranks "is it near the
                         thing it talks to".
      seed on difficulty when nothing placed connects to anything yet, take the
                         biggest and most awkward. That is the bin-packing
                         answer and it is the right one with no graph to walk.
    """
    if not cands:
        raise ValueError("next_to_place: nothing to place")
    w = dict(ORDER_WEIGHTS)
    w.update(weights or {})
    free = max(float(free_area), 1e-6)
    rows = []
    for c in cands:
        area = max(float(c.get("area", 0.0)), 0.0)
        bw = max(float(c.get("w", 0.0)), 1e-9)
        bh = max(float(c.get("h", 0.0)), 1e-9)
        bbox = max(float(c.get("bbox_area", bw * bh)), 1e-9)
        fit = area / free
        aspect = 1.0 - min(bw, bh) / max(bw, bh)
        sprawl = max(0.0, 1.0 - area / bbox)
        shape = max(aspect, sprawl)
        # room is reported as "how many of me fit near my hint"; scarcity is
        # its inverse, so one lonely pocket outranks a wide-open face. None
        # means the caller could not measure it, which must not read as scarce.
        room = c.get("room")
        scarce = 0.0 if room is None else 1.0 / (1.0 + max(float(room), 0.0))
        rows.append(dict(name=c.get("name", "?"), fit=fit, shape=shape,
                         pressure=fit * (1.0 + w["shape"] * shape),
                         pull=max(float(c.get("pull", 0.0)), 0.0),
                         apart=max(float(c.get("apart", 0.0)), 0.0),
                         room=room, scarce=scarce))

    def pick(score):
        # DECLARATION ORDER IS NOT AN INPUT. max() returns the lowest index on a
        # tie, which is exactly the caller's order - so a stage of equal
        # candidates would be allocated by line number and nothing would say so.
        # Rank on the quantised score (float noise is not a reason to prefer a
        # candidate either) and break the tie on the name, which no reordering
        # of the file can change.
        return min(range(len(rows)),
                   key=lambda i: (-round(score(rows[i]), 9), rows[i]["name"]))

    hardest = pick(lambda r: r["pressure"])
    if rows[hardest]["pressure"] >= w["dominates"]:
        r = rows[hardest]
        return hardest, ("fit dominates: needs %.0f%% of the free area (shape %.2f)"
                         % (100.0 * r["fit"], r["shape"]))

    if all(r["pull"] <= 0.0 for r in rows):
        # Nothing to walk the order outward from, so difficulty decides - and
        # difficulty includes how little room is left where this one was asked
        # to go, which is the only thing separating two cells of the same kind.
        i = pick(lambda r: r["pressure"] + w["scarce"] * r["scarce"])
        r = rows[i]
        room = "" if r["room"] is None else ", room for %.1f of it near its hint" % r["room"]
        return i, ("seed on difficulty: no DECLARED link to anything placed "
                   "(fit %.0f%%, shape %.2f%s)" % (100.0 * r["fit"], r["shape"], room))

    top = max(r["pull"] for r in rows) or 1.0
    def score(r):
        return (w["fit"] * r["pressure"] + w["pull"] * r["pull"] / top
                + w["apart"] * r["apart"] + w["scarce"] * r["scarce"])
    best = pick(score)
    r = rows[best]
    # NAME THE TERM THAT ACTUALLY DECIDED. A reason that cites the wrong one is
    # worse than none: it is what an owner argues with, and arguing with a
    # sentence that did not choose this candidate wastes the exchange.
    parts = (("standoff", w["apart"] * r["apart"]),
             ("room", w["scarce"] * r["scarce"]),
             ("link", w["pull"] * r["pull"] / top),
             ("fit", w["fit"] * r["pressure"]))
    lead = max(parts, key=lambda p: p[1])[0]
    room = "" if r["room"] is None else ", room for %.1f of it near its hint" % r["room"]
    if lead == "standoff":
        why = ("claims its standoff now: a cell it must stand off from is down "
               "(link %.2g, fit %.0f%%)" % (r["pull"], 100.0 * r["fit"]))
    elif lead == "room":
        why = ("fewest places left to land%s (link %.2g, fit %.0f%%)"
               % (room, r["pull"], 100.0 * r["fit"]))
    elif lead == "link":
        why = ("heaviest declared link to what is already placed (weight %.2g, "
               "fit %.0f%%%s)" % (r["pull"], 100.0 * r["fit"], room))
    else:
        why = ("fit %.0f%% and shape %.2f outweigh a link of %.2g%s"
               % (100.0 * r["fit"], r["shape"], r["pull"], room))
    return best, why


def path_of(fp):
    """The generator's `Path` field: '<inst>.<PartName>' for a loose part,
    '<cell>.<member>.<PartName>' for a cell member."""
    for f in fp.GetFields():
        if f.GetName() == "Path":
            return f.GetText()
    return ""


def _boxes_overlap(a, c, gap=0.0):
    return not (a[2] + gap <= c[0] or c[2] + gap <= a[0] or a[3] + gap <= c[1] or c[3] + gap <= a[1])


def _inside(poly, x, y):
    """Even-odd point-in-polygon, for asking whether a pad sits under a zone."""
    n, inside = len(poly), False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
            inside = not inside
    return inside


def _pad_boxes(f):
    out = []
    for pd in f.Pads():
        bb = pd.GetBoundingBox()
        out.append((bb.GetLeft() / 1e6, bb.GetTop() / 1e6, bb.GetRight() / 1e6, bb.GetBottom() / 1e6))
    return out


class BoardLayout:
    """Placement state and primitives for one board (see the module docstring)."""

    BUCKET = 3.0            # spatial hash cell, mm
    EDGE_CLR = 0.4          # board edge to copper/body
    CU_CLR = 0.25           # copper-to-copper between different nets
    CY_GAP = 0.01            # courtyards may touch, not overlap
    SETTLE_MARGIN = 1.5      # how far past the first legal ring a spiral keeps looking
    SILK_GAP = 0.15         # silk boxes are centreline boxes; half a stroke each side + KiCad's own clearance

    def __init__(self, layout, width, height=None, plane_nets=(), redrop_keepout=(), groups=None):
        self.layout = layout
        self.pcb = layout.pcb
        self.width = width
        self.height = height if height is not None else width
        self.plane_nets = set(plane_nets)
        self.redrop_keepout = list(redrop_keepout)
        from placemat.layout_helpers import groups_by_name
        self.cells = groups if groups is not None else groups_by_name(self.pcb)
        self.by_path = {path_of(f): f for f in self.pcb.GetFootprints()}
        self.placed_refs = set()        # refs already on the board (only these can collide)
        self.free_calls = []            # every place_free() call, so resettle_free() can redo it
        self.reserved = []              # bands spoken for by copper not drawn yet (see reserve())
        self.free_fallback = []         # loose parts whose own nets had no room: placed on the hint
        self.doomed = []                # copper removed at the very end by purge()
        self.provisional_drops = []     # stripped plane vias kept LIVE; legality decided at save
        self.stripped = {}              # cell -> number of plane vias stripped at stamp time
        self.free_placed = []           # (inst, distance moved or None) in place_free order
        self.unstamped = set()          # cells that found no clear run and fall back to loose members
        self.stamped = set()            # cells stamp() has landed: only these own their artwork's position
        self.stamp_box = {}             # cell -> the box it landed in, for stamp_report()
        self.rules = []                 # (name, condition, constraint) for the sibling .kicad_dru
        layout.before_save.append(self._settle_drops)   # a drop's legality needs ALL the copper
        layout.on_save.append(self._write_rules)
        layout.on_save.append(self._write_stamp_provenance)
        self.flattened = set()          # cells whose own artwork is queued for removal
        self.labels = []                # (text, owner refs) for a silk-collision audit
        self.pours = []                 # (net, layer, rects) drawn by pour()
        self._foreign_cache = {}

    # -- lookup ---------------------------------------------------------------
    def part(self, inst):
        """Footprint by Zener instance path (everything but the Path's last segment)."""
        for p, f in self.by_path.items():
            if p.rsplit(".", 1)[0] == inst:
                return f
        raise KeyError(inst)

    def flatten(self, *names):
        """Queue a cell's own artwork for removal (its members get placed one by
        one instead). Copper AND the cell's silk: a fragment's knockout labels
        are drawn for the poses the fragment had, so a cell whose members are
        re-placed individually keeps labels that name nothing. Removal happens
        last, in purge(): deleting while another group's item list is later
        walked leaves dangling wrappers in pcbnew."""
        for name in names:
            self.flattened.add(name)
            for it in group_items(self.cells[name]):
                if it.GetClass() in ("PCB_TRACK", "PCB_VIA", "PCB_SHAPE", "PCB_TEXT", "PCB_TEXTBOX"):
                    self.doomed.append(it)

    # -- outline + mounting ---------------------------------------------------
    def edge(self, x1, y1, x2, y2, width=0.1):
        s = pcbnew.PCB_SHAPE(self.pcb, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(from_mm(width))
        s.SetStart(pcbnew.VECTOR2I(from_mm(x1), from_mm(y1))); s.SetEnd(pcbnew.VECTOR2I(from_mm(x2), from_mm(y2)))
        self.pcb.Add(s)
        return s

    def arc(self, cx, cy, sx, sy, angle_deg, width=0.1):
        """An Edge.Cuts arc centred on (cx, cy) from (sx, sy) through `angle_deg`."""
        a = pcbnew.PCB_SHAPE(self.pcb, pcbnew.SHAPE_T_ARC)
        a.SetLayer(pcbnew.Edge_Cuts); a.SetWidth(from_mm(width))
        a.SetCenter(pcbnew.VECTOR2I(from_mm(cx), from_mm(cy))); a.SetStart(pcbnew.VECTOR2I(from_mm(sx), from_mm(sy)))
        a.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(angle_deg, pcbnew.DEGREES_T)); self.pcb.Add(a)
        return a

    def outline_rounded(self, radius, width=0.1):
        """Rectangle W x H with rounded corners of `radius` on Edge.Cuts."""
        W, H, R = self.width, self.height, radius
        self.edge(R, 0, W - R, 0, width); self.edge(W, R, W, H - R, width)
        self.edge(W - R, H, R, H, width); self.edge(0, H - R, 0, R, width)
        self.arc(R, R, 0, R, 90, width); self.arc(W - R, R, W - R, 0, 90, width)
        self.arc(W - R, H - R, W, H - R, 90, width); self.arc(R, H - R, R, H, 90, width)

    def mounting_keepout(self, inst_or_ref, clearance, box="house"):
        """Real keepout box of a mounting hole: its own pad + annular ring +
        courtyard (`box="house"`, the house placement box) or its physical
        body box (`box="body"`), grown by `clearance`. Any other-net copper
        inside it is a short / courtyard / mask-bridge risk."""
        f = self.layout.footprints[inst_or_ref] if inst_or_ref in self.layout.footprints else self.part(inst_or_ref)
        base = fp_bbox_mm(f) if box == "house" else fp_body_box_mm(f)
        return inflate_box(base, clearance)

    def box_of(self, thing, kind="phys"):
        """The mm box of whatever a board names: a 4-tuple as given, a cell name
        (its group box), an instance path, or a refdes. `kind` picks the
        footprint box - "phys" (pads + graphics), "body", "court" or "silk"."""
        if isinstance(thing, (tuple, list)) and len(thing) == 4:
            return tuple(thing)
        if thing in self.cells:
            return group_bbox_mm(self.cells[thing])
        try:
            f = self.part(thing)
        except KeyError:
            f = self.layout.footprints[thing]
        return {"phys": fp_phys_box_mm, "body": fp_body_box_mm,
                "court": fp_courtyard_box_mm, "silk": silk_box_mm}[kind](f)

    def assert_clear(self, a, b, gap=0.0, why="", kind="phys"):
        """Assert two things do not come within `gap` of each other.

        The check a board wants to state is "these two must not touch, because
        <reason>"; written out longhand it becomes four coordinate comparisons
        whose arithmetic hides the intent and whose box choice (courtyard? pads?
        silk?) is usually accidental. State the intent, let the library measure."""
        ba, bb_ = self.box_of(a, kind), self.box_of(b, kind)
        if boxes_overlap(ba, bb_, gap):
            raise AssertionError("%s <-> %s closer than %.2f%s\n  %s %s\n  %s %s"
                                 % (a, b, gap, (" - " + why) if why else "",
                                    a, tuple(round(v, 2) for v in ba),
                                    b, tuple(round(v, 2) for v in bb_)))
        return self

    def assert_inside(self, thing, region, why="", kind="phys"):
        """Assert one thing lies wholly inside a region (a box or a cell)."""
        x1, y1, x2, y2 = self.box_of(thing, kind)
        rx1, ry1, rx2, ry2 = self.box_of(region, kind)
        if x1 < rx1 or y1 < ry1 or x2 > rx2 or y2 > ry2:
            raise AssertionError("%s is not inside %s%s\n  %s %s\n  region %s"
                                 % (thing, region, (" - " + why) if why else "", thing,
                                    tuple(round(v, 2) for v in (x1, y1, x2, y2)),
                                    tuple(round(v, 2) for v in (rx1, ry1, rx2, ry2))))
        return self

    def loose(self):
        """The footprints in no group: everything the board itself has to place.
        Sorted by reference, because the generator emits footprints in a
        different order every run and a first-match lookup would not be
        regenerable."""
        ingrp = {it.GetReference() for g in self.cells.values() for it in group_items(g)
                 if it.GetClass() == "FOOTPRINT"}
        return sorted((f for f in self.pcb.GetFootprints() if f.GetReference() not in ingrp),
                      key=lambda f: f.GetReference())

    def single_pad_by_net(self, refs=None):
        """{net: refdes} for every ONE-PAD footprint (test points, fiducials,
        pads brought out for a probe). A one-pad part has no identity but the
        net it sits on, and its refdes churns between generations."""
        out = {}
        for f in (refs if refs is not None else self.pcb.GetFootprints()):
            pads = list(f.Pads())
            if len(pads) == 1:
                out[pads[0].GetNetname()] = f.GetReference()
        return out

    def require_nets(self, *names):
        """Fail NOW if a net the script names is not on the board.

        A layout script references nets by string, and the schematic can rename
        one. Nothing then errors: a pour finds no pads, a report prints "-", a
        name in plane_nets stops matching and the stripping quietly changes.
        This turns a rename into a first-second failure that names the net."""
        have = {n.GetNetname() for n in self.pcb.GetNetsByNetcode().values()}
        want = set()
        for n in names:
            want |= set(n) if isinstance(n, (set, frozenset, list, tuple)) else {n}
        missing = sorted(w for w in want if w not in have)
        if missing:
            raise KeyError("net(s) not on this board: %s - renamed in the schematic?"
                           % ", ".join(missing))
        return self

    def content_extent(self, exclude=()):
        """Bbox of every placed part's body box, `exclude` refs skipped (mounting
        holes, render-only mockups)."""
        xs, ys = [], []
        for fp in self.pcb.GetFootprints():
            if fp.GetReference() in exclude:
                continue
            bx = fp_body_bbox(fp)
            xs += [to_mm(bx.GetLeft()), to_mm(bx.GetRight())]
            ys += [to_mm(bx.GetTop()), to_mm(bx.GetBottom())]
        return min(xs), min(ys), max(xs), max(ys)

    def outline_chamfered(self, chamfer):
        """Rectangle W x H with equal corner chamfers on Edge.Cuts."""
        W, H, CH = self.width, self.height, chamfer
        for (x1, y1, x2, y2) in [(CH, 0, W - CH, 0), (W, CH, W, H - CH), (W - CH, H, CH, H), (0, H - CH, 0, CH),
                                 (W - CH, 0, W, CH), (W, H - CH, W - CH, H), (CH, H, 0, H - CH), (0, CH, CH, 0)]:
            self.edge(x1, y1, x2, y2)

    def fix(self, inst, x, y):
        """Put a footprint at (x, y) as a fixed feature (a mounting hole)."""
        f = self.part(inst)
        f.SetPosition(pcbnew.VECTOR2I(from_mm(x), from_mm(y)))
        self.placed_refs.add(f.GetReference())
        return f

    # -- cells ----------------------------------------------------------------
    def stamp(self, name, cx, cy, rot=0, bottom=False, anchor=None, strip_plane_vias=False,
              extra_strip=(), mode=None, accept=None):
        """Stamp a cell: rotate, flip to the back if asked, then land it so that
        either its bbox centre (default) or its `anchor` member's footprint origin
        (a '<cell>.<member>' path prefix) sits on (cx, cy).
        strip_plane_vias: queue the cell's PLANE-DROP vias (gnd/rail landings) for
        removal so the cell carries no through-feature of its own beyond footprint
        PTH pads; purge() keeps the ones whose spot is clear on both faces and the
        board re-drops the rest at routing time. Placement and hot-loop copper
        stay. Never for a cell whose vias are architecture (relief lanes, silent
        rails).

        `accept` is a predicate on the landed box: a cell that can go down two
        ways (a strip that may stand either way up) states which landing it
        wanted, and the stamp adds 180 and re-anchors when the first fails,
        rather than the board writing the retry out longhand."""
        box = self._stamp_once(name, cx, cy, rot, bottom, anchor, strip_plane_vias, extra_strip, mode)
        if accept is not None and not accept(box):
            group_rotate(self.cells[name], 180, *((mode,) if mode else ()))
            box = (self.anchor_to(name, anchor, cx, cy) if anchor
                   else group_bbox_mm(self.cells[name], *((mode,) if mode else ())))
        self.stamp_box[name] = box
        return box

    def _stamp_once(self, name, cx, cy, rot, bottom, anchor, strip_plane_vias, extra_strip, mode):
        g = self.cells[name]
        self.stamped.add(name)
        margs = (mode,) if mode else ()          # the group-box mode ("physical" ...) some boards place by
        if rot:
            group_rotate(g, rot, *margs)
        if bottom:
            group_flip(g)
        group_move_to(g, cx, cy, *margs)
        if anchor:
            f = self.part(anchor); p = f.GetPosition()
            for it in group_items(g):
                it.Move(pcbnew.VECTOR2I(from_mm(cx) - p.x, from_mm(cy) - p.y))
        for it in group_items(g):
            if isinstance(it, pcbnew.FOOTPRINT):
                self.placed_refs.add(it.GetReference())
        if strip_plane_vias:
            n = 0
            for it in group_items(g):
                if it.GetClass() == "PCB_VIA" and it.GetNetname().split(".")[-1] in self.plane_nets | set(extra_strip):
                    self.doomed.append(it); n += 1
            self.stripped[name] = n
        return group_bbox_mm(g, *margs)

    def net_offset(self, name, net):
        """Where a cell's `net` copper sits relative to the cell's own centre,
        as "+x,+y of centre".

        A stamped cell lands at a rotation, and a rotation is the easiest thing
        to get wrong without noticing: the cell is in the right place, the right
        way up, and facing the wrong way. Its key net is the tell - a bridge
        frontier that should face the legs, a connector pair that should face
        the edge - so the report says which way each cell actually landed."""
        xs, ys = [], []
        for it in group_items(self.cells[name]):
            if isinstance(it, pcbnew.FOOTPRINT):
                for p in it.Pads():
                    if p.GetNetname() == net:
                        xs.append(to_mm(p.GetPosition().x)); ys.append(to_mm(p.GetPosition().y))
            elif it.GetClass() == "PCB_TRACK" and it.GetNetname() == net:
                for pt in (it.GetStart(), it.GetEnd()):
                    xs.append(to_mm(pt.x)); ys.append(to_mm(pt.y))
        if not xs:
            return "-"
        l, t, r, bo = group_bbox_mm(self.cells[name])
        return "%s@(%+.1f,%+.1f) of centre" % (net, sum(xs) / len(xs) - (l + r) / 2,
                                               sum(ys) / len(ys) - (t + bo) / 2)

    def stamp_report(self, probe_nets=()):
        """Print where every stamped cell landed, and (for the cells named in
        `probe_nets`, as {cell: net}) which way it faces - see net_offset."""
        probe = dict(probe_nets)
        for name in sorted(self.stamp_box):
            l, t, r, bo = self.stamp_box[name]
            extra = self.net_offset(name, probe[name]) if name in probe else ""
            print("  %-8s x %5.1f..%5.1f  y %5.1f..%5.1f   %s" % (name, l, r, t, bo, extra))
        return self.stamp_box

    def anchor_to(self, name, anchor, cx, cy):
        g = self.cells[name]; f = self.part(anchor); p = f.GetPosition()
        for it in group_items(g):
            it.Move(pcbnew.VECTOR2I(from_mm(cx) - p.x, from_mm(cy) - p.y))
        return group_bbox_mm(g)

    def edge_align(self, target, side, clr=0.45, group=False, box="phys"):
        """Slide a footprint (or a stamped cell) until its extent sits `clr`
        inside the named board edge: the PHYSICAL box (pads plus body graphics,
        courtyard excluded; default) or the BODY box (`box="body"`, for a part
        whose silk draws an off-board barrel). A courtyard is an assembly margin
        and may overhang; copper and body may not. Returns the delta applied."""
        if group:
            g = self.cells[target]; l, t, r, bo = group_bbox_mm(g)
        else:
            f = self.layout.footprints[target] if target in self.layout.footprints else self.part(target)
            l, t, r, bo = fp_phys_box_mm(f) if box == "phys" else fp_body_box_mm(f)
        d = {"N": (0.0, clr - t), "S": (0.0, (self.height - clr) - bo),
             "W": (clr - l, 0.0), "E": ((self.width - clr) - r, 0.0)}[side]
        if group:
            for it in group_items(g):
                it.Move(pcbnew.VECTOR2I(from_mm(d[0]), from_mm(d[1])))
        else:
            pos = f.GetPosition(); f.SetPosition(pcbnew.VECTOR2I(pos.x + from_mm(d[0]), pos.y + from_mm(d[1])))
        return d

    def hard_edge(self, ref, edge, pos, overhang=0.0, rot=None, w=None, h=None):
        """layout_helpers.place_hard_edge bound to this board's outline: the
        library measures the real rotated body box and solves the offset."""
        return place_hard_edge(self.layout, ref, edge, pos, w=self.width, h=self.height, overhang=overhang, rot=rot)

    def group_hard_edge(self, name, member_ref, x_edge, cy, outward_sign, overhang=0.0):
        """Slide a rigid cell so ONE named member's body box (its connector,
        already rotated to face outward) touches or overhangs a vertical board
        edge; the cell's overall box may be dominated by another member.
        Returns the member's inward body edge."""
        group_move_to(self.cells[name], 150, cy)
        bb = fp_body_bbox(self.layout.footprints[member_ref])
        dx = (x_edge - overhang) - to_mm(bb.GetLeft()) if outward_sign < 0 else (x_edge + overhang) - to_mm(bb.GetRight())
        group_move_by(self.cells[name], dx, 0)
        bb = fp_body_bbox(self.layout.footprints[member_ref])
        return to_mm(bb.GetRight()) if outward_sign < 0 else to_mm(bb.GetLeft())

    def place_row(self, refs, cx, cy, pitch, rot=0):
        """Parts in one row centred on (cx, cy) at `pitch` (an indicator triad,
        a resistor pair, an LED bank). refs are footprint references."""
        n = len(refs)
        for i, ref in enumerate(refs):
            self.layout.place(ref, cx + (i - (n - 1) / 2.0) * pitch, cy, rot)

    def row_clear_of(self, items, keepout, label=None, label_clear=0.0, label_half=0.0):
        """Place a row (items = [(ref, x, y, rot)]) and, if its real house box
        intersects `keepout` (l, t, r, b), slide the whole row left so its
        right edge sits 0.1 past the keepout's left edge. An optional knockout
        `label` = (text, x, y, rot, size_mm, thickness_mm) rides with the row
        and is then re-anchored off the row's real silk east face plus
        `label_half` + `label_clear`, corrected from the label's drawn box."""
        for ref, x, y, rot in items:
            self.layout.place(ref, x, y, rot)
        row_bbox = union_box([fp_bbox_mm(self.layout.footprints[r]) for r, _x, _y, _r in items])
        if boxes_overlap(row_bbox, keepout):
            shift = keepout[0] - row_bbox[2] - 0.1
            items = [(ref, x + shift, y, rot) for ref, x, y, rot in items]
            for ref, x, y, rot in items:
                self.layout.place(ref, x, y, rot)
            if label:
                t, lx, ly, lrot, sz, th = label
                label = (t, lx + shift, ly, lrot, sz, th)
            row_bbox = union_box([fp_bbox_mm(self.layout.footprints[r]) for r, _x, _y, _r in items])
        text = None
        if label:
            t, lx, ly, lrot, sz, th = label
            row_silk = max([row_bbox[2]] + [silk_box_mm(self.layout.footprints[r])[2] for r, _x, _y, _r in items])
            lx = row_silk + label_half + label_clear
            text = knockout_label(self.pcb, t, lx, ly, lrot, size_mm=sz, thickness_mm=th)
            short = label_clear - (to_mm(text.GetBoundingBox().GetLeft()) - row_silk)
            if short > 0:
                text.SetPosition(point(text.GetPosition().x + from_mm(short), text.GetPosition().y))
        return row_bbox, text

    def label(self, text, x, y, rot=0, size_mm=1.2, thickness_mm=0.2, owners=(), align=None):
        """A knockout silk label, recorded with its owner refs for the
        end-of-run collision audit.

        `align` says what the given y MEANS: None centres the label on it (the
        default), "bottom" lands the label's bottom edge there, "top" its top.
        A label is set in a row with its neighbours, and centring a vertical
        one starts a three-character marking lower than a two-character one -
        so a row of centred labels is a row that does not line up."""
        t = knockout_label(self.pcb, text, x, y, rot, size_mm=size_mm, thickness_mm=thickness_mm)
        if align in ("bottom", "top"):
            bb = t.GetBoundingBox()
            edge = bb.GetBottom() if align == "bottom" else bb.GetTop()
            t.SetPosition(point(t.GetPosition().x, t.GetPosition().y + from_mm(y) - edge))
        elif align is not None:
            raise ValueError("label align %r is not one of None, 'bottom', 'top'" % (align,))
        self.labels.append((t, set(owners)))
        return t

    def clear_of(self, item, box, gap=0.4, side=None):
        """Move a placed ITEM (a label, a marking) out of `box` by `gap`.

        Silk is placed against the geometry it names, and the thing it has to
        miss is usually something else's body or pad block - known only after
        both are down. `side` forces a direction ("W", "E", "N", "S"); the
        default takes the shortest escape. An item already clear is not moved,
        so this is a repair, not a placement.

        Returns whether it moved, so a script can say so."""
        x1, y1, x2, y2 = box
        bb = item.GetBoundingBox()
        l, t, r, bo = to_mm(bb.GetLeft()), to_mm(bb.GetTop()), to_mm(bb.GetRight()), to_mm(bb.GetBottom())
        if r < x1 or l > x2 or bo < y1 or t > y2:
            return False
        moves = {"W": (x1 - gap - r, 0.0), "E": (x2 + gap - l, 0.0),
                 "N": (0.0, y1 - gap - bo), "S": (0.0, y2 + gap - t)}
        dx, dy = moves[side] if side else min(moves.values(), key=lambda d: abs(d[0]) + abs(d[1]))
        item.Move(point(from_mm(dx), from_mm(dy)))
        return True

    def pad_xy(self, inst, key):
        """(x, y) mm of a pad on an INSTANCE, as placed - `key` is a pad number
        or a net name.

        Everything else here addresses parts by instance path, because that is
        what survives a schematic edit; the pad helpers take a refdes, so a
        script that has an instance had to convert. This is that bridge."""
        return self.layout.pad_xy(self.part(inst).GetReference(), key)

    def silk_line(self, x1, y1, x2, y2, width=0.15, layer="F.SilkS"):
        """A line on a NON-COPPER layer: a barrier a person has to see, a
        keep-clear boundary, a fold or a datum. The copper helpers layout nets and
        the outline helpers layout the board; this draws what is only ever read."""
        sg = pcbnew.PCB_SHAPE(self.pcb, pcbnew.SHAPE_T_SEGMENT)
        sg.SetLayer(self.pcb.GetLayerID(layer))
        sg.SetWidth(from_mm(width))
        sg.SetStart(point(from_mm(x1), from_mm(y1))); sg.SetEnd(point(from_mm(x2), from_mm(y2)))
        self.pcb.Add(sg)
        return sg

    def note_rect(self, x1, y1, x2, y2, width=0.15, layer="User.Comments"):
        """A rectangle on a documentation layer - a shadow, a reserved volume, a
        region a later reader needs to see. The fab never receives it, which is
        the point: it records WHY a region is empty, where a keepout would also
        constrain the board."""
        sh = pcbnew.PCB_SHAPE(self.pcb, pcbnew.SHAPE_T_RECTANGLE)
        sh.SetLayer(self.pcb.GetLayerID(layer))
        sh.SetWidth(from_mm(width))
        sh.SetStart(point(from_mm(x1), from_mm(y1))); sh.SetEnd(point(from_mm(x2), from_mm(y2)))
        self.pcb.Add(sh)
        return sh

    def mockup(self, ref, model, x, y, rot=0, bottom=False, value=""):
        """A render-only footprint carrying nothing but a 3D model.

        A plugged module, a mating connector, a case boss: a part the board has
        to make room for and a reviewer has to SEE in the iso render, that no
        netlist carries because the board does not buy it. Marked board-only and
        out of the BOM and the position file, so it reaches the render and
        nothing else."""
        fp = pcbnew.FOOTPRINT(self.pcb)
        fp.SetReference(ref)
        fp.SetValue(value or (ref + "-mockup"))
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        fp.SetAttributes(pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_BOARD_ONLY)
        m = pcbnew.FP_3DMODEL()
        m.m_Filename = model
        fp.Models().push_back(m)
        self.pcb.Add(fp)
        if rot:
            fp.SetOrientationDegrees(rot)
        if bottom:
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetPosition(point(from_mm(x), from_mm(y)))
        return fp

    def label_at_part(self, inst, text, y_edge, size_mm=0.9, rot=90, thickness_mm=0.15):
        """A knockout marking centred on the x of the part it names, read from
        where the part actually landed. Vertical markings land their BOTTOM
        edge on y_edge, horizontal ones their centre."""
        f = self.part(inst)
        x = to_mm(f.GetPosition().x)
        t = knockout_label(self.pcb, text, x, y_edge, rot, size_mm=size_mm, thickness_mm=thickness_mm)
        if rot in (90, 270):
            bb = t.GetBoundingBox()
            t.SetPosition(point(t.GetPosition().x, t.GetPosition().y + from_mm(y_edge) - bb.GetBottom()))
        self.labels.append((t, {f.GetReference()}))
        return t

    def tp_row(self, items, y, size_mm, thickness_mm, gap):
        """Test points in one row with rotated knockout labels under them:
        items = [(ref, x, label_text)]. Each label's NORTH end sits on its own
        TP's south body edge + `gap`. Returns the deepest silk y."""
        deep = y
        for ref, x, txt in items:
            self.layout.place(ref, x, y, 0)
            base = to_mm(fp_body_bbox(self.layout.footprints[ref]).GetBottom()) + gap
            t = knockout_label(self.pcb, txt, x, base, 90, size_mm=size_mm, thickness_mm=thickness_mm)
            t.SetPosition(point(from_mm(x), from_mm(base + (base - to_mm(t.GetBoundingBox().GetTop())))))
            tb = t.GetBoundingBox()
            assert to_mm(tb.GetTop()) >= base - 0.01, ref
            deep = max(deep, to_mm(tb.GetBottom()))
        return deep

    def assert_pour_clear(self, net, rects, layer="F.Cu", clearance=0.2):
        """No foreign pad may intersect any pour rect. F.Cu pours check SMD and
        THT pads; B.Cu pours check only THT (SMD pads live on F.Cu alone)."""
        for fp in self.pcb.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() == net:
                    continue
                tht = p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
                if layer == "B.Cu" and not tht:
                    continue
                bbp = p.GetBoundingBox()
                box = (to_mm(bbp.GetLeft()) - clearance, to_mm(bbp.GetTop()) - clearance,
                       to_mm(bbp.GetRight()) + clearance, to_mm(bbp.GetBottom()) + clearance)
                for rc in rects:
                    assert not boxes_overlap(box, rc), \
                        "pour %s on %s hits %s.%s (%s) at %s" % (net, layer, fp.GetReference(), p.GetNumber(), p.GetNetname(), rc)

    def _npth_circles(self, clearance):
        """(x, y, radius) to cut out of a fill: every UNPLATED drill, grown by
        `clearance`. An unplated hole is drilled through whatever copper is
        under it, and KiCad's own fill does not pull back from one - it prices
        copper against nets and an NPTH barrel has no net."""
        out = []
        for f in self.pcb.GetFootprints():
            for pd in f.Pads():
                if pd.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                    continue
                r = max(pd.GetDrillSize().x, pd.GetDrillSize().y) / 2e6
                out.append((pd.GetPosition().x / 1e6, pd.GetPosition().y / 1e6, r + clearance))
        return out

    def plane(self, net, layers=("F.Cu", "B.Cu"), outline=None, inset=0.4,
              clearance=0.2, min_thickness=0.2, chamfer=None, solid_pads=True,
              fill=True, npth_clearance=0.25):
        """A filled plane on `net`, as a KiCad ZONE per layer.

        A plane has to pull back around every pad, track and via that is not on
        its net, and to do it again after each routing change. That is what a
        zone is; a drawn polygon cannot, and a signal crossing one would be a
        short rather than a gap. So a board plane is a zone even though the
        cells' own power copper is drawn - the cells shape copper by hand, the
        board fills what is left.

        `outline` is the shape to fill: omit it for the whole layer (the board
        edge inset by `inset`, with the same corner chamfer), which is what a
        DEDICATED plane layer wants, or pass a vertex list [(x, y), ...] for a
        shaped region, which is what a power layer usually needs - it rarely
        carries one rail for the whole board, and two rails have to divide it.

        `solid_pads` connects pads to the fill without thermal spokes: on a
        0.5 mm-pitch package the spokes do not fit, and a ground pin that gets
        no spoke is a pin the fill has not joined - which is the whole job for
        a ground plane (skill tactic 12's EP-grounded exception relies on it).
        Returns the zones.
        """
        W, H = self.width, self.height
        ch = (chamfer if chamfer is not None else 0.0)
        i = inset
        pts = list(outline) if outline else [
            (ch + i, i), (W - ch - i, i), (W - i, ch + i), (W - i, H - ch - i),
            (W - ch - i, H - i), (ch + i, H - i), (i, H - ch - i), (i, ch + i)]
        code = self.layout._nc(net)
        zones = []
        # One zone per layer, same outline and settings, independent objects -
        # so a face can later take its own pull-back without splitting a
        # multi-layer zone. Deduplicated: a caller that builds the tuple
        # programmatically can repeat a layer, and two identical zones stacked
        # on one layer is copper nobody meant to layout.
        for layer in dict.fromkeys(layers):
            z = pcbnew.ZONE(self.pcb)
            z.SetLayer(self.pcb.GetLayerID(layer))
            z.SetNetCode(code)
            z.SetLocalClearance(from_mm(clearance))
            z.SetMinThickness(from_mm(min_thickness))
            z.SetIsRuleArea(False)
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if solid_pads
                               else pcbnew.ZONE_CONNECTION_THERMAL)
            o = z.Outline()
            o.NewOutline()
            for x, y in pts:
                o.Append(from_mm(x), from_mm(y))
            for hx, hy, hr in self._npth_circles(npth_clearance):
                # CIRCUMSCRIBED: a polygon through the points of the circle sits
                # INSIDE it between them, so an inscribed cut leaves a sliver of
                # copper within the clearance all the way round - 0.007 mm2 of
                # it at 32 sides, which the occupancy gate reads as a real
                # finding. Push the vertices out by 1/cos(pi/n) instead.
                # ...and a margin on top: KiCad fills a zone with its own
                # segment approximation of the cut, which lands a fraction of a
                # micron inside the clearance and reads as a finding. 0.02
                # absorbs it and is a hundredth of the clearance it protects.
                n = 32
                rr = (hr + 0.02) / math.cos(math.pi / n)
                hole = pcbnew.SHAPE_POLY_SET()
                hole.NewOutline()
                for a in range(n):
                    th = 2.0 * math.pi * a / n
                    hole.Append(from_mm(hx + rr * math.cos(th)), from_mm(hy + rr * math.sin(th)))
                o.BooleanSubtract(hole)
            self.pcb.Add(z)
            zones.append(z)
        if fill:
            pcbnew.ZONE_FILLER(self.pcb).Fill(self.pcb.Zones())
        return zones

    def foreign_vias(self, x0, y0, x1, y1, net=None):
        """(x, y, left, right, bottom) mm of every via in the rectangle that is
        NOT on `net` - the holes a pour drawn here has to clear."""
        out = []
        for t in self.pcb.GetTracks():
            if t.GetClass() != "PCB_VIA" or (net is not None and t.GetNetname() == net):
                continue
            x, y = to_mm(t.GetPosition().x), to_mm(t.GetPosition().y)
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                continue
            bb = t.GetBoundingBox()
            out.append((x, y, to_mm(bb.GetLeft()), to_mm(bb.GetRight()), to_mm(bb.GetBottom())))
        return sorted(out)

    def band_with_notches(self, net, x0, x1, y_top, y_bot, clear=0.35):
        """Points for a copper band across (x0..x1, y_top..y_bot) whose TOP edge
        steps around every foreign hole inside it.

        A bar drawn straight through a foreign via is a short; drawn to miss it
        by eye it is either a clearance violation or a bar that gave up half its
        width for one hole. The notch is measured off each via's own land, so
        the band keeps full width everywhere else."""
        pts = [(x0, y_top)]
        for _hx, _hy, hl, hr, hb in self.foreign_vias(x0, y_top, x1, y_bot, net=net):
            pts += [(hl - clear, y_top), (hl - clear, hb + clear),
                    (hr + clear, hb + clear), (hr + clear, y_top)]
        pts += [(x1, y_top), (x1, y_bot), (x0, y_bot)]
        return pts

    def rule_area(self, x0, y0, x1, y1, layers=("F.Cu", "B.Cu"), name="keepout",
                  tracks=False, vias=False, pads=True, footprints=False, fill=False):
        """A KiCad rule area over a rectangle: each flag says what is ALLOWED
        there (pads default on - a keepout drawn over a part's own pads is a
        keepout nobody can satisfy).

        Use it for a volume the board must keep clear for a reason no netlist
        carries: an antenna window, a mating volume, a creepage gap, a thermal
        or isolation region."""
        out = []
        for lay in layers:
            z = pcbnew.ZONE(self.pcb)
            z.SetIsRuleArea(True)
            z.SetDoNotAllowTracks(not tracks)
            z.SetDoNotAllowVias(not vias)
            z.SetDoNotAllowPads(not pads)
            z.SetDoNotAllowFootprints(not footprints)
            if hasattr(z, "SetDoNotAllowZoneFills"):
                z.SetDoNotAllowZoneFills(not fill)
            else:
                z.SetDoNotAllowCopperPour(not fill)
            z.SetLayer(self.pcb.GetLayerID(lay))
            o = z.Outline(); o.NewOutline()
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                o.Append(from_mm(x), from_mm(y))
            z.SetZoneName("%s_%s" % (name, lay.split(".")[0]))
            self.pcb.Add(z)
            out.append(z)
        return out

    def design_rule(self, name, condition, constraint):
        """One KiCad custom rule, written to the sibling .kicad_dru on save.

        The generated board directory is rebuilt from the schematic every run,
        so a rule file that is not written by the script does not survive - and
        the DRC the pass runs (and the routing trial, which copies the .dru
        beside the board) would then judge the board by rules the board was
        never designed to."""
        self.rules.append((name, condition, constraint))
        return self

    def cell_clearance(self, cell, mm, why=""):
        """Relax clearance to `mm` INSIDE one stamped cell.

        A cell is verified at its own clearance; a board netclass written for
        its bus copper can demand more than a fine-pitch package can physically
        give between its own adjacent pads, and every pass then reports
        violations in geometry nobody can change. Scope it to the cell, and say
        why - this is a waiver, and a waiver without a reason is a silenced
        check."""
        return self.design_rule("%s cell internal%s" % (cell, (" - " + why) if why else ""),
                                "A.memberOf('%s') && B.memberOf('%s')" % (cell, cell),
                                "(constraint clearance (min %smm))" % mm)

    def _write_rules(self, pcb_path):
        """Save hook: the .kicad_dru beside the board (KiCad reads it by name)."""
        dru = os.path.splitext(pcb_path)[0] + ".kicad_dru"
        if not self.rules:
            if os.path.exists(dru):
                os.remove(dru)          # rules were withdrawn: do not leave the last run's file
            return
        body = ["(version 1)"]
        for name, condition, constraint in self.rules:
            body.append('(rule "%s"\n  (condition "%s")\n  %s)' % (name, condition, constraint))
        open(dru, "w").write("\n".join(body) + "\n")

    def stamped_modules(self, pcb_path=None):
        """{module name: (folder, fragment path, instance count)} for the cells
        this board stamped - resolved the way the derived clearance floors do,
        through each instance's own name in the board's .zen sources."""
        from placemat import clearance_floors as cf
        pcb_path = os.path.abspath(pcb_path or self.layout.path)
        # ASK THE PROJECT which board this is. Counting dirname() calls encoded
        # <board>/layout/<Name>/layout.kicad_pcb in the library as though it
        # were a law, and it is this repo's convention.
        from placemat import project
        board_dir = project.active().board_dir_of(pcb_path) or \
            os.path.dirname(os.path.dirname(os.path.dirname(pcb_path)))
        zens = [z for z in sorted(glob.glob(os.path.join(board_dir, "*.zen")))]
        if not zens:
            return {}
        exact, prefix = cf.instances(zens)
        dirs = cf.module_dirs(cf.repo_root(board_dir))
        # From the BOARD, not from what this script happened to call: a cell is
        # stamped whether the script moved it with stamp(), with group ops, or
        # left it where the generator put it. Every footprint carries its
        # instance path, so the board itself says which cells it holds.
        insts = {p.split(".", 1)[0] for p in self.by_path if "." in p}
        out = {}
        for inst in sorted(insts):
            mod = cf.module_of(inst, exact, prefix)
            d = dirs.get(mod) if mod else None
            if not d:
                continue
            frag = os.path.join(d, "layout", "layout.kicad_pcb")
            if not os.path.exists(frag):
                continue
            name, folder, path_, n = mod, d, frag, out.get(mod, (None, None, 0))[2]
            out[name] = (folder, path_, n + 1)
        return out

    def _write_stamp_provenance(self, pcb_path):
        """Save hook: record WHICH VERSION of each cell this board was placed
        against, as board properties, inside the board file.

        A module's layout reaches a board only when the board is generated from
        an empty directory - the generator applies a fragment solely to
        footprints that are new in that sync, because re-applying it to parts
        already on a board would move them. So a board placed last month and a
        cell re-laid-out yesterday disagree, and nothing says so: the board
        still opens, still passes DRC, and its own geometry asserts fail the
        moment somebody regenerates it.

        The record travels INSIDE the board file, so it survives a checkout and
        answers the question without regenerating anything (`placemat stale`)."""
        mods = self.stamped_modules(pcb_path)
        if not mods:
            return
        # the map hands back wxString keys, which are not str
        props = {str(k): str(v) for k, v in self.pcb.GetProperties().items()
                 if not str(k).startswith("stamp.")}
        for mod, (_folder, frag, n) in sorted(mods.items()):
            props["stamp." + mod] = "%s x%d" % (
                hashlib.sha256(open(frag, "rb").read()).hexdigest()[:12], n)
        m = pcbnew.MAP_STRING_STRING()
        for k, v in props.items():
            m[k] = v
        self.pcb.SetProperties(m)
        self.pcb.Save(pcb_path)          # the hook runs after the write, so re-save with it

    def pour(self, net, rects, layer="F.Cu", stroke=0.2, clearance=0.2):
        """Board-level power copper as axis-aligned rectangles, each proven
        clear of every foreign pad first; recorded in `self.pours`."""
        self.assert_pour_clear(net, rects, layer, clearance)
        for rc in rects:
            self.layout.poly(net, rect_pts(*rc), layer=layer, stroke_mm=stroke)
        self.pours.append((net, layer, rects))

    def place(self, inst, x, y, rot=0, bottom=False):
        f = self.part(inst)
        if bottom and not f.IsFlipped():
            f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        f.SetPosition(pcbnew.VECTOR2I(from_mm(x), from_mm(y)))
        f.SetOrientationDegrees(rot)
        self.placed_refs.add(f.GetReference())
        return f

    def place_knob(self, inst, y, side="E", x=None):
        """Stand a side-actuated part (its actuator is the asymmetric end of its
        own body) against a board edge, actuator outward and flush with the
        outline. The rotation is chosen by measuring which way the BODY overhangs
        the PAD field, never assumed (a whole-outline measure picks the wrong
        rotation on a switch whose pads reach further than its knob)."""
        f = self.part(inst)
        best = None
        cx = x if x is not None else self.width / 2
        for r in (0, 90, 180, 270):
            f.SetOrientationDegrees(r)
            f.SetPosition(pcbnew.VECTOR2I(from_mm(cx), from_mm(y)))
            sl, st, sr, sb = silk_box_mm(f)
            pads = _pad_boxes(f)
            pl, pt, pr, pb = (min(q[0] for q in pads), min(q[1] for q in pads),
                              max(q[2] for q in pads), max(q[3] for q in pads))
            over = {"E": sr - pr, "W": pl - sl, "N": pt - st, "S": sb - pb}[side]
            if best is None or over > best[1]:
                best = (r, over)
        f.SetOrientationDegrees(best[0])
        f.SetPosition(pcbnew.VECTOR2I(from_mm(cx), from_mm(y)))
        self.edge_align(inst, side, clr=0.0)
        self.placed_refs.add(f.GetReference())
        return f

    # -- geometry the tests read ----------------------------------------------
    def _doomed_uu(self):
        return {it.m_Uuid.AsString() for it in self.doomed}

    def _through_points(self):
        """(x, y, owner, land radius) for every hole that punches both faces.
        The radius is what the far face actually sees: a via's land, a PTH pad's
        annulus (an M3 mounting pad is 6.4 across), or an NPTH's drill."""
        doomed = self._doomed_uu()
        pts = []
        for t in self.pcb.GetTracks():
            if t.GetClass() == "PCB_VIA" and t.m_Uuid.AsString() not in doomed:
                pts.append((t.GetPosition().x / 1e6, t.GetPosition().y / 1e6, "via", t.GetWidth() / 2e6))
        for f in self.pcb.GetFootprints():
            if f.GetReference() not in self.placed_refs:
                continue
            for pd in f.Pads():
                if pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                    bb = pd.GetBoundingBox()
                    pts.append((pd.GetPosition().x / 1e6, pd.GetPosition().y / 1e6, f.GetReference(),
                                max(bb.GetWidth(), bb.GetHeight()) / 2e6))
                elif pd.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    pts.append((pd.GetPosition().x / 1e6, pd.GetPosition().y / 1e6, f.GetReference(),
                                max(pd.GetDrillSize().x, pd.GetDrillSize().y) / 2e6))
        return pts

    def _face_copper(self, layer):
        """Live copper (tracks + filled polygons) on `layer`, doomed items
        excluded: what a loose part's pads must clear."""
        doomed = self._doomed_uu()
        items = []
        for t in self.pcb.GetTracks():
            if t.GetClass() == "PCB_TRACK" and t.GetLayer() == layer and t.m_Uuid.AsString() not in doomed:
                items.append(t)
        for d in self.pcb.GetDrawings():
            if d.GetClass() == "PCB_SHAPE" and d.GetLayer() == layer and d.m_Uuid.AsString() not in doomed and d.GetNetCode() > 0:
                items.append(d)
        return [(it, it.GetBoundingBox()) for it in items]

    # -- re-dropping stripped plane vias --------------------------------------
    def redrop_ok(self, v):
        """A stripped plane via may stay where its cell put it if the hole clears
        every foreign pad on both faces (land + 0.30), every foreign track or
        polygon on EVERY copper layer (land + 0.25), no other hole within 0.8,
        and it is outside every reserved lane."""
        vx, vy = v.GetPosition().x / 1e6, v.GetPosition().y / 1e6
        if not (0.4 <= vx <= self.width - 0.4 and 0.4 <= vy <= self.height - 0.4):
            return False                # a flattened cell's via still at the fragment's own origin, off the board
        for x1, y1, x2, y2 in self.redrop_keepout:
            if x1 - 0.3 <= vx <= x2 + 0.3 and y1 - 0.3 <= vy <= y2 + 0.3:
                return False
        reach = 0.30 + 0.30
        for f in self.pcb.GetFootprints():
            if f.GetReference() not in self.placed_refs:
                continue
            for pd in f.Pads():
                if pd.GetNetCode() == v.GetNetCode():
                    continue
                bb = pd.GetBoundingBox()
                if bb.GetLeft() / 1e6 - reach <= vx <= bb.GetRight() / 1e6 + reach and bb.GetTop() / 1e6 - reach <= vy <= bb.GetBottom() / 1e6 + reach:
                    return False
        doomed = self._doomed_uu()
        for t in self.pcb.GetTracks():
            if t.GetClass() == "PCB_VIA" and t.m_Uuid.AsString() not in doomed and t.m_Uuid.AsString() != v.m_Uuid.AsString():
                tp = t.GetPosition()
                if abs(tp.x / 1e6 - vx) < 0.8 and abs(tp.y / 1e6 - vy) < 0.8:
                    return False
        vbb = v.GetBoundingBox(); vbb.Inflate(from_mm(0.6))
        for layer in self._cu_layers():   # a through via punches every one of them
            vshape = v.GetEffectiveShape(layer)
            for it, bb in self._face_copper(layer):
                if it.GetNetCode() == v.GetNetCode() or it.m_Uuid.AsString() in doomed or not vbb.Intersects(bb):
                    continue
                if vshape.Collide(it.GetEffectiveShape(layer), from_mm(0.25)):
                    return False
        return True

    # -- serving a plane ------------------------------------------------------
    def _cu_layers(self):
        return list(self.pcb.GetEnabledLayers().CuStack())

    def _layer_copper(self, lid):
        """Live copper items on one layer, doomed excluded, with bounding boxes.
        `_face_copper` under its own name: it never was face-specific."""
        return self._face_copper(lid)

    def drop_ok(self, x, y, netcode, land=0.30, pad_clr=0.30, cu_clr=0.25, hole_gap=0.8):
        """Can a through via on `netcode` go at (x, y)? None when it can, and
        the reason it cannot otherwise.

        The same test redrop_ok() applies to a via a cell already placed, asked
        about a point instead - and asked on EVERY copper layer, because a
        through via punches all of them and a board with rails on its inner
        layers has copper there to hit.
        """
        e = self.EDGE_CLR + land
        if not (e <= x <= self.width - e and e <= y <= self.height - e):
            return "off the board"
        for x1, y1, x2, y2 in self.redrop_keepout:
            if x1 - land <= x <= x2 + land and y1 - land <= y <= y2 + land:
                return "reserved lane"
        reach = land + pad_clr
        for f in self.pcb.GetFootprints():
            if f.GetReference() not in self.placed_refs:
                continue
            for pd in f.Pads():
                if pd.GetNetCode() == netcode:
                    continue
                bb = pd.GetBoundingBox()
                if (bb.GetLeft() / 1e6 - reach <= x <= bb.GetRight() / 1e6 + reach
                        and bb.GetTop() / 1e6 - reach <= y <= bb.GetBottom() / 1e6 + reach):
                    return "pad %s.%s" % (f.GetReference(), pd.GetNumber())
        for px, py, owner, pr in self._through_points():
            if math.hypot(px - x, py - y) < (hole_gap if owner == "via" else pr + reach):
                return "hole (%s)" % owner
        pt = point(from_mm(x), from_mm(y))
        for lid in self._cu_layers():
            for it, bb in self._layer_copper(lid):
                if it.GetNetCode() == netcode:
                    continue
                if not (bb.GetLeft() / 1e6 - reach <= x <= bb.GetRight() / 1e6 + reach
                        and bb.GetTop() / 1e6 - reach <= y <= bb.GetBottom() / 1e6 + reach):
                    continue
                if it.GetEffectiveShape(lid).Collide(pt, from_mm(land + cu_clr)):
                    return "copper on %s" % self.pcb.GetLayerName(lid)
        return None

    def stub_ok(self, x1, y1, x2, y2, netcode, lid, w=0.25, clr=0.25, pad_clr=0.20):
        """Can a track of width `w` run from (x1, y1) to (x2, y2) on layer `lid`?
        None when it can, the reason it cannot otherwise. Sampled along the run
        rather than swept: the runs this answers for are short stubs, and a
        sample every tenth of a millimetre is finer than the clearance it
        protects."""
        halo = w / 2
        n = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.1) + 1)
        pts = [(x1 + (x2 - x1) * k / (n - 1), y1 + (y2 - y1) * k / (n - 1)) for k in range(n)]
        for f in self.pcb.GetFootprints():
            if f.GetReference() not in self.placed_refs:
                continue
            for pd in f.Pads():
                if pd.GetNetCode() == netcode or not pd.IsOnLayer(lid):
                    continue
                bb = pd.GetBoundingBox()
                r = halo + pad_clr
                for x, y in pts:
                    if (bb.GetLeft() / 1e6 - r <= x <= bb.GetRight() / 1e6 + r
                            and bb.GetTop() / 1e6 - r <= y <= bb.GetBottom() / 1e6 + r):
                        return "pad %s.%s" % (f.GetReference(), pd.GetNumber())
        same = {(v.GetPosition().x / 1e6, v.GetPosition().y / 1e6) for v in self.pcb.GetTracks()
                if v.GetClass() == "PCB_VIA" and v.GetNetCode() == netcode}
        for px, py, owner, pr in self._through_points():
            if (px, py) in same:
                continue                                  # the net's own drop is what this runs to
            r = halo + clr + pr
            for x, y in pts:
                if math.hypot(px - x, py - y) < r:
                    return "hole (%s)" % owner
        for it, bb in self._layer_copper(lid):
            if it.GetNetCode() == netcode:
                continue
            shape = it.GetEffectiveShape(lid)
            for x, y in pts:
                if not (bb.GetLeft() / 1e6 - 1 <= x <= bb.GetRight() / 1e6 + 1
                        and bb.GetTop() / 1e6 - 1 <= y <= bb.GetBottom() / 1e6 + 1):
                    continue
                if shape.Collide(point(from_mm(x), from_mm(y)), from_mm(halo + clr)):
                    return "copper on %s" % self.pcb.GetLayerName(lid)
        return None

    def plane_serve(self, net, layer, region=None, w=0.25, reach=2.6, step=0.2):
        """Give every unserved ISLAND of `net` a via down to the plane on `layer`.

        A plane reaches a pad through a via, so what the plane layer needs from
        the board is one drop per island of the net - not one per pad. A cell
        that dropped its own via has already been served, and a pad joined to
        that via by the cell's copper is served through it; what is left is the
        board's loose parts and the pads a cell left bare on purpose. So the
        unit here is the connected ISLAND: one that already owns a via is
        skipped, one that does not gets exactly one drop.

        The drop is via-in-pad where every layer is clear under the pad, and
        otherwise a stub on the pad's own face out to the nearest clear point
        within `reach` (spiral, `step` mm). `region` is the plane's own outline:
        an island with no pad inside it cannot be served from this layer, and is
        reported rather than drilled into nothing.

        Returns (n_served, [(island label, why not), ...]) and prints both.
        """
        code = self.layout._nc(net)
        clusters = self.layout.oracle.refresh()._cluster().get(net, [])
        objs = self.layout.oracle._cluster_objs.get(net, [])
        served, refused = 0, []
        for labels, items in zip(clusters, objs):
            if any(isinstance(it, pcbnew.PCB_VIA) for it in items):
                continue                                  # a cell already dropped this one
            pads = [it for it in items if isinstance(it, pcbnew.PAD)]
            pads.sort(key=lambda p: -min(p.GetSize().x, p.GetSize().y))
            spot = None
            for pd in pads:
                px, py = pd.GetPosition().x / 1e6, pd.GetPosition().y / 1e6
                if region is not None and not _inside(region, px, py):
                    continue
                lid = pd.GetLayerSet().CuStack()[0]
                for r in [0.0] + [step * k for k in range(1, int(reach / step) + 1)]:
                    n = max(1, int(2 * math.pi * r / step))
                    for j in range(n):
                        a = 2 * math.pi * j / n
                        cx, cy = px + r * math.cos(a), py + r * math.sin(a)
                        if region is not None and not _inside(region, cx, cy):
                            continue
                        if self.drop_ok(cx, cy, code) is not None:
                            continue
                        if r > 0 and self.stub_ok(px, py, cx, cy, code, lid, w=w) is not None:
                            continue                      # the drop is clear, the stub to it is not
                        spot = (pd, lid, px, py, cx, cy)
                        break
                    if spot:
                        break
                if spot:
                    break
            if spot is None:
                inside = any(region is None or _inside(region, p.GetPosition().x / 1e6,
                                                       p.GetPosition().y / 1e6) for p in pads)
                refused.append((labels[0], "no clear drop within %.1f mm" % reach
                                if inside else "outside the plane's own outline"))
                continue
            pd, lid, px, py, cx, cy = spot
            if math.hypot(cx - px, cy - py) > 1e-6:
                self.layout.track(net, w, px, py, cx, cy, layer=self.pcb.GetLayerName(lid))
            self.layout.via(net, cx, cy)
            served += 1
        print("plane_serve %s on %s: %d island(s) dropped, %d refused%s"
              % (net, layer, served, len(refused),
                 "".join("\n   %-14s %s" % r for r in refused)))
        return served, refused

    def spine(self, net, layer, runs, snap=1.5):
        """Join a net's plane drops with hand-planned runs on `layer`.

        A rail with a handful of pads gets a drop per island from plane_serve()
        and then has to be JOINED, which is routing, not filling. `runs` is
        [(width, [(x, y), ...]), ...] in board mm - the lanes a person chose
        through the layer's via field, which no rule can pick for them.

        Each run's ENDPOINTS snap to the nearest drop within `snap`, so the run
        still lands on its via after a loose part moves; interior points are
        taken as written. An endpoint with no drop near it is printed, because
        that is the case where the lane no longer means what it meant.
        """
        vias = [(v.GetPosition().x / 1e6, v.GetPosition().y / 1e6) for v in self.pcb.GetTracks()
                if v.GetClass() == "PCB_VIA" and v.GetNetname().split(".")[-1] == net.split(".")[-1]]
        loose, moved, drawn = [], 0, 0
        for w, pts in runs:
            pts = list(pts)
            ok = True
            for i in (0, -1):
                x, y = pts[i]
                near = sorted(vias, key=lambda v: math.hypot(v[0] - x, v[1] - y))
                if near and math.hypot(near[0][0] - x, near[0][1] - y) <= snap:
                    if math.hypot(near[0][0] - x, near[0][1] - y) > 0.01:
                        moved += 1
                    pts[i] = near[0]
                else:
                    loose.append((x, y))
                    ok = False
            # A RUN WITH A LOOSE END IS NOT DRAWN. Its endpoint was a drop when
            # the lane was planned; if the drop is gone the cell now joins that
            # pad itself, or it moved - either way the lane no longer means what
            # it meant, and copper drawn into open board is worse than a gap the
            # report names.
            if ok:
                self.layout.route(net, pts, w=w, layer=layer)
                drawn += 1
        print("spine %s on %s: %d of %d run(s) drawn, %d end(s) snapped to a moved drop%s"
              % (net, layer, drawn, len(runs), moved,
                 "".join("\n   loose end at (%.2f, %.2f): no drop within %.1f mm - run skipped"
                         % (x, y, snap) for x, y in loose)))
        return loose

    def purge(self, redrop_nets=()):
        """Remove the doomed copper. A plane-drop via (a plane net, or one of
        `redrop_nets`) stays where its cell put it when redrop_ok() says its spot
        is free on both faces."""
        # A cell that was never stamped still has its fragment's copper and silk
        # AT THE FRAGMENT ORIGIN - tens of millimetres off the board - because
        # only stamp() moves a group. Its members were placed one by one, so that
        # artwork belongs to nothing: flatten it here rather than trust every
        # board script to remember. Flattening before the first Remove() keeps
        # the group item lists walkable.
        orphans = sorted(set(self.cells) - self.stamped - self.flattened)
        if orphans:
            print("purge: unstamped cells, artwork left at the fragment origin: %s" % orphans)
            self.flatten(*orphans)
        keep_nets = self.plane_nets | set(redrop_nets)
        seen = set(); n = 0; kept = 0
        for it in self.doomed:
            k = it.m_Uuid.AsString()
            if k in seen:
                continue
            seen.add(k)
            if it.GetClass() == "PCB_VIA" and it.GetNetname().split(".")[-1] in keep_nets:
                # PROVISIONAL, not decided. Whether this via may stay depends
                # on copper not drawn yet - the rails, the spines, the zones -
                # so the question has no answer here. It stays LIVE, so every
                # geometry test after this sees a real via and nothing settles
                # on top of it, and _settle_drops() removes it at save if the
                # finished board makes it illegal. Present-until-disproved: the
                # cost of being wrong is a reported unlanded drop.
                self.provisional_drops.append(it)
                kept += 1; continue
            self.pcb.Remove(it); n += 1
        # NOTHING IS DOOMED ANY MORE: every item here was either removed from the
        # board or kept as live copper. Leaving the kept ones on the list makes
        # them INVISIBLE - _doomed_uu() is consulted by every geometry test after
        # this point, so a re-dropped via would go on reading as absent to
        # drop_ok, stub_ok, the face-copper scan and the loose-part repair pass,
        # and a part settled on top of one would look legal right up to DRC.
        self.doomed = []
        print(f"purged {n} copper items; {kept} stripped plane vias held live pending the "
              f"save-time check (stripped per cell: {self.stripped})")
        return n, kept

    def _settle_drops(self):
        """Terminal step: drop the provisional vias the finished board rejects.

        Runs from `before_save`, so it sees every rail, spine, zone and trace
        the script drew, which is the only state in which "may this via stay"
        has an answer. A script cannot call it: the answer would then sit at
        whatever line the call was written on, and a rail drawn afterwards
        would cross a via that was legal when it was asked.

        What it removes it REPORTS. An unlanded drop is outstanding work the
        stamp-contract gate counts; a short is a puzzle."""
        if not self.provisional_drops:
            return
        gone = []
        for v in self.provisional_drops:
            if self.redrop_ok(v):
                continue
            p = v.GetPosition()
            gone.append((v.GetNetname().split(".")[-1], round(to_mm(p.x), 2), round(to_mm(p.y), 2)))
            self.pcb.Remove(v)
        held = len(self.provisional_drops) - len(gone)
        self.provisional_drops = []
        print("drops: %d held, %d removed as illegal against the finished board%s"
              % (held, len(gone), (" " + repr(gone[:8])) if gone else ""))

    # -- loose parts ----------------------------------------------------------
    def reserve(self, x0, y0, x1, y1, layer=None, why="", allow=(), no_vias=False):
        """Declare a band that loose parts may not enter, because copper that is
        not drawn yet will occupy it.

        The board draws its own copper AFTER the loose parts go down - it has to,
        since most of that copper is anchored on where the parts landed - so
        place_free() cannot see it. While the hints were hand-picked this never
        showed. Once the search follows each part's own nets it will happily
        settle a part in the middle of a bar the script is about to layout, and the
        first anyone hears of it is a short in DRC.

        A reservation is a claim with a reason, not a fudge: say WHY, and only
        for copper whose position is decided before placement. Copper that lands
        wherever the parts end up is resettle_free()'s job instead.

        `layer` is "F.Cu"/"B.Cu" for one face, or None for both. `allow` names
        the nets the reserved copper carries: a part with a pad on one of them
        BELONGS in the band and is let through, which is what lets a rail's own
        bulk cap sit on the bar that feeds it. `no_vias` extends the claim to
        holes, so purge() will not re-drop a stripped plane via into the lane."""
        lid = self.pcb.GetLayerID(layer) if isinstance(layer, str) else layer
        self.reserved.append((x0, y0, x1, y1, lid, why, frozenset(allow)))
        if no_vias:
            # a lane is spoken for against HOLES as well as parts: a re-dropped
            # plane via inside it costs every net the lane carries
            self.redrop_keepout.append((x0, y0, x1, y1))
        return self.reserved[-1]

    def _free_checker(self, f, clr=0.55, debug=False, skip_refs=()):
        """The legality test place_free() searches with, as a closure over the
        board AS IT STANDS. Handed out separately because the board grows copper
        after the loose parts go down - the cells' escape fans, the rails, the
        planes - and a pose that was legal when it was chosen can stop being so.
        resettle_free() re-runs this and moves only what actually broke."""
        face_flipped = f.IsFlipped()
        layer = pcbnew.B_Cu if face_flipped else pcbnew.F_Cu
        copper = self._face_copper(layer)
        cu_clr = from_mm(self.CU_CLR)
        myref = f.GetReference()
        mine = set(skip_refs) | {myref}      # a block tests against the board, not against itself
        thru = [(px, py, pr) for px, py, ref, pr in self._through_points() if ref not in mine]
        others = [g for g in self.pcb.GetFootprints() if g.GetReference() not in mine and g.IsFlipped() == face_flipped
                  and g.GetReference() in self.placed_refs]      # swig wrappers are fresh objects: compare by ref
        DEBUG = debug
        W, H, E = self.width, self.height, self.EDGE_CLR

        def ok_at(px, py):

            f.SetPosition(pcbnew.VECTOR2I(from_mm(px), from_mm(py)))
            cy = fp_courtyard_box_mm(f)
            if cy[0] < E or cy[1] < E or cy[2] > W - E or cy[3] > H - E:
                if DEBUG: print("   edge", cy)
                return False
            for rx0, ry0, rx1, ry1, rlay, _why, _allow in self.reserved:
                if rlay is not None and rlay != layer:
                    continue
                if _allow and any(pd.GetNetname() in _allow for pd in f.Pads()):
                    continue
                for bx in _pad_boxes(f):
                    if bx[0] - self.CU_CLR <= rx1 and bx[2] + self.CU_CLR >= rx0 \
                       and bx[1] - self.CU_CLR <= ry1 and bx[3] + self.CU_CLR >= ry0:
                        if DEBUG: print("   reserved", (rx0, ry0, rx1, ry1), _why)
                        return False
            # A PLANE PAD IS A FUTURE HOLE. Each takes a via-in-pad once the
            # drops are made, and a via has to clear every other hole by
            # hole-to-hole, which is wider than the pad clearance tested below.
            # The drop does not exist yet, so this is the only chance to see it:
            # a part settled with its supply pad on a connector's mounting post
            # reads legal until the drop lands in the post.
            for pd in f.Pads():
                if pd.GetNetname() not in self.plane_nets:
                    continue
                q = pd.GetPosition(); vx, vy = to_mm(q.x), to_mm(q.y)
                for tx, ty, tr in thru:
                    if (vx - tx) ** 2 + (vy - ty) ** 2 < (max(tr, 0.30) + 0.30) ** 2:
                        if DEBUG: print("   future drop vs hole", (vx, vy), (tx, ty, tr))
                        return False
            for bx in _pad_boxes(f):
                for tx, ty, tr in thru:
                    reach = tr + (clr - 0.3)
                    if bx[0] - reach <= tx <= bx[2] + reach and bx[1] - reach <= ty <= bx[3] + reach:
                        if DEBUG: print("   thru", (tx, ty, tr), bx)
                        return False
            for g in others:
                if _boxes_overlap(cy, fp_courtyard_box_mm(g), self.CY_GAP):
                    if DEBUG: print("   crt", g.GetReference(), fp_courtyard_box_mm(g), cy)
                    return False
            sk = silk_box_mm(f)
            if sk:
                for g in others:
                    gs = silk_box_mm(g)
                    if gs and _boxes_overlap(sk, gs, self.SILK_GAP):
                        if DEBUG: print("   silk", g.GetReference(), gs, sk)
                        return False
                    for gb in _pad_boxes(g):
                        if _boxes_overlap(sk, gb, self.SILK_GAP):
                            if DEBUG: print("   silk/pad", g.GetReference(), gb, sk)
                            return False
            for pd in f.Pads():
                pbb = pd.GetBoundingBox(); pbb.Inflate(cu_clr + from_mm(0.2))
                pshape = pd.GetEffectiveShape(layer)
                for it, bb in copper:
                    if not pbb.Intersects(bb):
                        continue
                    if it.GetNetCode() == pd.GetNetCode():
                        continue
                    if pshape.Collide(it.GetEffectiveShape(layer), cu_clr):
                        if DEBUG: print("   copper", it.GetClass(), it.GetNetname())
                        return False
            return True
        return ok_at

    def place_free_all(self, requests):
        """Place a whole stage of loose parts, in the order their LINKS demand.

        The script declares WHAT to place and under what constraints; working
        out the sequence is this library's job, not the file's. Hand over every
        request for the stage at once:

            board.place_free_all([
                dict(inst="c_bypass", x=12.0, y=8.0, bottom=True),
                dict(inst="r_series", x=20.0, y=8.0, radius=4.0),
            ])

        Order is by heaviest declared link first, ties keeping the caller's
        order so a script's own reasoning about the rest survives. Every other
        key is passed to place_free unchanged.

        Why this rather than a sequence of calls: adjacency is scarce and goes
        to whoever asks first, so if the order calls appear in decides who gets
        the room, the FILE is the allocator. Moving two lines then re-allocates
        the board silently, the weights are advisory, and adding one part means
        knowing where in the sequence it belongs. Hoisting the constrained parts
        to the top by hand is the same bug with better manners - it hard-codes
        one correct answer instead of deriving it, and it is wrong again the
        moment a weight changes."""
        reqs = [dict(r) for r in requests]
        by_inst = {}
        for i, r in enumerate(reqs):
            by_inst.setdefault(r["inst"], []).append(i)
        placed = []
        for inst in self.by_link_priority([r["inst"] for r in reqs]):
            i = by_inst[inst].pop(0)
            r = dict(reqs[i])
            r.pop("inst")
            placed.append(self.place_free(inst, **r))
        return placed

    def place_free(self, inst, x, y, rot=0, bottom=False, radius=2.5, step=0.2, clr=0.55,
                   score="airwire", anchor="net", reach=5.0):
        """A loose part's final spot is a position where (a) none of the other
        face's through-features lands within `clr` of one of its pads (clr is
        stated for a 0.6 via: land radius + copper clearance; larger lands
        reach further), (b) its courtyard clears every other same-face courtyard
        by CY_GAP, (c) its silk clears every neighbour's silk and pads by SILK_GAP
        (a courtyard is an assembly keepout; two parts can clear it and still
        merge their silk outlines, which DRC reports and a person sees), (d) its
        pads clear the face's live copper by CU_CLR, and (e) it stays EDGE_CLR
        inside the outline.

        WHERE IT SEARCHES IS DECIDED BY THE PART'S OWN NETS, not by the hint.
        `anchor="net"` (the default) seeds the spiral at net_seed() - the point
        with the shortest total airwire over the routed nets this part shares
        with the placed board - and searches `reach` mm around it. A hint is a
        hand-typed guess at where there is ROOM; it says nothing about where
        the part's net is, so seeding from it reliably parks a part in free
        board far from everything it connects to. The hint stays as the
        fallback: if nothing within `reach` of the net seed is clear, the
        search runs again from the hint out to `radius`, and if that fails too
        the part is left on the hint and recorded unsettled.

        `anchor="hint"` pins the search to the hint. Use it only where the spot
        is chosen for something the netlist cannot see - a thermal region, a
        mating volume, a lane that must stay open - and say which in a comment.

        `score="airwire"` (the default) takes the clear position whose airwires
        are shortest rather than the one nearest the seed; ties go to the
        nearer. `score=None` takes the nearest clear position."""
        f = self.place(inst, x, y, rot, bottom)
        myref = f.GetReference()
        ok_at = self._free_checker(f, clr, debug=(os.environ.get("PF_DEBUG") == inst))
        if score not in (None, "airwire"):
            raise ValueError("place_free: unknown score %r" % (score,))
        if anchor not in ("net", "hint"):
            raise ValueError("place_free: unknown anchor %r" % (anchor,))
        cost = self._airwire_scorer(refs=(myref,)) if score == "airwire" else None

        def search(sx, sy, rad):
            """Spiral out from (sx, sy). Returns the chosen point or None.

            The spiral STOPS EARLY once the answer cannot improve much: the
            airwire cost rises with distance from the seed, so once a ring has
            produced legal candidates there is little to gain from walking the
            rest of the radius. Without this the cost is the whole disc for
            every part, which on this board is minutes rather than seconds."""
            cands = []
            first = None
            if ok_at(sx, sy):
                if score is None:
                    return (sx, sy)
                cands.append((cost(), 0.0, sx, sy))
                first = 0.0
            r = step
            while r <= rad:
                n = max(8, int(2 * 3.1416 * r / step))
                for k in range(n):
                    px = sx + r * math.cos(2 * math.pi * k / n); py = sy + r * math.sin(2 * math.pi * k / n)
                    px = round(px / 0.1) * 0.1; py = round(py / 0.1) * 0.1
                    if ok_at(px, py):
                        if score is None:
                            return (px, py)
                        cands.append((cost(), round(r, 3), px, py))
                        if first is None:
                            first = r
                if first is not None and r > first + self.SETTLE_MARGIN and len(cands) >= 12:
                    break
                r += step
            if not cands:
                return None
            cands.sort(key=lambda c: (round(c[0], 3), c[1]))
            return (cands[0][2], cands[0][3])

        best = None
        seed = self.net_seed(f) if anchor == "net" else None
        if seed is not None:
            best = search(seed[0], seed[1], reach)
            if best is None:
                # The net's own corner can be full - a two-pad net whose partner
                # sits in a crowded strip is the usual case. Widen before giving
                # up on the net: anywhere near it beats the hint's free board.
                best = search(seed[0], seed[1], reach * 2.5)
        if best is None:
            if seed is not None:
                self.free_fallback.append(inst)
            best = search(x, y, radius)          # the hint is the fallback, not the plan
        self.free_calls.append(dict(inst=inst, ref=f.GetReference(), x=x, y=y, rot=rot, bottom=bottom,
                                    radius=radius, step=step, clr=clr, score=score, anchor=anchor,
                                    reach=reach))
        if best is None:
            f.SetPosition(pcbnew.VECTOR2I(from_mm(x), from_mm(y)))
            self.free_placed.append((inst, None)); return f
        f.SetPosition(pcbnew.VECTOR2I(from_mm(best[0]), from_mm(best[1])))
        self.free_placed.append((inst, round(((best[0] - x) ** 2 + (best[1] - y) ** 2) ** 0.5, 2)))
        return f

    def resettle_free(self):
        """Move every loose part that the board's LATER copper has made illegal.

        Loose parts go down before the board draws its own copper - the cells'
        escape fans, the rails, the planes - so `place_free` cannot see any of
        it. While the hints were hand-picked around that copper this never
        showed; once the search follows each part's own nets it lands them
        exactly where the fan-out legs run, because that is where their nets
        are. This re-runs the SAME legality test against the board as it now
        stands and re-searches only what actually broke; a part that is still
        legal is not touched, so a settled placement stays settled."""
        moved, stuck = [], []
        for c in self.free_calls:
            f = self.layout.footprints.get(c["ref"])
            if f is None:
                continue
            here = fp_courtyard_box_mm(f)
            px, py = (here[0] + here[2]) / 2.0, (here[1] + here[3]) / 2.0
            pos = f.GetPosition(); px, py = to_mm(pos.x), to_mm(pos.y)
            ok_at = self._free_checker(f, c["clr"])
            if ok_at(px, py):
                continue                              # still legal: leave it alone
            was = (px, py)
            cost = self._airwire_scorer(refs=(c["ref"],)) if c["score"] == "airwire" else None
            best = None
            for sx, sy, rad in ((None, None, c["reach"]), (c["x"], c["y"], c["radius"])):
                if sx is None:
                    seed = self.net_seed(f) if c["anchor"] == "net" else None
                    if seed is None:
                        continue
                    sx, sy = seed
                cands = []
                r = 0.0
                first = None
                while r <= rad:
                    n = 1 if r == 0.0 else max(8, int(2 * 3.1416 * r / c["step"]))
                    for k in range(n):
                        qx = sx + r * math.cos(2 * math.pi * k / n); qy = sy + r * math.sin(2 * math.pi * k / n)
                        qx = round(qx / 0.1) * 0.1; qy = round(qy / 0.1) * 0.1
                        if ok_at(qx, qy):
                            if cost is None:
                                cands = [(0, r, qx, qy)]; r = rad + 1; break
                            cands.append((cost(), round(r, 3), qx, qy))
                            if first is None:
                                first = r
                    if first is not None and r > first + self.SETTLE_MARGIN and len(cands) >= 12:
                        break
                    r += c["step"]
                if cands:
                    cands.sort(key=lambda t: (round(t[0], 3), t[1]))
                    best = (cands[0][2], cands[0][3]); break
            if best is None and c["anchor"] == "net":
                # Nothing within reach: a part sitting on structural copper has
                # to go somewhere, so the last try trades airwire for legality.
                seed = self.net_seed(f) or (c["x"], c["y"])
                r = 0.0
                while r <= c["reach"] * 3.0:
                    n = 1 if r == 0.0 else max(8, int(2 * 3.1416 * r / c["step"]))
                    hit = None
                    for k in range(n):
                        qx = seed[0] + r * math.cos(2 * math.pi * k / n)
                        qy = seed[1] + r * math.sin(2 * math.pi * k / n)
                        qx = round(qx / 0.1) * 0.1; qy = round(qy / 0.1) * 0.1
                        if ok_at(qx, qy):
                            hit = (qx, qy); break
                    if hit:
                        best = hit; break
                    r += c["step"]
            if best is None:
                f.SetPosition(pcbnew.VECTOR2I(from_mm(was[0]), from_mm(was[1])))
                stuck.append(c["inst"]); continue
            f.SetPosition(pcbnew.VECTOR2I(from_mm(best[0]), from_mm(best[1])))
            moved.append((c["inst"], round(math.hypot(best[0] - was[0], best[1] - was[1]), 2)))
        moved.sort(key=lambda m: -m[1])
        print("resettle_free: %d of %d loose part(s) sat on copper drawn after them, %d moved, %d stuck%s"
              % (len(moved) + len(stuck), len(self.free_calls), len(moved), len(stuck),
                 (" " + str(stuck)) if stuck else ""))
        if moved:
            print("   largest: %s" % moved[:8])
        return moved, stuck

    def place_block(self, anchor, x, y, rot=0, bottom=False, build=None,
                    radius=6.0, step=0.2, clr=0.55, score="airwire", seed="net"):
        """Place an anchor part AND the satellites whose positions derive from
        it, searched as ONE unit.

        A block is neither a cell nor a loose part, and before this it had
        nowhere to live. A cell comes from a module fragment and carries its own
        geometry and routing; a loose part is placed and judged alone. A
        board-local group - a regulator and the two capacitors that serve its
        pins - is neither: the satellites' positions are computed from the
        anchor's own pad boxes, so they cannot be placed one at a time, and the
        group as a whole still has to find somewhere it fits.

        Written at a bare coordinate instead, it does not fit anywhere - it
        simply lands, and everything placed afterwards has to work around it.
        That is backwards. A stamped cell's position is often fixed by geometry
        that cannot move at all; a three-part block is the flexible one, so the
        block searches and the cell does not.

        `build(anchor_footprint)` places the satellites off the anchor's real
        pads and returns them. It is called at every candidate pose, so it must
        derive everything and assume nothing."""
        fa = self.place(anchor, x, y, rot, bottom)

        def realise(px, py):
            fa.SetPosition(pcbnew.VECTOR2I(from_mm(px), from_mm(py)))
            return [fa] + [f for f in (build(fa) if build else [])]

        members = realise(x, y)
        refs = [f.GetReference() for f in members]
        check = {f.GetReference(): self._free_checker(f, clr, skip_refs=refs) for f in members}
        cost = self._airwire_scorer(refs=tuple(refs)) if score == "airwire" else None

        def ok_at(px, py):
            for f in realise(px, py):
                q = f.GetPosition()
                if not check[f.GetReference()](to_mm(q.x), to_mm(q.y)):
                    return False
            return True

        def search(sx, sy, rad):
            cands = []
            first = None
            r = 0.0
            while r <= rad:
                n = 1 if r == 0.0 else max(8, int(2 * 3.1416 * r / step))
                for k in range(n):
                    px = sx + r * math.cos(2 * math.pi * k / n); py = sy + r * math.sin(2 * math.pi * k / n)
                    px = round(px / 0.1) * 0.1; py = round(py / 0.1) * 0.1
                    if ok_at(px, py):
                        if cost is None:
                            return (px, py)
                        cands.append((cost(), round(r, 3), px, py))
                        if first is None:
                            first = r
                if first is not None and r > first + self.SETTLE_MARGIN and len(cands) >= 8:
                    break
                r += step
            if not cands:
                return None
            cands.sort(key=lambda c: (round(c[0], 3), c[1]))
            return (cands[0][2], cands[0][3])

        best = None
        if seed == "net":
            s0 = self.net_seed(fa)
            if s0 is not None:
                best = search(s0[0], s0[1], radius)
        if best is None:
            best = search(x, y, radius)
        if best is None:
            realise(x, y)
            print("place_block %s: NO clear pose within %.1f mm - left on the hint" % (anchor, radius))
            self.free_placed.append((anchor, None))
            return members
        members = realise(best[0], best[1])
        print("place_block %s: %d part(s) at (%.2f, %.2f), %.2f mm from the hint"
              % (anchor, len(members), best[0], best[1], math.hypot(best[0] - x, best[1] - y)))
        self.free_placed.append((anchor, round(math.hypot(best[0] - x, best[1] - y), 2)))
        return members

    def retry_fallbacks(self):
        """Re-place the loose parts whose nets had no anchor the first time.

        Loose parts go down one at a time, so a part is seeded against whatever
        is ALREADY placed. A flattened cell breaks on that: its members mostly
        connect to each other, so the first one down has no sibling to aim at,
        takes its hand-typed hint, and every later member is then seeded on that
        arbitrary spot. The cell ends up strung across the board.

        Once every part is placed the anchors exist, so this re-runs the search
        for exactly those parts and keeps the result only where the airwire
        actually improves. It is one extra pass over a handful of parts, not a
        second placement round."""
        if not self.free_fallback:
            return []
        want = set(self.free_fallback)
        moved = []
        for c in self.free_calls:
            if c["inst"] not in want:
                continue
            f = self.layout.footprints.get(c["ref"])
            if f is None:
                continue
            pos = f.GetPosition(); was = (to_mm(pos.x), to_mm(pos.y))
            seed = self.net_seed(f)
            if seed is None:
                continue
            ok_at = self._free_checker(f, c["clr"])
            cost = self._airwire_scorer(refs=(c["ref"],))
            ok_at(was[0], was[1])
            here = cost()
            cands = []
            first = None
            r = 0.0
            while r <= c["reach"] * 2.5:
                n = 1 if r == 0.0 else max(8, int(2 * 3.1416 * r / c["step"]))
                for k in range(n):
                    qx = seed[0] + r * math.cos(2 * math.pi * k / n)
                    qy = seed[1] + r * math.sin(2 * math.pi * k / n)
                    qx = round(qx / 0.1) * 0.1; qy = round(qy / 0.1) * 0.1
                    if ok_at(qx, qy):
                        cands.append((cost(), round(r, 3), qx, qy))
                        if first is None:
                            first = r
                if first is not None and r > first + self.SETTLE_MARGIN and len(cands) >= 12:
                    break
                r += c["step"]
            cands.sort(key=lambda t: (round(t[0], 3), t[1]))
            if cands and cands[0][0] < here - 0.05:
                f.SetPosition(pcbnew.VECTOR2I(from_mm(cands[0][2]), from_mm(cands[0][3])))
                moved.append((c["inst"], round(here - cands[0][0], 1)))
            else:
                f.SetPosition(pcbnew.VECTOR2I(from_mm(was[0]), from_mm(was[1])))
        fixed = {m[0] for m in moved}
        self.free_fallback = [i for i in self.free_fallback if i not in fixed]
        moved.sort(key=lambda m: -m[1])
        print("retry_fallbacks: %d of %d hint-placed part(s) improved once their siblings existed%s"
              % (len(moved), len(want), (", best " + str(moved[:6])) if moved else ""))
        return moved

    def block(self, rows, x0, y0, pitch_x=2.2, pitch_y=2.2, bottom=True, rot=0, radius=2.5):
        """Grid of loose parts by instance name (None = empty slot), each settled
        by place_free() from its grid spot."""
        for r, row in enumerate(rows):
            for c, inst in enumerate(row):
                if inst:
                    self.place_free(inst, x0 + pitch_x * c, y0 + pitch_y * r, rot, bottom=bottom, radius=radius)

    # -- cell-vs-board clash on real geometry ---------------------------------
    def _cu_records(self, items, footprints, skip_uu):
        """(bbox, layer or None for both, net, shape) for real copper geometry.
        Bounding boxes are only a prefilter; the decision is made on the
        effective shape, because a diagonal track's bbox would veto placements
        nothing actually touches."""
        out = []
        for it in items:
            cls = it.GetClass()
            if cls not in ("PCB_VIA", "PCB_TRACK", "PCB_SHAPE"):
                continue
            if it.m_Uuid.AsString() in skip_uu or it.GetNetCode() <= 0:
                continue
            if cls == "PCB_VIA":
                lay = None
            elif it.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu):
                lay = it.GetLayer()
            else:
                continue
            bb = it.GetBoundingBox()
            out.append(((bb.GetLeft() / 1e6, bb.GetTop() / 1e6, bb.GetRight() / 1e6, bb.GetBottom() / 1e6),
                        lay, it.GetNetname(), it.GetEffectiveShape(), it.GetEffectiveShape))
        for f in footprints:
            for pd in f.Pads():
                if pd.GetNetCode() <= 0:
                    continue
                lay = None if pd.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) else \
                    (pcbnew.B_Cu if f.IsFlipped() else pcbnew.F_Cu)
                bb = pd.GetBoundingBox()
                face = pcbnew.B_Cu if f.IsFlipped() else pcbnew.F_Cu
                out.append(((bb.GetLeft() / 1e6, bb.GetTop() / 1e6, bb.GetRight() / 1e6, bb.GetBottom() / 1e6),
                            lay, pd.GetNetname(), pd.GetEffectiveShape(face),
                            (lambda pd=pd, face=face: pd.GetEffectiveShape(face))))
        return out

    def cell_geometry(self, name):
        """(courtyard boxes, copper records, through-points) for one stamped cell."""
        g = self.cells[name]
        doomed = self._doomed_uu()
        fps, items, cys, thru = [], [], [], []
        for it in group_items(g):
            if isinstance(it, pcbnew.FOOTPRINT):
                fps.append(it)
                cys.append((fp_courtyard_box_mm(it), it.IsFlipped()))
                for pd in it.Pads():
                    if pd.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                        thru.append((pd.GetPosition().x / 1e6, pd.GetPosition().y / 1e6))
            else:
                items.append(it)
                if it.GetClass() == "PCB_VIA" and it.m_Uuid.AsString() not in doomed:
                    p = it.GetPosition(); thru.append((p.x / 1e6, p.y / 1e6))
        return cys, self._cu_records(items, fps, doomed), thru

    def _hash(self, recs, key):
        h = {}
        B, C = self.BUCKET, self.CU_CLR
        for r in recs:
            bb = key(r)
            for gx in range(int((bb[0] - C) // B), int((bb[2] + C) // B) + 1):
                for gy in range(int((bb[1] - C) // B), int((bb[3] + C) // B) + 1):
                    h.setdefault((gx, gy), []).append(r)
        return h

    def _near(self, h, bb):
        out, seen = [], set()
        B, C = self.BUCKET, self.CU_CLR
        for gx in range(int((bb[0] - C) // B), int((bb[2] + C) // B) + 1):
            for gy in range(int((bb[1] - C) // B), int((bb[3] + C) // B) + 1):
                for r in h.get((gx, gy), ()):
                    if id(r) not in seen:
                        seen.add(id(r)); out.append(r)
        return out

    def forget(self, name):
        """Drop the cached foreign geometry for a cell (call after anything
        placed since the cache was built could touch it)."""
        self._foreign_cache.pop(name, None)

    def _foreign(self, name):
        """Everything placed OUTSIDE this cell, hashed; it does not move while
        the cell slides."""
        if name in self._foreign_cache:
            return self._foreign_cache[name]
        g = self.cells[name]
        mine_uu = {it.m_Uuid.AsString() for it in group_items(g)}
        doomed = self._doomed_uu()
        fps = [f for f in self.pcb.GetFootprints()
               if f.GetReference() in self.placed_refs and f.m_Uuid.AsString() not in mine_uu]
        items = [it for it in list(self.pcb.GetTracks()) + list(self.pcb.GetDrawings())
                 if it.m_Uuid.AsString() not in mine_uu]
        cys = [(fp_courtyard_box_mm(f), f.IsFlipped()) for f in fps]
        cys = [c for c in cys if c[0]]
        pads = [pb for f in fps for pb in _pad_boxes(f)]
        thru = [(x, y, r) for x, y, ref, r in self._through_points() if ref in {f.GetReference() for f in fps} | {"via"}]
        thru = [t for t in thru if not any(abs(t[0] - v.GetPosition().x / 1e6) < 1e-3 and abs(t[1] - v.GetPosition().y / 1e6) < 1e-3
                                            for v in group_items(g) if v.GetClass() == "PCB_VIA")]
        rec = (self._hash(cys, lambda r: r[0]), self._hash([(pb,) for pb in pads], lambda r: r[0]),
               self._hash(self._cu_records(items, fps, doomed | mine_uu), lambda r: r[0]),
               self._hash(thru, lambda r: (r[0] - r[2], r[1] - r[2], r[0] + r[2], r[1] + r[2])))
        self._foreign_cache[name] = rec
        return rec

    def cell_base(self, name):
        """The cell's own geometry at its CURRENT pose, kept so a translation
        search can slide boxes instead of re-measuring pcbnew objects for every
        candidate: (courtyard boxes, copper records, through-points) as
        cell_geometry() gives them, plus the physical boxes of its footprints.
        Only translations may reuse it (a rotation changes the boxes)."""
        cys, cu, thru = self.cell_geometry(name)
        phys = [fp_phys_box_mm(f) for f in group_items(self.cells[name]) if isinstance(f, pcbnew.FOOTPRINT)]
        return dict(cys=cys, cu=cu, thru=thru, phys=[b for b in phys if b])

    @staticmethod
    def _shift_box(b, dx, dy):
        return (b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy)

    def cell_clash(self, name, base=None, off=(0.0, 0.0)):
        """Why this cell's REAL geometry touches something placed outside it, or
        None. Three ways to touch, and only these: a courtyard over a foreign
        courtyard on the same face, a hole over a foreign pad (every hole
        punches both faces), or copper within CU_CLR of foreign copper on
        another net. Leaving the outline's keep-in is also a clash.

        With `base` (cell_base() taken at the hint) and `off` (the translation
        applied since), the boxes are slid rather than re-measured; the exact
        copper test still reads the live item's shape, which the mover has
        already moved, so the decision is the same as the slow path's."""
        dx, dy = off
        if base is None:
            cys, cu, thru = self.cell_geometry(name)
            phys = None
        else:
            cys = [(self._shift_box(cy, dx, dy), flip) for cy, flip in base["cys"]]
            cu = [(self._shift_box(bb, dx, dy), lay, net, None, live) for bb, lay, net, sh, live in base["cu"]]
            thru = [(x + dx, y + dy) for x, y in base["thru"]]
            phys = [self._shift_box(b, dx, dy) for b in base["phys"]]
        lo, hix, hiy = self.EDGE_CLR, self.width - self.EDGE_CLR, self.height - self.EDGE_CLR
        if phys is None:
            phys = [fp_phys_box_mm(f) for f in group_items(self.cells[name]) if isinstance(f, pcbnew.FOOTPRINT)]
        for bx in phys:
            if bx and (bx[0] < lo or bx[1] < lo or bx[2] > hix or bx[3] > hiy):
                return True
        for mbb, _l, _n, _sh, _live in cu:
            if mbb[0] < lo or mbb[1] < lo or mbb[2] > hix or mbb[3] > hiy:
                return True
        hcys, hpads, hcu, hthru = self._foreign(name)
        for cy, myflip in cys:
            for fcy, flip in self._near(hcys, cy):
                if myflip == flip and _boxes_overlap(cy, fcy, self.CY_GAP):
                    return "courtyard %s vs foreign %s" % (cy, fcy)
        for tx, ty in thru:
            tb = (tx - 0.35, ty - 0.35, tx + 0.35, ty + 0.35)
            for (pb,) in self._near(hpads, tb):
                if pb[0] - 0.35 <= tx <= pb[2] + 0.35 and pb[1] - 0.35 <= ty <= pb[3] + 0.35:
                    return "cell hole (%.2f,%.2f) on foreign pad %s" % (tx, ty, pb)
        for it in group_items(self.cells[name]):
            if isinstance(it, pcbnew.FOOTPRINT):
                for pb in _pad_boxes(it):
                    for (tx, ty, tr) in self._near(hthru, pb):
                        reach = tr + 0.25
                        if pb[0] - reach <= tx <= pb[2] + reach and pb[1] - reach <= ty <= pb[3] + reach:
                            return "foreign hole (%.2f,%.2f r%.2f) on cell pad %s of %s" % (tx, ty, tr, pb, it.GetReference())
        clr = from_mm(self.CU_CLR)
        for mbb, mlay, mnet, msh, mlive in cu:
            for fbb, flay, fnet, fsh, _flive in self._near(hcu, mbb):
                if mnet == fnet or not _boxes_overlap(mbb, fbb, self.CU_CLR):
                    continue
                if mlay is not None and flay is not None and mlay != flay:
                    continue
                if msh is None:
                    msh = mlive()          # the item has been moved: read its shape now
                if msh.Collide(fsh, clr):
                    return "copper %s (%s) vs foreign %s (%s)" % (mbb, mnet, fbb, fnet)
        return None

    def _mover(self, g):
        at = [0.0, 0.0]

        def goto(dx, dy):
            for it in group_items(g):
                it.Move(pcbnew.VECTOR2I(from_mm(dx - at[0]), from_mm(dy - at[1])))
            at[0], at[1] = dx, dy
        return goto

    def settle_cell(self, name, x=None, y=None, rot=0, bottom=False, radius=9.0,
                    step=0.5, _seeded=False, **kw):
        """Place a cell where its own nets want it, then ring-search outward for
        the nearest spot its real geometry is clear, trying the other three
        orientations after the first fails (a long strip may only fit the other
        way). The rotation fallback means a TURNED cell can come back un-turned:
        use settle_shift() for a cell whose orientation is a decision.

        WHERE IT STARTS, in order, and it says which it used:

          1. the cell's own nets (`cell_seed`) - where the things it connects to
             already are;
          2. the best-fitting free pocket for its envelope (`free_pockets`) -
             what a person otherwise scans for by hand and writes down, and the
             answer whenever a cell's partners are not placed yet or its nets
             are all planes;
          3. the caller's `x`/`y`, which is a FALLBACK and is named as one.

        A coordinate is not a placement. It says where there was room when
        somebody looked, and nothing about where this cell's nets are, so a
        search seeded on it lands the cell in free board far from everything it
        connects to - and the result reads as deliberate, because a human typed
        it. Pass one only as a genuine mechanical fact, or as the last resort
        when the two searches above have nothing to go on.
        """
        # _seeded: the caller has already chosen the point (the pocket retry
        # below). Without it the retry would re-seed on the same nets, ignore
        # the pocket it was given, fail again and recurse forever.
        seed, how = ((x, y), "the pocket it was given") if _seeded else \
                    (self.cell_seed(name), "its own nets")
        if seed is None:
            pockets = self.free_pockets(name, bottom=bottom)
            if pockets:
                px, py, turns, _s = pockets[0]
                seed, rot = (px, py), rot + 90 * turns
                how = "the best-fitting free pocket" + (" turned %d" % (90 * turns) if turns else "")
        if seed is None:
            if x is None or y is None:
                print("settle %s: no nets to aim at, no pocket that fits, and no hint" % name)
                return None
            seed, how = (x, y), "THE HINT (fallback: no nets to aim at, no pocket that fits)"
        print("settle %s: seeded on %s at (%.2f, %.2f)" % (name, how, seed[0], seed[1]))
        x, y = seed
        self.stamp(name, x, y, rot, bottom=bottom, **kw)
        self.forget(name)
        g = self.cells[name]
        why = self.cell_clash(name)
        if not why:
            return (0.0, 0.0)
        print("settle %s: hint (%.2f, %.2f) clashes: %s" % (name, x, y, why))
        goto = self._mover(g)
        tried_pocket = how.startswith("the best-fitting")
        for turn in range(4):
            if turn:
                goto(0.0, 0.0)
                group_rotate(g, 90)
                if not self.cell_clash(name):
                    return (0.0, 0.0, 90 * turn)
            for r in range(1, int(radius / step) + 1):
                for i in range(-r, r + 1):
                    for j in range(-r, r + 1):
                        if max(abs(i), abs(j)) != r:
                            continue
                        goto(i * step, j * step)
                        if not self.cell_clash(name):
                            return (round(i * step, 2), round(j * step, 2), 90 * turn)
        goto(0.0, 0.0)
        # THE RING SEARCH IS LOCAL. Nothing clear within `radius` of the seed
        # does not mean nothing clear on the board, and that distinction is the
        # whole reason hints existed: a pocket in another quarter is invisible
        # from here. So ask for one before giving up - the scan is global, and
        # a cell that lands in a far pocket beats a cell scattered into loose
        # members, which throws away its geometry AND its routing.
        if not tried_pocket:
            found = self.free_pockets(name, bottom=bottom)
            if not found:
                print("settle %s: its own geometry fits nowhere on its face" % name)
            for px, py, turns, _slack in found:
                print("settle %s: nothing clear near its nets, trying the pocket at "
                      "(%.2f, %.2f)%s" % (name, px, py,
                                          " turned %d" % (90 * turns) if turns else ""))
                d = self.settle_cell(name, px, py, rot=rot + 90 * turns, bottom=bottom,
                                     radius=radius, step=step, _seeded=True, **kw)
                if d is not None:
                    return d
        return None

    def settle_shift(self, name, radius=2.0, step=0.05, score=None):
        """Translate a stamped cell to the NEAREST clear pose (ring search, no
        rotation). Returns the (dx, dy) applied, or None (cell left at its hint)
        when nothing within `radius` is clear.

        `score="airwire"`: search the whole radius and take the clear pose
        whose airwires are shortest - the sum, over the cell's external nets,
        of the distance from the cell's nearest pad or via on that net to the
        nearest same-net copper outside the cell (ties go to the smallest
        shift). The hint's cost, if it is clear, and the chosen cost are
        printed; a hint that is clear and already best stays put."""
        g = self.cells[name]
        self.forget(name)
        base = self.cell_base(name)
        why = self.cell_clash(name, base)
        if not why and score is None:
            return (0.0, 0.0)
        if score not in (None, "airwire"):
            raise ValueError("settle_shift: unknown score %r" % (score,))
        if why:
            print("settle_shift %s: hint clashes: %s" % (name, why))
        goto = self._mover(g)
        cands = []
        if score == "airwire":
            cost = self._airwire_scorer(cell=name)
            if not why:
                cands.append((cost(), 0.0, 0, 0))
        for r in range(1, int(round(radius / step)) + 1):
            ring = sorted({(i, j) for i in range(-r, r + 1) for j in range(-r, r + 1) if max(abs(i), abs(j)) == r},
                          key=lambda ij: (ij[0] * ij[0] + ij[1] * ij[1], ij))
            for i, j in ring:
                goto(i * step, j * step)
                if not self.cell_clash(name, base, (i * step, j * step)):
                    if score == "airwire":
                        cands.append((cost(), math.hypot(i, j) * step, i, j))
                    else:
                        print("settle_shift %s: moved (%+.2f, %+.2f)" % (name, i * step, j * step))
                        return (round(i * step, 2), round(j * step, 2))
        if cands:
            cands.sort(key=lambda c: (round(c[0], 3), c[1]))
            c0 = cands[0]
            hint = [c for c in cands if c[1] == 0.0]
            goto(c0[2] * step, c0[3] * step)
            print("settle_shift %s: airwire %.2f mm at (%+.2f, %+.2f)%s" % (
                name, c0[0], c0[2] * step, c0[3] * step,
                " (hint %.2f mm)" % hint[0][0] if hint else " (hint not clear)"))
            return (round(c0[2] * step, 2), round(c0[3] * step, 2))
        goto(0.0, 0.0)
        print("settle_shift %s: NO clear pose within %.1f mm; left at the hint" % (name, radius))
        return None

    # -- the airwire score: what a pose costs the ratsnest --------------------
    def link(self, a_ref, a_pad, b_ref, b_pad, weight=None, why="", limit_mm=None):
        """Declare a link's proximity class for the board's own loose parts.

        A cell's links come with the cell (`adopt_links`); this is for the
        connections the BOARD owns - a loose pull-up to the pin it holds up, a
        bulk cap to the rail's entry, a gate resistor to its FET. `weight` is a
        LinkWeight or a number, see ModuleLayout.link."""
        if weight is None:
            weight = self.layout.LinkWeight.SHORT
        return self.layout.link(a_ref, a_pad, b_ref, b_pad, weight, why, limit_mm)

    def adopt_links(self, name, module_dir=None):
        """Take a stamped cell's declared links into the board's own list.

        A cell knows which of ITS connections must be short; the board is where
        they get spent or lost, so they have to survive the stamp. The cell
        records endpoints by instance path and the board's copy of that
        footprint carries `<instance>.<path in the fragment>` - the same
        mapping the derived clearance floors use."""
        if module_dir is None:
            # which module is this instance? the same question the derived
            # clearance floors answer, so ask them rather than parse again
            from placemat import clearance_floors
            root = clearance_floors.repo_root()
            mod = None
            for zens, pcb in clearance_floors.boards(root):
                exact, prefix = clearance_floors.instances(zens)
                mod = clearance_floors.module_of(name, exact, prefix)
                if mod:
                    break
            module_dir = clearance_floors.module_dirs(root).get(mod) if mod else None
            if module_dir is None:
                return 0
        f = os.path.join(module_dir, "layout", "links.json")
        if not os.path.exists(f):
            return 0
        by_path = {}
        for fp in self.pcb.GetFootprints():
            path = fp.GetFieldsText().get("Path", "")
            if path.startswith(name + "."):
                by_path[path[len(name) + 1:]] = fp.GetReference()
        taken = 0
        for rec in json.load(open(f)):
            a, b = by_path.get(rec["a"]["path"]), by_path.get(rec["b"]["path"])
            if not a or not b:
                continue
            self.layout.links.append({"weight": rec["weight"], "name": rec.get("name"),
                                 "why": rec.get("why", ""),
                                 "limit_mm": rec.get("limit_mm"), "cell": name,
                                 "a": {"ref": a, "pad": rec["a"]["pad"], "net": rec["a"].get("net"),
                                       "path": name + "." + rec["a"]["path"]},
                                 "b": {"ref": b, "pad": rec["b"]["pad"], "net": rec["b"].get("net"),
                                       "path": name + "." + rec["b"]["path"]}})
            taken += 1
        return taken

    def by_link_priority(self, insts):
        """The given instances, heaviest declared link first.

        Scarce adjacency goes to whoever asks first, so the order loose parts
        are placed in IS an allocation. A part whose link is short by function
        cannot take second best; one holding only preferences can. Ties keep
        the caller's order, so a script's own reasoning about the rest of the
        board survives.
        """
        # a caller may hold instance names (place_free) or refdes (place); rank
        # under both so neither spelling silently falls back to the default
        rank = {}
        for rec in self.layout.links:
            w = rec["weight"]
            for end in ("a", "b"):
                ref = rec[end]["ref"]
                for key in {ref, self.inst_of_ref.get(ref, ref)}:
                    rank[key] = max(rank.get(key, 0.0), w)
        return sorted(insts, key=lambda i: (-rank.get(i, float(self.layout.LINK_DEFAULT)),
                                            insts.index(i)))

    # -- placement order: cells and loose parts, one rule ----------------------
    def free_area(self):
        """Board area not covered by anything already placed, in mm^2.

        The union, not the sum, so overlapping courtyards are not counted twice
 - the number is the denominator of every fit ratio below and an
        over-count would quietly promote every remaining candidate."""
        boxes = [fp_courtyard_box_mm(f) for f in self.pcb.GetFootprints()
                 if f.GetReference() in self.placed_refs]
        return max(self.width * self.height - rect_union_area(boxes), 1e-6)

    def _place_refs(self, name):
        """The refdes a placement request owns: a cell's members, or one part."""
        if name in self.cells:
            return {it.GetReference() for it in group_items(self.cells[name])
                    if isinstance(it, pcbnew.FOOTPRINT)}
        f = self.part(name)
        if f is None:
            f = next((x for x in self.pcb.GetFootprints() if x.GetReference() == name), None)
        return {f.GetReference()} if f is not None else set()

    def _place_metrics(self, name):
        """Occupied area, extent and bbox for a cell or a loose part.

        Occupied area is the union of real courtyards, which is what a cell
        actually consumes - a sprawling bbox around a thin cell is not area
        spent, and pricing it as though it were is what makes an interleaving
        cell look unplaceable (tactic 5b)."""
        if name in self.cells:
            boxes = [b for b, _flip in self.cell_geometry(name)[0]]
            l, t, r, bo = group_bbox_mm(self.cells[name])
        else:
            f = self.part(name)
            if f is None:
                f = next((x for x in self.pcb.GetFootprints() if x.GetReference() == name), None)
            if f is None:
                return dict(area=0.0, w=0.0, h=0.0, bbox_area=1e-9)
            boxes = [fp_courtyard_box_mm(f)]
            l, t, r, bo = boxes[0]
        w, h = max(r - l, 0.0), max(bo - t, 0.0)
        return dict(area=rect_union_area(boxes), w=w, h=h,
                    bbox_area=max(w * h, 1e-9))

    def hint_room(self, x, y, radius, area=None):
        """Free board within `radius` of (x, y), as mm^2 or as "how many of me".

        The only measurement in the order that reads the REQUEST rather than
        the thing being placed. Two cells of the same kind are identical in
        every term but this one, and they are not interchangeable: each was
        asked to go somewhere different, and the one with fewer places left to
        land has to take one while any are left.

        The radius is the search's own reach, because room the search cannot
        get to is not room this candidate has. Free means inside the board and
        not already covered by a placed courtyard - copper is not counted, since
        a part may sit over a track it does not touch.
        """
        r = float(radius)
        x0, y0 = max(0.0, x - r), max(0.0, y - r)
        x1, y1 = min(self.width, x + r), min(self.height, y + r)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        window = (x1 - x0) * (y1 - y0)
        taken = []
        for f in self.pcb.GetFootprints():
            if f.GetReference() not in self.placed_refs:
                continue
            l, tp, rr, bo = fp_courtyard_box_mm(f)
            if rr <= x0 or l >= x1 or bo <= y0 or tp >= y1:
                continue
            taken.append((max(l, x0), max(tp, y0), min(rr, x1), min(bo, y1)))
        free = max(window - rect_union_area(taken), 0.0)
        return free if not area else free / max(float(area), 1e-9)

    def _place_pull(self, name, refs=None):
        """Heaviest declared link from this candidate to something ALREADY placed.

        Placed, not merely declared: a candidate whose partners are all still
        loose has nothing to aim at, so pulling it forward buys nothing and
        every candidate seeded on it afterwards inherits an arbitrary spot
        (tactic 2c)."""
        refs = self._place_refs(name) if refs is None else refs
        best = 0.0
        for rec in self.layout.links:
            a, b = rec["a"]["ref"], rec["b"]["ref"]
            try:
                w = float(rec["weight"])
            except (TypeError, ValueError):
                continue
            for near, far in ((a, b), (b, a)):
                if near in refs and far not in refs and far in self.placed_refs:
                    best = max(best, w)
        return best

    def cell_seed(self, name):
        """Where a CELL's own nets want it, as a position for the cell.

        The counterpart of net_seed() for a stamped fragment, and it exists for
        the same reason: a coordinate somebody typed says where there is ROOM,
        and nothing at all about where this cell's nets are. The cell path had
        no equivalent, so the biggest and most constrained thing on the board
        was the one placed by a hand-written number.

        A part can be seeded AT an anchor, because its pads sit within its own
        courtyard and landing the part there lands its pads there too. A cell's
        pads are distributed across the cell, over whatever extent that cell
        has, so the same shortcut puts the cell's centre on the anchor and the
        pad that wanted it somewhere else entirely. Each external net is
        therefore asked from the position of the PAD that carries it: the pad's
        offset from the cell's own reference point is measured off the cell and
        subtracted from the anchor, so the candidate is where the cell has to
        sit for that pad to land there. Nothing here assumes a size - the offset
        is read from the geometry, so it is right for a cell of any extent.

        Plane nets are excluded (a plane is reachable from anywhere by a via, so
        counting it prices every position about equally), as is the cell's own
        copper. None when nothing this cell connects to is placed yet - which is
        the common case early in a stage, and what free_pockets() answers.
        """
        anchors = self._net_anchors(skip_group=name)
        refs = self._place_refs(name)
        if not refs:
            return None
        l, tp, r, bo = group_bbox_mm(self.cells[name])
        cx, cy = (l + r) / 2.0, (tp + bo) / 2.0
        want = []                    # (candidate position for the cell, net's anchor list)
        for f in self.pcb.GetFootprints():
            if f.GetReference() not in refs:
                continue
            for pd in f.Pads():
                n = pd.GetNetname()
                if pd.GetNetCode() <= 0 or n in self.plane_nets or n not in anchors:
                    continue
                q = pd.GetPosition()
                dx, dy = to_mm(q.x) - cx, to_mm(q.y) - cy      # pad, relative to the cell
                want.append(((dx, dy), anchors[n]))
        if not want:
            return None
        cands = []
        for (dx, dy), pts in want:
            for ax, ay in pts[:40]:
                cands.append((round(ax - dx, 3), round(ay - dy, 3)))
        if not cands:
            return None
        mx = sum(c[0] for c in cands) / len(cands)
        my = sum(c[1] for c in cands) / len(cands)
        cands.append((round(mx, 3), round(my, 3)))

        def cost(px, py):
            return sum(min(math.hypot(px + dx - ax, py + dy - ay) for ax, ay in pts)
                       for (dx, dy), pts in want)

        best = min(cands, key=lambda c: (round(cost(*c), 3), c))
        return best

    def _face_mask(self, step, bottom, skip=()):
        """The board's occupied space on one face, one integer bitmask per row.

        A row is a single int, so testing a shape against it is a shift and an
        AND rather than a loop over cells. Occupied means a real courtyard on
        THIS face, plus every hole from either face - a body on the far side
        does not occupy this one, but a through pad or via punches both.
        """
        nx, ny = int(self.width / step) + 1, int(self.height / step) + 1
        rows = [0] * ny

        def block(bl, bt, br, bb):
            i0, i1 = max(0, int(bl / step)), min(nx - 1, int(br / step) + 1)
            j0, j1 = max(0, int(bt / step)), min(ny - 1, int(bb / step) + 1)
            if i1 < i0 or j1 < j0:
                return
            span = ((1 << (i1 - i0 + 1)) - 1) << i0
            for j in range(j0, j1 + 1):
                rows[j] |= span

        for f in self.pcb.GetFootprints():
            if f.GetReference() not in self.placed_refs or f.GetReference() in skip:
                continue
            if bool(f.IsFlipped()) == bool(bottom):
                block(*fp_courtyard_box_mm(f))
                continue
            for pd in f.Pads():
                if pd.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                    bb = pd.GetBoundingBox()
                    block(to_mm(bb.GetLeft()), to_mm(bb.GetTop()), to_mm(bb.GetRight()), to_mm(bb.GetBottom()))
        for v in self.pcb.GetTracks():
            # a via's own bounding box: GetWidth() wants a layer in KiCad 10 and
            # a via is not one width anyway
            if v.GetClass() == "PCB_VIA":
                bb = v.GetBoundingBox()
                block(to_mm(bb.GetLeft()) - 0.2, to_mm(bb.GetTop()) - 0.2,
                      to_mm(bb.GetRight()) + 0.2, to_mm(bb.GetBottom()) + 0.2)
        return rows, nx, ny

    def _cell_mask(self, name, step, turns=0):
        """The cell's OWN occupied space, as row bitmasks plus its origin offset.

        Its real courtyards, never its bounding box. A cell is not a rectangle:
        one thin part or one stub pushes the rectangle far out while leaving
        that whole flank free board a neighbour may occupy (tactic 5b), so
        fitting the rectangle asks for space the cell does not use and reports
        "no room" on a board that has plenty. Sliding this mask is what lets
        cells interleave, which is how they are packed in the first place.
        """
        boxes = [b for b, _flip in self.cell_geometry(name)[0]]
        if not boxes:
            return [], 0, 0.0, 0.0
        # THE OTHER THREE POSES. An irregular cell often fits one way round and
        # not another, and the ring search knows that - it retries at 90, 180
        # and 270 - so a scan that only ever asks about the pose the cell
        # happens to be in now is blind to most of its options. A right-angle
        # turn of an axis-aligned box is another axis-aligned box, so the mask
        # is exact at every pose, not an approximation of one.
        if turns % 4:
            l0 = min(b[0] for b in boxes); t0 = min(b[1] for b in boxes)
            r0 = max(b[2] for b in boxes); b0 = max(b[3] for b in boxes)
            cx, cy = (l0 + r0) / 2.0, (t0 + b0) / 2.0
            for _ in range(turns % 4):
                boxes = [(cx - (bb - cy), cy + (bl - cx),
                          cx - (bt - cy), cy + (br - cx))
                         for bl, bt, br, bb in boxes]
                boxes = [(min(q[0], q[2]), min(q[1], q[3]),
                          max(q[0], q[2]), max(q[1], q[3])) for q in boxes]
        ox = min(b[0] for b in boxes); oy = min(b[1] for b in boxes)
        w = max(b[2] for b in boxes) - ox; h = max(b[3] for b in boxes) - oy
        nx, ny = int(w / step) + 1, int(h / step) + 1
        rows = [0] * ny
        for bl, bt, br, bb in boxes:
            i0, i1 = max(0, int((bl - ox) / step)), min(nx - 1, int((br - ox) / step) + 1)
            j0, j1 = max(0, int((bt - oy) / step)), min(ny - 1, int((bb - oy) / step) + 1)
            if i1 < i0 or j1 < j0:
                continue
            span = ((1 << (i1 - i0 + 1)) - 1) << i0
            for j in range(j0, j1 + 1):
                rows[j] |= span
        return rows, nx, ox, oy

    def free_pockets(self, name, bottom=False, step=0.1, stride=0.5, limit=6):
        """Where this cell's real geometry fits, best-fit first, over the WHOLE face.

        The scan a person otherwise runs by hand and writes down as a hint. It
        answers what the ring search cannot, because the ring search is LOCAL: a
        pocket in another quarter is invisible from the seed, and a cell whose
        seed points at a full corner reads as "no fit" on a board with room.

        It slides the cell's occupied mask, not a rectangle around it, so a cell
        interleaves with its neighbours exactly as it is meant to, and it tries
        all four right-angle poses. Returns (x, y, turns, slack) - slack
        counting the board already taken around the pose, so the snuggest fit
        comes first and the open face is left for whatever still needs it.

        TWO RESOLUTIONS, because they answer different questions. `step` is how
        finely the SHAPES are drawn, and it has to be fine: a coarse raster
        rounds every edge outward, so half a millimetre of invented margin per
        edge is enormous beside a 0.2 mm clearance and quietly refuses fits that
        exist. `stride` is how finely POSITIONS are tried, and it can stay
        coarse - this is a candidate generator, and the ring search and the
        exact clash test settle the final pose from whatever it proposes.
        """
        board, bnx, bny = self._face_mask(step, bottom, skip=self._place_refs(name))
        jump = max(1, int(round(stride / step)))
        l, tp, r, bo = group_bbox_mm(self.cells[name])
        cx, cy = (l + r) / 2.0, (tp + bo) / 2.0
        out = []
        for turns in range(4):
            cell, cnx, ox, oy = self._cell_mask(name, step, turns)
            if not cell:
                continue
            ch = len(cell)
            if ch >= bny or cnx >= bnx:
                continue
            band = max(1, int(round(2.0 / step)))
            for dj in range(0, bny - ch, jump):
                for di in range(0, bnx - cnx, jump):
                    if any(board[dj + k] & (cell[k] << di) for k in range(ch)):
                        continue
                    slack = sum(bin(board[j]).count("1") for j in
                                range(max(0, dj - band), min(bny, dj + ch + band)))
                    out.append((round(di * step + (cx - ox), 2),
                                round(dj * step + (cy - oy), 2), turns, slack))
        if not out:
            return []
        out.sort(key=lambda c: (-c[3], c[2], c[0], c[1]))   # crowded surroundings = snuggest
        return out[:limit]

    def placement_order(self, requests, key="inst", weights=None, verbose=False):
        """A stage of placements, in the order the constraints demand.

        ONE rule for cells and for loose parts, because the thing being
        allocated is the same in both cases and only the magnitudes differ. A
        request is a dict naming what to place; the tier and separation facts
        it may carry are:

            tier="fixed"  position is decided outside the layout (a panel
                          cutout, a board-to-board mate, a sensor whose
                          position IS its function). Transcribed, not placed.
            tier="edge"   one degree of freedom, sliding along its edge.
            apart_from=("cell", ...)
                          this candidate must stand off from those, so it is
                          brought forward once one of them is down - distance
                          is spent like area and there is none left late.

        Everything else is free in the plane and ranked by `next_to_place`,
        re-scored after every placement because both fit and pull move.

        Why one function serves a 520 mm^2 cell and a 0402: `fit` is a ratio to
        the free area REMAINING, so a small part scores near zero on it and its
        heaviest declared link decides - which is what by_link_priority already
        does. The same call on a tight board full of awkward cells is dominated
        by fit and shape instead. Nothing switches; the terms just scale.

        Returns the requests in order, each with `why` recording what chose it.
        """
        pending = [dict(r) for r in requests]
        for r in pending:
            r.setdefault("tier", "free")
        out = []
        for tier in ("fixed", "edge"):
            for r in [x for x in pending if x["tier"] == tier]:
                r["why"] = ("position decided outside the layout" if tier == "fixed"
                            else "edge-bound: one degree of freedom")
                out.append(r)
        pending = [x for x in pending if x["tier"] not in ("fixed", "edge")]
        while pending:
            cands = []
            for r in pending:
                name = r[key]
                refs = self._place_refs(name)
                m = self._place_metrics(name)
                m["name"] = name
                m["pull"] = self._place_pull(name, refs)
                if "x" in r and "y" in r:
                    m["room"] = self.hint_room(r["x"], r["y"],
                                               r.get("radius", 9.0), area=m["area"])
                m["apart"] = 1.0 if any(a in self.stamped or a in self.flattened
                                        or not self._place_refs(a).isdisjoint(self.placed_refs)
                                        for a in r.get("apart_from", ())) else 0.0
                cands.append(m)
            i, why = next_to_place(cands, self.free_area(), weights)
            r = pending.pop(i)
            r["why"] = why
            if verbose:
                print("order %-14s %s" % (r[key], why))
            out.append(r)
        return out

    def settle_all(self, requests, weights=None, verbose=True):
        """Place a whole stage of CELLS, in the order the constraints demand.

        The cell counterpart of place_free_all: the script says what to place
        and under what constraints, and the sequence - which is an allocation
        of area, adjacency and standoff - is derived here rather than being
        whatever order the calls happen to appear in.

            board.settle_all([
                dict(inst="opto_in1", x=42.5, y=28.0, rot=0, bottom=True),
                dict(inst="permit_a_rx", x=45.0, y=22.0, rot=0, bottom=True,
                     apart_from=("buck24",)),
            ])

        `x`/`y`/`rot` stay HINTS - a measured starting guess the search is free
        to leave. Every other key goes to settle_cell unchanged. A cell that
        finds no clear run falls back to its loose members exactly as before,
        and says so."""
        placed = []
        for r in self.placement_order(requests, weights=weights, verbose=verbose):
            r = dict(r)
            name = r.pop("inst"); why = r.pop("why", ""); r.pop("tier", None)
            r.pop("apart_from", None)
            if name in self.unstamped:
                self.flatten(name)
                placed.append((name, None, why))
                continue
            d = self.settle_cell(name, r.pop("x", None), r.pop("y", None),
                                 r.pop("rot", 0), **r)
            if d is None:
                self.unstamped.add(name)
                self.flatten(name)
            if verbose:
                print("settle %s: %s (%s)" % (name, d if d is not None
                                              else "NO FIT - falls back to loose members", why))
            placed.append((name, d, why))
        return placed


    @property
    def inst_of_ref(self):
        """{refdes: instance name} from the generated board's Path fields."""
        if getattr(self, "_inst_of_ref", None) is None:
            self._inst_of_ref = {}
            for fp in self.pcb.GetFootprints():
                path = fp.GetFieldsText().get("Path", "")
                if path:
                    self._inst_of_ref[fp.GetReference()] = path.split(".", 1)[0]
        return self._inst_of_ref

    def link_report(self, path=None):
        """The declared links with their achieved lengths (see
        ModuleLayout.link_report); written automatically on save."""
        rows = self.layout.link_report()
        if path:
            json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(path)),
                                              "links-achieved.json"), "w"), indent=1)
        return rows

    def _link_index(self):
        """{(ref, pad): [(other_ref, other_pad, weight, name)]} for every
        declared link, both ways round. Zero-weight links are kept: the audit
        reports them, the objective skips them by their weight."""
        idx = {}
        for rec in self.layout.links:
            w, nm = rec["weight"], rec.get("name")
            a, b = rec["a"], rec["b"]
            idx.setdefault((a["ref"], a["pad"]), []).append((b["ref"], b["pad"], w, nm))
            idx.setdefault((b["ref"], b["pad"]), []).append((a["ref"], a["pad"], w, nm))
        return idx

    def _pad_xy(self, ref, pad):
        fp = self.layout.footprints.get(ref)
        if fp is None:
            return None
        for p in fp.Pads():
            if p.GetNumber() == str(pad):
                q = p.GetPosition()
                return (to_mm(q.x), to_mm(q.y))
        return None

    def _net_anchors(self, skip_refs=(), skip_group=None, planes=False):
        """net -> [(x, y)] of every pad, via and track end on the board that
        does NOT belong to the excluded part(s) or cell: the targets a moving
        part's or cell's nets have to reach.

        Only PLACED parts count. An unplaced footprint still sits wherever the
        netlist dropped it, so counting it would price a mover against a
        position nothing has chosen yet - and on this flow the loose parts go
        down last, so that is most of the board.

        PLANE NETS ARE EXCLUDED unless asked for. Where the stackup gives a net
        a plane, every connection to it is a via drop and no placement is
        closer to it than any other; letting ground into the objective prices
        every position almost equally and drowns out the nets that do have to
        reach something."""
        out = {}
        skip = set(skip_refs)
        drop = set() if planes else set(self.plane_nets)
        for fp in self.pcb.GetFootprints():
            if fp.GetReference() in skip or (skip_group and geometry.in_cell(fp, skip_group)):
                continue
            if fp.GetReference() not in self.placed_refs:
                continue
            for p in fp.Pads():
                if p.GetNetCode() > 0 and p.GetNetname() not in drop:
                    q = p.GetPosition()
                    out.setdefault(p.GetNetname(), []).append((to_mm(q.x), to_mm(q.y)))
        for t in self.pcb.GetTracks():
            if t.GetNetCode() <= 0 or t.GetNetname() in drop:
                continue
            grp = t.GetParentGroup()
            if skip_group and grp and grp.GetName() == skip_group:
                continue
            if isinstance(t, pcbnew.PCB_VIA):
                q = t.GetPosition()
                out.setdefault(t.GetNetname(), []).append((to_mm(q.x), to_mm(q.y)))
            else:
                for q in (t.GetStart(), t.GetEnd()):
                    out.setdefault(t.GetNetname(), []).append((to_mm(q.x), to_mm(q.y)))
        return out

    def net_seed(self, f):
        """Where a part's OWN NETS want it: of every anchor its routed nets
        offer (plus their centroid), the point with the shortest total airwire
 - the sum, over those nets, of the distance to that net's nearest
        anchor. None when the part shares no routed net with anything placed,
        which is when the caller's hint is all there is to go on.

        A DECLARED LINK is the strongest form of that statement, and it is the
        only one that works for a part whose pads are all on planes. A bypass
        capacitor reads as "3V3 and GND", both reachable from anywhere by a via
        and therefore both excluded from the anchors - so without its link the
        part has no nets to be seeded by, falls back to its hint, and the search
        never visits the pin it is meant to be serving. The scorer would price
        that link correctly; the search simply never goes where it could.

        This is the seed, not the answer: it ignores whether a part can BE
        there. The search around it is what settles that."""
        anchors = self._net_anchors(skip_refs=(f.GetReference(),))
        nets = {}
        for p in f.Pads():
            n = p.GetNetname()
            if p.GetNetCode() > 0 and n in anchors:
                nets[n] = anchors[n]
        # the far end of every declared link this part holds, priced by weight
        # exactly as the scorer prices it, so seed and score agree
        links = self._link_index()
        pulls = []
        for p in f.Pads():
            for other_ref, other_pad, w, _name in links.get((f.GetReference(), p.GetNumber()), ()):
                if w <= 0 or other_ref == f.GetReference():
                    continue                     # fixed asks for no adjacency
                if other_ref not in self.placed_refs:
                    continue                     # nothing to aim at yet
                t = self._pad_xy(other_ref, other_pad)
                if t:
                    pulls.append((t[0], t[1], w))
        if not nets and not pulls:
            return None
        pts = [pt for ps in nets.values() for pt in ps] + [(x, y) for x, y, _ in pulls]
        cx = sum(a for a, _ in pts) / len(pts)
        cy = sum(b for _, b in pts) / len(pts)
        # A bus net can offer hundreds of track ends; the ones far from the
        # centroid never win, so pricing them all only costs time.
        pts.sort(key=lambda q: (q[0] - cx) ** 2 + (q[1] - cy) ** 2)
        cands = pts[:120] + [(round(cx, 2), round(cy, 2))]

        def cost(px, py):
            c = sum(w * math.hypot(px - ax, py - ay) for ax, ay, w in pulls)
            return c + sum(min(math.hypot(px - ax, py - ay) for ax, ay in ps) for ps in nets.values())

        return min(cands, key=lambda c: (round(cost(*c), 3), c))

    def _airwire_scorer(self, refs=(), cell=None):
        """A closure that prices the CURRENT pose of the given part(s) or
        cell: for every net the mover shares with the rest of the board, the
        shortest gap between one of its own pads/vias on that net and the
        nearest same-net anchor outside it. Nets the mover does not share
        (a cell's internal nets) cost nothing."""
        if cell:
            fps = [fp for fp in self.pcb.GetFootprints() if geometry.in_cell(fp, cell)]
            vias = [t for t in self.pcb.GetTracks() if isinstance(t, pcbnew.PCB_VIA)
                    and t.GetParentGroup() and t.GetParentGroup().GetName() == cell]
            anchors = self._net_anchors(skip_group=cell)
        else:
            fps = [self.layout.footprints[r] for r in refs]
            vias = []
            anchors = self._net_anchors(skip_refs=refs)

        links = self._link_index()
        movers = {fp.GetReference() for fp in fps}

        def cost():
            best = {}
            declared = 0.0
            for fp in fps:
                for p in fp.Pads():
                    net = p.GetNetname()
                    if p.GetNetCode() <= 0:
                        continue
                    q = p.GetPosition(); px, py = to_mm(q.x), to_mm(q.y)
                    # A DECLARED link is priced pad to pad and weighted by its
                    # class, so a `short` link outbids the rest of the board for
                    # adjacency and a `fixed` one asks for none. Its net is then
                    # not priced again below: the link is the constraint.
                    mine = links.get((fp.GetReference(), p.GetNumber()))
                    priced = False
                    for other_ref, other_pad, w, _name in (mine or ()):
                        if w <= 0 or other_ref in movers:
                            continue                      # fixed, or both ends moving together
                        if other_ref not in self.placed_refs:
                            continue                      # nothing to measure against yet
                        t = self._pad_xy(other_ref, other_pad)
                        if t:
                            declared += w * math.hypot(px - t[0], py - t[1])
                            priced = True
                    if priced:
                        # the link IS the constraint for this net; pricing the
                        # net again would count the same pull twice
                        best.setdefault(net, None)
                        continue
                    # a declared link whose partner is not placed yet leaves the
                    # net to the ordinary anchor pricing, rather than to nothing
                    tg = anchors.get(net)
                    if not tg:
                        continue
                    d = min(math.hypot(px - x, py - y) for x, y in tg)
                    if best.get(net) is None or d < best[net]:
                        best[net] = d
            for v in vias:
                net = v.GetNetname()
                tg = anchors.get(net)
                if not tg:
                    continue
                q = v.GetPosition(); px, py = to_mm(q.x), to_mm(q.y)
                d = min(math.hypot(px - x, py - y) for x, y in tg)
                if best.get(net) is None or d < best[net]:
                    best[net] = d
            undeclared = sum(v for v in best.values() if v is not None)
            return round(declared + undeclared, 3)
        return cost

    def grid_align(self, name, step=0.1, ref=None):
        """Slide a cell so its fine-pitch pad rows sit ON the routing grid.

        A pad's escape leaves along the pad's own axis, and the lane it leaves
        in is only (pitch - pad width) wide. A router places that lane's
        centreline on its grid, so a pad row half a grid step off the grid
        loses half the lane to quantisation and the terminal reads as boxed
        even though a track fits. Aligning the row costs a fraction of a grid
        step of travel and gives the lane back.

        The row along a north or south face is set by x, along a west or east
        face by y, so each axis is chosen independently: the offset that puts
        the most pads on the grid, ties going to the smaller move. The cell
        moves only if its real geometry stays clear at the new position.
        Returns (dx, dy) actually applied.
        """
        g = self.cells[name]
        f = self.part(ref) if ref else None
        fps = [f] if f else [it for it in group_items(g) if isinstance(it, pcbnew.FOOTPRINT)]
        if f is None:
            fps = [max(fps, key=lambda q: len(list(q.Pads())))]     # the cell's own fine-pitch part
        fp = fps[0]
        cx, cy = fp.GetPosition().x / 1e6, fp.GetPosition().y / 1e6
        along = {0: [], 1: []}
        for pd in fp.Pads():
            px, py = pd.GetPosition().x / 1e6, pd.GetPosition().y / 1e6
            along[0 if abs(py - cy) > abs(px - cx) else 1].append(px if abs(py - cy) > abs(px - cx) else py)

        def best_offset(vals):
            if not vals:
                return 0.0
            cands = sorted({round((-v) % step, 4) for v in vals} | {round((-v) % step - step, 4) for v in vals})
            return max(cands, key=lambda d: (sum(1 for v in vals if abs(((v + d) % step + step) % step) < 1e-6), -abs(d)))
        dx, dy = best_offset(along[0]), best_offset(along[1])
        if not dx and not dy:
            return (0.0, 0.0)
        self.forget(name)
        base = self.cell_base(name)
        goto = self._mover(g)
        goto(dx, dy)
        if self.cell_clash(name, base, (dx, dy)):
            goto(0.0, 0.0)
            return (0.0, 0.0)
        return (round(dx, 4), round(dy, 4))

    def compact(self, name, dx, dy, limit=6.0, step=0.1):
        """Slide a stamped cell as far along (dx, dy) as its real geometry
        allows. Scans from the far end back, so a cell that starts in graze
        contact with a neighbour can still travel. Returns how far it moved."""
        g = self.cells[name]
        self.forget(name)
        base = self.cell_base(name)
        at = 0.0

        def goto(t):
            nonlocal at
            d = t - at
            if d:
                for it in group_items(g):
                    it.Move(pcbnew.VECTOR2I(from_mm(dx * d), from_mm(dy * d)))
                at = t
        n = int(round(limit / step))
        for i in range(n, 0, -1):
            goto(i * step)
            if not self.cell_clash(name, base, (dx * at, dy * at)):
                return at
        goto(0.0)
        return 0.0
