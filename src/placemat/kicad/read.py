"""Reads a .kicad_pcb through pcbnew into a Snapshot.

Box conventions: the body box is the courtyard deflated by the fab's
courtyard excess, unioned with the pads (a courtyard is an assembly keepout,
and fab and silk drawings over-draw bodies); the courtyard box is courtyard
outlines plus pads; the physical box is pads plus drawn graphics, courtyard
excluded."""
from __future__ import annotations

from pathlib import Path

import pcbnew

from ..snapshot import CellGeom, CopperItem, Footprint, NetClass, PadGeom, Snapshot
from ..values import Box, CopperLayer, Face, Location

CLEAR_ERR_NM = 5000     # arc approximation error for TransformShapeToPolySet
# Layer IDs, not names: KiCad 10 reports "F.Silkscreen"/"F.Courtyard" where
# older versions said "F.SilkS"/"F.CrtYd".
_PHYS_LAYERS = {pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.F_SilkS, pcbnew.B_SilkS, pcbnew.F_Fab, pcbnew.B_Fab,
                pcbnew.F_Mask, pcbnew.B_Mask, pcbnew.F_Paste, pcbnew.B_Paste, pcbnew.Edge_Cuts}
_COURTYARD_LAYERS = {pcbnew.F_CrtYd, pcbnew.B_CrtYd}


def mm(v) -> float:
    return pcbnew.ToMM(int(v))


def _box_of(bb) -> Box:
    return Box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))


def _layer_names(board, layer_set) -> list[str]:
    return [board.GetLayerName(l) for l in layer_set.CuStack()]


def _copper_layers(board, layer_set) -> frozenset[CopperLayer]:
    out = set()
    for name in _layer_names(board, layer_set):
        try:
            out.add(CopperLayer.of(name))
        except ValueError:
            continue
    return frozenset(out)


def outlines_of(item, layer_id, err_nm=CLEAR_ERR_NM):
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolySet(ps, layer_id, 0, err_nm, pcbnew.ERROR_OUTSIDE)
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        pts = tuple((mm(o.CPoint(j).x), mm(o.CPoint(j).y)) for j in range(o.PointCount()))
        if len(pts) >= 3:
            out.append(pts)
    return tuple(out)


def _kiid(item) -> str:
    return item.m_Uuid.AsString()


def path_of(fp) -> str:
    try:
        return fp.GetFieldText("Path") or ""
    except KeyError:
        return ""


def inst_of(fp) -> str:
    """The schematic instance: the Path field minus its last component (the
    part's own symbol name), e.g. `power_drop0.conn.DEGSON_x` -> `power_drop0.conn`.
    A footprint with no Path is addressed by its refdes."""
    path = path_of(fp)
    if not path:
        return fp.GetReference()
    return path.rsplit(".", 1)[0] if "." in path else path


def _pads_box(fp) -> Box | None:
    boxes = [_box_of(p.GetBoundingBox()) for p in fp.Pads()]
    return Box.union(boxes)


def phys_box(fp, text=False) -> Box:
    boxes = [_pads_box(fp)]
    for d in fp.GraphicalItems():
        if d.GetLayer() not in _PHYS_LAYERS:
            continue
        if not text and isinstance(d, pcbnew.PCB_TEXT):
            continue
        boxes.append(_box_of(d.GetBoundingBox()))
    box = Box.union(boxes)
    if box is None:
        return _box_of(fp.GetBoundingBox(False, False))
    return box


def courtyard_box(fp) -> Box:
    boxes = [_box_of(d.GetBoundingBox()) for d in fp.GraphicalItems()
             if d.GetLayer() in _COURTYARD_LAYERS]
    boxes.append(_pads_box(fp))
    box = Box.union(boxes)
    return box if box is not None else phys_box(fp)


def body_box(fp, excess_mm: float) -> Box:
    has_ct = any(d.GetLayer() in _COURTYARD_LAYERS for d in fp.GraphicalItems())
    if not has_ct:
        return phys_box(fp)
    ct = courtyard_box(fp)
    ct = Box(ct.left + excess_mm, ct.top + excess_mm, ct.right - excess_mm, ct.bottom - excess_mm)
    return Box.union([ct, _pads_box(fp)])


def _pads(board, fp) -> tuple[PadGeom, ...]:
    ref, inst = fp.GetReference(), inst_of(fp)
    pads = []
    for pad in fp.Pads():
        attr = pad.GetAttribute()
        if attr == pcbnew.PAD_ATTRIB_NPTH:
            continue
        cu = [l for l in pad.GetLayerSet().CuStack()]
        if not cu:
            continue
        outs = outlines_of(pad, cu[0])
        if not outs:
            continue
        drill = pad.GetDrillSize()
        pads.append(PadGeom(owner=ref, inst=inst, number=pad.GetNumber() or "?",
                            net=pad.GetNetname(), layers=_copper_layers(board, pad.GetLayerSet()),
                            outlines=outs, box=Box.of_points([p for o in outs for p in o]),
                            through=attr == pcbnew.PAD_ATTRIB_PTH,
                            drill_mm=mm(drill.x) if attr == pcbnew.PAD_ATTRIB_PTH else 0.0))
    return tuple(pads)


def _npth(fp):
    out = []
    for pad in fp.Pads():
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            c = pad.GetPosition()
            out.append((Location(mm(c.x), mm(c.y)), mm(pad.GetDrillSize().x)))
    return tuple(out)


