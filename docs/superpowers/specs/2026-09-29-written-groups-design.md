# Groups a hand placement can move

Date: 2026-09-29
Status: approved 2026-09-29; item 1 revised the same day (below)
Source: a board's PLACEMAT_GAPS.md, 2026-09-29 "groups a hand placement can
move"; its workaround `a board's regroup script`

## The problem

The generator (`pcb layout`) makes one KiCad group per module sheet. A
stamped cell is a group of its own, nested inside its module's group. The
written board keeps every group as generated. Placemat moves a placed
cell's group whole (`write._move_cell`), and places everything else part by
part.

When a script places a module's parts apart, some fixed on the board and
others parked or searched elsewhere, that module's group still holds them
all:
- **power input:** its two tabs are fixed on the board and its filter is
  parked 100 mm away.
- **sensors:** the light sensor is fixed and the rest are parked.
- **radio:** the antenna cell is fixed and the receiver is parked.
- **power delivery:** its group holds its three stamped cells as sub-groups, plus 15
  parts of its own.

In pcbnew, selecting any one of these parts drags all of them.

Placemat reads groups but writes none of its own. Its reads take their
geometry from the cached generation (`previewer.resolve_like_last_run`), not
from the written board, so what the written board's groups say changes no
later placement.

## Revision (2026-09-29, a board session relaying the owner's direction)

No part is pulled out of its module; every module gets its own layout;
sub-modules are their own groups. So the default is "lift": each nested
group (a stamped cell in its module sheet's) is lifted to the top level,
whole, and a module keeps its own parts even when the script places them
one by one. Taking out the parts placed apart (item 1 below) is the
`"split"` option; `"keep"` writes the groups as generated. A group left
empty is removed.

Later the same day: groups on the board are one level, never nested (KiCad
makes a nested group entered before anything in it moves). `board.group`
takes parts only; a cell stays a group of its own at the top level.

## The change (as first approved)

1. **A group whose members the plan placed apart is dissolved on the written
   board.**
   - "Placed apart": any of its footprints or sub-groups was placed by a
     step of its own, and the group itself was not placed as one cell.
   - Its footprints are left ungrouped. Its sub-groups (stamped cells) move
     to the top level, still whole.
   - A group the plan left alone, or placed as a cell, is written as it was.
   - `[write] split_groups = "keep"` keeps every group as generated. The
     default, `"dissolve"`, dissolves as above.
   - This is the generic form of what `regroup_clusters.py` does by name.
2. **`board.group(name, items, why="")`** writes a KiCad group called `name`
   holding `items`:
   - Items are `Part(...)`s and `Cell(...)`s. A cell becomes a sub-group, a
     part a member.
   - It has no effect on placement; the script places the items as it wants,
     for example parked as one cluster.
   - Refused when the script declares it:
     - a name another group or cell on the board already has;
     - an item already in another declared group.
   - Refused at resolve: a part whose own cell group is written whole (the
     script placed that cell as one). Group the cell instead.
3. **The run says so**, one line per change:
   - `groups  pd dissolved: its parts were placed apart; pd.controller, pd.paths, pd.moisture now stand alone`
   - `groups  power_in.filter written: 4 parts`

## Verification

KiCad tests on the breakout, which has cells:
- A module group whose parts are placed apart is gone on the written board.
  Its sub-group is at the top level and still holds its members.
- A cell placed whole keeps its group.
- `split_groups = "keep"` keeps the dissolved group.
- `board.group` writes a group with the parts and the cell's group as
  members.
- A declared name that clashes with a cell is refused. So is a member of a
  cell placed whole.
- The written board reads back with the declared groups and without the
  dissolved ones. A following run's resolve, from the cached generation, is
  unchanged.

## Not in scope

- Placement by group: `board.group` only writes the group. Keeping a set
  together is the placement's job (a cell, a block, a cluster).
