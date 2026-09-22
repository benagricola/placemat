# A module's keepout on layers its own board does not have

Date: 2026-09-22
Status: design

A module fragment is a two-layer board, because `Layout()` takes no layer
count. A keepout declared in it on every copper layer, or on an inner layer,
has to mean something on the four-layer board that stamps it. Today it does
not, and nothing says so.

## What happens now, measured

The W3011 antenna module declares `keepout antenna` on every copper layer
(datasheet Detail A/B: no metallisation on any layer) and `keepout antenna_c`
on In2 (Detail C). Read back:

| where | rule area | layers |
|---|---|---|
| fragment `modules/gnss_antenna` | `keepout antenna` | F.Cu, B.Cu |
| fragment | `keepout antenna_c` | none - In2 is not on this board |
| generated parent `boards/main` | `keepout antenna_1` | F.Cu, B.Cu |
| generated parent | `keepout antenna_c_1` | In2.Cu |

So In2 survives and the all-layer keepout does not: the parent's pours fill
under the antenna on In1 and In2, which is the entry in `PLACEMAT_GAPS.md`
that cost a board. The parent script currently restates both shapes by hand as
`w3011_ab` and `w3011_c`.

Why, established by saving test boards:

- KiCad saves a multi-layer zone on the layers the board has. On a two-layer
  board, `AllCuMask(2)`, `AllCuMask()` (all 32) and an explicit
  F/In1/In2/B set **all** save as `(layers "F.Cu" "B.Cu")`.
- A single-layer zone keeps its layer even when the board lacks it:
  `keepout antenna_c` is saved as `(layer "In2.Cu")`.
- `pcb layout` stamps a fragment's rule areas into the parent inside the
  cell's group and appends `_1` to the name. Nothing else survives: a zone has
  no user properties.

## The design: the declaration travels in the name

The zone name is the one thing that survives the save and the stamp, so a
keepout whose layers the board cannot hold records them there.

- **`layers=None` - every copper layer - writes ` [*.Cu]`** after the name:
  `keepout antenna [*.Cu]`. It means every copper layer of whatever board the
  region ends up on.
- **Explicit layers the board does not all have write the whole declared
  list**: `keepout antenna_c [In2.Cu]`, `keepout shield [In1.Cu,In2.Cu]`.
- **Explicit layers the board has write no marker**, because the layer set
  already says it exactly.

Verified before designing on it: a zone named `keepout probe_all [*.Cu]` in the
PowerDrop fragment arrives in each of the Breakout's three power-drop cells as
`keepout probe_all [*.Cu]_1`. The bracket survives and the suffix lands after
it, so the marker is found anywhere in the name.

### Reading

`read_board` parses the marker. `[*.Cu]` resolves to every copper layer the
board has; a list resolves to the named layers the board has. `RuleArea.layers`
is the resolved set, so occupancy, `check` and everything else that reads a
rule area honour the declaration without learning about markers. A declared
layer the board lacks is kept on `RuleArea.missing`.

### Writing

A stamped cell's rule areas are not placemat's to delete, and are carried
with the cell. They are placemat's to **correct**: a grouped rule area whose
marker resolves to more layers than the zone is on has its layer set widened
to match, so KiCad's own filler, DRC and anything else that reads the board
honour the declaration. Widening only ever adds layers the declaration named.

### Saying so

- A keepout declared, in a script, on a layer its board lacks is a finding:
  `keepout antenna_c declares In2.Cu, which this 2-layer board does not have:
  recorded in its name, and honoured by a board that has it.` The loss the
  gaps file describes stops being silent at the point it happens.
- A stamped rule area declaring a layer the parent also lacks is a finding on
  the parent, naming the cell.

### Names

The clash check in `board.keepout` compares against existing rule areas by
**base name**, the name with the marker and a trailing `_<n>` removed, so
`keepout antenna` still clashes with a stamped `keepout antenna [*.Cu]_1`.

## What this does NOT do

**Add a layer count to `Layout()`.** That is the `pcb` toolchain's surface, not
placemat's. The marker makes the question moot for keepouts.

**Carry anything but keepouts.** A copper pour declared on In1 in a fragment is
a different object and is not in scope.

**Rename existing rule areas in place.** A fragment gains the marker when its
module's placemat script is next run; until then its keepouts arrive as they
do today.

## Test plan

Pure, no KiCad:

1. `layers=None` gives the marker `[*.Cu]`;
2. explicit layers the board lacks give the declared list, in stackup order;
3. explicit layers the board has give no marker;
4. a name with a marker and a `_1` suffix splits into base name and declaration;
5. `*.Cu` resolves to every layer of a four-layer board, a list to the named
   layers present, and absent ones to `missing`;
6. the clash check matches a stamped marked name against the plain one.

With KiCad:

7. a keepout declared with `layers=None` on a two-layer board is written with
   `[*.Cu]` in its zone name;
8. a stamped rule area named `keepout antenna [*.Cu]_1` on F and B reads on all
   four layers of a four-layer board;
9. writing a four-layer board widens that grouped zone to all four layers, and
   leaves an unmarked grouped zone alone;
10. a script keepout on In2 of a two-layer board raises the finding.

## Documentation

- `api.md`, Keepouts: the marker, what it means, and that a module's keepouts
  now hold on the parent's inner layers.
- `SKILL.md`: a module's keepout needs no restating in the parent; run the
  module's script once so its keepouts carry the marker.
- `references/migration.md`, `## To 0.17`: keepout zone names gain a marker;
  re-run each module's script, then the boards that stamp it; hand-restated
  copies of a module's keepouts in a parent can come out.

## Migration

Keepout zone names change on every board: one declared on every layer gains
` [*.Cu]`. A module fragment carries the marker once its script is re-run, and
a parent honours it once regenerated. A parent's hand-written copy of a
module's keepout still works, and now duplicates a region the module brings.