def _footprint(board, fp, excess_mm, cell) -> Footprint:
    pos = fp.GetPosition()
    return Footprint(ref=fp.GetReference(), inst=inst_of(fp), cell=cell, value=fp.GetValue(),
                     location=Location(mm(pos.x), mm(pos.y)),
                     rotation=fp.GetOrientationDegrees(),
                     face=Face.BACK if fp.IsFlipped() else Face.FRONT,
                     body_box=body_box(fp, excess_mm), courtyard_box=courtyard_box(fp),
                     phys_box=phys_box(fp), pads=_pads(board, fp), npth=_npth(fp))


def _copper(board, groups_of) -> tuple[CopperItem, ...]:
    items = []

    def add(kind, obj, net, owner=None, width=0.0):
        cu = [l for l in obj.GetLayerSet().CuStack()]
        if not cu:
            return
        outs = outlines_of(obj, cu[0])
        if not outs:
            return
        items.append(CopperItem(kind, net, _copper_layers(board, obj.GetLayerSet()), outs,
                                Box.of_points([p for o in outs for p in o]), owner, width))

    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                continue
            add("pad", pad, pad.GetNetname(), fp.GetReference())
    for t in board.GetTracks():
        owner = groups_of.get(_kiid(t))
        if isinstance(t, pcbnew.PCB_VIA):
            add("via", t, t.GetNetname(), owner)
        else:
            add("track", t, t.GetNetname(), owner, mm(t.GetWidth()))
    for d in board.GetDrawings():
        if isinstance(d, pcbnew.PCB_SHAPE) and d.GetLayerSet().CuStack():
            add("poly", d, d.GetNetname(), groups_of.get(_kiid(d)))
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        for layer in z.GetLayerSet().CuStack():
            ps = z.GetFilledPolysList(layer)
            outs = []
            for k in range(ps.OutlineCount()):
                o = ps.Outline(k)
                outs.append(tuple((mm(o.CPoint(j).x), mm(o.CPoint(j).y)) for j in range(o.PointCount())))
            if outs:
                items.append(CopperItem("zone", z.GetNetname(), frozenset([CopperLayer.of(board.GetLayerName(layer))]),
                                        tuple(outs), Box.of_points([p for o in outs for p in o])))
    return tuple(items)


def _outline(board) -> tuple:
    outs = []
    for d in board.GetDrawings():
        if isinstance(d, pcbnew.PCB_SHAPE) and d.GetLayer() == pcbnew.Edge_Cuts:
            bb = d.GetBoundingBox()
            b = _box_of(bb)
            outs.append(((b.left, b.top), (b.right, b.top), (b.right, b.bottom), (b.left, b.bottom)))
    return tuple(outs)


def _netclasses(board) -> tuple[dict[str, NetClass], float]:
    classes = {}
    for ni in board.GetNetInfo().NetsByName().values():
        name = ni.GetNetname()
        if not name:
            continue
        nc = ni.GetNetClassSlow()
        parts = [p for p in str(nc.GetName()).split(",") if p and p != "Default"]
        classes[name] = NetClass(",".join(parts) or "Default", mm(nc.GetTrackWidth()),
                                 mm(nc.GetClearance()), mm(nc.GetViaDiameter()), mm(nc.GetViaDrill()))
    default = mm(board.GetDesignSettings().m_NetSettings.GetDefaultNetclass().GetClearance())
    return classes, default


def read_board(path, courtyard_excess_mm: float = 0.10) -> Snapshot:
    path = str(Path(path))
    board = pcbnew.LoadBoard(path)
    return snapshot_of(board, path, courtyard_excess_mm)


def snapshot_of(board, path: str, courtyard_excess_mm: float = 0.10) -> Snapshot:
    """Build a Snapshot from an already-loaded pcbnew BOARD."""
    member_cell = {}
    groups_of = {}
    group_items = {}
    for g in board.Groups():
        name = g.GetName()
        group_items[name] = list(g.GetItems())
        for it in group_items[name]:
            groups_of[_kiid(it)] = name
            if isinstance(it, pcbnew.FOOTPRINT):
                member_cell[it.GetReference()] = name
    fps = tuple(_footprint(board, fp, courtyard_excess_mm, member_cell.get(fp.GetReference()))
                for fp in board.GetFootprints())
    by_ref = {fp.ref: fp for fp in fps}
    copper = _copper(board, groups_of)
    cells = {}
    for name, items in group_items.items():
        members = tuple(by_ref[it.GetReference()] for it in items if isinstance(it, pcbnew.FOOTPRINT))
        own = [c.box for c in copper if c.owner == name and c.kind != "pad"]
        copper_box = Box.union(own)
        box = Box.union([fp.body_box for fp in members] + own)
        phys = Box.union([fp.phys_box for fp in members] + own)
        court = Box.union([fp.courtyard_box for fp in members] + own)
        cells[name] = CellGeom(name, members, box, phys, court, copper_box)
    classes, default_clr = _netclasses(board)
    layers = tuple(CopperLayer.of(board.GetLayerName(l)) for l in board.GetEnabledLayers().CuStack()
                   if board.GetLayerName(l) in {m.value for m in CopperLayer})
    return Snapshot(path=path, footprints=fps, cells=cells, copper=copper, outline=_outline(board),
                    nets=frozenset(classes), netclasses=classes, default_clearance=default_clr,
                    layers=layers)
