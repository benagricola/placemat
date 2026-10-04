"""Writes a resolved Plan into a .kicad_pcb through pcbnew: moves parts and
cells, draws the outline and copper, fills zones, moves reference
designators to the fab layers, patches render colours and project presets,
renders PNGs.

Cells move as rigid bodies about the box centre they had in the generated
board the plan was resolved against. KiCad's UUID generator is seeded before new items are
created, so an unchanged plan writes an unchanged file."""
from __future__ import annotations

import os
from pathlib import Path

from .quiet import import_pcbnew, quiet_stderr
from ..childenv import child_env

pcbnew = import_pcbnew()

from ..layout import MergedZone, Plan
from ..copper import Pour, Text, Track, Via, Zone
from ..geometry import Transform, poly_within
from ..placement import Placement
from ..board_geometry import (CellGeom, Footprint, allow_marker, cell_tagged, layer_marker, resolve_marker,
                              split_allow, split_marker, stackup_order)
from ..cutouts import closes_itself
from .read import FACES_PREFIX
from ..rules import RULE_PREFIX, rule_note
from ..values import Box, CopperLayer, Face

def nm(v: float) -> int:
    return pcbnew.FromMM(float(v))


def vec(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I(nm(x), nm(y))


# The layers KiCad's DRC judges a text's mirroring on (drc_test_provider_text_mirroring.cpp): a text on a back one must
# be mirrored, one on a front one must not be.
_FRONT_TEXT_LAYERS = (pcbnew.F_Cu, pcbnew.F_SilkS, pcbnew.F_Mask, pcbnew.F_Fab)
_BACK_TEXT_LAYERS = (pcbnew.B_Cu, pcbnew.B_SilkS, pcbnew.B_Mask, pcbnew.B_Fab)


def _mirror_for_layer(text, default: bool = False) -> None:
    """Mirror a text as its layer's face asks: on a back layer mirrored, on a front one not, elsewhere `default`."""
    layer = text.GetLayer()
    text.SetMirrored(True if layer in _BACK_TEXT_LAYERS else False if layer in _FRONT_TEXT_LAYERS else default)


def seed_uuids(seed: int = 0x5EED):
    """New board items draw their UUIDs from a seeded generator, so a plan
    applied twice writes the same file."""
    pcbnew.KIID.SeedGenerator(seed)


def _place_footprint(fp, current: Placement, target: Placement):
    """Move one footprint. A flip to the back mirrors about the VERTICAL axis,
    which is what KiCad's own F key does (`editing.flip_left_right`, true by
    default in KiCad 7, 9 and 10) and what `_move_cell` already does to a
    cell's items.

    `Flip` computes the orientation that mirror implies - 180 for a part that
    was upright - and the rotation asked for is applied on top of it. Setting
    the orientation to `target.rotation` alone would discard the flip's half
    turn and quietly mirror the part top-to-bottom instead, which is what the
    planner and the writer used to disagree about."""
    if target.face != current.face:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(target.rotation + 180)
    else:
        fp.SetOrientationDegrees(target.rotation)
    fp.SetPosition(vec(target.location.x, target.location.y))


def _move_cell(board, cell: CellGeom, target: Placement, groups: dict):
    ref = Placement(cell.box.center, 0.0, Face.FRONT)
    flip = target.face != ref.face
    t = (Transform.translate(-ref.location.x, -ref.location.y)
         .then(Transform.rotate(target.rotation))
         .then(Transform.translate(target.location.x, target.location.y)))
    pivot = vec(ref.location.x, ref.location.y)
    angle = pcbnew.EDA_ANGLE(target.rotation, pcbnew.DEGREES_T)
    dx, dy = t.apply((ref.location.x, ref.location.y))
    delta = vec(dx - ref.location.x, dy - ref.location.y)
    for it in groups[cell.name].GetItems():
        if isinstance(it, pcbnew.PCB_GROUP):
            continue        # a nested cell is its own: the plan's cell holds only its own parts and copper
        if flip:
            _flip_keeping_inner(it, pivot)
        if target.rotation:
            it.Rotate(pivot, angle)
        it.Move(delta)
        if isinstance(it, pcbnew.PCB_TEXT):
            _mirror_for_layer(it, it.IsMirrored())     # a fragment written before its back texts were mirrored


def _flip_keeping_inner(it, pivot) -> None:
    """KiCad's flip of one of a cell's own items, with its inner copper put
    back on the layer it was drawn on: F and B swap, In1..In4 stay, so the
    module keeps the layer roles it was laid out for. This diverges from
    KiCad, whose flip mirrors inner layers through the stack. A via that
    reaches a face keeps KiCad's mirror (F-In1 becomes B-In4); a buried one
    keeps its layers. A footprint flips as KiCad flips it: it is one part
    drawn for a face, so its whole stack mirrors."""
    if isinstance(it, pcbnew.FOOTPRINT):
        it.Flip(pivot, pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        return
    inner = pcbnew.IsInnerCopperLayer
    if isinstance(it, pcbnew.PCB_VIA):
        pair = (it.TopLayer(), it.BottomLayer())
        it.Flip(pivot, pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        if all(inner(l) for l in pair):
            it.SetLayerPair(*pair)
        return
    if isinstance(it, pcbnew.ZONE):
        kept = [l for l in it.GetLayerSet().CuStack() if inner(l)]
        it.Flip(pivot, pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        if kept:
            ls = pcbnew.LSET(it.GetLayerSet())
            ls.RemoveLayerSet(pcbnew.LSET.InternalCuMask())
            for l in kept:
                ls.AddLayer(l)
            it.SetLayerSet(ls)
        return
    layer = it.GetLayer()
    it.Flip(pivot, pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    if inner(layer):
        it.SetLayer(layer)


def _thin_cell(board, group, gone) -> None:
    """Delete the cell's vias at `gone` ((x, y) where the generated board
    has them): the ones its `drops=` did not keep. Each is found before any
    is deleted, and deleted, not only removed, as a zone is."""
    near = lambda v: any(abs(pcbnew.ToMM(v.GetPosition().x) - x) < 1e-6 and abs(pcbnew.ToMM(v.GetPosition().y) - y) < 1e-6
                         for x, y in gone)
    for v in [it for it in group.GetItems() if isinstance(it, pcbnew.PCB_VIA) and near(it)]:
        group.RemoveItem(v)
        board.Delete(v)


_ON_MM = 0.001      # a via or a track end the plan names, found on the board within this


def _given_way(board, plan: Plan, groups: dict) -> None:
    """What a stamped cell's own vias did as it was placed (giveway.py),
    done to the moved cell: each via moved or removed, and the tail it was
    drawn with removed where the plan draws another or none. The plan's
    copper carries the tails drawn in their place."""
    def on(v, at):
        return abs(v.x / 1e6 - at[0]) <= _ON_MM and abs(v.y / 1e6 - at[1]) <= _ON_MM
    # Delete, not Remove: an item Remove hands to its Python wrapper is freed when the wrapper
    # goes, and on a large board that left pcbnew's bindings returning unwrapped objects
    from ..giveway_field import write as write_field
    write_field(board, [a for a in plan.given_way if getattr(a, "field", "")], groups)
    for a in plan.given_way:
        g = groups.get(a.home)
        if g is None or getattr(a, "field", ""):
            continue
        items = list(g.GetItems())
        via = next((it for it in items if isinstance(it, pcbnew.PCB_VIA) and it.GetNetname() == a.net
                    and on(it.GetPosition(), a.at)), None)
        if via is None:
            continue
        gone = ([a.old_tail] if a.old_tail is not None else []) + list(a.old_tracks)
        # every track is found before any is deleted: a deleted item's wrapper is dead
        for it in [it for it in items if isinstance(it, pcbnew.PCB_TRACK) and not isinstance(it, pcbnew.PCB_VIA)
                   and it.GetNetname() == a.net
                   and any((on(it.GetStart(), p) and on(it.GetEnd(), q)) or (on(it.GetStart(), q) and on(it.GetEnd(), p))
                           for p, q in gone)]:
            g.RemoveItem(it)
            board.Delete(it)
        if a.kind in ("move", "leave", "route"):
            via.SetPosition(vec(*a.to))
        else:
            g.RemoveItem(via)
            board.Delete(via)


def _group_given_way_tracks(board, plan: Plan, groups: dict) -> None:
    """The tracks a via's giving way drew (a tail, a move's redrawn tail, a routed via's rebuilt tracks) join the
    group of the cell the via belongs to. They are the cell's copper, and KiCad applies a clearance rule that
    holds within a cell (`A.memberOf('cell') && B.memberOf('cell')`) only to the items of its group: left outside,
    the tail was judged against the cell's rule here and by the board's netclass there."""
    def at(v, p):
        return abs(v.x / 1e6 - p[0]) <= _ON_MM and abs(v.y / 1e6 - p[1]) <= _ON_MM
    loose = [t for t in board.GetTracks() if not isinstance(t, pcbnew.PCB_VIA) and t.GetParentGroup() is None]
    for a in plan.given_way:
        g = groups.get(a.home)
        if g is None or getattr(a, "field", ""):
            continue
        for op in ([a.tail] if a.tail is not None else []) + list(a.tracks):
            ends = ((op.start.x, op.start.y), (op.end.x, op.end.y))
            for t in loose:
                if t.GetNetname() == op.net and t.GetLayerName() == op.layer.value \
                        and ((at(t.GetStart(), ends[0]) and at(t.GetEnd(), ends[1]))
                             or (at(t.GetStart(), ends[1]) and at(t.GetEnd(), ends[0]))):
                    g.AddItem(t)
                    loose.remove(t)
                    break


def _merge_cell_zones(board, plan: Plan) -> list:
    """Leave out a stamped cell's zone on each layer where the board's own
    plane has the same net and wholly covers it: the plane fills that area
    anyway, and a second zone there is filled separately with the cell's
    settings. Rule areas, pours and zones the board does not cover stay, and
    so does one whose pads join otherwise than the plane's (a cell's solid
    ground under a thermal board fill: merged, its solid joins became
    spokes or none) - recorded in `plan.kept_zones`."""
    planes = [op for op in plan.copper if isinstance(op, Zone)]
    # every zone is found before any is deleted, and deleted, not removed: a
    # removed zone is freed with its Python wrapper and corrupts board.Zones()
    zones = [(g, it) for g in board.Groups() if g.GetName() in plan.geometry.cells
             for it in g.GetItems() if isinstance(it, pcbnew.ZONE) and not it.GetIsRuleArea()]
    merged = []
    keep_in = _keep_in_region(board, plan)
    for g, z in zones:
        net = z.GetNetname()
        o = pcbnew.SHAPE_POLY_SET(z.Outline())
        if keep_in is not None:         # what nears the edge past the keep-in can hold no copper: the rest is judged
            o.BooleanIntersection(keep_in)
        outlines = [[(pcbnew.ToMM(o.COutline(k).CPoint(j).x), pcbnew.ToMM(o.COutline(k).CPoint(j).y))
                     for j in range(o.COutline(k).PointCount())] for k in range(o.OutlineCount())]
        keep = pcbnew.LSET()
        for layer_id in z.GetLayerSet().CuStack():
            layer = CopperLayer.of(board.GetLayerName(layer_id))
            plane = next((p for p in planes if p.net == net and p.layer == layer
                          and all(poly_within(ol, p.points) for ol in outlines)), None)
            if plane is None:
                keep.AddLayer(layer_id)
            elif z.GetPadConnection() != _plane_connection(plane):
                keep.AddLayer(layer_id)
                plan.kept_zones.append(MergedZone(g.GetName(), net, layer, _zone_difference(z, plane)))
            else:
                merged.append(MergedZone(g.GetName(), net, layer, _zone_difference(z, plane)))
        if keep.CuStack().size() == 0:
            g.RemoveItem(z)
            board.Delete(z)
        elif keep.CuStack().size() < z.GetLayerSet().CuStack().size():
            z.SetLayerSet(keep)
    return merged


def _separate_cell_zone_priorities(board, plan: Plan) -> list:
    """Give stamped cells' zones of one net that overlap on a layer distinct priorities. Each cell was
    stamped with its zone at the module's priority, so two cells' zones overlapping (their frames reach a
    keep-in past their content) are at one priority, which KiCad's DRC reports as zones_intersect. Same
    net, so which fills first does not change the copper's connection: the later zone, in group-name
    order, is raised past every zone it overlaps. Returns (zone name, cell, old, new) for each raised."""
    zones = sorted(((g.GetName(), it) for g in board.Groups() if g.GetName() in plan.geometry.cells
                    for it in g.GetItems() if isinstance(it, pcbnew.ZONE) and not it.GetIsRuleArea()),
                   key=lambda t: (t[0], t[1].GetZoneName()))
    raised, done = [], []
    for cell, z in zones:
        mine = set(z.GetLayerSet().CuStack())
        near = [o for o in done if o.GetNetname() == z.GetNetname() and mine & set(o.GetLayerSet().CuStack())
                and _zones_overlap(z, o)]
        old = new = z.GetAssignedPriority()
        while any(o.GetAssignedPriority() == new for o in near):
            new += 1
        if new != old:
            z.SetAssignedPriority(new)
            raised.append((z.GetZoneName(), cell, old, new))
        done.append(z)
    return raised


def _zones_overlap(a, b) -> bool:
    """Whether two zones' outlines share area."""
    o = pcbnew.SHAPE_POLY_SET(a.Outline())
    o.BooleanIntersection(b.Outline())
    return o.OutlineCount() > 0


def _keep_in_region(board, plan: Plan):
    """The board less the edge keep-in, as a polygon set: where copper may
    be. None when the board has no outline to shrink."""
    keep = plan.geometry.edge_clearance
    if plan.outline is not None and plan.shape is None:
        b = plan.outline
        pts = ((b.left, b.top), (b.right, b.top), (b.right, b.bottom), (b.left, b.bottom))
    elif plan.geometry.outline:
        pts = plan.geometry.outline[0]
    else:
        return None
    ps = pcbnew.SHAPE_POLY_SET()
    ps.NewOutline()
    for x, y in pts:
        ps.Append(nm(x), nm(y))
    # the outline's box includes the edge line itself (half its width outside the board's frame, which a
    # plane is inset from): 0.1 mm more, where no copper may be either
    if keep > 0:
        ps.Inflate(-nm(keep + 0.1), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.005))
    return ps


def _plane_connection(plane: Zone):
    """How the board's plane joins its pads, as a zone's pad connection."""
    return pcbnew.ZONE_CONNECTION_FULL if plane.solid_pads else pcbnew.ZONE_CONNECTION_THERMAL


def _pad_join(connection) -> str:
    return {pcbnew.ZONE_CONNECTION_FULL: "solid", pcbnew.ZONE_CONNECTION_THERMAL: "thermal",
            pcbnew.ZONE_CONNECTION_THT_THERMAL: "solid, thermal on through pads",
            pcbnew.ZONE_CONNECTION_NONE: "not joined"}.get(connection, "joined otherwise")


def _zone_difference(z, plane: Zone) -> str:
    """How a cell's zone was set up differently from the plane it merges into."""
    words = []
    mine, theirs = z.GetPadConnection(), _plane_connection(plane)
    if mine != theirs:
        words.append("its pads were %s, the plane's are %s" % (_pad_join(mine), _pad_join(theirs)))
    clearance = pcbnew.ToMM(z.GetLocalClearance())
    if abs(clearance - plane.clearance) > 1e-6:
        words.append("its clearance was %.2f mm, the plane's is %.2f mm" % (clearance, plane.clearance))
    return "; ".join(words)


def _xy(p) -> tuple:
    """A declared outline point as a pair, whether it came as one or as a Location."""
    return (float(p.x), float(p.y)) if hasattr(p, "x") else (float(p[0]), float(p[1]))


def _draw_path(board, path):
    """One closed path onto Edge.Cuts, as the legs and arcs it was declared
    as. A path whose last piece already lands on its start - a circle of
    arcs, a rounded slot - is closed already, and drawing a leg back to the
    start would put a segment of nothing on the layer."""
    here = _xy(path[0])
    pieces = list(path[1:]) + ([] if closes_itself(path) else [path[0]])
    for piece in pieces:
        if hasattr(piece, "via"):
            a = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
            a.SetLayer(pcbnew.Edge_Cuts)
            a.SetWidth(nm(0.1))
            a.SetArcGeometry(vec(*here), vec(*_xy(piece.via)), vec(*_xy(piece.to)))
            board.Add(a)
            here = _xy(piece.to)
        else:
            s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetWidth(nm(0.1))
            s.SetStart(vec(*here))
            s.SetEnd(vec(*_xy(piece)))
            board.Add(s)
            here = _xy(piece)


_KEEPOUT_FLAGS = {"parts": "SetDoNotAllowFootprints", "fill": "SetDoNotAllowZoneFills",
                  "tracks": "SetDoNotAllowTracks", "vias": "SetDoNotAllowVias",
                  "pads": "SetDoNotAllowPads"}


def _layer_set(board, layers):
    out = pcbnew.LSET()
    for layer in layers:
        out.addLayer(board.GetLayerID(layer.value))
    return out


def _draw_keepouts(board, plan):
    """A KiCad rule area per keepout. KiCad's own filler keeps a zone out of
    one, and DRC and the router judge by it, so a region declared once is
    honoured by everything downstream without placemat clipping anything.

    The layer set comes from the board's own copper count, so a keepout
    covers a two-layer board and a thirty-two-layer one alike without naming
    a layer.

    A keepout on every copper layer, or on layers the board lacks, carries its
    declaration in its name - ` [*.Cu]` or the list - because KiCad saves a
    zone on the layers its board has, and a module fragment has two.

    Only rule areas placemat itself wrote are replaced, and those belong to no
    group. A stamped module fragment's are members of the cell's group and are
    never deleted: `_move_cell` carries them with the cell, and deleting them
    would silently drop a clearance the module declared. One whose name
    declares more layers than it is on is widened to match."""
    grouped = {_kiid(it) for g in board.Groups() for it in g.GetItems()}
    for z in list(board.Zones()):
        if z.GetIsRuleArea() and _kiid(z) not in grouped:
            board.Delete(z)                 # placemat's own: a rerun replaces them, never doubles them
    stack = tuple(CopperLayer.of(board.GetLayerName(l)) for l in board.GetEnabledLayers().CuStack())
    for z in board.Zones():
        # A stamped module's rule area is not placemat's to delete, but it is
        # placemat's to correct: its module could only save F and B, and its
        # name says what it declared. Only ever widened, to what it declared.
        if not (z.GetIsRuleArea() and _kiid(z) in grouped):
            continue
        if split_allow(z.GetZoneName())[1] and z.GetParentGroup() is not None:
            # its allow rule names it: by its cell's own name, not the one every stamp of the module shares
            z.SetZoneName(cell_tagged(z.GetZoneName(), z.GetParentGroup().GetName()))
        declared = split_marker(z.GetZoneName())[1]
        if declared is None:
            continue
        want, _ = resolve_marker(declared, stack)
        have = {CopperLayer.of(board.GetLayerName(l)) for l in z.GetLayerSet().CuStack()}
        if want - have:
            z.SetLayerSet(_layer_set(board, tuple(sorted(want | have, key=stackup_order))))
    for k in plan.keepouts.values():
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetLayerSet(pcbnew.LSET.AllCuMask(board.GetCopperLayerCount()) if k.layers is None
                      else _layer_set(board, k.layers))
        relaxed = _relaxed(k)
        for name, setter in _KEEPOUT_FLAGS.items():
            # one that admits parts allows footprints: a .kicad_dru rule forbids the rest (keepout_rules); one
            # that lets nets through allows what they keep, and a rule forbids it to the others (allow_rules)
            getattr(z, setter)(name in k.excludes and not (name == "parts" and _admits_parts(k)) and name not in relaxed)
        o = z.Outline()
        o.NewOutline()
        for x, y in k.poly:
            o.Append(nm(x), nm(y))
        z.SetZoneName(_keepout_zone_name(k, stack))
        board.Add(z)


_ALLOWED_TYPES = ("tracks", "vias", "pads")


def _relaxed(k) -> tuple:
    """What a keepout's rule area is written allowing because its `allow=` nets keep it: the copper types
    it excludes, when it lets any net through."""
    return tuple(t for t in _ALLOWED_TYPES if t in k.excludes) if k.allow else ()


def _keepout_zone_name(k, stack) -> str:
    name = "keepout %s%s" % (k.name, layer_marker(k.layers, stack))
    return name + allow_marker(k.allow, _relaxed(k)) if _relaxed(k) else name


def allow_rules(plan, stack) -> list:
    """An AllowRule for each keepout of the plan that lets nets through, and for each stamped cell's rule
    area that declares such a list (it arrives with the cell: board_geometry.allow_marker)."""
    from ..rules import AllowRule
    out = [AllowRule(_keepout_zone_name(k, stack), tuple(sorted(k.allow)), _relaxed(k))
           for k in plan.keepouts.values() if _relaxed(k)]
    out += [AllowRule(cell_tagged(ra.name, ra.cell), tuple(sorted(ra.allow)), ra.relaxed, ra.cell)
            for ra in plan.geometry.rule_areas if ra.cell is not None and ra.relaxed]
    return out


def _admits_parts(k) -> bool:
    """Whether a keepout that excludes parts lets some in: by name
    (`allow=` parts or cells) or by height (`max_height=`)."""
    return "parts" in k.excludes and (bool(k.owners) or k.max_height is not None)


def keepout_rules(plan, refs, stack) -> list:
    """A KeepoutRule for each keepout that admits parts: the footprints of
    `refs` (the board's references) it does not admit, forbidden in its
    rule area. None for a keepout that admits every one of them."""
    from ..rules import KeepoutRule
    out = []
    for k in plan.keepouts.values():
        if not _admits_parts(k):
            continue
        if k.barred and k.max_height is None:       # bars=: exactly the parts it names, whatever else the board holds
            forbid = tuple(sorted(r for r in set(refs) if r in k.barred))
        else:
            forbid = tuple(sorted(r for r in set(refs) if r not in k.owners))
        if not forbid:
            continue
        faces = {l for l in (k.layers or ()) if l in (CopperLayer.F, CopperLayer.B)}
        layer = next(iter(faces)).value if k.layers and len(faces) == 1 and len(k.layers) == 1 else None
        out.append(KeepoutRule(_keepout_zone_name(k, stack), forbid, layer))
    return out


_KEEPOUT_DRAWINGS_GROUP = "keepout drawings"


def _keepout_drawing_layer(layers):
    """The Fab layer a keepout's outline and label are drawn on: F.Fab or
    B.Fab when every one of its copper layers is on one face, else
    User.Comments (both faces, layers=None, or inner layers only)."""
    if layers is None:
        return pcbnew.Cmts_User
    faces = {l.face for l in layers if l.face is not None}
    if len(faces) != 1:
        return pcbnew.Cmts_User
    return pcbnew.F_Fab if next(iter(faces)) is Face.FRONT else pcbnew.B_Fab


def _keepout_admits_text(k) -> str:
    """The keepout's name, and its height limit when it has one: `<name>:
    parts <= H mm`. What it admits or bars by name is the rule's to say (its
    rule area and .kicad_dru rule), not board text's."""
    if k.max_height is not None:
        return "%s: parts <= %.2f mm" % (k.name, k.max_height)
    return k.name


def _keepout_admits(k) -> bool:
    return k.max_height is not None or bool(k.owners - k.admitted) or bool(k.allow) or bool(k.barred)


def _unique_uuid(board, it) -> None:
    """`seed_uuids` draws a deterministic sequence for the items one write
    creates, so an unchanged plan writes an unchanged file - but a board
    this project already wrote once (or hand-built with the same seed) can
    already carry an unrelated item at a UUID this write's own sequence
    lands on next; a group keyed by UUID (`keepout drawings`) would then
    read that unrelated item as one of its own. `ResolveItem` (None: not
    found) is asked before `it` joins the board, so it can only find an
    EXISTING item; `ResetUuid` redraws from the same seeded generator,
    deterministic for a given board and call order, until free."""
    while board.ResolveItem(it.m_Uuid, True) is not None:
        it.ResetUuid()


def _draw_keepout_drawings(board, plan):
    """Each keepout that admits something (write.keepout_drawings), drawn as
    its outline and a label naming what it admits, in placemat's own group
    `keepout drawings`, replaced whole every run. Only a TOP-LEVEL group by
    this name is ours to replace (`GetParentGroup() is None`): a stamped
    fragment's own, wherever the external generator puts it, is left
    alone, the same as `_draw_keepouts` leaves a fragment's own rule areas.

    A fragment's own rule area is a DIRECT member of its cell's own group
    (see tests/test_write_roundtrip.py's `_add_rule_area`), which
    `_move_cell` already moves and flips like any other member; a
    fragment's own keepout drawing is expected to arrive the same way once
    a generator writes one, but this is unverified against a real
    generator (this feature is new; no generated fragment carries one
    yet) - if it instead arrives nested one level inside the cell's group,
    `_move_cell`'s own `isinstance(it, pcbnew.PCB_GROUP): continue` will
    skip it, and it will not move with the cell."""
    for g in list(board.Groups()):
        if g.GetName() == _KEEPOUT_DRAWINGS_GROUP and g.GetParentGroup() is None:
            for it in list(g.GetItems()):
                g.RemoveItem(it)
                board.Delete(it)
            board.Delete(g)
    mode = plan.occupancy.settings.write_keepout_drawings
    if mode == "none":
        return
    line = plan.occupancy.settings.write_keepout_line_width
    size = plan.occupancy.settings.write_keepout_text_height
    drawn = []
    for k in plan.keepouts.values():
        if mode == "admitting" and not _keepout_admits(k):
            continue
        layer = _keepout_drawing_layer(k.layers)
        sh = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
        sh.SetLayer(layer)
        sh.SetFilled(False)
        sh.SetWidth(nm(line))
        ps = pcbnew.SHAPE_POLY_SET()
        ps.NewOutline()
        for x, y in k.poly:
            ps.Append(nm(x), nm(y))
        sh.SetPolyShape(ps)
        _unique_uuid(board, sh)
        board.Add(sh)
        drawn.append(sh)
        centre = Box.of_points(k.poly).center
        t = pcbnew.PCB_TEXT(board)
        t.SetText(_keepout_admits_text(k))
        t.SetLayer(layer)
        _mirror_for_layer(t)
        t.SetTextSize(pcbnew.VECTOR2I(nm(size), nm(size)))
        t.SetTextThickness(nm(line))
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        t.SetPosition(vec(centre.x, centre.y))
        _unique_uuid(board, t)
        board.Add(t)
        drawn.append(t)
    if drawn:
        g = pcbnew.PCB_GROUP(board)
        g.SetName(_KEEPOUT_DRAWINGS_GROUP)
        for it in drawn:
            g.AddItem(it)
        _unique_uuid(board, g)
        board.Add(g)


def _draw_outline(board, plan: Plan):
    if not plan.draw_outline:
        return                       # a frame for placement only: Edge.Cuts is left exactly as it was
    for d in list(board.GetDrawings()):
        if isinstance(d, pcbnew.PCB_SHAPE) and d.GetLayer() == pcbnew.Edge_Cuts:
            board.Delete(d)      # Remove() orphans the item and corrupts a later in-process LoadBoard
    if plan.shape is not None and hasattr(plan.shape, "paths"):   # a shaped board: its own path, arcs and all
        for path in plan.shape.paths:
            _draw_path(board, path)
        return
    if plan.shape is not None:                   # a round board: the rim, the bore, and any cutout in it
        c = plan.shape.centre
        for r in (plan.shape.radius, plan.shape.bore):
            if r <= 0:
                continue
            circle = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_CIRCLE)
            circle.SetLayer(pcbnew.Edge_Cuts)
            circle.SetWidth(nm(0.1))
            circle.SetCenter(vec(c.x, c.y))
            circle.SetEnd(vec(c.x + r, c.y))
            board.Add(circle)
        for path in plan.shape.holes:
            _draw_path(board, path)
        return
    if plan.outline is None:
        return
    W, H = plan.outline.width, plan.outline.height
    x0, y0 = plan.outline.left, plan.outline.top
    segs = []
    if plan.chamfer:
        c = plan.chamfer
        segs = [(c, 0, W - c, 0), (W, c, W, H - c), (W - c, H, c, H), (0, H - c, 0, c),
                (W - c, 0, W, c), (W, H - c, W - c, H), (c, H, 0, H - c), (0, c, c, 0)]
    elif plan.radius:
        r = plan.radius
        segs = [(r, 0, W - r, 0), (W, r, W, H - r), (W - r, H, r, H), (0, H - r, 0, r)]
        for cx, cy, sx, sy in ((r, r, 0, r), (W - r, r, W - r, 0), (W - r, H - r, W, H - r), (r, H - r, r, H)):
            a = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
            a.SetLayer(pcbnew.Edge_Cuts)
            a.SetWidth(nm(0.1))
            a.SetCenter(vec(x0 + cx, y0 + cy))
            a.SetStart(vec(x0 + sx, y0 + sy))
            a.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(90, pcbnew.DEGREES_T))
            board.Add(a)
    else:
        segs = [(0, 0, W, 0), (W, 0, W, H), (W, H, 0, H), (0, H, 0, 0)]
    for i, (x1, y1, x2, y2) in enumerate(segs):
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(nm(0.1))
        s.SetStart(vec(x0 + x1, y0 + y1))
        s.SetEnd(vec(x0 + x2, y0 + y2))
        board.Add(s)
    for path in plan.cutouts.paths:          # a rectangle's holes hang off the board, not a shape
        _draw_path(board, path)


def _netcode(board, net: str) -> int:
    ni = board.FindNet(net)
    if ni is None:
        raise KeyError("no net named %r on the board" % net)
    return ni.GetNetCode()


def _layer_id(board, layer) -> int:
    return board.GetLayerID(layer.value)


def _draw_track(board, op: Track):
    """A segment, or - with a mid point - KiCad's arc track through start, mid and end."""
    t = pcbnew.PCB_ARC(board) if op.mid is not None else pcbnew.PCB_TRACK(board)
    t.SetLayer(_layer_id(board, op.layer))
    t.SetNetCode(_netcode(board, op.net))
    t.SetWidth(nm(op.width))
    t.SetStart(vec(op.start.x, op.start.y))
    t.SetEnd(vec(op.end.x, op.end.y))
    if op.mid is not None:
        t.SetMid(vec(op.mid.x, op.mid.y))
    board.Add(t)


def _via_type(span) -> int:
    """KiCad's via type for a span of layers in stackup order: a micro via
    for an outer face and the layer next to it, blind for a span from an
    outer face, buried for one between inner layers. KiCad 9 has one type
    for blind and buried, KiCad 10 one each."""
    if len(span) == 2 and any(l.face is not None for l in span):
        return pcbnew.VIATYPE_MICROVIA
    blind = any(l.face is not None for l in span)
    name = "VIATYPE_BLIND" if blind else "VIATYPE_BURIED"
    return getattr(pcbnew, name, None) if hasattr(pcbnew, name) else pcbnew.VIATYPE_BLIND_BURIED


def _draw_via(board, op: Via):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(vec(op.at.x, op.at.y))
    if op.layers:
        # a KiCad 9 board allows the type in its design settings; KiCad 10 has no such switch
        ds = board.GetDesignSettings()
        for allow in ("m_MicroViasAllowed", "m_BlindBuriedViaAllowed"):
            if hasattr(ds, allow):
                setattr(ds, allow, True)
        v.SetViaType(_via_type(op.layers))
        v.SetLayerPair(_layer_id(board, op.layers[0]), _layer_id(board, op.layers[-1]))
    v.SetDrill(nm(op.drill))
    v.SetWidth(nm(op.size))
    v.SetNetCode(_netcode(board, op.net))
    board.Add(v)


_HJUST = {"left": pcbnew.GR_TEXT_H_ALIGN_LEFT, "centre": pcbnew.GR_TEXT_H_ALIGN_CENTER, "right": pcbnew.GR_TEXT_H_ALIGN_RIGHT}
_VJUST = {"top": pcbnew.GR_TEXT_V_ALIGN_TOP, "centre": pcbnew.GR_TEXT_V_ALIGN_CENTER, "bottom": pcbnew.GR_TEXT_V_ALIGN_BOTTOM}


def _draw_text(board, op: Text):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(op.text)
    t.SetLayer(board.GetLayerID(op.layer) if op.layer else (pcbnew.B_SilkS if op.face is Face.BACK else pcbnew.F_SilkS))
    _mirror_for_layer(t, op.mirrored)
    t.SetTextSize(pcbnew.VECTOR2I(nm(op.size), nm(op.size)))
    t.SetTextThickness(nm(op.thickness))
    t.SetHorizJustify(_HJUST[op.hjust])
    t.SetVertJustify(_VJUST[op.vjust])
    t.SetTextAngleDegrees(op.rotation)
    t.SetIsKnockout(op.knockout)
    t.SetPosition(vec(op.at.x, op.at.y))
    if op.side is not None:
        # KiCad's box round the text (descenders, the knockout margin) reaches past the
        # anchor: slide the text so the edge of what it draws (the glyphs, or the
        # knockout frame) facing the item sits exactly at the anchor.
        bb = t.GetEffectiveShape().BBox()
        name = op.side.name
        if name == "NORTH":
            t.Move(pcbnew.VECTOR2I(0, nm(op.at.y) - bb.GetBottom()))
        elif name == "SOUTH":
            t.Move(pcbnew.VECTOR2I(0, nm(op.at.y) - bb.GetTop()))
        elif name == "WEST":
            t.Move(pcbnew.VECTOR2I(nm(op.at.x) - bb.GetRight(), 0))
        else:
            t.Move(pcbnew.VECTOR2I(nm(op.at.x) - bb.GetLeft(), 0))
    board.Add(t)


def _draw_pour(board, op: Pour):
    """A pour is a graphic polygon of the net, filled, drawn exactly as planned."""
    one = pcbnew.SHAPE_POLY_SET()
    one.NewOutline()
    for x, y in op.points:
        one.Append(nm(x), nm(y))
    sh = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
    sh.SetLayer(_layer_id(board, op.layer))
    sh.SetFilled(True)
    sh.SetWidth(nm(op.stroke))
    sh.SetPolyShape(one)
    sh.SetNetCode(_netcode(board, op.net))
    board.Add(sh)


def _npth_circles(board, clearance: float):
    out = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                c = p.GetPosition()
                out.append((pcbnew.ToMM(c.x), pcbnew.ToMM(c.y), pcbnew.ToMM(p.GetDrillSize().x) / 2.0 + clearance))
    return out


def _draw_zone(board, op: Zone):
    import math
    z = pcbnew.ZONE(board)
    z.SetLayer(_layer_id(board, op.layer))
    z.SetNetCode(_netcode(board, op.net))
    z.SetLocalClearance(nm(op.clearance))
    z.SetMinThickness(nm(op.min_thickness))
    z.SetIsRuleArea(False)
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if op.solid_pads else pcbnew.ZONE_CONNECTION_THERMAL)
    o = z.Outline()
    o.NewOutline()
    for x, y in op.points:
        o.Append(nm(x), nm(y))
    for hx, hy, hr in _npth_circles(board, op.npth_clearance):
        n = 32
        rr = (hr + 0.02) / math.cos(math.pi / n)
        hole = pcbnew.SHAPE_POLY_SET()
        hole.NewOutline()
        for a in range(n):
            th = 2.0 * math.pi * a / n
            hole.Append(nm(hx + rr * math.cos(th)), nm(hy + rr * math.sin(th)))
        o.BooleanSubtract(hole)
    board.Add(z)
    return z


def _raise_planes_over_zones(board, planes) -> None:
    """Give each drawn plane a priority above every same-net zone it overlaps on a shared layer: the zones
    the board already had (a board-wide ground zone under a plane bounded to a fit frame) and the planes
    drawn before it. KiCad's DRC reports two overlapping zones at one priority as zones_intersect. Same
    net, so which fills first does not change the connection; the plane, drawn by the script, fills first
    where they overlap."""
    uid = lambda z: z.m_Uuid.AsString()
    later = {uid(z) for z in planes}
    for z in planes:
        later.discard(uid(z))               # what is left is the planes not yet raised
        layers = set(z.GetLayerSet().CuStack())
        near = [o for o in board.Zones() if uid(o) != uid(z) and uid(o) not in later and not o.GetIsRuleArea()
                and o.GetNetname() == z.GetNetname() and layers & set(o.GetLayerSet().CuStack())
                and _zones_overlap(z, o)]
        if near:
            z.SetAssignedPriority(max(o.GetAssignedPriority() for o in near) + 1)


def draw_copper(board, ops):
    zones = []
    for op in ops:
        if isinstance(op, Track):
            _draw_track(board, op)
        elif isinstance(op, Via):
            _draw_via(board, op)
        elif isinstance(op, Pour):
            _draw_pour(board, op)
        elif isinstance(op, Text):
            _draw_text(board, op)
        elif isinstance(op, Zone):
            zones.append(_draw_zone(board, op))
    if zones:
        _raise_planes_over_zones(board, zones)
        # The filler removes a fill's isolated islands by the board's connectivity, which LoadBoard built
        # before the plan moved the parts and drew its copper. Filled on that, a module's ground fill kept
        # islands a refill of the saved board removes (tests/test_keep_out_modules.py).
        board.BuildConnectivity()
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())


