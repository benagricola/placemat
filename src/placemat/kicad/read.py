"""Reads a generated .kicad_pcb through pcbnew into a BoardGeometry.

Box conventions: the body box is the courtyard deflated by the fab's
courtyard excess, unioned with the pads (a courtyard is an assembly keepout,
and fab and silk drawings over-draw bodies); the courtyard box is courtyard
outlines plus pads; the physical box is pads plus drawn graphics, courtyard
excluded."""
from __future__ import annotations

from pathlib import Path

from .quiet import import_pcbnew, quiet_stderr

pcbnew = import_pcbnew()

from ..board_geometry import CellGeom, CopperItem, Footprint, NetClass, PadGeom, RuleArea, BoardGeometry
from ..values import Box, CopperLayer, Face, Location

CLEAR_ERR_NM = 5000     # arc approximation error for TransformShapeToPolySet; [geometry] arc_error_nm
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
    """Named copper layers of a set, restricted to the ones this board has.

    A through-hole pad carries every copper layer KiCad can name, whatever
    board it is on, so a pad on a 2-layer board reported In1.Cu through
    In30.Cu. A layer the board has not enabled does not exist for anything
    read off it - not for a clearance, and not for a printed line."""
    return [board.GetLayerName(l) for l in layer_set.CuStack() if board.IsLayerEnabled(l)]


def _copper_layers(board, layer_set) -> frozenset[CopperLayer]:
    """The copper layers of a layer set. A set names the non-copper layers an
    item is on too - silk, mask, paste - and those are skipped by name; a
    copper layer that cannot be named is a defect, not something to drop."""
    out = set()
    for name in _layer_names(board, layer_set):
        if not name.endswith(".Cu"):
            continue                    # silk, mask, paste: not this function's business
        out.add(CopperLayer.of(name))
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


def _pads(board, fp, err_nm: int = CLEAR_ERR_NM) -> tuple[PadGeom, ...]:
    ref, inst = fp.GetReference(), inst_of(fp)
    pads = []
    for pad in fp.Pads():
        attr = pad.GetAttribute()
        if attr == pcbnew.PAD_ATTRIB_NPTH:
            continue
        cu = [l for l in pad.GetLayerSet().CuStack() if board.IsLayerEnabled(l)]
        if not cu:
            continue                    # nothing on a layer this board has
        outs = outlines_of(pad, cu[0], err_nm)
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


def _footprint(board, fp, excess_mm, cell, err_nm: int = CLEAR_ERR_NM) -> Footprint:
    pos = fp.GetPosition()
    return Footprint(ref=fp.GetReference(), inst=inst_of(fp), cell=cell, value=fp.GetValue(),
                     location=Location(mm(pos.x), mm(pos.y)),
                     rotation=fp.GetOrientationDegrees(),
                     face=Face.BACK if fp.IsFlipped() else Face.FRONT,
                     body_box=body_box(fp, excess_mm), courtyard_box=courtyard_box(fp),
                     phys_box=phys_box(fp), pads=_pads(board, fp, err_nm), npth=_npth(fp),
                     fields={f.GetName(): f.GetText() for f in fp.GetFields()})


def _copper(board, groups_of, err_nm: int = CLEAR_ERR_NM) -> tuple[CopperItem, ...]:
    items = []

    def add(kind, obj, net, owner=None, width=0.0):
        cu = [l for l in obj.GetLayerSet().CuStack() if board.IsLayerEnabled(l)]
        if not cu:
            return                      # nothing on a layer this board has
        outs = outlines_of(obj, cu[0], err_nm)
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


_KEEPOUT_GETTERS = (("parts", "GetDoNotAllowFootprints"), ("fill", "GetDoNotAllowZoneFills"),
                    ("tracks", "GetDoNotAllowTracks"), ("vias", "GetDoNotAllowVias"),
                    ("pads", "GetDoNotAllowPads"))


def _rule_areas(board, groups_of) -> tuple:
    """Every rule area on the board. A stamped module fragment's are members
    of the cell's group, which is how placemat tells them from its own."""
    out = []
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if not z.GetIsRuleArea():
            continue
        outline = z.Outline()
        if not outline.OutlineCount():
            continue
        o = outline.Outline(0)
        poly = tuple((mm(o.CPoint(j).x), mm(o.CPoint(j).y)) for j in range(o.PointCount()))
        excludes = frozenset(name for name, getter in _KEEPOUT_GETTERS if getattr(z, getter)())
        out.append(RuleArea(z.GetZoneName(), groups_of.get(_kiid(z)), poly,
                            _copper_layers(board, z.GetLayerSet()), excludes))
    return tuple(out)


