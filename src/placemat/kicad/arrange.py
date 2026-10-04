"""pcbnew side of arrangements: the fragment's notes (`write_notes`) and the stamped cell's arrange step (`arrange_cell`)."""
from __future__ import annotations

import re

from .quiet import import_pcbnew, quiet_stderr

pcbnew = import_pcbnew()

from ..arrangement_note import ARRANGEMENT_PREFIX
from ..board_geometry import CellGeom
from ..copper import Pour, Text, Track, Via, Zone
from ..rules import RULE_PREFIX
from ..values import CopperLayer
from .write import (ARRANGEMENT_NOTES_MM, NOTE_PITCH_MM, RULE_NOTES_MM, _delete_note, _draw_pour, _draw_text, _draw_track, _draw_via,
                    _draw_zone, _keepout_admits, _keepout_admits_text, _keepout_zone_name, _place_footprint, add_notes_below,
                    keepout_drawing, rule_area, save, seed_uuids)


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
_STAMP = re.compile(r"_(\d+)$")     # pcb's suffix on a stamped zone's name (board_geometry._MARKER)


def _own_items(group) -> list:
    """What a stamped cell's group holds that is its module's own drawing: tracks and vias, copper polygons, zones and rule areas, and
    drawn text (a keepout drawing's label among it). Footprints, nested groups and other graphics are not."""
    out = []
    for it in group.GetItems():
        if isinstance(it, (pcbnew.PCB_TRACK, pcbnew.ZONE, pcbnew.PCB_TEXT)):
            out.append(it)
        elif isinstance(it, pcbnew.PCB_SHAPE) and it.IsOnCopperLayer():
            out.append(it)
    return out


def _corners(poly_set) -> frozenset:
    """The corners of a polygon set's outlines, to the micron."""
    return frozenset((round(pcbnew.ToMM(poly_set.CVertex(i).x), 3), round(pcbnew.ToMM(poly_set.CVertex(i).y), 3))
                     for i in range(poly_set.TotalVertices()))


def _keepout_drawings(group, areas) -> list:
    """The outlines of the keepout drawings the fragment drew for its rule areas `areas`: a graphic polygon off copper whose corners
    are a rule area's. Their labels are drawn text, which `_own_items` takes."""
    outlines = {_corners(z.Outline()) for z in areas}
    return [it for it in group.GetItems() if isinstance(it, pcbnew.PCB_SHAPE) and not it.IsOnCopperLayer()
            and it.GetShape() == pcbnew.SHAPE_T_POLY and _corners(it.GetPolyShape()) in outlines]


def _label(texts, k):
    """The stamped label of keepout `k`'s drawing, the text `_keepout_admits_text` gave it: its name, or its name and height limit."""
    return next((t for t in texts if t == k.name or t.startswith(k.name + ": ")), None)


def _zone_name(base: str, stamped: dict, used: set) -> str:
    """The name of an arranged rule area whose written name is `base`: with the suffix pcb gave the cell's stamped default of it
    (`stamped`: base -> suffix, else the cell's own suffix), or the next one no other zone on the board has. pcb names a module's
    keepout `<name>_1` in every cell it stamps, and a cell's AllowRule finds its area by name, so two cells' areas must differ."""
    n = stamped.get(base) or next(iter(sorted(stamped.values())), 1)
    while "%s_%d" % (base, n) in used:
        n += 1
    return "%s_%d" % (base, n)


def arrange_cell(board, group, cell: CellGeom, ident: str, settings=None) -> CellGeom:
    """Put a stamped cell's group in arrangement `ident` before it is moved: each member to the arrangement's place, and the module's
    own copper, rule areas, keepout drawings and text replaced by the arrangement's, all in the frame the cell was stamped in.
    Returns the arranged cell, whose box `_move_cell` turns about. `settings` (Settings) say which keepouts are drawn and how.
    Items leave the group with RemoveItem and are deleted with board.Delete, never board.Remove (CLAUDE.md: Remove hands the item
    to its Python wrapper, and on a large board that has broken pcbnew's bindings)."""
    from ..settings import Settings
    settings = settings or Settings()
    arranged = cell.arranged(ident)
    arr = next(a for a in cell.arrangements if a.id == ident)
    by_ref = {it.GetReference(): it for it in group.GetItems() if isinstance(it, pcbnew.FOOTPRINT)}
    for mp in arr.members:
        if mp.pose != mp.default:
            _place_footprint(by_ref[mp.ref], mp.default, mp.pose)
    gone = _own_items(group)                    # all found before any is deleted: a deleted item's wrapper is dead
    areas = [it for it in gone if isinstance(it, pcbnew.ZONE) and it.GetIsRuleArea()]
    labels = [it.GetText() for it in gone if isinstance(it, pcbnew.PCB_TEXT)]
    stamped = {}
    for z in areas:
        m = _STAMP.search(z.GetZoneName())
        if m:
            stamped[z.GetZoneName()[:m.start()]] = int(m.group(1))
    gone += _keepout_drawings(group, areas)
    for it in gone:
        group.RemoveItem(it)
        board.Delete(it)
    drawn = []
    for op in arr.ops:
        draw = next(d for kind, d in _DRAW if isinstance(op, kind))
        drawn.append(draw(board, op))
    stack = tuple(CopperLayer.of(board.GetLayerName(l)) for l in board.GetEnabledLayers().CuStack())
    used = {z.GetZoneName() for z in board.Zones()}
    mode = settings.write_keepout_drawings
    for k in arr.keepouts:
        name = _zone_name(_keepout_zone_name(k, stack), stamped, used)
        used.add(name)
        drawn.append(rule_area(board, k, stack, name))
        # drawn as the fragment drew it: with its stamped label, else as the board's own drawings choose
        text = _label(labels, k)
        if text is None and (mode == "all" or (mode == "admitting" and _keepout_admits(k))):
            text = _keepout_admits_text(k)
        if text is not None and mode != "none":
            drawn += keepout_drawing(board, k, text, settings.write_keepout_line_width, settings.write_keepout_text_height)
    for it in drawn:
        group.AddItem(it)
    return arranged
