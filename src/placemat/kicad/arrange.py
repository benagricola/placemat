"""pcbnew side of arrangements: the fragment's notes (`write_notes`) and, in Phase 2, the stamped cell's arrange step."""
from __future__ import annotations

from .quiet import import_pcbnew, quiet_stderr

pcbnew = import_pcbnew()

from ..arrangement_note import ARRANGEMENT_PREFIX
from ..rules import RULE_PREFIX
from .write import (ARRANGEMENT_NOTES_MM, NOTE_PITCH_MM, RULE_NOTES_MM, _delete_note, add_notes_below, save,
                    seed_uuids)


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