def refs_to_fab(board, text_mm: float = 0.8, thick_mm: float = 0.15):
    """Every reference designator onto the fab layer of its own face, nudged
    clear of pads and of refs already placed; smallest parts first."""
    clr = nm(0.12)
    pad_boxes = []
    fps = list(board.GetFootprints())
    for fp in fps:
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            bb.Inflate(clr)
            pad_boxes.append(bb)
    placed = []
    dirs = [(0, -1), (0, 1), (1, 0), (-1, 0), (1, -1), (-1, -1), (1, 1), (-1, 1)]
    for fp in sorted(fps, key=lambda f: (f.GetBoundingBox(False, False).GetArea(), f.GetReference())):
        t = fp.Reference()
        t.SetLayer(pcbnew.B_Fab if fp.IsFlipped() else pcbnew.F_Fab)
        t.SetMirrored(fp.IsFlipped())
        t.SetTextSize(pcbnew.VECTOR2I(nm(text_mm), nm(text_mm)))
        t.SetTextThickness(nm(thick_mm))
        fx, fy = fp.GetPosition().x, fp.GetPosition().y
        best, best_hits = None, 10 ** 9
        for r in (0.9, 1.4, 1.9, 2.5, 3.1, 3.8):
            for dx, dy in dirs:
                n = (dx * dx + dy * dy) ** 0.5
                t.SetPosition(pcbnew.VECTOR2I(fx + int(nm(r) * dx / n), fy + int(nm(r) * dy / n)))
                box = t.GetBoundingBox()
                box.Inflate(clr)
                hits = sum(1 for pb in pad_boxes if box.Intersects(pb)) + sum(1 for rb in placed if box.Intersects(rb))
                if hits < best_hits:
                    best, best_hits = t.GetPosition(), hits
                if hits == 0:
                    break
            if best_hits == 0:
                break
        t.SetPosition(best)
        placed.append(t.GetBoundingBox())


