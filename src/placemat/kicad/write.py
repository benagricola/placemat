"""Apply a resolved Plan to a .kicad_pcb through pcbnew, then save.

Cells move as rigid bodies: every member footprint and every piece of the
cell's own copper takes the same transform, computed from the cell's box
centre in the snapshot the plan was resolved against. New drawings get
deterministic UUIDs derived from their geometry, so an unchanged plan
writes an unchanged file.
"""
from __future__ import annotations

import os

import pcbnew

from ..board import Plan
from ..geometry import Transform
from ..placement import Placement
from ..snapshot import CellGeom, Footprint
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


def _draw_outline(board, plan: Plan):
    for d in list(board.GetDrawings()):
        if isinstance(d, pcbnew.PCB_SHAPE) and d.GetLayer() == pcbnew.Edge_Cuts:
            board.Delete(d)      # Remove() orphans the item and corrupts a later in-process LoadBoard
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


def save(board, path: str):
    """Atomic save: write beside the target and move it into place."""
    tmp = path + ".writing"
    board.Save(tmp)
    os.replace(tmp, path)


def apply_plan(pcb_path, plan: Plan, out_path=None) -> str:
    pcb_path = str(pcb_path)
    board = pcbnew.LoadBoard(pcb_path)
    seed_uuids()
    groups = {g.GetName(): g for g in board.Groups()}
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for step in plan.steps:
        item = plan._items[step.item]
        if isinstance(item, Footprint):
            fp = by_ref[item.ref]
            _place_footprint(fp, Placement(item.location, item.rotation, item.face), step.placement)
        elif isinstance(item, CellGeom):
            _move_cell(board, item, step.placement, groups)
    _draw_outline(board, plan)
    out = str(out_path or pcb_path)
    save(board, out)
    return out
