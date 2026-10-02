# Fragment notes out of sight on the stamping board

## Problem

A module fragment carries two facts for the board that stamps it as visible
User.Comments texts: `placemat faces outward=...` and, one per clearance rule,
`placemat rule clearance=... between=... why=...`. pcb layout copies them into
the parent's generated board, in the cell's group. The parent reads them
(`read.board_geometry_of`) and was meant to leave none on its written board.
They showed in KiCad, a few millimetres from their cell, stretching the cell's
group box.

Two causes.

1. The generated board is the layout folder's board for the whole run. A run
   reads it, resolves (minutes on a large board) and only then writes. A run
   stopped before the write leaves the generated board, notes and all, as the
   folder's board. The board that showed them was byte for byte the cached
   generation.
2. `_drop_stamped_notes` removed a note only when it was a member of a group,
   on the theory that a loose note is the fragment's own. A note a parent
   holds loose was kept, though a fragment's own notes are written afresh by
   every fragment run and never need keeping from the loaded board.

A written core board from the current code, run on the real board, has none:
the group case was already handled. The loose case and the interrupted run were
not.

## Design

### Where a fragment keeps its facts

Kept as texts on the fragment. The alternatives:

- A sidecar beside the fragment's layout, read by the parent. The parent can
  not find it: a stamped footprint's properties (`Path`, `Prefix`, ...) and
  the cell's group name record the instance path in the parent's design, not
  the fragment's folder, and the parent's board source has no map from a cell
  to the module's file. Finding it means parsing the netlist and the `.zen`
  imports, a second path to the same fact. The texts already ride with the
  stamp.
- A layer KiCad hides by default. KiCad shows every layer a board enables; one
  that is not enabled is enabled by the board that has an item on it, or the
  item is dropped by the stamp. Not tested with the generator, and the notes
  would still show in the fragment's own view.

So the transport stays as it is, and the parent clears it.

### The stamping board

- `apply_plan` drops every faces and rule note from the loaded board, in a
  group or loose (`_drop_stamped_notes`). A note a board writes is its own and
  is written afterwards from its plan: `board.faces()` as a text op,
  `write_rule_notes` for a fragment's rules.
- The run clears the generated board in the layout folder as soon as the
  facts are read (`write.strip_stamped_notes`, called in `runner.run` after
  `scripted_board`). Later steps of the run read the geometry already held, not
  the file. The cached generation is untouched: it is what pcb layout wrote.

### A fragment run alone

Its own notes are written afresh each run, so none needs keeping from the
loaded board, with one exception: the faces text `placemat faces` stamped into
a fragment. A loose faces text on a fragment (`draw=False`) that declares no
`board.faces()` is kept, by `apply_plan` and by the early clearing. A fragment
that declares `board.faces()` replaces it. A fragment that stamps a cell drops
the cell's notes and carries the cell's clearance rules on as its own, as before.

### Old fragments

The notes are unchanged in form, so a fragment written by any release reads
as before.

## Verification

- Pure pcbnew tests (`tests/test_fragment_notes.py`): a parent stamping a cell
  with faces and rule notes, in the group and loose, reads both facts and
  writes none, and its `.kicad_dru` has the rule; the generated board is
  cleared once read, keeping parts in their groups; a fragment run alone keeps
  its stamped faces and writes its rules, writes its declared faces once, and
  carries a stamped cell's rule on.
- A real parent board with its cached generation and module layouts, run end
  to end: the written board has no faces or rule texts, the stamped rules
  reach its `.kicad_dru`, and the board in the layout folder after the
  read has none. Recorded in the commit message.