def patch_stackup_colors(path: str, mask: str = "Green", silk: str = "White") -> bool:
    """House render convention: green mask, white silk, so copper reads in a
    render. pcbnew exposes no setter, so this edits the (stackup) block of the
    saved file. Idempotent; a board with no stackup block is left alone."""
    import re
    src = open(path).read()
    if "(stackup" not in src:
        return False
    for names, color in ((("F.Mask", "B.Mask"), mask), (("F.SilkS", "B.SilkS"), silk)):
        for name in names:
            pat = re.compile(r'(\(layer "%s"\s*\n\s*\(type "[^"]*(?:Silk Screen|Solder Mask)"\))'
                             r'(\s*\n\s*\(color "[^"]*"\))?' % re.escape(name))
            src, _ = pat.subn(lambda m: m.group(1) + '\n\t\t\t\t(color "%s")' % color, src, count=1)
    open(path, "w").write(src)
    return True


def patch_project_presets(pcb_path: str, fab) -> None:
    """Track-width and via presets from the fab profile into the sibling
    .kicad_pro, so a hand edit in KiCad can pick real widths."""
    import json
    pro = os.path.splitext(pcb_path)[0] + ".kicad_pro"
    if not os.path.exists(pro):
        return
    try:
        d = json.load(open(pro))
    except json.JSONDecodeError:
        return
    ds = d.setdefault("board", {}).setdefault("design_settings", {})
    ds["trace_widths"] = list(fab.track_widths)
    ds["via_dimensions"] = [{"diameter": fab.via_size, "drill": fab.via_drill}]
    json.dump(d, open(pro, "w"), indent=2)


