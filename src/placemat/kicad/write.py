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

pcbnew = import_pcbnew()

from ..layout import Plan
from ..copper import Pour, Text, Track, Via, Zone
from ..geometry import Transform
from ..placement import Placement
from ..board_geometry import CellGeom, Footprint
from ..cutouts import closes_itself
from ..values import Face, Location

def nm(v: float) -> int:
    return pcbnew.FromMM(float(v))


def vec(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I(nm(x), nm(y))


def seed_uuids(seed: int = 0x5EED):
    """New board items draw their UUIDs from a seeded generator, so a plan
    applied twice writes the same file."""
    pcbnew.KIID.SeedGenerator(seed)


def _place_footprint(fp, current: Placement, target: Placement):
    if target.face != current.face:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
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
        if flip:
            it.Flip(pivot, pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        if target.rotation:
            it.Rotate(pivot, angle)
        it.Move(delta)


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
    a layer."""
    for z in list(board.Zones()):
        if z.GetIsRuleArea():
            board.Delete(z)                 # a rerun replaces them, never doubles them
    for k in plan.keepouts.values():
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetLayerSet(pcbnew.LSET.AllCuMask(board.GetCopperLayerCount()) if k.layers is None
                      else _layer_set(board, k.layers))
        for name, setter in _KEEPOUT_FLAGS.items():
            getattr(z, setter)(name in k.excludes)
        o = z.Outline()
        o.NewOutline()
        for x, y in k.poly:
            o.Append(nm(x), nm(y))
        z.SetZoneName("keepout %s" % k.name)
        board.Add(z)


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
    t = pcbnew.PCB_TRACK(board)
    t.SetLayer(_layer_id(board, op.layer))
    t.SetNetCode(_netcode(board, op.net))
    t.SetWidth(nm(op.width))
    t.SetStart(vec(op.start.x, op.start.y))
    t.SetEnd(vec(op.end.x, op.end.y))
    board.Add(t)


def _draw_via(board, op: Via):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(vec(op.at.x, op.at.y))
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
    t.SetMirrored(op.mirrored)
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
    code = _netcode(board, op.net)
    ps = pcbnew.SHAPE_POLY_SET()
    ps.NewOutline()
    for x, y in op.points:
        ps.Append(nm(x), nm(y))
    if op.swallow_pads:
        m = nm(0.12)
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetCode() != code:
                    continue
                bb = p.GetBoundingBox()
                corners = [pcbnew.VECTOR2I(bb.GetLeft(), bb.GetTop()), pcbnew.VECTOR2I(bb.GetRight(), bb.GetTop()),
                           pcbnew.VECTOR2I(bb.GetRight(), bb.GetBottom()), pcbnew.VECTOR2I(bb.GetLeft(), bb.GetBottom()),
                           p.GetPosition()]
                if any(ps.Contains(c) for c in corners):
                    r = pcbnew.SHAPE_POLY_SET()
                    r.NewOutline()
                    for x, y in ((bb.GetLeft() - m, bb.GetTop() - m), (bb.GetRight() + m, bb.GetTop() - m),
                                 (bb.GetRight() + m, bb.GetBottom() + m), (bb.GetLeft() - m, bb.GetBottom() + m)):
                        r.Append(x, y)
                    ps.BooleanAdd(r)
        ps.Simplify()
    sh = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
    sh.SetLayer(_layer_id(board, op.layer))
    sh.SetFilled(True)
    sh.SetWidth(nm(op.stroke))
    sh.SetPolyShape(ps)
    sh.SetNetCode(code)
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


def render_board(pcb_path, log, both_faces: bool = False) -> list:
    """layout.png (top), layout-iso.png, and layout-bottom.png when the board
    carries parts on both faces, beside the board file."""
    import subprocess
    pcb_path = str(pcb_path)
    out_dir = os.path.dirname(pcb_path)
    views = [("layout.png", "top", []), ("layout-iso.png", "top", ["--rotate", "-45,0,45", "--perspective"])]
    if both_faces:
        views.append(("layout-bottom.png", "bottom", []))
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    done = []
    with open(log, "w") as f:
        for name, side, extra in views:
            cmd = ["kicad-cli", "pcb", "render", "--side", side, "--background", "opaque", "--quality", "high",
                   "--use-board-stackup-colors", "-o", os.path.join(out_dir, name), pcb_path] + extra
            f.write("$ %s\n" % " ".join(cmd))
            f.flush()
            try:
                subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=300, env=env)
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
    with quiet_stderr():
        board = pcbnew.LoadBoard(pcb_path)
    seed_uuids()
    groups = {g.GetName(): g for g in board.Groups()}
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for step in plan.steps:
        if step.placement is None or step.kind == "block":
            continue                     # copper is drawn below; a block's members have their own steps
        item = plan._items[step.item]
        if isinstance(item, Footprint):
            fp = by_ref[item.ref]
            _place_footprint(fp, Placement(item.location, item.rotation, item.face), step.placement)
        elif isinstance(item, CellGeom):
            _move_cell(board, item, step.placement, groups)
    _draw_outline(board, plan)
    _draw_keepouts(board, plan)
    draw_copper(board, plan.copper)
    out = str(out_path or pcb_path)
    save(board, out)
    from ..rules import write_rules
    write_rules(out, plan.rules)
    return out


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
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
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
        boxes += [d.GetBoundingBox() for d in board.GetDrawings() if not (isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith("placemat faces "))]
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