def _board_polygon(board) -> tuple:
    """The board's real edge as polygons: the outline first, then its holes.

    `_outline` below keeps one bounding box per Edge.Cuts drawing, which every
    placement path consumes and which reads a disc as a square. This is the
    shape itself, for measuring how near a thing comes to the edge."""
    ps = pcbnew.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(ps, False) or not ps.OutlineCount():
        return ()
    out = []
    o = ps.Outline(0)
    out.append(tuple((mm(o.CPoint(i).x), mm(o.CPoint(i).y)) for i in range(o.PointCount())))
    for h in range(ps.HoleCount(0)):
        hole = ps.Hole(0, h)
        out.append(tuple((mm(hole.CPoint(i).x), mm(hole.CPoint(i).y))
                         for i in range(hole.PointCount())))
    return tuple(out)


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
                                 mm(nc.GetClearance()), mm(nc.GetViaDiameter()), mm(nc.GetViaDrill()),
                                 mm(nc.GetDiffPairWidth()) or None, mm(nc.GetDiffPairGap()) or None)
    default = mm(board.GetDesignSettings().m_NetSettings.GetDefaultNetclass().GetClearance())
    return classes, default


def read_board(path, courtyard_excess_mm: float = 0.10, arc_error_nm: int | None = None) -> BoardGeometry:
    if arc_error_nm is None:
        from ..settings import active
        arc_error_nm = active().geometry_arc_error_nm
    path = str(Path(path))
    with quiet_stderr():
        board = pcbnew.LoadBoard(path)
    return board_geometry_of(board, path, courtyard_excess_mm, arc_error_nm)


def read_footprint(path, courtyard_excess_mm: float = 0.10) -> tuple:
    """A `.kicad_mod` read on its own, with no board: the footprint in its own
    frame at the origin, and the file's SHA-256 so two variants of a part can
    be told apart.

    A through-hole pad gets NO layers. An empty scratch board has all 32
    copper layers enabled and `SetCopperLayerCount` does not restrict a pad's
    own layer set, so a through pad read this way would claim In1 through
    In30 - true of the scratch board and of no real one. `PadGeom.through`
    already says what it is; an SMD pad's single face is read normally."""
    import hashlib
    p = Path(path)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    with quiet_stderr():
        fp = pcbnew.FootprintLoad(str(p.parent), p.stem)
    if fp is None:
        raise ValueError("pcbnew could not load a footprint from %s" % p)
    scratch = pcbnew.CreateEmptyBoard()
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
        through = attr == pcbnew.PAD_ATTRIB_PTH
        pads.append(PadGeom(owner=p.stem, inst=p.stem, number=pad.GetNumber() or "?", net="",
                            layers=frozenset() if through else _copper_layers(scratch, pad.GetLayerSet()),
                            outlines=outs, box=Box.of_points([q for o in outs for q in o]),
                            through=through,
                            drill_mm=mm(pad.GetDrillSize().x) if through else 0.0))
    geom = Footprint(ref=p.stem, inst=p.stem, cell=None, value=fp.GetValue() or p.stem,
                     location=Location(0.0, 0.0), rotation=0.0, face=Face.FRONT,
                     body_box=body_box(fp, courtyard_excess_mm), courtyard_box=courtyard_box(fp),
                     phys_box=phys_box(fp), pads=tuple(pads), npth=_npth(fp),
                     fields={f.GetName(): f.GetText() for f in fp.GetFields()})
    return geom, digest


FACES_PREFIX = "placemat faces "     # a User.Comments text a module fragment carries: `placemat faces outward=N quiet=S handoff=E`


def board_geometry_of(board, path: str, courtyard_excess_mm: float = 0.10,
                      arc_error_nm: int = CLEAR_ERR_NM) -> BoardGeometry:
    """Build a BoardGeometry from an already-loaded pcbnew BOARD."""
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
    fps = tuple(_footprint(board, fp, courtyard_excess_mm, member_cell.get(fp.GetReference()), arc_error_nm)
                for fp in board.GetFootprints())
    by_ref = {fp.ref: fp for fp in fps}
    copper = _copper(board, groups_of, arc_error_nm)
    cells = {}
    for name, items in group_items.items():
        members = tuple(by_ref[it.GetReference()] for it in items if isinstance(it, pcbnew.FOOTPRINT))
        own = [c.box for c in copper if c.owner == name and c.kind != "pad"]
        copper_box = Box.union(own)
        box = Box.union([fp.body_box for fp in members] + own)
        phys = Box.union([fp.phys_box for fp in members] + own)
        court = Box.union([fp.courtyard_box for fp in members] + own)
        faces = {}
        for it in items:
            if isinstance(it, pcbnew.PCB_TEXT) and it.GetText().startswith(FACES_PREFIX):
                for word in it.GetText()[len(FACES_PREFIX):].split():
                    k, _, v = word.partition("=")
                    if v:
                        faces[k] = v
        cells[name] = CellGeom(name, members, box, phys, court, copper_box, faces)
    classes, default_clr = _netclasses(board)
    layers = tuple(CopperLayer.of(board.GetLayerName(l)) for l in board.GetEnabledLayers().CuStack())
    return BoardGeometry(path=path, footprints=fps, cells=cells, copper=copper, outline=_outline(board),
                    nets=frozenset(classes), netclasses=classes, default_clearance=default_clr,
                    layers=layers, edge_clearance=mm(board.GetDesignSettings().m_CopperEdgeClearance),
                    rule_areas=_rule_areas(board, groups_of),
                    board_polygon=_board_polygon(board))