def finish_board(pcb_path, fab, refs_to_fab_layer: bool = True, refs_to_fab=None) -> None:
    """The save-time work every board gets: refs onto fab, render colours,
    project presets."""
    pcb_path = str(pcb_path)
    if refs_to_fab is None:
        refs_to_fab = refs_to_fab_layer
    if refs_to_fab:
        with quiet_stderr():
            board = pcbnew.LoadBoard(pcb_path)
        seed_uuids()
        globals()["refs_to_fab"](board)
        save(board, pcb_path)
    patch_stackup_colors(pcb_path)
    patch_project_presets(pcb_path, fab)
    from ..settings import active
    from .drc import patch_rule_severities
    patch_rule_severities(pcb_path, active().drc_severities)


def render_board(pcb_path, log, both_faces: bool = False, timeout: int | None = None) -> list:
    """layout.png (top), layout-iso.png, and layout-bottom.png when the board
    carries parts on both faces, beside the board file."""
    import subprocess
    from ..settings import active
    timeout = active().timeout_render if timeout is None else timeout
    pcb_path = str(pcb_path)
    out_dir = os.path.dirname(pcb_path)
    views = [("layout.png", "top", []), ("layout-iso.png", "top", ["--rotate", "-45,0,45", "--perspective"])]
    if both_faces:
        views.append(("layout-bottom.png", "bottom", []))
    env = child_env()
    done = []
    with open(log, "w") as f:
        for name, side, extra in views:
            cmd = ["kicad-cli", "pcb", "render", "--side", side, "--background", "opaque", "--quality", "high",
                   "--use-board-stackup-colors", "-o", os.path.join(out_dir, name), pcb_path] + extra
            f.write("$ %s\n" % " ".join(cmd))
            f.flush()
            try:
                subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout, env=env)
                done.append(name)
            except Exception as e:
                f.write("render %s failed: %s\n" % (name, e))
    return done


