# Labels yield to searches

Follows `2026-10-01-labels-give-way-design.md`, which made a label move for a
firm part and left searched items treating labels as obstacles.

## Problem

A label's text box is reserved on its face and its silk is an obstacle, from
the moment its item is placed. A searched item (a part or cell searched near
a hint, along a run, round a rim, in a pocket) is judged against both, so a
label placed early can hold the only room. Sessions report:

- a cell searched along a run: "UNPLACED: its member C6 sits in the
  reservation for label X; cell's C6 mask opening is 0.11 mm from label X
  silk (needs 0.20)" and "no room anywhere along the run";
- another searched cell: "its member C58 sits in the reservation for label Y".

The rule is the user's (see the first spec): a user label moves before a part
does, as long as it still clearly refers to its item. A label must never cost
an item its place.

## Options

(a) Labels are not obstacles to a searched item during its search. Once it
is down, the labels it meets give way by the existing `_labels_give_way`; a
label with no clear spot is a finding, and the item stays.

(b) A candidate refused only by labels is re-judged with those labels moved.
Each such candidate costs a label search (every slide step on every side,
each judged against the board) inside a scan that asks tens of thousands of
candidates, and the native sweep would have to hand refusals back to Python
to be re-judged. The label positions it assumes also differ per candidate,
so scoring and the "first legal" choice depend on label room.

(a) is chosen. It is the same rule as for a firm part (the item stays, the
label moves), costs one label pass per placed item, and leaves the scan and
the native sweep unchanged apart from not seeing the labels. Scoring does not
count label room: no score reads a label's reservation or silk.

## Design

- A label's reservation carries `source = "label"` (`occupancy.LABEL_SOURCE`);
  its silk obstacle is the silk shape owned by "label ...".
- `Occupancy.labels_yield`, set while a searched item (not a block) is
  settled, drops both from what the item is judged against:
  - `_edge_or_reservation_conflict` skips label reservations;
  - `_obstacle_shapes` leaves label silk out, and the native obstacle index
    is cached under its own key for it;
  - `NativeSweeper` leaves label reservations out of the list it hands the
    native board (the board itself is unchanged, the list holds indexes).
- `_recorded_settle` sets the flag around the rider check, `_riders_alone`
  and `_settle`, and clears it before `_settle_riders`, which gives the
  riders' labels way as before.
- After the item is committed, `place_one` already runs `_labels_give_way`
  for it (and its riders); that is the step that moves the label, and it
  runs the same on a replay, which does not search.
- Other items' silk, pads and courtyards stay obstacles. Grouped labels
  (a list, or `line=`) still do not give way; a searched item is placed over
  them and the label is a finding.
- A label with nowhere to go: the `label` finding from the first spec ("no
  clear spot beside ... for it to move to, and C1 is in the way") and the
  item placed. Silk that lands on a label also shows in DRC.
- Not done: a block is searched with labels in view, since its members are
  firm relative to each other and are not swept; a label's candidate spots
  are not checked against the board outline.

## Verification

`tests/test_label_yields_to_search.py`, synthetic boards:

- a searched part whose only room is under another item's label places there
  and the label moves to another side;
- a label with no room anywhere becomes a `label` finding and the part still
  places;
- a searched part still keeps off another item's silk;
- a replayed run ends with the same label, part, notes and findings;
- native and Python sweeps give the same placements, labels and findings (the
  test fails with the native reservation filter removed).

The earlier firm-part tests (`test_label_gives_way.py`, `test_labels.py`)
pass unchanged. Full suite, and `fixtures/bench.py --jobs 4` for drift (the
bench boards have no labels, so the tally is expected unchanged).
