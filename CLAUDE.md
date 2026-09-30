# placemat

## pcbnew: delete board items with `board.Delete`, not `board.Remove`

To take an item off a board for good, use `board.Delete(item)`, after
`group.RemoveItem(item)` if it is in a group.

`board.Remove(item)` hands the C++ item to its Python wrapper
(`thisown=1`), and the item is freed when that wrapper is garbage-collected.
On a large board this has left pcbnew's bindings broken for the rest of the
process. Calls that return board items or vectors then give back bare
`SwigPyObject`s: `GetItems()` fails with "'SwigPyObject' object has no
attribute 'Cast'", and `GetPosition()` with "... no attribute 'x'". It has
been seen twice:
- a cell zone removed while merging zones (`_merge_cell_zones`), which
  corrupted `board.Zones()`;
- vias and tracks removed when vias gave way (`_given_way`, 0.57.0), which
  broke every group on the board.

Small synthetic boards do not reproduce it, so a passing test does not
show that a `Remove` is safe.

Use `Remove` only to move an item into another container that takes
ownership (`Add` sets `thisown=0` again).