def save(board, path: str):
    """Atomic save: write beside the target and move it into place. pcbnew
    writes a project file beside whatever name it saves, so the temporary
    name keeps the board's own stem and the project it makes for the
    temporary name is removed."""
    d, name = os.path.split(path)
    stem = os.path.splitext(name)[0]
    tmp = os.path.join(d, ".%s.writing.kicad_pcb" % stem)
    with quiet_stderr():
        board.Save(tmp)
    os.replace(tmp, path)
    for ext in (".kicad_pro", ".kicad_prl"):
        stray = os.path.join(d, ".%s.writing%s" % (stem, ext))
        if os.path.exists(stray):
            os.remove(stray)


def apply_plan(pcb_path, plan: Plan, out_path=None) -> str:
    pcb_path = str(pcb_path)
    if any(isinstance(op, Zone) for op in plan.copper):
        # KiCad reads the rules file beside a board as the board loads, and a plane's fill keeps the
        # clearance rules the script declared: they are there before the load, not only after the save
        from ..rules import write_rules
        write_rules(pcb_path, list(plan.rules))
    with quiet_stderr():
        board = pcbnew.LoadBoard(pcb_path)
    seed_uuids()
    _drop_stamped_notes(board, plan)
    groups = {g.GetName(): g for g in board.Groups()}
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for name, gone in sorted(plan.thinned.items()):
        _thin_cell(board, groups[name], gone)
    for step in plan.steps:
        if step.placement is None or step.kind == "block":
            continue                     # copper is drawn below; a block's members have their own steps
        item = plan._items[step.item]
        if isinstance(item, Footprint):
            fp = by_ref[item.ref]
            _place_footprint(fp, Placement(item.location, item.rotation, item.face), step.placement)
        elif isinstance(item, CellGeom):
            _move_cell(board, item, step.placement, groups)
    _given_way(board, plan, groups)
    if plan.cell_zones_under_planes == "drop":
        plan.merged_zones = _merge_cell_zones(board, plan)
    _separate_cell_zone_priorities(board, plan)
    _draw_outline(board, plan)
    _draw_keepouts(board, plan)
    _draw_keepout_drawings(board, plan)
    if not plan.draw_outline:
        write_rule_notes(board, plan.rules)         # a fragment: its clearance rules ride with the cell
    draw_copper(board, plan.copper)
    _group_given_way_tracks(board, plan, groups)
    plan.group_notes = _write_groups(board, plan)
    out = str(out_path or pcb_path)
    plan.models = _reanchor_models(board, Path(out).parent)
    save(board, out)
    from ..rules import write_rules
    stack = tuple(CopperLayer.of(board.GetLayerName(l)) for l in board.GetEnabledLayers().CuStack())
    write_rules(out, list(plan.rules) + keepout_rules(plan, [fp.GetReference() for fp in board.GetFootprints()],
                                                      stack) + allow_rules(plan, stack))
    return out


