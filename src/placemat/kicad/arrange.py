"""pcbnew side of arrangements: the fragment's notes (`write_notes`) and the stamped cell's arrange step (`arrange_cell`)."""
from __future__ import annotations

from .quiet import import_pcbnew, quiet_stderr

pcbnew = import_pcbnew()

from ..arrangement_note import ARRANGEMENT_PREFIX
from ..board_geometry import CellGeom
from ..copper import Pour, Text, Track, Via, Zone
from ..rules import RULE_PREFIX
from ..values import CopperLayer
from .write import (ARRANGEMENT_NOTES_MM, NOTE_PITCH_MM, RULE_NOTES_MM, _delete_note, _draw_pour, _draw_text, _draw_track, _draw_via,
                    _draw_zone, _place_footprint, add_notes_below, rule_area, save, seed_uuids)


def _texts(board, prefix) -> list:
    return [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(prefix)]


def write_notes(pcb_path, texts) -> list:
    """Put a fragment's arrangement notes into it (replacing any it has): User.Comments texts below everything the fragment draws
    and its other notes, which pcb layout stamps with the cell. A board with none and none to write is not touched. Returns the
    texts."""
    texts = list(texts)
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(pcb_path))
        had = _texts(board, ARRANGEMENT_PREFIX)
        if not texts and not had:
            return []
        for d in had:
            _delete_note(board, d)
        seed_uuids()
        rules = len(_texts(board, RULE_PREFIX))           # the clearance notes' lines, which start higher up
        add_notes_below(board, texts, max(ARRANGEMENT_NOTES_MM, RULE_NOTES_MM + NOTE_PITCH_MM * rules))
        save(board, str(pcb_path))
    return texts


_DRAW = ((Track, _draw_track), (Via, _draw_via), (Pour, _draw_pour), (Zone, _draw_zone), (Text, _draw_text))


def _own_items(group) -> list:
    """What a stamped cell's group holds that is its module's own drawing: tracks and vias, copper polygons, zones and rule areas, and
    drawn text. Footprints, nested groups and other graphics are not."""
    out = []
    for it in group.GetItems():
        if isinstance(it, (pcbnew.PCB_TRACK, pcbnew.ZONE, pcbnew.PCB_TEXT)):
            out.append(it)
        elif isinstance(it, pcbnew.PCB_SHAPE) and it.IsOnCopperLayer():
            out.append(it)
    return out


def arrange_cell(board, group, cell: CellGeom, ident: str) -> CellGeom:
    """Put a stamped cell's group in arrangement `ident` before it is moved: each member to the arrangement's place, and the module's
    own copper, rule areas and text replaced by the arrangement's, all in the frame the cell was stamped in. Returns the arranged
    cell, whose box `_move_cell` turns about. Items leave the group with RemoveItem and are deleted with board.Delete, never
    board.Remove (CLAUDE.md: Remove hands the item to its Python wrapper, and on a large board that has broken pcbnew's bindings)."""
    arranged = cell.arranged(ident)
    arr = next(a for a in cell.arrangements if a.id == ident)
    by_ref = {it.GetReference(): it for it in group.GetItems() if isinstance(it, pcbnew.FOOTPRINT)}
    for mp in arr.members:
        if mp.pose != mp.default:
            _place_footprint(by_ref[mp.ref], mp.default, mp.pose)
    gone = _own_items(group)                    # all found before any is deleted: a deleted item's wrapper is dead
    for it in gone:
        group.RemoveItem(it)
        board.Delete(it)
    drawn = []
    for op in arr.ops:
        draw = next(d for kind, d in _DRAW if isinstance(op, kind))
        drawn.append(draw(board, op))
    stack = tuple(CopperLayer.of(board.GetLayerName(l)) for l in board.GetEnabledLayers().CuStack())
    drawn += [rule_area(board, k, stack) for k in arr.keepouts]
    for it in drawn:
        group.AddItem(it)
    return arranged