def _is_note(item) -> bool:
    return isinstance(item, pcbnew.PCB_TEXT) and item.GetText().startswith((FACES_PREFIX, RULE_PREFIX))


def _delete_note(board, note) -> None:
    group = note.GetParentGroup()
    if group is not None:
        group.RemoveItem(note)
    board.Delete(note)


def _loose_faces(item) -> bool:
    return item.GetParentGroup() is None and item.GetText().startswith(FACES_PREFIX)


def _drop_stamped_notes(board, plan: Plan) -> None:
    """Take a stamped fragment's notes (its faces, its clearance rules) off the board. A note is the
    fragment's fact for the parent, read at load (read.board_geometry_of), so it does not stay: stamped,
    it sits below the fragment's content, stays behind when the cell is turned and placed, and stretches
    the group's box across the gap. Every note goes, in a group or loose on the board. The board's own
    are written again below from its plan (`board.faces()`, `board.rule()` on a fragment); the one
    exception is the faces text a fragment was stamped with by `placemat faces`, loose on a fragment
    that declares none of its own: that is the fragment's fact, and is kept."""
    declares = any(isinstance(op, Text) and op.text.startswith(FACES_PREFIX) for op in plan.copper)
    keep_loose_faces = not plan.draw_outline and not declares
    for d in list(board.GetDrawings()):
        if _is_note(d) and not (keep_loose_faces and _loose_faces(d)):
            _delete_note(board, d)


def strip_stamped_notes(pcb_path, keep_loose_faces: bool = False) -> int:
    """Take the stamped notes off the board at `pcb_path` and save it (a fragment keeps the faces text
    it was stamped with, loose on the board: `keep_loose_faces`). A run does this once it has read
    the facts the notes carry, so the generated board it leaves in the layout folder while it works
    does not show them. Returns how many were taken off."""
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(pcb_path))
        notes = [d for d in board.GetDrawings() if _is_note(d) and not (keep_loose_faces and _loose_faces(d))]
        if not notes:
            return 0
        for d in notes:
            _delete_note(board, d)
        save(board, str(pcb_path))
    return len(notes)


def _write_groups(board, plan: Plan) -> list:
    """The board's KiCad groups as the plan leaves them. "lift" (the
    default): each group nested in another (a stamped cell in its module
    sheet's) is lifted to the top level, whole, and a module keeps its own
    parts. "split": as well, the parts the plan placed by steps of their own
    are taken out of a group it did not place whole. "keep": as generated.
    A group left empty is removed. Then each group the script declared is
    written. A line for each change, for the run to say."""
    notes = []
    placed = {s.item for s in plan.steps if s.placement is not None and s.kind != "block"}
    whole = {k for k in placed if isinstance(plan._items.get(k), CellGeom)}
    moved_refs = {plan._items[k].ref for k in placed if isinstance(plan._items.get(k), Footprint)}
    if plan.split_groups in ("lift", "split"):
        lifted: dict = {}
        for g in list(board.Groups()):
            parent = g.GetParentGroup()
            if parent is not None:
                lifted.setdefault(parent.GetName(), []).append(g.GetName())
                parent.RemoveItem(g)
        for name, cells in sorted(lifted.items()):
            notes.append("%s: cell(s) %s lifted to the top level" % (name, ", ".join(sorted(cells))))
    if plan.split_groups == "split":
        for g in list(board.Groups()):
            name = g.GetName()
            if name in whole:
                continue
            items = list(g.GetItems())
            out = [it for it in items if isinstance(it, pcbnew.FOOTPRINT) and it.GetReference() in moved_refs]
            if not out:
                continue
            for it in out:
                g.RemoveItem(it)
            notes.append("%s: %d part(s) placed apart, taken out%s" % (
                name, len(out), "; left empty, removed" if len(out) == len(items) else
                "; %d item(s) stay in it" % (len(items) - len(out))))
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for d in plan.groups:
        g = pcbnew.PCB_GROUP(board)
        g.SetName(d.name)
        for it in [by_ref[r] for r in d.parts]:
            parent = it.GetParentGroup()
            if parent is not None:
                parent.RemoveItem(it)
            g.AddItem(it)
        board.Add(g)
        notes.append("%s written: %d part(s)%s" % (d.name, len(d.parts), " (%s)" % d.why if d.why else ""))
    for g in list(board.Groups()):                  # a module's group that held only its cells, or what a declared one took
        if not list(g.GetItems()):
            board.Delete(g)
    return notes


def _reanchor_models(board, project_dir) -> dict:
    """Each footprint's model path that does not resolve from the project's
    folder, re-anchored to the folder above that holds it (models.reanchor).
    What was done: {"reanchored": n, "missing": [file names]}."""
    from ..models import reanchor, workspace_root
    stop = workspace_root(project_dir)
    done, missing = 0, []
    for fp in board.GetFootprints():
        models = fp.Models()
        for i in range(len(models)):
            m = models[i]                 # by index: iterating the list hands out copies
            new, found = reanchor(m.m_Filename, project_dir, stop)
            if new is not None:
                m.m_Filename = new
                done += 1
            elif not found:
                missing.append(m.m_Filename.replace("\\", "/").rsplit("/", 1)[-1])
    return {"reanchored": done, "missing": sorted(set(missing))}


def _kiid(item) -> str:
    return item.m_Uuid.AsString()


def _extract_item(pcb_path: str, name: str, scratch: str) -> None:
    """Save a board that holds only the group (or footprint) called `name`:
    the kept items are duplicated into a fresh board. Nothing is removed
    from the loaded one, which pcbnew's Python proxies do not survive."""
    src = pcbnew.LoadBoard(pcb_path)
    keep = set()
    for g in src.Groups():
        if g.GetName() == name:
            keep = {_kiid(it) for it in g.GetItems()}
    if not keep:
        for fp in src.GetFootprints():
            if fp.GetReference() == name or fp.GetFieldText("Path").rsplit(".", 1)[0] == name:
                keep = {_kiid(fp)}
    if not keep:
        raise KeyError("no cell or part named %r on the board" % name)
    new = pcbnew.BOARD()
    for coll in (list(src.GetFootprints()), list(src.GetTracks()), list(src.GetDrawings())):
        for it in coll:
            if _kiid(it) in keep:
                new.Add(it.Duplicate(False) if isinstance(it, pcbnew.FOOTPRINT) else it.Duplicate())
    _reanchor_models(new, Path(scratch).parent)          # the models as the scratch board's folder finds them
    new.Save(scratch)


def show_item(pcb_path, name: str, out_dir, quality: str = "basic") -> list:
    """Render one cell or part on its own, from above and below. Returns
    the PNG paths written, top then bottom."""
    import subprocess
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch = out_dir / (".%s.show.kicad_pcb" % name)
    with quiet_stderr():
        _extract_item(str(pcb_path), name, str(scratch))
    env = child_env()
    done = []
    views = [("iso", "top", ["--rotate", "-45,0,45", "--perspective"]),
             ("iso-bottom", "bottom", ["--rotate", "45,0,45", "--perspective"]),
             ("top", "top", []), ("bottom", "bottom", [])]
    for view, side, extra in views:
        png = out_dir / ("%s-%s.png" % (name, view))
        cmd = ["kicad-cli", "pcb", "render", "--side", side, "--background", "opaque", "--quality", quality,
               "-w", "1000", "-h", "600", "-o", str(png), str(scratch)] + extra
        subprocess.run(cmd, capture_output=True, timeout=300, env=env)
        if png.exists():
            done.append(png)
    for ext in (".kicad_pcb", ".kicad_pro", ".kicad_prl"):
        stray = out_dir / (".%s.show%s" % (name, ext))
        if stray.exists():
            stray.unlink()
    return done


def write_rule_notes(board, rules) -> list:
    """The clearance rules a fragment declares, as User.Comments texts (`rules.rule_note`) that pcb layout
    stamps with the cell, replacing any the board has outside a group. A rule of a part (`of=`) is
    the part's own annotation, which the stamped board reads off the part, so it has none. Returns the
    texts written."""
    for d in list(board.GetDrawings()):
        if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(RULE_PREFIX) and d.GetParentGroup() is None:
            board.Delete(d)
    texts = [rule_note(r) for r in rules if r.kind == "clearance" and r.of is None]
    if not texts:
        return []
    # in the margin below everything the fragment draws, under its faces note: never over a part
    boxes = [fp.GetBoundingBox(True, True) for fp in board.GetFootprints()]
    boxes += [d.GetBoundingBox() for d in board.GetDrawings()
              if not (isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith((FACES_PREFIX, RULE_PREFIX)))]
    boxes += [t.GetBoundingBox() for t in board.GetTracks()] + [z.GetBoundingBox() for z in board.Zones()]
    left = min(b.GetLeft() for b in boxes) if boxes else 0
    bottom = max(b.GetBottom() for b in boxes) if boxes else 0
    for i, text in enumerate(texts):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(text)
        t.SetLayer(pcbnew.Cmts_User)
        t.SetTextSize(pcbnew.VECTOR2I(nm(0.5), nm(0.5)))
        t.SetTextThickness(nm(0.1))
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_TOP)
        t.SetPosition(pcbnew.VECTOR2I(left, bottom + nm(2.0 + 0.7 * i)))
        _unique_uuid(board, t)
        board.Add(t)
    return texts


def write_faces(pcb_path, faces: dict) -> str:
    """Put a module fragment's faces fact into it (replacing any it has):
    a User.Comments text `placemat faces outward=N ...` that pcb layout stamps
    with the cell. Returns the text written."""
    from ..values import Edge
    words = ["%s=%s" % (k, Edge(v).value) for k, v in faces.items() if v]
    text = "placemat faces " + " ".join(words)
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(pcb_path))
        for d in list(board.GetDrawings()):
            if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith("placemat faces "):
                board.Delete(d)
        # Below everything the module draws (courtyards included), left-aligned with it:
        # a note in the margin, never over the module's origin or a part.
        boxes = [fp.GetBoundingBox(True, True) for fp in board.GetFootprints()]
        boxes += [d.GetBoundingBox() for d in board.GetDrawings() if not (isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith((FACES_PREFIX, RULE_PREFIX)))]
        boxes += [t.GetBoundingBox() for t in board.GetTracks()]
        boxes += [z.GetBoundingBox() for z in board.Zones()]
        left = min(b.GetLeft() for b in boxes) if boxes else 0
        bottom = max(b.GetBottom() for b in boxes) if boxes else 0
        t = pcbnew.PCB_TEXT(board)
        t.SetText(text)
        t.SetLayer(pcbnew.Cmts_User)
        t.SetTextSize(pcbnew.VECTOR2I(nm(0.5), nm(0.5)))
        t.SetTextThickness(nm(0.1))
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_TOP)
        t.SetPosition(pcbnew.VECTOR2I(left, bottom + nm(1.0)))
        board.Add(t)
        seed_uuids()
        save(board, str(pcb_path))
    return text
